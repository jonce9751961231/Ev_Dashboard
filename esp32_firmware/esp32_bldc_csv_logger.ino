/**
 * ============================================================================
 * Project: 48V - 96V EV BLDC Motor Telemetry, CSV Logger & Web Server
 * Target Hardware: ESP32 Dev Module (ESP32-WROOM-32 / NodeMCU-32S)
 * Author: Antigravity Autonomous Systems
 * 
 * Features:
 *   1. 48V-96V Wide Range DC Bus Voltage Sensing (Scaled Voltage Divider + Clamping)
 *   2. High-Current Motor Phase/Bus Sensing (ACS758 / ACS770 Hall Sensor)
 *   3. Stator Winding Temperature (DS18B20 1-Wire Digital Sensor)
 *   4. BLDC Motor Speed (RPM) via Hall Sensor Pulse Interrupt
 *   5. CSV File Logging on ESP32 Internal Flash (LittleFS / SPIFFS)
 *   6. Real-Time CSV Streaming over USB Serial (115200 baud)
 *   7. Embedded Wi-Fi Web Server:
 *        - http://<ESP_IP>/              -> Live Cockpit Telemetry Webpage
 *        - http://<ESP_IP>/download_csv  -> One-Click CSV File Download
 *        - http://<ESP_IP>/api/live      -> JSON Telemetry Endpoint
 *        - http://<ESP_IP>/clear         -> Wipe & Reset CSV Log
 * ============================================================================
 * 
 * --- HARDWARE WIRING & CIRCUIT DIAGRAM ---
 * 
 * 1. 48V - 96V VOLTAGE DIVIDER (Max 115V DC Peak Charge):
 *    Battery (+) ----[ R1: 270 kOhm 1W ]----+----[ R2: 8.2 kOhm 0.25W ]---- Battery (-) / GND
 *                                           |
 *                                           +----[ 3.3V Zener Diode (Cathode) ] to GND (Anode)
 *                                           |     (Protection against over-voltage spikes)
 *                                           +----[ 100nF Ceramic Filter Cap ] to GND
 *                                           |
 *                                           +----> ESP32 GPIO 34 (ADC1_CH6)
 *    Division Ratio = R2 / (R1 + R2) = 8.2 / (270 + 8.2) = 0.029475
 *    At 115.0V Input -> ADC pin receives 115.0 * 0.029475 = 3.389V (Zener clamps at 3.3V)
 *    At 96.0V Input  -> ADC pin receives 2.83V (Safe for ESP32 ADC)
 *    At 48.0V Input  -> ADC pin receives 1.415V
 * 
 * 2. ACS758 / ACS770 CURRENT SENSOR (e.g. ACS758ECB-100B Bidirectional):
 *    VCC       ----> 5V (from ESP32 5V / VIN pin)
 *    GND       ----> GND
 *    VOUT      ----> ESP32 GPIO 35 (ADC1_CH7) via 2:1 divider or direct with calibration
 *    Sensitivity: 20 mV/A (for 100B), Zero Current VOUT = 2.5V (or VCC/2)
 * 
 * 3. DS18B20 1-WIRE TEMPERATURE SENSOR:
 *    VDD (Pin 3)  ----> 3.3V
 *    GND (Pin 1)  ----> GND
 *    DATA (Pin 2) ----> ESP32 GPIO 4 (with 4.7 kOhm pull-up resistor to 3.3V)
 * 
 * 4. BLDC HALL SENSOR (Motor Speed RPM):
 *    Hall A/B/C Out ----> ESP32 GPIO 18 (with internal/external pull-up, triggers RISING interrupt)
 * ============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <FS.h>
#include <LittleFS.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// --- Configuration & Constants ---
#define USE_LITTLEFS            1     // 1 = LittleFS (faster, reliable), 0 = SPIFFS
#define CSV_FILE_PATH           "/telemetry.csv"
#define LOG_INTERVAL_MS         200   // 5 Hz sampling rate (200 ms)

// --- Wi-Fi Settings ---
// Set to 1 to create an ESP32 Access Point (Connect phone/laptop directly to "ESP32_EV_TELEMETRY")
// Set to 0 to connect to your existing home/workshop Wi-Fi network
#define WIFI_AP_MODE            1     

const char* AP_SSID = "ESP32_EV_TELEMETRY";
const char* AP_PASS = "12345678";       // Minimum 8 characters

const char* STA_SSID = "YOUR_WIFI_SSID";
const char* STA_PASS = "YOUR_WIFI_PASSWORD";

// --- GPIO Pin Assignments ---
#define PIN_VOLTAGE_ADC         34    // GPIO34: 48V-96V Voltage Divider (ADC1)
#define PIN_CURRENT_ADC         35    // GPIO35: Current Sensor Analog In (ADC1)
#define PIN_ONE_WIRE_TEMP       4     // GPIO4:  DS18B20 1-Wire Stator Temp
#define PIN_HALL_SPEED_INT      18    // GPIO18: BLDC Motor Hall Pulse Interrupt
#define PIN_STATUS_LED          2     // GPIO2:  Onboard Blue Status LED

// --- Voltage Divider Calibration Factors ---
// Ratio = (R1 + R2) / R2 = (270k + 8.2k) / 8.2k = 33.9268
// ADC 12-bit: 0 to 4095 over 0 to 3.3V (ESP32 ADC is slightly non-linear, calibrated here)
const float VOLTAGE_DIVIDER_RATIO = 34.15f; 
const float ADC_REF_VOLTAGE       = 3.30f;
const int   ADC_RESOLUTION        = 4095;

// --- Current Sensor Calibration (ACS758 100B Bidirectional) ---
const float CURRENT_VREF_ZERO     = 2.50f;   // 2.5V = 0 Ampere
const float CURRENT_SENSITIVITY   = 0.020f;  // 20 mV per Ampere (for 100A bidirectional)

// --- Motor Kinematics (BLDC) ---
const int   MOTOR_POLE_PAIRS      = 4;       // 8-pole BLDC motor (4 electrical cycles / mechanical rev)

// --- Instances ---
OneWire oneWire(PIN_ONE_WIRE_TEMP);
DallasTemperature ds18b20(&oneWire);
WebServer server(80);

// --- Global Sensor Variables ---
volatile unsigned long g_hall_pulse_count = 0;
unsigned long g_last_hall_calc_time = 0;
float g_filtered_rpm = 0.0f;

float g_voltage_v = 72.0f;
float g_current_a = 0.0f;
float g_stator_temp_c = 30.0f;
float g_ambient_temp_c = 28.0f;
float g_power_w = 0.0f;

unsigned long g_last_sample_time = 0;
unsigned long g_record_count = 0;
bool g_is_logging = true;

// --- Interrupt Service Routine for BLDC Hall Sensor ---
void IRAM_ATTR onHallPulseISR() {
  g_hall_pulse_count++;
}

// --- Function Declarations ---
void initSensors();
void initFileSystem();
void initWiFiAndWebServer();
void sampleSensors();
void logTelemetryToCSV();
float calculateBLDCSpeedRPM();
void handleRoot();
void handleDownloadCSV();
void handleLiveAPI();
void handleClearCSV();

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n=======================================================");
  Serial.println("  48V - 96V EV BLDC MOTOR CSV LOGGER & TELEMETRY NODE  ");
  Serial.println("=======================================================");

  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, LOW);

  // 1. Initialize Sensors & Hall Interrupt
  initSensors();

  // 2. Initialize LittleFS Flash Storage
  initFileSystem();

  // 3. Setup Wi-Fi & Web Server
  initWiFiAndWebServer();

  Serial.println("[SYSTEM READY] Logging telemetry to CSV. Open web browser to download!");
  digitalWrite(PIN_STATUS_LED, HIGH);
}

void loop() {
  // Handle incoming HTTP client requests
  server.handleClient();

  unsigned long now = millis();

  // Sample and log at defined interval (e.g. 200 ms / 5 Hz)
  if (now - g_last_sample_time >= LOG_INTERVAL_MS) {
    g_last_sample_time = now;

    // 1. Read raw sensor inputs
    sampleSensors();

    // 2. Append to CSV file and stream over USB Serial
    if (g_is_logging) {
      logTelemetryToCSV();
    }
  }
}

/**
 * Initializes ADC pins, DS18B20 temp sensor, and BLDC Hall ISR
 */
