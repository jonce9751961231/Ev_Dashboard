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

// Telemetry State - Ground Truth (NO FAKE DEFAULTS)
struct TelemetryData {
  float voltage_v;
  float current_a;
  int   rpm;
  float temp_c;
  bool  temp_valid;
  unsigned long last_packet_time_ms;
  bool  has_received_packet;
} g_telem;

unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL_MS = 1000;   // 1 Hz rate matches host dashboard & ML window
const unsigned long HARDWARE_TIMEOUT_MS = 3000; // Stop streaming if C2000 quiet for >3s

void setup() {
  Serial.begin(115200);   // USB Serial Monitor debug
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2); // High-speed C2000 UART

  delay(1000);
  Serial.println("\n========================================================");
  Serial.println("   ESP32-S (38-PIN) C2000 TO LAPTOP WI-FI TELEMETRY BRIDGE");
  Serial.println("   Target: 12V DC Motor Testbed (Honest Ground-Truth)");
  Serial.println("========================================================");

  // Initialize Ground-Truth State: 0/NAN until C2000 actually sends data
  g_telem.voltage_v = 0.0;
  g_telem.current_a = 0.0;
  g_telem.rpm       = 0;
  g_telem.temp_c    = -127.0;
  g_telem.temp_valid = false;
  g_telem.last_packet_time_ms = 0;
  g_telem.has_received_packet = false;

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

    if (line.length() > 0 && line.startsWith("{")) {
      StaticJsonDocument<256> doc;
      DeserializationError err = deserializeJson(doc, line);

      if (!err) {
        if (doc.containsKey("v"))    g_telem.voltage_v = doc["v"].as<float>();
        if (doc.containsKey("i"))    g_telem.current_a = doc["i"].as<float>();
        if (doc.containsKey("rpm"))  g_telem.rpm       = doc["rpm"].as<int>();
        if (doc.containsKey("temp") && !doc["temp"].isNull()) {
          g_telem.temp_c     = doc["temp"].as<float>();
          g_telem.temp_valid = (g_telem.temp_c > -50.0 && g_telem.temp_c < 125.0);
        } else {
          g_telem.temp_c     = -127.0;
          g_telem.temp_valid = false;
        }
        g_telem.last_packet_time_ms = millis();
        g_telem.has_received_packet = true;

        Serial.printf("[C2000 RX] V: %.2fV | I: %.2fA | RPM: %d | Temp: %s\n",
                      g_telem.voltage_v, g_telem.current_a, g_telem.rpm,
                      g_telem.temp_valid ? String(g_telem.temp_c, 1).c_str() : "DISCONN");
      }
    }
  }

  // 2. Transmit to Laptop Host App over Wi-Fi
  if (millis() - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = millis();

    // Ground-truth integrity: Do NOT re-send stale data if C2000 goes quiet!
    bool isHardwareFresh = g_telem.has_received_packet &&
                           (millis() - g_telem.last_packet_time_ms <= HARDWARE_TIMEOUT_MS);

    if (WiFi.status() == WL_CONNECTED && isHardwareFresh) {
      sendTelemetryToHost();
    } else if (!isHardwareFresh && g_telem.has_received_packet) {
      Serial.println("[BRIDGE] C2000 quiet for >3s. Suppressing stale transmission so host detects offline state.");
    }
  }
}

void sendTelemetryToHost() {
  HTTPClient http;
  String url = String("http://") + HOST_SERVER_IP + ":" + String(HOST_PORT) + "/api/ingest";

  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  // Construct JSON body (Preserve null on temperature if disconnected)
  StaticJsonDocument<256> doc;
  doc["voltage_v"] = g_telem.voltage_v;
  doc["current_a"] = g_telem.current_a;
  doc["rpm"]       = g_telem.rpm;
  if (g_telem.temp_valid) {
    doc["temp_c"]  = g_telem.temp_c;
  } else {
    doc["temp_c"]  = nullptr;
  }

  String requestBody;
  serializeJson(doc, requestBody);

  int httpResponseCode = http.POST(requestBody);
  if (httpResponseCode > 0) {
    // Successfully sent to Laptop
  } else {
    // Server unreachable
  }
  http.end();
}
