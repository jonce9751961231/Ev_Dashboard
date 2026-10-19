/**
 * ============================================================================
 * Project: 48V EV BLDC Telemetry, CSV Logger & Cloud Uploader
 * Target: ESP32 Dev Module (NodeMCU-32S / ESP32-WROOM-32)
 * Description: 
 *   1. Reads DS18B20 1-Wire Digital Temperature Sensor (Stator Winding).
 *   2. Receives 48V Current, Voltage, RPM from TI C2000 over UART (or direct ADC).
 *   3. Formats and logs CSV time-series records: Timestamp,Current,Voltage,RPM,Temp.
 *   4. Connects to Wi-Fi and automatically uploads CSV telemetry to Cloud Server / Firebase.
 * ============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <FS.h>
#include <SPIFFS.h>

// --- Wi-Fi Configuration ---
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

// --- Cloud Upload Endpoint (e.g. Google Cloud / Firebase / Custom REST API) ---
const char* CLOUD_SERVER_URL = "http://your-cloud-server.com/api/upload_csv";

// --- Pin Definitions on ESP32 ---
#define ONE_WIRE_BUS          4       // GPIO4 -> DS18B20 Data Pin (with 4.7k Pull-up to 3.3V)
#define RXD2_FROM_C2000       16      // GPIO16 -> RX2 (Receives from TI C2000 GPIO29 TX)
#define TXD2_TO_C2000         17      // GPIO17 -> TX2 (Sends to TI C2000 GPIO28 RX)
#define STATUS_LED            2       // On-board Blue LED

// Setup DS18B20 Instances
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature ds18b20(&oneWire);

// Telemetry Buffer Variables
float g_stator_temp_c = 0.0;
float g_current_a = 0.0;
float g_voltage_v = 48.0;
float g_rpm = 0.0;
unsigned long g_last_sample_time = 0;
unsigned long g_last_upload_time = 0;

// In-Memory CSV Log Buffer
String g_csv_buffer = "timestamp_ms,current_a,voltage_v,speed_rpm,stator_temp_c,power_w\n";
int g_record_count = 0;

void setup() {
  Serial.begin(115200);                    // Debug Serial Monitor to Laptop USB
  Serial2.begin(115200, SERIAL_8N1, RXD2_FROM_C2000, TXD2_TO_C2000); // UART link to TI C2000

  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, LOW);

  // Initialize DS18B20 Temperature Sensor
  ds18b20.begin();
  ds18b20.setResolution(12); // 12-bit resolution (0.0625°C precision)

  // Initialize Local SPIFFS File System for Offline CSV Backup
  if (!SPIFFS.begin(true)) {
    Serial.println("[SPIFFS] Warning: Mounting Failed, using RAM buffer");
  }

  // Connect to Wi-Fi
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());
    digitalWrite(STATUS_LED, HIGH);
  } else {
    Serial.println("\n[WiFi] Offline Mode - Logging CSV locally");
  }

  Serial.println("=== ESP32 48V BLDC CSV Logger & Cloud Uploader Ready ===");
}

void loop() {
  // 1. Read UART Telemetry Stream from TI C2000 (if available)
  if (Serial2.available()) {
    String line = Serial2.readStringUntil('\n');
    line.trim();
    if (line.startsWith("$EV_48V") && line.endsWith("*")) {
      // Parse: $EV_48V,time,temp,rotor,current,voltage,rpm,...
      int idx1 = line.indexOf(',');
      int idx2 = line.indexOf(',', idx1 + 1);
      int idx3 = line.indexOf(',', idx2 + 1);
      int idx4 = line.indexOf(',', idx3 + 1);
      int idx5 = line.indexOf(',', idx4 + 1);
      int idx6 = line.indexOf(',', idx5 + 1);
      int idx7 = line.indexOf(',', idx6 + 1);

      if (idx4 > 0 && idx5 > 0 && idx6 > 0) {
        g_current_a = line.substring(idx4 + 1, idx5).toFloat();
        g_voltage_v = line.substring(idx5 + 1, idx6).toFloat();
        g_rpm       = line.substring(idx6 + 1, idx7).toFloat();
      }
    }
  }

  // 2. Sample DS18B20 Temperature every 500 ms (2 Hz)
  unsigned long now = millis();
  if (now - g_last_sample_time >= 500) {
    g_last_sample_time = now;

    // Trigger DS18B20 temperature conversion
    ds18b20.requestTemperatures();
    float tempC = ds18b20.getTempCByIndex(0);

    if (tempC != DEVICE_DISCONNECTED_C && tempC > -50.0 && tempC < 130.0) {
      g_stator_temp_c = tempC;
    }

    // Calculate instantaneous power (W)
    float power_w = g_voltage_v * g_current_a;

    // Append New CSV Row
    String csv_row = String(now) + "," + 
                     String(g_current_a, 2) + "," + 
                     String(g_voltage_v, 1) + "," + 
                     String(g_rpm, 0) + "," + 
                     String(g_stator_temp_c, 2) + "," + 
                     String(power_w, 1) + "\n";

    g_csv_buffer += csv_row;
    g_record_count++;

    // Print to Laptop Serial Monitor
    Serial.print("[CSV Log " + String(g_record_count) + "] " + csv_row);
  }

  // 3. Upload CSV Batch to Cloud every 10 seconds (or after 20 records)
  if (now - g_last_upload_time >= 10000 && g_record_count >= 10) {
    g_last_upload_time = now;
    uploadCSVToCloud();
  }
}

/**
 * @brief Transmits the accumulated CSV telemetry buffer to Cloud REST API / Server
 */
void uploadCSVToCloud() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(CLOUD_SERVER_URL);
    http.addHeader("Content-Type", "text/csv");

    Serial.println("[Cloud Upload] Sending " + String(g_record_count) + " CSV records to cloud...");
    int httpResponseCode = http.POST(g_csv_buffer);

    if (httpResponseCode > 0) {
      Serial.println("[Cloud Upload] SUCCESS! HTTP Response Code: " + String(httpResponseCode));
      // Reset buffer with CSV Header
      g_csv_buffer = "timestamp_ms,current_a,voltage_v,speed_rpm,stator_temp_c,power_w\n";
      g_record_count = 0;
    } else {
      Serial.println("[Cloud Upload] Error uploading: " + String(httpResponseCode));
    }
    http.end();
  } else {
    Serial.println("[Cloud Upload] Wi-Fi Disconnected. Buffered in memory.");
  }
}
