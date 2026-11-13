/*
 * PRISMA — gateway ESP32-S3 (protótipo, ainda não validado fisicamente).
 * DEMOEM SCI -> UART RX -> USB CDC (PRISMA desktop), painel HTTP, MQTT/TLS.
 * Nenhuma amostra elétrica é gerada aqui; só aceita dados vindos da placa.
 * Não confundir o painel HTML touch com driver de tela TFT física.
 */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <math.h>
#include <time.h>
#include "dashboard.h"

#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef PRISMA_WIFI_SSID
#define PRISMA_WIFI_SSID ""
#endif
#ifndef PRISMA_WIFI_PASSWORD
#define PRISMA_WIFI_PASSWORD ""
#endif
#ifndef PRISMA_MQTT_HOST
#define PRISMA_MQTT_HOST ""
#endif
#ifndef PRISMA_MQTT_PORT
#define PRISMA_MQTT_PORT 8883
#endif
#ifndef PRISMA_MQTT_USER
#define PRISMA_MQTT_USER ""
#endif
#ifndef PRISMA_MQTT_PASSWORD
#define PRISMA_MQTT_PASSWORD ""
#endif
#ifndef PRISMA_MQTT_CA_PEM
#define PRISMA_MQTT_CA_PEM ""
#endif
#ifndef PRISMA_UART_RX_GPIO
#define PRISMA_UART_RX_GPIO -1
#endif
#ifndef PRISMA_VBAT_ADC_GPIO
#define PRISMA_VBAT_ADC_GPIO -1
#endif
#ifndef PRISMA_VBAT_DIVIDER_RATIO
#define PRISMA_VBAT_DIVIDER_RATIO 2.0f
#endif

namespace {
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t WINDOW_MS = 1000;
constexpr uint32_t STALE_MS = 3500;
constexpr size_t LINE_MAX = 512;
HardwareSerial boardSerial(1);
WebServer web(80);
WiFiClientSecure tls;
PubSubClient mqtt(tls);
bool uartEnabled = false;
bool wifiAttempted = false;
bool clockStarted = false;
unsigned long lastWiFiTry = 0, lastMqttTry = 0, lastWindow = 0;
unsigned long lastSample = 0;
uint32_t sampleCount = 0, invalidCount = 0, overflowCount = 0;
uint32_t usbDropped = 0, backwardTimeCount = 0;
uint32_t mqttSent = 0, mqttFailed = 0;
bool hasTimestamp = false;
double previousTimestamp = 0;
char id[32] = {}, topic[96] = {};
char incoming[LINE_MAX + 1] = {};
size_t incomingLength = 0;
bool discardLine = false;

struct Window {
  double v[3] = {}, v2[3] = {}, i[3] = {}, i2[3] = {}, vi[3] = {};
  uint32_t count = 0, withCurrent = 0;
} windowData;

struct Summary {
  double vrms[3] = {}, irms[3] = {}, power[3] = {};
  double sourceTime = 0;
  uint32_t count = 0;
  bool currentValid = false, valid = false;
} summary;

bool finiteNumber(JsonVariantConst value) {
  if (value.isNull() || value.is<bool>()) return false;
  if (!(value.is<int>() || value.is<unsigned int>() || value.is<long>() ||
        value.is<unsigned long>() || value.is<float>() || value.is<double>()))
    return false;
  return isfinite(value.as<double>());
}

bool validSample(JsonDocument &doc) {
  if (!finiteNumber(doc["t"]) || !finiteNumber(doc["va"]) ||
      !finiteNumber(doc["vb"]) || !finiteNumber(doc["vc"])) return false;
  const bool a = !doc["ia"].isNull();
  const bool b = !doc["ib"].isNull();
  const bool c = !doc["ic"].isNull();
  if ((a != b) || (b != c)) return false;
  return !a || (finiteNumber(doc["ia"]) && finiteNumber(doc["ib"]) &&
                finiteNumber(doc["ic"]));
}

void record(const JsonDocument &doc) {
  const double t = doc["t"].as<double>();
  if (hasTimestamp && t <= previousTimestamp) {
    // Reset do relógio da placa ou amostra repetida: não misturar janelas.
    ++backwardTimeCount;
    windowData = Window();
    summary.valid = false;
  }
  hasTimestamp = true;
  previousTimestamp = t;
  lastSample = millis();
  ++sampleCount;
  const double v[3] = {
    doc["va"].as<double>(), doc["vb"].as<double>(), doc["vc"].as<double>()
  };
  const bool currents = !doc["ia"].isNull();
  double i[3] = {};
  if (currents) {
    i[0] = doc["ia"].as<double>();
    i[1] = doc["ib"].as<double>();
    i[2] = doc["ic"].as<double>();
  }
  for (unsigned p = 0; p != 3; ++p) {
    windowData.v[p] += v[p];
    windowData.v2[p] += v[p] * v[p];
    if (currents) {
      windowData.i[p] += i[p];
      windowData.i2[p] += i[p] * i[p];
      windowData.vi[p] += v[p] * i[p];
    }
  }
  ++windowData.count;
  if (currents) ++windowData.withCurrent;
}

void receiveLine(const char *line, size_t length) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, line, length);
  if (error || !doc.is<JsonObject>() || !doc["type"].is<const char *>()) {
    ++invalidCount;
    return;
  }
  const char *type = doc["type"];
  if (strcmp(type, "sample") == 0) {
    if (!validSample(doc)) {
      ++invalidCount;
      return;
    }
    record(doc);
  } else if (strcmp(type, "status") != 0) {
    ++invalidCount;
    return;
  }
  // Encaminha JSON intacto; nenhum texto de debug pela USB CDC.
  if (Serial && Serial.availableForWrite() >= static_cast<int>(length + 1)) {
    Serial.write(reinterpret_cast<const uint8_t *>(line), length);
    Serial.write('\n');
  } else {
    ++usbDropped;  // permite diagnosticar queda/backpressure
  }
}

