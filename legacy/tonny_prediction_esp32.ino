/******************************************************************************
 * Project: EV Predictive Dashboard (AURA EV Cockpit)
 * Sketch: ESP32_ALL_SENSORS.ino
 * Target Board: ESP-WROOM-32 / ESP32 Dev Module (38-Pin NodeMCU ESP-32S V1.1)
 * Description: Directly reads all 4 sensors on ESP32:
 *              1. 0-25V Voltage Divider Sensor (GPIO 34 / P34)
 *              2. ACS712 5A Current Sensor (GPIO 35 / P35)
 *              3. LM393 Optical RPM Encoder (GPIO 18 / P18 - Interrupt)
 *              4. Dallas DS18B20 1-Wire Temperature Sensor (GPIO 4 / P4)
 *              Outputs formatted JSON on Serial (USB COM17) at 115200 baud
 *              for Thonny IDE or Python.
 ******************************************************************************/

#include <OneWire.h>
#include <DallasTemperature.h>

// ============================================================================
// 1. PIN DEFINITIONS ON ESP32 (38-Pin Board)
// ============================================================================
#define PIN_VOLTAGE   34   // ADC1_CH6: 0-25V Voltage Divider Signal (P34)
#define PIN_CURRENT   35   // ADC1_CH7: ACS712 5A Current Sensor OUT (P35)
#define PIN_SPEED     18   // GPIO 18 : LM393 Optical Sensor D0 (P18 - Interrupt)
#define PIN_TEMP      4    // GPIO 4  : DS18B20 1-Wire Data (P4 - internal pullup enabled)

// ============================================================================
// 2. HARDWARE CALIBRATION CONSTANTS
// ============================================================================
// Voltage Sensor: 30k / 7.5k divider ratio = 5.0
const float VOLTAGE_DIVIDER_RATIO = 5.0f;

// ACS712 5A: Sensitivity is 185 mV/A (0.185 V/A), Quiescent VCC/2 = 2.50V
const float ACS712_SENSITIVITY = 0.185f;
const float ACS712_VREF        = 2.50f;

// LM393 Encoder: Standard optical wheel has 20 slots
const int ENCODER_SLOTS = 20;

// Setup OneWire & DallasTemperature
OneWire oneWire(PIN_TEMP);
DallasTemperature sensors(&oneWire);

// Speed pulse counting variables
volatile unsigned long pulseCount = 0;
unsigned long lastCalcTime = 0;
float currentRPM = 0.0f;

// Interrupt Service Routine for LM393 Optical Sensor
void IRAM_ATTR countPulse() {
  pulseCount++;
}

void setup() {
  // Initialize Serial Monitor (115200 baud)
  Serial.begin(115200);
  delay(1000);

  // Configure Analog Pins (12-bit ADC, 0-4095, 3.3V range)
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db); // Full 0-3.3V range

  // Configure Optical Speed Interrupt
  pinMode(PIN_SPEED, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_SPEED), countPulse, FALLING);

  // Start DS18B20 Temperature Sensor (enables internal pull-up so external resistor is optional)
  pinMode(PIN_TEMP, INPUT_PULLUP);
  sensors.begin();

  lastCalcTime = millis();
}

void loop() {
  // Sample every 500 ms (2 Hz)
  if (millis() - lastCalcTime >= 500) {
    unsigned long dt = millis() - lastCalcTime;
    lastCalcTime = millis();

    // 1. Calculate Motor RPM from pulse count
    noInterrupts();
    unsigned long count = pulseCount;
    pulseCount = 0;
    interrupts();

    currentRPM = ((float)count / (float)ENCODER_SLOTS) * (60000.0f / (float)dt);

    // 2. Read Voltage Sensor (GPIO 34 / P34)
    int rawVolt = analogRead(PIN_VOLTAGE);
    float v_pin = ((float)rawVolt / 4095.0f) * 3.3f;
    float voltage_v = v_pin * VOLTAGE_DIVIDER_RATIO;
    if (voltage_v < 0.1f) voltage_v = 0.0f;

    // 3. Read Current Sensor (GPIO 35 / P35) - ACS712 5A
    int rawCurr = analogRead(PIN_CURRENT);
    float i_pin = ((float)rawCurr / 4095.0f) * 3.3f;
    float current_a = (i_pin - ACS712_VREF) / ACS712_SENSITIVITY;
    if (current_a < 0.0f) current_a = 0.0f;

    // 4. Read Temperature Sensor (GPIO 4 / P4) - DS18B20
    sensors.requestTemperatures();
    float temp_c = sensors.getTempCByIndex(0);
    if (temp_c == DEVICE_DISCONNECTED_C || temp_c < -50.0f) {
      temp_c = 28.5f; // Fallback ambient reading if disconnected
    }

    // 5. Output JSON telemetry string over USB Serial for Thonny
    // Format: {"v":12.10,"i":2.20,"rpm":2150,"temp":34.5}
    Serial.printf("{\"v\":%.2f,\"i\":%.2f,\"rpm\":%d,\"temp\":%.1f}\n",
                  voltage_v, current_a, (int)currentRPM, temp_c);
  }
}