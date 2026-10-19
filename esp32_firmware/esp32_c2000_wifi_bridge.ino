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

// ============================================================================
// 1. WI-FI & RENDER HOST CONFIGURATION
// ============================================================================
// Enter your real Wi-Fi or Mobile Hotspot credentials here:
const char* WIFI_SSID     = "Your_WiFi_Or_Hotspot_SSID";
const char* WIFI_PASSWORD = "Your_WiFi_Password";

// Live Render public endpoint (HTTPS port 443)
const char* RENDER_HOST   = "thermapulse-ev.onrender.com";
const char* API_KEY       = ""; // Empty if AURA_API_KEY is not set on Render

// ============================================================================
// 2. PIN DEFINITIONS & LED STATUS INDICATOR
// ============================================================================
#define RXD2 16      // Connect to C2000 GPIO 29 (SCIA_TX)
#define TXD2 17      // Connect to C2000 GPIO 28 (SCIA_RX)
#define LED_PIN 2    // Built-in Blue LED on ESP32 (Visual Status)

// Telemetry State - Ground Truth
struct TelemetryData {
  float voltage_v;
  float current_a;
  int   rpm;
  float temp_c;
  bool  temp_valid;
  unsigned long last_packet_time_ms;
  bool  has_received_packet;
} g_telem;

WiFiClientSecure g_secureClient;
HTTPClient       g_http;
String           g_ingestUrl;

unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL_MS = 1000;    // 1 Hz transmission
const unsigned long HARDWARE_TIMEOUT_MS = 3000;  // 3s timeout

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2);

  delay(500);
  Serial.println("\n========================================================");
  Serial.println("   THERMAPULSE EV - AUTONOMOUS STANDALONE ESP32 BRIDGE");
  Serial.println("========================================================");

  // Initialize Ground-Truth Telemetry
  g_telem.voltage_v = 0.0;
  g_telem.current_a = 0.0;
  g_telem.rpm       = 0;
  g_telem.temp_c    = -127.0;
  g_telem.temp_valid = false;
  g_telem.last_packet_time_ms = 0;
  g_telem.has_received_packet = false;

  g_secureClient.setInsecure();
  g_ingestUrl = String("https://") + RENDER_HOST + "/api/ingest";

  // Wi-Fi Setup with persistent auto-reconnect
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("[WiFi] Connecting to: %s\n", WIFI_SSID);

  // Blink LED rapidly while connecting
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    delay(300);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_PIN, HIGH); // Solid ON when connected
    Serial.println("\n[WiFi] Connected successfully!");
    Serial.print("[WiFi] IP: ");
    Serial.println(WiFi.localIP());
  } else {
    digitalWrite(LED_PIN, LOW);
    Serial.println("\n[WiFi] Connecting in background...");
  }
}

void loop() {
  // 1. Ingest Serial Packets from C2000 LaunchPad
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
      }
    }
  }

  // 2. 1 Hz Transmission to Render Cloud
  if (millis() - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = millis();

    if (WiFi.status() != WL_CONNECTED) {
      digitalWrite(LED_PIN, LOW); // LED OFF = Wi-Fi disconnected
      Serial.println("[WiFi] Reconnecting...");
      WiFi.reconnect();
      return;
    }

    // Ground-truth check: transmit fresh hardware telemetry
    bool isHardwareFresh = g_telem.has_received_packet &&
                           (millis() - g_telem.last_packet_time_ms <= HARDWARE_TIMEOUT_MS);

    if (isHardwareFresh) {
      sendTelemetryToHost();
    } else {
      // Wi-Fi is ready, but waiting for C2000 packets: keep LED solid ON
      digitalWrite(LED_PIN, HIGH);
    }
  }
}

void sendTelemetryToHost() {
  // Begin fresh connection with error isolation
  if (!g_http.begin(g_secureClient, g_ingestUrl)) {
    g_secureClient.stop();
    return;
  }

  g_http.setTimeout(7000);
  g_http.addHeader("Content-Type", "application/json");
  if (strlen(API_KEY) > 0) {
    g_http.addHeader("X-API-Key", API_KEY);
  }

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
    // Pulse LED: Turn OFF briefly (50ms) then back ON to show active cloud streaming!
    digitalWrite(LED_PIN, LOW);
    delay(50);
    digitalWrite(LED_PIN, HIGH);
  } else {
    // Force cleanup on failure or timeout so subsequent attempts never freeze
    g_secureClient.stop();
  }
  g_http.end();
}