void initSensors() {
  pinMode(PIN_VOLTAGE_ADC, INPUT);
  pinMode(PIN_CURRENT_ADC, INPUT);
  pinMode(PIN_HALL_SPEED_INT, INPUT_PULLUP);

  // Attach interrupt on Hall pulse rising edge
  attachInterrupt(digitalPinToInterrupt(PIN_HALL_SPEED_INT), onHallPulseISR, RISING);
  g_last_hall_calc_time = millis();

  // Initialize DS18B20
  ds18b20.begin();
  ds18b20.setResolution(11); // 11-bit: 0.125°C precision, 375ms conversion time
  ds18b20.setWaitForConversion(false); // Non-blocking
  ds18b20.requestTemperatures();

  Serial.println("[SENSORS] DS18B20, Voltage ADC, Current ADC & Hall ISR Initialized.");
}

/**
 * Initializes LittleFS and ensures CSV header exists
 */
void initFileSystem() {
  if (!LittleFS.begin(true)) {
    Serial.println("[LittleFS] Warning: Mount failed! Formatting...");
    LittleFS.format();
    LittleFS.begin();
  }

  // Check if CSV exists, if not create header
  if (!LittleFS.exists(CSV_FILE_PATH)) {
    File f = LittleFS.open(CSV_FILE_PATH, "w");
    if (f) {
      f.println("timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w");
      f.close();
      Serial.println("[LittleFS] Created fresh '" CSV_FILE_PATH "' with header.");
    }
  } else {
    File f = LittleFS.open(CSV_FILE_PATH, "r");
    if (f) {
      Serial.printf("[LittleFS] Existing CSV found. Current size: %u bytes\n", f.size());
      f.close();
    }
  }
}

