#pragma once
// Núcleo portátil do gateway PRISMA (sem Arduino): testado no PC com g++ em
// tests/test_gateway.py e compilado no ESP32-S3 pelo PlatformIO.
//
// - LinkParser separa, de um fluxo serial, linhas JSON e quadros binários v2
//   (A5 5A | tipo | len u16 | payload | CRC-16), como prisma.core.protocol.StreamDecoder.
//   Quadros grandes (rajadas de até 48 KiB) têm o CRC conferido sem guardar o payload.
// - Summary decodifica o resumo 0x02 (prisma_meter.h) e calcula RMS AC, potência
//   ativa e frequência com as somas inteiras exatas, como o MeterSummary do PC.
// - encodeCommand monta um comando 0x10 (prisma_command.h).
#include <stddef.h>
#include <stdint.h>

namespace prisma {

constexpr uint8_t kFrameBurst = 0x01;
constexpr uint8_t kFrameSummary = 0x02;
constexpr uint8_t kFrameCommand = 0x10;
constexpr uint8_t kFrameReply = 0x11;
constexpr uint16_t kMaxFramePayload = 12 + 4096 * 6 * 2;  // cabeçalho da rajada + 4096 × 6 canais

uint16_t crc16Update(uint16_t crc, uint8_t value);
uint16_t crc16(const uint8_t *data, size_t length);

class LinkParser {
 public:
  static constexpr size_t kMaxStored = 256;  // resumo de 6 canais = 116 B; respostas < 40 B
  static constexpr size_t kMaxLine = 512;

  enum Event { kNone, kFrame, kLine };

  // Processa um byte. kFrame: quadro com CRC válido (payload() só se stored());
  // kLine: linha de texto completa, sem \r\n, em line().
  Event feed(uint8_t value);
  // Recomeça do zero (ex.: depois de outra parte usar a UART), mantendo os contadores.
  void resync() {
    state_ = kText;
    discard_ = lineDone_ = false;
    lineLength_ = 0;
  }

  uint8_t type() const { return type_; }
  uint16_t length() const { return length_; }
  bool stored() const { return length_ <= kMaxStored; }
  const uint8_t *payload() const { return payload_; }
  const char *line() const { return line_; }
  size_t lineLength() const { return lineLength_; }

  uint32_t frames = 0;      // quadros válidos (inclusive os não guardados)
  uint32_t crcErrors = 0;   // quadros descartados pelo CRC
  uint32_t badHeaders = 0;  // tamanho impossível depois de A5 5A
  uint32_t longLines = 0;   // linhas de texto acima de kMaxLine (descartadas)

 private:
  enum State { kText, kSync2, kType, kLenL, kLenH, kPayload, kCrcL, kCrcH };
  void textByte(uint8_t value);

  State state_ = kText;
  bool discard_ = false;  // descartando texto até a próxima linha ou sincronismo
  bool lineDone_ = false;  // line() foi entregue e é limpa no próximo byte
  uint8_t type_ = 0;
  uint16_t length_ = 0;
  uint16_t pos_ = 0;
  uint16_t crc_ = 0xFFFF;
  uint16_t receivedCrc_ = 0;
  uint8_t payload_[kMaxStored] = {};
  char line_[kMaxLine + 1] = {};
  size_t lineLength_ = 0;
};

// Comando 0x10: id, código, argumentos. Devolve o tamanho do quadro (7 + 2 + nArgs)
// ou 0 se não couber em out.
size_t encodeCommand(uint8_t id, uint8_t code, const uint8_t *args, size_t nArgs, uint8_t *out,
                     size_t capacity);

struct Reply {
  uint8_t id = 0, code = 0, status = 0;
  const uint8_t *data = nullptr;
  size_t length = 0;
};
bool parseReply(const uint8_t *payload, size_t length, Reply &out);

constexpr uint8_t kSummaryNoSync = 0x08;
constexpr uint8_t kSummaryOverrun = 0x10;

struct Summary {
  uint32_t seq = 0, fsMhz = 0, n = 0;
  uint8_t mask = 0, flags = 0, channels = 0;  // canais: 3 (va..vc) ou 6 (va..ic)
  uint16_t cycles = 0;
  uint32_t periodQ8 = 0;
  uint32_t sum[6] = {};
  uint64_t sumsq[6] = {};
  uint64_t sumvi[3] = {};

  double fsHz() const { return fsMhz / 1000.0; }
  double durationS() const { return n / fsHz(); }
  bool synced() const { return !(flags & kSummaryNoSync) && cycles >= 2 && periodQ8 > 0; }
  bool hasCurrents() const { return channels == 6; }
  double frequencyHz() const;      // NAN sem sincronismo
  double acRms(unsigned ch) const;  // contagens, sem a componente contínua
  double active(unsigned phase) const;  // média de (v − v̄)(i − ī), contagens²; NAN sem correntes
};
bool parseSummary(const uint8_t *payload, size_t length, Summary &out);

// Ganhos lineares por canal (unidade física por contagem), como "gain" do perfil
// de calibração do PC. Sem ganho (0), o valor sai em contagens.
struct Gains {
  double channel[6] = {};
  bool voltages() const { return channel[0] && channel[1] && channel[2]; }
  bool currents() const { return channel[3] && channel[4] && channel[5]; }
};

struct Measurement {
  bool valid = false;
  bool currents = false;    // correntes e potência disponíveis
  bool calibratedV = false;  // V RMS em volts (senão, contagens)
  bool calibratedI = false;  // I RMS em ampères e P em watts (senão, contagens)
  uint32_t seq = 0;
  double durationS = 0, frequencyHz = 0;  // frequência NAN sem sincronismo
  double vrms[3] = {}, irms[3] = {}, power[3] = {};
};
Measurement measure(const Summary &s, const Gains &gains);

}  // namespace prisma