void pollUart() {
  if (!uartEnabled) return;
  unsigned budget = 4096;
  while (budget-- && boardSerial.available()) {
    const int byte = boardSerial.read();
    if (byte == '\n') {
      if (!discardLine && incomingLength) {
        incoming[incomingLength] = '\0';
        receiveLine(incoming, incomingLength);
      }
      incomingLength = 0;
      discardLine = false;
    } else if (byte == '\r') {
      continue;
    } else if (!discardLine) {
      if (incomingLength < LINE_MAX) {
        incoming[incomingLength++] = static_cast<char>(byte);
      } else {
        ++overflowCount;
        incomingLength = 0;
        discardLine = true;
      }
    }
  }
}

bool fresh() {
  return summary.valid && sampleCount &&
         millis() - lastSample < STALE_MS;
}

void closeWindow() {
  if (windowData.count >= 10) {
    const double n = windowData.count;
    summary.count = windowData.count;
    summary.sourceTime = previousTimestamp;
    summary.currentValid = windowData.withCurrent == windowData.count;
    for (unsigned p = 0; p != 3; ++p) {
      const double meanV = windowData.v[p] / n;
      const double v2 = windowData.v2[p] / n - meanV * meanV;
      summary.vrms[p] = sqrt(fmax(0.0, v2)); // RMS AC, sem componente DC
      if (summary.currentValid) {
        const double meanI = windowData.i[p] / n;
        const double i2 = windowData.i2[p] / n - meanI * meanI;
        summary.irms[p] = sqrt(fmax(0.0, i2));
        summary.power[p] = windowData.vi[p] / n - meanV * meanI;
      }
    }
    summary.valid = true;
  } else {
    summary.valid = false;
  }
  windowData = Window();
}

bool brokerConfigured() {
  // sem credenciais e CA, MQTT fica desligado (nunca inseguro)
  return PRISMA_MQTT_HOST[0] && PRISMA_MQTT_USER[0] &&
         PRISMA_MQTT_PASSWORD[0] && PRISMA_MQTT_CA_PEM[0];
}

void serviceWiFi() {
  if (!PRISMA_WIFI_SSID[0]) return;
  if (WiFi.status() == WL_CONNECTED) {
    if (!clockStarted) {
      configTime(0, 0, "pool.ntp.org", "time.google.com");
      clockStarted = true;
    }
  } else if (!wifiAttempted || millis() - lastWiFiTry >= 10000) {
    wifiAttempted = true;
    lastWiFiTry = millis();
    WiFi.begin(PRISMA_WIFI_SSID, PRISMA_WIFI_PASSWORD);
  }
}

void serviceMqtt() {
  if (!brokerConfigured() || WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) {
    mqtt.loop();
    return;
  }
  if (time(nullptr) < 1577836800) return; // relógio confiável para TLS
  if (lastMqttTry && millis() - lastMqttTry < 15000) return;
  lastMqttTry = millis();
  if (!mqtt.connect(id, PRISMA_MQTT_USER, PRISMA_MQTT_PASSWORD)) {
    ++mqttFailed;
  }
}