/**
 * Configures Wi-Fi (AP mode or Station mode) and mounts Web Server routes
 */
void initWiFiAndWebServer() {
#if WIFI_AP_MODE
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  IPAddress IP = WiFi.softAPIP();
  Serial.print("[WiFi] Created Access Point: ");
  Serial.println(AP_SSID);
  Serial.print("[WiFi] Connect laptop/phone to AP and open: http://");
  Serial.println(IP);
#else
  WiFi.mode(WIFI_STA);
  WiFi.begin(STA_SSID, STA_PASS);
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(STA_SSID);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 20) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\n[WiFi] Connected! IP Address: http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Connection failed. Fallback to AP Mode.");
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    Serial.print("[WiFi] AP IP: http://");
    Serial.println(WiFi.softAPIP());
  }
#endif

  // Register Web Server Handlers
  server.on("/", HTTP_GET, handleRoot);
  server.on("/download_csv", HTTP_GET, handleDownloadCSV);
  server.on("/api/live", HTTP_GET, handleLiveAPI);
  server.on("/clear", HTTP_POST, handleClearCSV);

  server.begin();
  Serial.println("[WEB SERVER] HTTP Server running on Port 80.");
}

/**
 * Samples ADC channels, calculates DC bus voltage (48V-96V), current, RPM, and temperature
 */
void sampleSensors() {
  // 1. Calculate Motor Speed RPM from Hall Pulse Counter
  g_filtered_rpm = calculateBLDCSpeedRPM();

  // 2. Measure 48V-96V Bus Voltage (Averaged 16 ADC samples for stability)
  long raw_volt_sum = 0;
  for (int i = 0; i < 16; i++) {
    raw_volt_sum += analogRead(PIN_VOLTAGE_ADC);
  }
  float avg_volt_adc = (float)raw_volt_sum / 16.0f;
  float adc_voltage = (avg_volt_adc / ADC_RESOLUTION) * ADC_REF_VOLTAGE;
  g_voltage_v = adc_voltage * VOLTAGE_DIVIDER_RATIO;

  // Sanity clamp for display
  if (g_voltage_v < 0.0f) g_voltage_v = 0.0f;

  // 3. Measure Current from ACS758 / ACS770
  long raw_curr_sum = 0;
  for (int i = 0; i < 16; i++) {
    raw_curr_sum += analogRead(PIN_CURRENT_ADC);
  }
  float avg_curr_adc = (float)raw_curr_sum / 16.0f;
  float curr_sensor_volt = (avg_curr_adc / ADC_RESOLUTION) * ADC_REF_VOLTAGE;
  // Current in Amperes
  g_current_a = (curr_sensor_volt - CURRENT_VREF_ZERO) / CURRENT_SENSITIVITY;
  if (abs(g_current_a) < 0.25f) g_current_a = 0.0f; // Deadband filter

  // 4. Calculate Electrical Power (Watts)
  g_power_w = g_voltage_v * g_current_a;

  // 5. Read DS18B20 Stator Temperature
  if (ds18b20.isConversionComplete()) {
    float temp = ds18b20.getTempCByIndex(0);
    if (temp != DEVICE_DISCONNECTED_C && temp > -40.0f && temp < 150.0f) {
      g_stator_temp_c = temp;
    }
    // Request next non-blocking conversion
    ds18b20.requestTemperatures();
  }
}

