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
 *   2. Connects to your Wi-Fi network (needs internet access).
 *   3. Posts the telemetry JSON once per second over HTTPS to the public
 *      Render website:   POST https://<RENDER_HOST>/api/ingest
 *      Everyone who opens the website then sees the live readings.
 *
 * SETUP: fill in WIFI_SSID, WIFI_PASSWORD, RENDER_HOST and API_KEY below.
 *   RENDER_HOST = your Render address WITHOUT "https://", e.g. thermapulse-ev.onrender.com
 *   API_KEY     = the AURA_API_KEY value shown in Render > Environment
 * ============================================================================
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- Wi-Fi Credentials ---
const char* WIFI_SSID     = "Your_WiFi_Or_Hotspot_SSID";
const char* WIFI_PASSWORD = "Your_WiFi_Password";

// --- Render website (HTTPS, port 443) ---
const char* RENDER_HOST = "thermapulse-ev.onrender.com";   // Live Render website URL
const char* API_KEY     = ""; // Unset on Render, leave empty

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

// One TLS connection is kept open and reused, because a new HTTPS handshake
// every second is slow and uses a lot of ESP32 memory.
WiFiClientSecure g_secureClient;
HTTPClient       g_http;
String           g_ingestUrl;

unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL_MS = 1000;   // 1 Hz rate matches host dashboard & ML window
const unsigned long HARDWARE_TIMEOUT_MS = 3000; // Stop streaming if C2000 quiet for >3s

void setup() {
  Serial.begin(115200);   // USB Serial Monitor debug
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2); // High-speed C2000 UART

  delay(1000);
  Serial.println("\n========================================================");
  Serial.println("   ESP32-S (38-PIN) C2000 TO RENDER WEBSITE TELEMETRY BRIDGE");
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

  // HTTPS client setup.
  // setInsecure() encrypts the traffic but does not verify the server certificate.
  // That is fine for this project; for stricter security pin Render's root CA instead.
  g_secureClient.setInsecure();
  g_http.setReuse(true);          // keep the TLS connection open between posts
  g_http.setTimeout(8000);        // Render's free tier can take a while to wake up
  g_ingestUrl = String("https://") + RENDER_HOST + "/api/ingest";

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
    Serial.print("[CLOUD] Posting to: ");
    Serial.println(g_ingestUrl);
  } else {
    Serial.println("\n[WiFi] Warning: Wi-Fi not connected yet. Will keep retrying.");
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

  // 2. Transmit to the Render website over Wi-Fi
  if (millis() - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = millis();

    // Ground-truth integrity: Do NOT re-send stale data if C2000 goes quiet!
    bool isHardwareFresh = g_telem.has_received_packet &&
                           (millis() - g_telem.last_packet_time_ms <= HARDWARE_TIMEOUT_MS);

    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] Disconnected - reconnecting...");
      WiFi.reconnect();
    } else if (isHardwareFresh) {
      sendTelemetryToHost();
    } else if (g_telem.has_received_packet) {
      Serial.println("[BRIDGE] C2000 quiet for >3s. Suppressing stale transmission so the website shows hardware offline.");
    }
  }
}

void sendTelemetryToHost() {
  g_http.begin(g_secureClient, g_ingestUrl);
  g_http.addHeader("Content-Type", "application/json");
  g_http.addHeader("X-API-Key", API_KEY);

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

  int code = g_http.POST(requestBody);
  if (code == 200) {
    // Delivered - the website now shows this reading.
  } else if (code == 401) {
    Serial.println("[CLOUD] 401 Unauthorized: API_KEY does not match AURA_API_KEY on Render.");
  } else if (code == 422) {
    Serial.println("[CLOUD] 422 Rejected: a sensor value was missing (is the DS18B20 connected?).");
  } else if (code > 0) {
    Serial.printf("[CLOUD] Server answered HTTP %d\n", code);
  } else {
    Serial.printf("[CLOUD] Post failed: %s (Render may be waking up; retrying)\n",
                  g_http.errorToString(code).c_str());
  }
  g_http.end();
}
