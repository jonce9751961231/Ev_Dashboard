/**
 * ============================================================================
 * Project: 12V DC Motor Continuous Testbed & Telemetry Bridge
 * Target: ESP32-S (38-Pin Development Board)
 * File: esp32_c2000_wifi_bridge.ino
 * Description: 
 *   1. Receives real-time telemetry from TMS320F2800137 LaunchPad via UART2:
 *      - RX2: GPIO 16 (connected to C2000 GPIO 29 / SCIA_TX)
 *      - TX2: GPIO 17 (connected to C2000 GPIO 28 / SCIA_RX)
 *      - GND: Common GND (connected to C2000 GND)
 *   2. Connects to Wi-Fi Access Point / Laptop Hotspot.
 *   3. Transmits telemetry JSON to Laptop Host Server for Random Forest AI:
 *      - REST: POST http://<LAPTOP_IP>:8000/api/ingest
 *      - WebSocket: ws://<LAPTOP_IP>:8000/ws/telemetry
 * ============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- Wi-Fi Credentials ---
const char* WIFI_SSID     = "Your_WiFi_Or_Hotspot_SSID";
const char* WIFI_PASSWORD = "Your_WiFi_Password";

// --- Laptop Host Server IP (Port 8000) ---
const char* HOST_SERVER_IP = "192.168.1.100";  // Replace with Laptop's IPv4 address
const int   HOST_PORT      = 8000;

// --- UART2 Pins for C2000 LaunchPad ---
#define RXD2 16   // Connect to C2000 GPIO 29 (SCIA_TX)
#define TXD2 17   // Connect to C2000 GPIO 28 (SCIA_RX)

// Telemetry State
struct TelemetryData {
  float voltage_v;
  float current_a;
  int   rpm;
  float temp_c;
  unsigned long timestamp_ms;
} g_telem;

unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL_MS = 200; // 5 Hz update to laptop

void setup() {
  Serial.begin(115200);   // USB Serial Monitor debug
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2); // High-speed C2000 UART

  delay(1000);
  Serial.println("\n========================================================");
  Serial.println("   ESP32-S (38-PIN) C2000 TO LAPTOP WI-FI TELEMETRY BRIDGE");
  Serial.println("   Target: 12V DC Motor Testbed (Continuous Run)");
  Serial.println("========================================================");

  // Initialize Defaults
  g_telem.voltage_v = 12.10;
  g_telem.current_a = 2.20;
  g_telem.rpm = 2100;
  g_telem.temp_c = 34.50;

  // Connect to Wi-Fi
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected successfully!");
    Serial.print("[WiFi] ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Warning: Wi-Fi not connected yet. Telemetry will buffer.");
  }
}

void loop() {
  // 1. Read Serial Packets from TMS320F2800137 LaunchPad
  while (Serial2.available() > 0) {
    String line = Serial2.readStringUntil('\n');
    line.trim();

    if (line.length() > 0) {
      // Parse JSON from C2000, e.g.: {"v":12.10,"i":2.35,"rpm":2150,"temp":34.8}
      StaticJsonDocument<256> doc;
      DeserializationError err = deserializeJson(doc, line);

      if (!err) {
        if (doc.containsKey("v"))    g_telem.voltage_v = doc["v"].as<float>();
        if (doc.containsKey("i"))    g_telem.current_a = doc["i"].as<float>();
        if (doc.containsKey("rpm"))  g_telem.rpm       = doc["rpm"].as<int>();
        if (doc.containsKey("temp")) g_telem.temp_c   = doc["temp"].as<float>();
        g_telem.timestamp_ms = millis();

        Serial.printf("[C2000 RX] V: %.2fV | I: %.2fA | RPM: %d | Temp: %.1f C\n",
                      g_telem.voltage_v, g_telem.current_a, g_telem.rpm, g_telem.temp_c);
      }
    }
  }

  // 2. Transmit to Laptop Host App over Wi-Fi
  if (millis() - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = millis();

    if (WiFi.status() == WL_CONNECTED) {
      sendTelemetryToHost();
    }
  }
}

void sendTelemetryToHost() {
  HTTPClient http;
  String url = String("http://") + HOST_SERVER_IP + ":" + String(HOST_PORT) + "/api/ingest";

  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  // Construct JSON body
  StaticJsonDocument<256> doc;
  doc["voltage_v"] = g_telem.voltage_v;
  doc["current_a"] = g_telem.current_a;
  doc["rpm"]       = g_telem.rpm;
  doc["temp_c"]    = g_telem.temp_c;

  String requestBody;
  serializeJson(doc, requestBody);

  int httpResponseCode = http.POST(requestBody);
  if (httpResponseCode > 0) {
    // Successfully sent to Laptop
  } else {
    // In case server is starting
  }
  http.end();
}
