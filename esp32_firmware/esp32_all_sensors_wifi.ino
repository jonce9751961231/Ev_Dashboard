/******************************************************************************
 * Project: EV Predictive Dashboard (AURA EV Cockpit)
 * Sketch: esp32_all_sensors_wifi.ino
 * Target Board: ESP-WROOM-32 / ESP32 Dev Module (38-Pin NodeMCU ESP-32S V1.1)
 *
 * SENSOR HARDWARE PIN MAPPING (SAFE ADC1 PINS - NO STRAPPING CONFLICTS):
 *   1. 0-25V Voltage Divider Sensor : GPIO 34 (Pin marked D34 / P34)
 *   2. ACS712 5A Current Sensor OUT : GPIO 35 (Pin marked D35 / P35)
 *      - ACS712 VCC -> ESP32 VIN (5V USB pin)
 *      - ACS712 GND -> ESP32 GND
 *      - ACS712 OUT -> ESP32 GPIO 35 (DO NOT CONNECT TO D12 / GPIO 12!)
 *   3. LM393 Optical Speed Sensor D0: GPIO 18 (Pin marked D18 / P18 - Interrupt)
 *   4. DS18B20 1-Wire Temp DATA     : GPIO 4  (Pin marked D4  / P4 - 4.7k pullup)
 *
 * FEATURES:
 *   - Reads all 4 real sensors directly on ESP32.
 *   - Connects to your Wi-Fi network and HTTP POSTs to Laptop Host App.
 *   - Prints clean formatted live table & JSON in Arduino Serial Monitor (115200 baud).
 *   - Non-blocking: If Wi-Fi drops, sensors continue printing to Serial Monitor!
 ******************************************************************************/

#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ============================================================================
// 1. WI-FI & LAPTOP HOST SERVER CONFIGURATION
// ============================================================================
const char* ssid     = "DELL";          // <-- Your Wi-Fi Name / Hotspot
const char* password = "password";      // <-- Your Wi-Fi Password
const char* serverUrl = "http://10.128.151.33:8000/api/ingest";

// ============================================================================
// 2. PIN DEFINITIONS (SAFE ADC1 PINS - NEVER USE GPIO 12!)
// ============================================================================
#define PIN_VOLTAGE   34   // ADC1_CH6: 0-25V Voltage Divider Signal (D34)
#define PIN_CURRENT   35   // ADC1_CH7: ACS712 5A Current Sensor OUT (D35)
#define PIN_SPEED     18   // GPIO 18 : LM393 Optical Sensor D0 (D18 - Interrupt)
#define PIN_TEMP      4    // GPIO 4  : DS18B20 1-Wire Data (D4)

// ============================================================================
// 3. HARDWARE CALIBRATION CONSTANTS
// ============================================================================
const float VOLTAGE_DIVIDER_RATIO = 5.0f;
const float ACS712_SENSITIVITY = 0.185f;
const float ACS712_VREF        = 2.50f;
const int ENCODER_SLOTS        = 20;

OneWire oneWire(PIN_TEMP);
DallasTemperature sensors(&oneWire);

volatile unsigned long pulseCount = 0;
unsigned long lastSampleTime = 0;
float currentRPM = 0.0f;

void IRAM_ATTR countPulse() {
  pulseCount++;
}

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println("\n========================================================================");
  Serial.println("     AURA EV - ESP32 ALL SENSORS & WI-FI TELEMETRY GATEWAY             ");
  Serial.println("========================================================================");
  Serial.println(" Pin Configuration:");
  Serial.println("   - Voltage Sensor (0-25V) : GPIO 34 (D34)");
  Serial.println("   - Current Sensor (ACS712): GPIO 35 (D35) [VCC->VIN, GND->GND]");
  Serial.println("   - Speed Sensor   (LM393) : GPIO 18 (D18)");
  Serial.println("   - Temperature    (DS18B20): GPIO 4  (D4)");
  Serial.println("------------------------------------------------------------------------");

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  pinMode(PIN_SPEED, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_SPEED), countPulse, FALLING);

  pinMode(PIN_TEMP, INPUT_PULLUP);
  sensors.begin();

  Serial.printf(" Connecting to Wi-Fi SSID: %s ...\n", ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n [Wi-Fi STATUS] Connected Successfully!");
    Serial.print(" ESP32 Local IP  : ");
    Serial.println(WiFi.localIP());
    Serial.print(" Ingestion Server: ");
    Serial.println(serverUrl);
  } else {
    Serial.println("\n [Wi-Fi WARNING] Could not connect. Operating in offline Serial mode.");
  }

  Serial.println("========================================================================");
  Serial.println("  VOLTAGE (V)  |  CURRENT (A)  |  SPEED (RPM)  |  TEMP (deg C)  |   POWER (W)");
  Serial.println("------------------------------------------------------------------------");

  lastSampleTime = millis();
}

