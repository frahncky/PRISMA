#pragma once
// Atualização da DEMOEM pelo bootloader serial PRISMA (docs/bootloader.md), no ESP32-S3.
//
// Mesmo fluxo e mesmas garantias do gravador do PC (prisma.core.bootloader.BootClient):
// INFO → ERASE → WRITE em blocos de até 128 bytes → COMMIT (a placa confere o CRC-32)
// → RUN. Uma resposta perdida é repetida sem regravar às cegas: um WRITE repetido que
// volta "destino não apagado" é conferido pelo CRC do bloco, e um COMMIT repetido, pelo INFO.
// Testado no PC contra o núcleo C do bootloader (prisma_boot.h) em tests/test_gateway.py.
#include <stddef.h>
#include <stdint.h>

#include <vector>

#include "prisma_link.h"

namespace prisma {

constexpr uint8_t kCmdEnterBoot = 0x04;  // aplicação: reinicia no bootloader
constexpr uint8_t kCmdBootInfo = 0x20;
constexpr uint8_t kCmdBootErase = 0x21;
constexpr uint8_t kCmdBootWrite = 0x22;
constexpr uint8_t kCmdBootCrc = 0x23;
constexpr uint8_t kCmdBootCommit = 0x24;
constexpr uint8_t kCmdBootRun = 0x25;
constexpr uint8_t kReplyOk = 0x00;
constexpr uint8_t kReplyUnknown = 0x01;
constexpr uint8_t kReplyFlash = 0x04;

uint32_t crc32(const uint8_t *data, size_t length, uint32_t crc = 0);

struct BootInfo {
  uint8_t revision = 0;
  bool appValid = false;
  uint16_t pageSize = 0;
  uint32_t appStart = 0, appLimit = 0;  // limite: fim exclusivo (o descritor começa ali)
  uint16_t maxChunk = 0;
  uint8_t flashError = 0;
  uint32_t holeStart = 0, holeEnd = 0;  // faixa que o bootloader nunca grava
};

// Imagem da aplicação montada a partir do S19, recebido aos pedaços (upload HTTP).
// A área e a faixa reservada são as do bootloader do MCF51EM256; o flash() confere
// com o INFO da placa antes de gravar.
class SrecImage {
 public:
  SrecImage(uint32_t start = 0x20000, uint32_t limit = 0x3FC00, uint32_t holeStart = 0x203FE,
            uint32_t holeEnd = 0x20410, size_t maxBytes = 0x10000);
  void reset();
  bool feed(const char *text, size_t length);  // false: erro em error()
  bool finish();                               // fecha a última linha e confere a faixa reservada

  const char *error() const { return error_; }
  uint32_t start() const { return start_; }
  uint32_t end() const { return start_ + static_cast<uint32_t>(data_.size()); }
  const std::vector<uint8_t> &data() const { return data_; }
  uint32_t crc() const;  // CRC-32 como o bootloader calcula (sem a faixa reservada)
  bool ready() const { return finished_ && !failed_; }

 private:
  bool line(const char *text, size_t length);
  bool fail(const char *message);

  uint32_t start_, limit_, holeStart_, holeEnd_;
  size_t maxBytes_;
  std::vector<uint8_t> data_;
  std::vector<uint8_t> written_;  // um bit por byte: endereço repetido no S19
  char pending_[600] = {};
  size_t pendingLength_ = 0;
  unsigned lineNumber_ = 0;
  bool failed_ = false, finished_ = false, any_ = false;
  char error_[96] = {};
};

// Canal serial com a placa. read devolve um byte ou -1 depois de timeoutMs.
class BootTransport {
 public:
  virtual ~BootTransport() {}
  virtual void write(const uint8_t *data, size_t length) = 0;
  virtual int read(uint32_t timeoutMs) = 0;
  virtual uint32_t millis() = 0;
  virtual void sleep(uint32_t ms) = 0;
};

class BootClient {
 public:
  typedef void (*Progress)(void *context, const char *stage, uint32_t done, uint32_t total);

  explicit BootClient(BootTransport &transport, uint32_t timeoutMs = 600, unsigned retries = 4)
      : transport_(transport), timeoutMs_(timeoutMs), retries_(retries) {}

  // INFO do bootloader; se a aplicação estiver rodando, pede o reinício nele (0x04).
  bool enter(BootInfo &info);
  bool info(BootInfo &out);
  bool flash(const SrecImage &image, const BootInfo &info, bool run, Progress progress = nullptr,
             void *context = nullptr);

  const char *error() const { return error_; }
  unsigned resends = 0;

 private:
  // Envia e espera a resposta casada (id e código). false: nada chegou no prazo.
  bool exchange(uint8_t code, const uint8_t *args, size_t nArgs, uint32_t timeoutMs, Reply &reply);
  bool request(uint8_t code, const uint8_t *args, size_t nArgs, uint32_t timeoutMs, Reply &reply);
  bool check(const Reply &reply, const char *what);
  bool crc(uint32_t address, uint32_t length, uint32_t &out);
  bool writeChunk(uint32_t address, const uint8_t *data, size_t length);
  bool fail(const char *format, ...);

  BootTransport &transport_;
  uint32_t timeoutMs_;
  unsigned retries_;
  uint8_t id_ = 0;
  LinkParser parser_;
  uint8_t reply_[LinkParser::kMaxStored] = {};
  char error_[120] = {};
};

}  // namespace prisma