void publish() {
  if (!fresh() || !mqtt.connected()) return;
  JsonDocument doc;
  doc["schema"] = "prisma.gateway.v1";
  doc["device_id"] = id;
  doc["origin"] = "DEMOEM-serial-unverified";
  doc["t_board_s"] = summary.sourceTime;
  doc["unix_s"] = static_cast<long>(time(nullptr));
  doc["window_samples"] = summary.count;
  JsonArray voltage = doc["vrms_V"].to<JsonArray>();
  JsonArray current = doc["irms_A"].to<JsonArray>();
  JsonArray power = doc["p_W"].to<JsonArray>();
  for (unsigned p = 0; p != 3; ++p) {
    voltage.add(summary.vrms[p]);
    if (summary.currentValid) {
      current.add(summary.irms[p]);
      power.add(summary.power[p]);
    }
  }
  if (!summary.currentValid) {
    doc.remove("irms_A");
    doc.remove("p_W");
  }
  char payload[1024];
  size_t written = serializeJson(doc, payload, sizeof(payload));
  if (!written || written >= sizeof(payload)) {
    ++mqttFailed;
  } else if (mqtt.publish(topic, payload, false)) {
    ++mqttSent;
  } else {
    ++mqttFailed;
  }
}

void statusPage() {
  JsonDocument doc;
  doc["device_id"] = id;
  doc["source"] = "DEMOEM serial (fisicamente nao validado)";
  doc["fresh"] = fresh();
  doc["samples"] = sampleCount;
  doc["window_samples"] = summary.count;
  doc["age_ms"] = sampleCount ? static_cast<long>(millis() - lastSample) : -1;
  doc["time_resets"] = backwardTimeCount;
  doc["invalid_lines"] = invalidCount;
  doc["long_lines"] = overflowCount;
  doc["usb_drops"] = usbDropped;
  doc["wifi"] = WiFi.status() == WL_CONNECTED ? "conectado" : "desconectado";
  doc["mqtt"] = !brokerConfigured() ? "desabilitado" :
      (mqtt.connected() ? "conectado" : "desconectado");
  doc["mqtt_sent"] = mqttSent;
  doc["mqtt_failures"] = mqttFailed;
  if (fresh()) {
    JsonArray voltage = doc["vrms_V"].to<JsonArray>();
    JsonArray current = doc["irms_A"].to<JsonArray>();
    JsonArray power = doc["p_W"].to<JsonArray>();
    for (unsigned p = 0; p != 3; ++p) {
      voltage.add(summary.vrms[p]);
      if (summary.currentValid) {
        current.add(summary.irms[p]);
        power.add(summary.power[p]);
      }
    }
    if (!summary.currentValid) {
      doc.remove("irms_A");
      doc.remove("p_W");
    }
  }
#if PRISMA_VBAT_ADC_GPIO >= 0
  // exige divisor resistivo e proteções apropriados, medidos em bancada
  doc["battery_V"] = analogReadMilliVolts(PRISMA_VBAT_ADC_GPIO) /
                      1000.0f * PRISMA_VBAT_DIVIDER_RATIO;
#else
  doc["battery_V"] = nullptr;
#endif
  String data;
  serializeJson(doc, data);
  web.sendHeader("Cache-Control", "no-store");
  web.send(200, "application/json; charset=utf-8", data);
}
} // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  const uint64_t mac = ESP.getEfuseMac();
  snprintf(id, sizeof(id), "prisma-%04X%08X",
           static_cast<unsigned>((mac >> 32) & 0xffffU),
           static_cast<unsigned>(mac & 0xffffffffU));
  snprintf(topic, sizeof(topic), "prisma/%s/measurements", id);
#if PRISMA_UART_RX_GPIO >= 0
  boardSerial.setRxBufferSize(8192);
  boardSerial.begin(SERIAL_BAUD, SERIAL_8N1, PRISMA_UART_RX_GPIO, -1);
  uartEnabled = true;
#endif
  WiFi.mode(WIFI_STA);                 // sem AP público
  WiFi.setAutoReconnect(true);
  if (brokerConfigured()) tls.setCACert(PRISMA_MQTT_CA_PEM);
  mqtt.setServer(PRISMA_MQTT_HOST, PRISMA_MQTT_PORT);
  mqtt.setBufferSize(2048);
  web.on("/", HTTP_GET, []() {
    web.sendHeader("Cache-Control", "no-store");
    web.send_P(200, "text/html; charset=utf-8", PRISMA_DASHBOARD);
  });
  web.on("/api/status", HTTP_GET, statusPage);
  web.onNotFound([]() { web.send(404, "text/plain", "Not found"); });
  // Sem autenticação HTTP. Deve operar somente em LAN isolada/confiável.
  web.begin();
  lastWindow = millis();
}

void loop() {
  pollUart();
  serviceWiFi();
  serviceMqtt();
  web.handleClient();
  const unsigned long now = millis();
  if (now - lastWindow >= WINDOW_MS) {
    lastWindow = now;
    closeWindow();
    publish();
  }
}