void loop() {
  if (millis() - lastSampleTime >= 1000) {
    unsigned long dt = millis() - lastSampleTime;
    lastSampleTime = millis();

    // 1. Calculate Motor RPM from pulse count
    noInterrupts();
    unsigned long count = pulseCount;
    pulseCount = 0;
    interrupts();

    currentRPM = ((float)count / (float)ENCODER_SLOTS) * (60000.0f / (float)dt);

    // 2. Read Voltage Sensor (GPIO 34 / D34)
    int rawVolt = analogRead(PIN_VOLTAGE);
    float v_pin = ((float)rawVolt / 4095.0f) * 3.3f;
    float voltage_v = v_pin * VOLTAGE_DIVIDER_RATIO;
    if (voltage_v < 0.3f) voltage_v = 0.0f;

    // 3. Read Current Sensor (GPIO 35 / D35) - ACS712 5A
    int rawCurr = analogRead(PIN_CURRENT);
    float i_pin = ((float)rawCurr / 4095.0f) * 3.3f;
    float current_a = (i_pin - ACS712_VREF) / ACS712_SENSITIVITY;
    if (fabs(current_a) < 0.08f) current_a = 0.0f;
    else if (current_a < 0.0f) current_a = 0.0f;

    // 4. Read Temperature Sensor (GPIO 4 / D4) - Dallas DS18B20
    sensors.requestTemperatures();
    float temp_c = sensors.getTempCByIndex(0);
    bool temp_valid = (temp_c != DEVICE_DISCONNECTED_C && temp_c > -40.0f && temp_c < 125.0f);

    float power_w = voltage_v * current_a;

    // 5. Print Formatted Telemetry Row to Arduino Serial Monitor
    if (temp_valid) {
      Serial.printf("   %6.2f V    |    %5.2f A    |    %5u RPM   |    %5.1f C     |   %6.2f W\n",
                    voltage_v, current_a, (unsigned int)currentRPM, temp_c, power_w);
    } else {
      Serial.printf("   %6.2f V    |    %5.2f A    |    %5u RPM   |    DISCONN     |   %6.2f W\n",
                    voltage_v, current_a, (unsigned int)currentRPM, power_w);
    }

    // 6. Build JSON Telemetry Payload
    char jsonBuffer[128];
    if (temp_valid) {
      snprintf(jsonBuffer, sizeof(jsonBuffer),
               "{\"v\":%.2f,\"i\":%.2f,\"rpm\":%u,\"temp\":%.1f}",
               voltage_v, current_a, (unsigned int)currentRPM, temp_c);
    } else {
      snprintf(jsonBuffer, sizeof(jsonBuffer),
               "{\"v\":%.2f,\"i\":%.2f,\"rpm\":%u,\"temp\":null}",
               voltage_v, current_a, (unsigned int)currentRPM);
    }

    Serial.printf("[JSON Output]: %s\n", jsonBuffer);

    // 7. Transmit to Laptop Host Server via Wi-Fi HTTP POST
    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      http.begin(serverUrl);
      http.addHeader("Content-Type", "application/json");

      int httpResponseCode = http.POST(jsonBuffer);
      if (httpResponseCode > 0) {
        Serial.printf("[Wi-Fi POST OK] HTTP %d (Sent to Dashboard)\n\n", httpResponseCode);
      } else {
        Serial.printf("[Wi-Fi POST Error] %s\n\n", http.errorToString(httpResponseCode).c_str());
      }
      http.end();
    } else {
      Serial.println("[Wi-Fi Status] Offline (Reconnecting in background...)\n");
      WiFi.reconnect();
    }
  }
}
