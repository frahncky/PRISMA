/*
 * PRISMA — gateway ESP32-S3 (protótipo, ainda não validado fisicamente).
 *
 * DEMOEM (SCI3, protocolo v2) <-> UART <-> ESP32-S3 <-> USB CDC (PRISMA no PC)
 *                                             |-> painel HTTP e /api/status
 *                                             |-> MQTT/TLS (resumos)
 *                                             '-> atualização da DEMOEM (POST /api/ota)
 *
 * - Ponte transparente nos dois sentidos: os bytes da placa vão intactos para a USB
 *   (o PC decodifica JSON e quadros v2), e os comandos do PC vão para a placa.
 * - Os resumos 0x02 da placa (uma janela de ciclos inteiros por ~1 s) viram RMS,
 *   potência e frequência no ESP, com as somas inteiras exatas (lib/prisma_link).
 * - A atualização usa o bootloader PRISMA da DEMOEM, com o mesmo fluxo do PC
 *   (scripts/atualizar_demoem.py); fica desligada sem PRISMA_OTA_TOKEN.
 * Nenhuma amostra elétrica é gerada aqui. O painel HTML não é driver de TFT físico.
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
#include "prisma_link.h"
#include "prisma_ota.h"

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
#ifndef PRISMA_OTA_TOKEN
#define PRISMA_OTA_TOKEN ""  // vazio: atualização da DEMOEM desligada
#endif
#ifndef PRISMA_CAL_GAINS
// Ganho por canal (va vb vc ia ib ic), unidade física por contagem, como "gain" do
// perfil de calibração do PC. Zeros: valores em contagens.
#define PRISMA_CAL_GAINS {0, 0, 0, 0, 0, 0}
#endif
#ifndef PRISMA_UART_RX_GPIO
#define PRISMA_UART_RX_GPIO -1
#endif
#ifndef PRISMA_UART_TX_GPIO
#define PRISMA_UART_TX_GPIO -1  // sem TX: só recepção (sem comandos nem atualização)
#endif
#ifndef PRISMA_VBAT_ADC_GPIO
#define PRISMA_VBAT_ADC_GPIO -1
#endif
#ifndef PRISMA_VBAT_DIVIDER_RATIO
#define PRISMA_VBAT_DIVIDER_RATIO 2.0f
#endif

namespace {
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t STALE_MS = 3500;          // janelas de ~1 s: 3 perdidas = dado antigo
constexpr size_t MIN_OTA_TOKEN = 12;
constexpr bool UART_TX = PRISMA_UART_TX_GPIO >= 0;
constexpr bool UART_RX = PRISMA_UART_RX_GPIO >= 0;

HardwareSerial boardSerial(1);
WebServer web(80);
WiFiClientSecure tls;
PubSubClient mqtt(tls);
prisma::LinkParser link;
prisma::Gains gains;

bool wifiAttempted = false, clockStarted = false;
unsigned long lastWiFiTry = 0, lastMqttTry = 0;
char id[32] = {}, topic[96] = {};

// Medição: último resumo da placa.
prisma::Measurement latest;
unsigned long lastSummaryMs = 0;
uint32_t summaries = 0, lostWindows = 0, invalidSummaries = 0, bursts = 0, replies = 0;
uint32_t usbDroppedBytes = 0, usbToBoardBytes = 0;
uint32_t mqttSent = 0, mqttFailed = 0;
bool published = true;
char lastStatus[160] = {};

// Atualização da DEMOEM (tarefa própria; enquanto roda, ela é dona da UART).
enum class OtaState { Idle, Receiving, Flashing, Done, Failed };
volatile bool otaBusy = false;
portMUX_TYPE otaLock = portMUX_INITIALIZER_UNLOCKED;
struct OtaStatus {
  OtaState state = OtaState::Idle;
  char stage[16] = "";
  uint32_t done = 0, total = 0, resends = 0, imageBytes = 0, imageCrc = 0;
  char message[140] = "";
} ota;
prisma::SrecImage image;
bool uploadAccepted = false;

bool otaEnabled() { return UART_TX && UART_RX && strlen(PRISMA_OTA_TOKEN) >= MIN_OTA_TOKEN; }

void otaSet(OtaState state, const char *message) {
  portENTER_CRITICAL(&otaLock);
  ota.state = state;
  strlcpy(ota.message, message, sizeof(ota.message));
  portEXIT_CRITICAL(&otaLock);
}

// ---- Placa -> ESP -> USB ---------------------------------------------------

void onSummary(const uint8_t *payload, size_t length) {
  prisma::Summary s;
  if (!prisma::parseSummary(payload, length, s)) {
    ++invalidSummaries;
    return;
  }
  if (latest.valid && s.seq > latest.seq + 1) lostWindows += s.seq - latest.seq - 1;
  latest = prisma::measure(s, gains);
  lastSummaryMs = millis();
  ++summaries;
  published = false;
}

void onLine(const char *line, size_t length) {
  // Linhas de estado da placa (ex.: "BOOTLOADER (APP OK)"): só para diagnóstico.
  JsonDocument doc;
  if (deserializeJson(doc, line, length) || !doc["message"].is<const char *>()) return;
  strlcpy(lastStatus, doc["message"].as<const char *>(), sizeof(lastStatus));
}

void pollBoard() {
  if (!UART_RX || otaBusy) return;
  uint8_t chunk[256];
  size_t budget = 8192;
  while (budget && boardSerial.available()) {
    const size_t n = boardSerial.read(chunk, min(sizeof(chunk), budget));
    if (!n) break;
    budget -= n;
    // Ponte: bytes intactos para o PRISMA no PC. Sem espaço, o pedaço se perde e o
    // PC descarta o quadro pelo CRC (contado aqui em usb_drop_bytes).
    if (Serial) {
      if (Serial.availableForWrite() >= static_cast<int>(n)) {
        Serial.write(chunk, n);
      } else {
        usbDroppedBytes += n;
      }
    }
    for (size_t i = 0; i < n; ++i) {
      switch (link.feed(chunk[i])) {
        case prisma::LinkParser::kFrame:
          if (link.type() == prisma::kFrameSummary && link.stored()) onSummary(link.payload(), link.length());
          else if (link.type() == prisma::kFrameBurst) ++bursts;
          else if (link.type() == prisma::kFrameReply) ++replies;
          break;
        case prisma::LinkParser::kLine:
          onLine(link.line(), link.lineLength());
          break;
        default:
          break;
      }
    }
  }
}

// USB -> placa: comandos do PRISMA no PC (identificar placa, rajadas, atualização).
void pollUsb() {
  if (!Serial || !Serial.available()) return;
  uint8_t chunk[160];
  const size_t n = Serial.read(chunk, sizeof(chunk));
  if (!UART_TX || otaBusy) return;  // durante a atualização pelo ESP, o PC espera
  boardSerial.write(chunk, n);
  usbToBoardBytes += n;
}

bool fresh() { return latest.valid && millis() - lastSummaryMs < STALE_MS; }

// ---- Atualização da DEMOEM -------------------------------------------------

class UartTransport : public prisma::BootTransport {
 public:
  void write(const uint8_t *data, size_t length) override { boardSerial.write(data, length); }
  int read(uint32_t timeoutMs) override {
    const uint32_t begin = ::millis();
    while (!boardSerial.available()) {
      if (::millis() - begin >= timeoutMs) return -1;
      vTaskDelay(1);
    }
    return boardSerial.read();
  }
  uint32_t millis() override { return ::millis(); }
  void sleep(uint32_t ms) override { vTaskDelay(pdMS_TO_TICKS(ms)); }
};

void otaProgress(void *, const char *stage, uint32_t done, uint32_t total) {
  portENTER_CRITICAL(&otaLock);
  strlcpy(ota.stage, stage, sizeof(ota.stage));
  ota.done = done;
  ota.total = total;
  portEXIT_CRITICAL(&otaLock);
}

void otaTask(void *) {
  UartTransport transport;
  prisma::BootClient client(transport, 600, 4);
  prisma::BootInfo info;
  while (boardSerial.available()) boardSerial.read();  // descarta o resto de um quadro
  bool ok = client.enter(info);
  if (ok) {
    otaProgress(nullptr, "bootloader", 0, 0);
    ok = client.flash(image, info, true, otaProgress, nullptr);
  }
  portENTER_CRITICAL(&otaLock);
  ota.resends = client.resends;
  portEXIT_CRITICAL(&otaLock);
  otaSet(ok ? OtaState::Done : OtaState::Failed, ok ? "DEMOEM atualizada e aplicação em execução" : client.error());
  image.reset();
  link.resync();  // o fluxo da placa recomeça do zero
  otaBusy = false;
  vTaskDelete(nullptr);
}

bool tokenMatches(const String &given) {
  const char *expected = PRISMA_OTA_TOKEN;
  const size_t n = strlen(expected);
  if (given.length() != n) return false;
  uint8_t diff = 0;  // tempo constante
  for (size_t i = 0; i < n; ++i) diff |= static_cast<uint8_t>(given[i] ^ expected[i]);
  return diff == 0;
}

void otaUpload() {
  HTTPUpload &upload = web.upload();
  if (upload.status == UPLOAD_FILE_START) {
    uploadAccepted = otaEnabled() && !otaBusy && tokenMatches(web.header("X-Prisma-Token"));
    if (uploadAccepted) {
      image.reset();
      otaSet(OtaState::Receiving, "recebendo S19");
    }
  } else if (upload.status == UPLOAD_FILE_WRITE && uploadAccepted) {
    image.feed(reinterpret_cast<const char *>(upload.buf), upload.currentSize);
  } else if (upload.status == UPLOAD_FILE_END && uploadAccepted) {
    image.finish();
  } else if (upload.status == UPLOAD_FILE_ABORTED) {
    uploadAccepted = false;
    image.reset();
    otaSet(OtaState::Failed, "envio interrompido");
  }
}

void otaStart() {
  if (!otaEnabled()) {
    web.send(403, "text/plain; charset=utf-8", "Atualização desligada (PRISMA_OTA_TOKEN e UART TX/RX).");
    return;
  }
  if (!uploadAccepted) {
    web.send(otaBusy ? 409 : 401, "text/plain; charset=utf-8",
             otaBusy ? "Atualização em andamento." : "Token inválido.");
    return;
  }
  uploadAccepted = false;
  if (!image.ready()) {
    otaSet(OtaState::Failed, image.error());
    web.send(400, "text/plain; charset=utf-8", image.error());
    image.reset();
    return;
  }
  portENTER_CRITICAL(&otaLock);
  ota.imageBytes = image.data().size();
  ota.imageCrc = image.crc();
  ota.done = ota.total = ota.resends = 0;
  ota.stage[0] = '\0';
  portEXIT_CRITICAL(&otaLock);
  otaSet(OtaState::Flashing, "gravando a DEMOEM");
  otaBusy = true;
  if (xTaskCreate(otaTask, "prisma_ota", 8192, nullptr, 1, nullptr) != pdPASS) {
    otaBusy = false;
    image.reset();
    otaSet(OtaState::Failed, "sem memória para a tarefa de atualização");
    web.send(500, "text/plain; charset=utf-8", "Sem memória.");
    return;
  }
  web.send(202, "text/plain; charset=utf-8", "Gravação iniciada; acompanhe em /api/ota.");
}

void otaStatus() {
  OtaStatus copy;
  portENTER_CRITICAL(&otaLock);
  copy = ota;
  portEXIT_CRITICAL(&otaLock);
  static const char *const names[] = {"idle", "receiving", "flashing", "done", "failed"};
  JsonDocument doc;
  doc["enabled"] = otaEnabled();
  doc["state"] = names[static_cast<int>(copy.state)];
  doc["stage"] = copy.stage;
  doc["done"] = copy.done;
  doc["total"] = copy.total;
  doc["resends"] = copy.resends;
  doc["image_bytes"] = copy.imageBytes;
  doc["image_crc32"] = copy.imageCrc;
  doc["message"] = copy.message;
  String data;
  serializeJson(doc, data);
  web.sendHeader("Cache-Control", "no-store");
  web.send(200, "application/json; charset=utf-8", data);
}

// ---- Rede ------------------------------------------------------------------

bool brokerConfigured() {
  // sem credenciais e CA, MQTT fica desligado (nunca inseguro)
  return PRISMA_MQTT_HOST[0] && PRISMA_MQTT_USER[0] && PRISMA_MQTT_PASSWORD[0] && PRISMA_MQTT_CA_PEM[0];
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
  if (time(nullptr) < 1577836800) return;  // relógio confiável para TLS
  if (lastMqttTry && millis() - lastMqttTry < 15000) return;
  lastMqttTry = millis();
  if (!mqtt.connect(id, PRISMA_MQTT_USER, PRISMA_MQTT_PASSWORD)) ++mqttFailed;
}

void addNumber(JsonDocument &doc, const char *key, double value) {
  if (isfinite(value)) doc[key] = value;
  else doc[key] = nullptr;
}

// Campos da medição comuns ao MQTT e ao /api/status.
void addMeasurement(JsonDocument &doc) {
  doc["seq"] = latest.seq;
  doc["window_s"] = latest.durationS;
  addNumber(doc, "f_Hz", latest.frequencyHz);
  doc["v_unit"] = latest.calibratedV ? "V" : "counts";
  JsonArray v = doc["vrms"].to<JsonArray>();
  for (double value : latest.vrms) v.add(value);
  if (latest.currents) {
    doc["i_unit"] = latest.calibratedI ? "A" : "counts";
    doc["p_unit"] = latest.calibratedI ? "W" : "counts2";
    JsonArray i = doc["irms"].to<JsonArray>();
    JsonArray p = doc["p"].to<JsonArray>();
    for (unsigned k = 0; k != 3; ++k) {
      i.add(latest.irms[k]);
      p.add(latest.power[k]);
    }
  }
}

void publish() {
  if (published || !fresh() || !mqtt.connected()) return;
  published = true;
  JsonDocument doc;
  doc["schema"] = "prisma.gateway.v2";
  doc["device_id"] = id;
  doc["origin"] = "DEMOEM-serial-unverified";
  doc["unix_s"] = static_cast<long>(time(nullptr));
  doc["lost_windows"] = lostWindows;
  addMeasurement(doc);
  char payload[768];
  const size_t written = serializeJson(doc, payload, sizeof(payload));
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
  doc["age_ms"] = latest.valid ? static_cast<long>(millis() - lastSummaryMs) : -1;
  if (fresh()) addMeasurement(doc);
  doc["summaries"] = summaries;
  doc["lost_windows"] = lostWindows;
  doc["bursts"] = bursts;
  doc["replies"] = replies;
  doc["frames"] = link.frames;
  doc["crc_errors"] = link.crcErrors;
  doc["bad_headers"] = link.badHeaders;
  doc["long_lines"] = link.longLines;
  doc["invalid_summaries"] = invalidSummaries;
  doc["usb_drop_bytes"] = usbDroppedBytes;
  doc["usb_to_board_bytes"] = usbToBoardBytes;
  doc["board_message"] = lastStatus;
  doc["uart_tx"] = UART_TX;
  doc["ota_enabled"] = otaEnabled();
  doc["ota_busy"] = static_cast<bool>(otaBusy);
  doc["wifi"] = WiFi.status() == WL_CONNECTED ? "conectado" : "desconectado";
  doc["mqtt"] = !brokerConfigured() ? "desabilitado" : (mqtt.connected() ? "conectado" : "desconectado");
  doc["mqtt_sent"] = mqttSent;
  doc["mqtt_failures"] = mqttFailed;
#if PRISMA_VBAT_ADC_GPIO >= 0
  // exige divisor resistivo e proteções apropriados, medidos em bancada
  doc["battery_V"] = analogReadMilliVolts(PRISMA_VBAT_ADC_GPIO) / 1000.0f * PRISMA_VBAT_DIVIDER_RATIO;
#else
  doc["battery_V"] = nullptr;
#endif
  String data;
  serializeJson(doc, data);
  web.sendHeader("Cache-Control", "no-store");
  web.send(200, "application/json; charset=utf-8", data);
}
}  // namespace

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(SERIAL_BAUD);
  const double configured[6] = PRISMA_CAL_GAINS;
  for (unsigned k = 0; k != 6; ++k) gains.channel[k] = configured[k];
  const uint64_t mac = ESP.getEfuseMac();
  snprintf(id, sizeof(id), "prisma-%04X%08X", static_cast<unsigned>((mac >> 32) & 0xffffU),
           static_cast<unsigned>(mac & 0xffffffffU));
  snprintf(topic, sizeof(topic), "prisma/%s/measurements", id);
  if (UART_RX) {
    boardSerial.setRxBufferSize(16384);  // rajada de 6 canais: ~6 KB de uma vez
    boardSerial.begin(SERIAL_BAUD, SERIAL_8N1, PRISMA_UART_RX_GPIO, PRISMA_UART_TX_GPIO);
  }
  WiFi.mode(WIFI_STA);  // sem AP público
  WiFi.setAutoReconnect(true);
  if (brokerConfigured()) tls.setCACert(PRISMA_MQTT_CA_PEM);
  mqtt.setServer(PRISMA_MQTT_HOST, PRISMA_MQTT_PORT);
  mqtt.setBufferSize(1024);
  static const char *headers[] = {"X-Prisma-Token"};
  web.collectHeaders(headers, 1);
  web.on("/", HTTP_GET, []() {
    web.sendHeader("Cache-Control", "no-store");
    web.send_P(200, "text/html; charset=utf-8", PRISMA_DASHBOARD);
  });
  web.on("/api/status", HTTP_GET, statusPage);
  web.on("/api/ota", HTTP_GET, otaStatus);
  web.on("/api/ota", HTTP_POST, otaStart, otaUpload);
  web.onNotFound([]() { web.send(404, "text/plain", "Not found"); });
  // Leitura sem autenticação: só em LAN isolada. A atualização exige o token.
  web.begin();
}

void loop() {
  pollBoard();
  pollUsb();
  serviceWiFi();
  serviceMqtt();
  web.handleClient();
  publish();
}