/**
 * Computes BLDC motor speed in RPM from Hall pulses
 */
float calculateBLDCSpeedRPM() {
  unsigned long now = millis();
  unsigned long dt_ms = now - g_last_hall_calc_time;
  if (dt_ms == 0) return g_filtered_rpm;

  // Disable interrupts briefly to read and reset pulse counter safely
  noInterrupts();
  unsigned long pulses = g_hall_pulse_count;
  g_hall_pulse_count = 0;
  interrupts();

  g_last_hall_calc_time = now;

  // Pulses per revolution = Pole Pairs (or 3x for all 3 halls, here 1 hall channel used)
  // RPM = (Pulses / PolePairs) * (60000 / dt_ms)
  float raw_rpm = ((float)pulses / (float)MOTOR_POLE_PAIRS) * (60000.0f / (float)dt_ms);

  // Low-pass exponential smoothing filter
  g_filtered_rpm = (0.75f * g_filtered_rpm) + (0.25f * raw_rpm);
  if (g_filtered_rpm < 10.0f) g_filtered_rpm = 0.0f;

  return g_filtered_rpm;
}

/**
 * Appends the current telemetry frame to the LittleFS CSV file and streams over USB Serial
 */
void logTelemetryToCSV() {
  unsigned long now = millis();

  // Format CSV Row: timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w
  char csv_row[128];
  snprintf(csv_row, sizeof(csv_row), "%lu,%.2f,%.2f,%.0f,%.2f,%.2f,%.1f",
           now, g_voltage_v, g_current_a, g_filtered_rpm, 
           g_stator_temp_c, g_ambient_temp_c, g_power_w);

  // 1. Output to USB Serial (so Laptop or Web Serial API can capture in real time)
  Serial.println(csv_row);

  // 2. Append to LittleFS file
  File f = LittleFS.open(CSV_FILE_PATH, "a");
  if (f) {
    f.println(csv_row);
    f.close();
    g_record_count++;
  } else {
    Serial.println("[LittleFS] Error opening CSV file for append!");
  }
}

// ============================================================================
// --- WEB SERVER ENDPOINT HANDLERS ---
// ============================================================================

/**
 * Root handler: Serves a mobile-friendly status dashboard directly from ESP32
 */
void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta charset='UTF-8'>";
  html += "<meta name='viewport' content='width=device-width,initial-scale=1'>";
  html += "<title>ESP32 48V-96V BLDC Telemetry Node</title>";
  html += "<style>";
  html += "body{background:#090d16;color:#e2e8f0;font-family:system-ui,-apple-system,sans-serif;margin:0;padding:20px;text-align:center}";
  html += ".card{background:#131c2e;border:1px solid #1e293b;border-radius:16px;max-width:500px;margin:20px auto;padding:24px;box-shadow:0 10px 25px rgba(0,0,0,0.5)}";
  html += "h1{color:#38bdf8;font-size:22px;margin-bottom:8px}";
  html += ".grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0}";
  html += ".metric{background:#1e293b;padding:12px;border-radius:12px}";
  html += ".metric-title{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px}";
  html += ".metric-val{font-size:24px;font-weight:bold;color:#f8fafc;margin-top:4px}";
  html += ".btn{display:inline-block;padding:12px 24px;border-radius:10px;text-decoration:none;font-weight:bold;margin:6px;transition:0.2s;border:none;cursor:pointer}";
  html += ".btn-dl{background:#0284c7;color:#fff}.btn-dl:hover{background:#0369a1}";
  html += ".btn-clr{background:#dc2626;color:#fff}.btn-clr:hover{background:#b91c1c}";
  html += "</style></head><body>";
  
  html += "<div class='card'>";
  html += "<h1>⚡ 48V - 96V EV BLDC TELEMETRY</h1>";
  html += "<p style='color:#94a3b8;font-size:13px'>ESP32 Hardware Logger & CSV Data Generator</p>";

  html += "<div class='grid'>";
  html += "<div class='metric'><div class='metric-title'>DC Bus Voltage</div><div class='metric-val' style='color:#38bdf8'>" + String(g_voltage_v, 1) + " V</div></div>";
  html += "<div class='metric'><div class='metric-title'>Motor Current</div><div class='metric-val' style='color:#a855f7'>" + String(g_current_a, 1) + " A</div></div>";
  html += "<div class='metric'><div class='metric-title'>BLDC Speed</div><div class='metric-val' style='color:#34d399'>" + String(g_filtered_rpm, 0) + " RPM</div></div>";
  html += "<div class='metric'><div class='metric-title'>Stator Winding</div><div class='metric-val' style='color:#f97316'>" + String(g_stator_temp_c, 1) + " °C</div></div>";
  html += "</div>";

  html += "<div style='margin-bottom:18px;font-size:13px;color:#cbd5e1'>";
  html += "Records Logged: <b>" + String(g_record_count) + "</b> | System Uptime: <b>" + String(millis() / 1000) + "s</b>";
  html += "</div>";

  html += "<div>";
  html += "<a href='/download_csv' class='btn btn-dl'>📥 Download telemetry.csv</a>";
  html += "<form method='POST' action='/clear' style='display:inline;' onsubmit='return confirm(\"Wipe recorded CSV telemetry?\")'>";
  html += "<button type='submit' class='btn btn-clr'>🗑️ Clear CSV</button>";
  html += "</form>";
  html += "</div>";

  html += "</div>";
  html += "<script>setTimeout(() => { if(!document.hidden) location.reload(); }, 2000);</script>";
  html += "</body></html>";

  server.send(200, "text/html", html);
}

/**
 * Downloads the accumulated telemetry CSV directly as an attachment
 */
void handleDownloadCSV() {
  if (!LittleFS.exists(CSV_FILE_PATH)) {
    server.send(404, "text/plain", "CSV file not found or empty.");
    return;
  }

  File f = LittleFS.open(CSV_FILE_PATH, "r");
  if (!f) {
    server.send(500, "text/plain", "Failed to open CSV file.");
    return;
  }

  server.sendHeader("Content-Disposition", "attachment; filename=bldc_telemetry.csv");
  server.streamFile(f, "text/csv");
  f.close();
  Serial.println("[Web Server] Served 'bldc_telemetry.csv' to client download.");
}

/**
 * Live JSON API endpoint
 */
void handleLiveAPI() {
  String json = "{";
  json += "\"uptime_ms\":" + String(millis()) + ",";
  json += "\"voltage_v\":" + String(g_voltage_v, 2) + ",";
  json += "\"current_a\":" + String(g_current_a, 2) + ",";
  json += "\"speed_rpm\":" + String(g_filtered_rpm, 1) + ",";
  json += "\"stator_temp_c\":" + String(g_stator_temp_c, 2) + ",";
  json += "\"ambient_temp_c\":" + String(g_ambient_temp_c, 2) + ",";
  json += "\"power_w\":" + String(g_power_w, 1) + ",";
  json += "\"records_count\":" + String(g_record_count);
  json += "}";
  server.send(200, "application/json", json);
}

/**
 * Wipes the existing CSV file and writes a fresh header
 */
void handleClearCSV() {
  File f = LittleFS.open(CSV_FILE_PATH, "w");
  if (f) {
    f.println("timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w");
    f.close();
    g_record_count = 0;
    Serial.println("[LittleFS] CSV file wiped and reset.");
  }
  server.sendHeader("Location", "/");
  server.send(303);
}
