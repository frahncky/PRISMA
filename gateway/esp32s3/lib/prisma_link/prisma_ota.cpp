#include "prisma_ota.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

namespace prisma {
namespace {

void le32(uint8_t *out, uint32_t value) {
  for (int i = 0; i < 4; ++i) out[i] = static_cast<uint8_t>(value >> (8 * i));
}
uint32_t rd32(const uint8_t *p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
int hexDigit(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}
const char *statusText(uint8_t status) {
  switch (status) {
    case 1: return "código desconhecido";
    case 2: return "argumentos inválidos";
    case 3: return "fora da área, desalinhado ou na faixa reservada";
    case 4: return "erro de gravação na flash";
    case 5: return "imagem inválida (CRC)";
    default: return "estado desconhecido";
  }
}

}  // namespace

uint32_t crc32(const uint8_t *data, size_t length, uint32_t crc) {
  crc = ~crc;
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}

// ---- S19 ------------------------------------------------------------------

SrecImage::SrecImage(uint32_t start, uint32_t limit, uint32_t holeStart, uint32_t holeEnd, size_t maxBytes)
    : start_(start), limit_(limit), holeStart_(holeStart), holeEnd_(holeEnd), maxBytes_(maxBytes) {}

void SrecImage::reset() {
  std::vector<uint8_t>().swap(data_);  // devolve a memória (até 64 KiB no ESP32)
  std::vector<uint8_t>().swap(written_);
  pendingLength_ = 0;
  lineNumber_ = 0;
  failed_ = finished_ = any_ = false;
  error_[0] = '\0';
}

bool SrecImage::fail(const char *message) {
  if (!failed_) snprintf(error_, sizeof(error_), "Linha %u: %s", lineNumber_, message);
  failed_ = true;
  return false;
}

bool SrecImage::feed(const char *text, size_t length) {
  for (size_t i = 0; i < length && !failed_; ++i) {
    const char c = text[i];
    if (c == '\n') {
      line(pending_, pendingLength_);
      pendingLength_ = 0;
    } else if (pendingLength_ < sizeof(pending_)) {
      pending_[pendingLength_++] = c;
    } else {
      ++lineNumber_;
      return fail("linha longa demais");
    }
  }
  return !failed_;
}

bool SrecImage::line(const char *text, size_t length) {
  ++lineNumber_;
  while (length && (text[length - 1] == '\r' || text[length - 1] == ' ')) --length;
  while (length && text[0] == ' ') ++text, --length;
  if (!length) return true;
  if (length < 4 || text[0] != 'S' || hexDigit(text[1]) < 0 || hexDigit(text[1]) > 9)
    return fail("não é um S-record");
  if (length % 2) return fail("hexadecimal inválido");
  uint8_t raw[300];
  const size_t count = (length - 2) / 2;
  if (count > sizeof(raw)) return fail("registro longo demais");
  unsigned sum = 0;
  for (size_t i = 0; i < count; ++i) {
    const int hi = hexDigit(text[2 + 2 * i]), lo = hexDigit(text[3 + 2 * i]);
    if (hi < 0 || lo < 0) return fail("hexadecimal inválido");
    raw[i] = static_cast<uint8_t>(hi * 16 + lo);
    sum += raw[i];
  }
  if (raw[0] != count - 1) return fail("tamanho não confere");
  if ((sum & 0xFF) != 0xFF) return fail("checksum inválido");
  const char kind = text[1];
  if (kind < '1' || kind > '3') return true;  // cabeçalho, contagem e início
  const size_t width = static_cast<size_t>(kind - '1') + 2;
  if (count < 1 + width + 1) return fail("registro curto");
  uint32_t address = 0;
  for (size_t i = 0; i < width; ++i) address = (address << 8) | raw[1 + i];
  const size_t n = count - 1 - width - 1;
  for (size_t k = 0; k < n; ++k) {
    const uint32_t a = address + static_cast<uint32_t>(k);
    if (a < start_ || a >= limit_) {
      char message[90];
      snprintf(message, sizeof(message), "0x%lX fora da área da aplicação (firmware sem bootloader?)",
               static_cast<unsigned long>(a));
      return fail(message);
    }
    const size_t offset = a - start_;
    if (offset >= maxBytes_) return fail("imagem maior que o limite do gateway");
    if (offset >= data_.size()) {
      data_.resize(offset + 1, 0xFF);
      written_.resize(offset / 8 + 1, 0);
    }
    if (written_[offset / 8] & (1u << (offset % 8))) return fail("endereço repetido");
    written_[offset / 8] |= static_cast<uint8_t>(1u << (offset % 8));
    data_[offset] = raw[1 + width + k];
    any_ = true;
  }
  return true;
}

bool SrecImage::finish() {
  if (failed_) return false;
  if (pendingLength_) {
    line(pending_, pendingLength_);
    pendingLength_ = 0;
    if (failed_) return false;
  }
  if (!any_) return fail("S19 sem dados");
  data_.resize((data_.size() + 3) & ~static_cast<size_t>(3), 0xFF);
  // Palavras inteiras da faixa reservada precisam ficar apagadas (0xFF).
  for (uint32_t a = holeStart_ & ~3u; a < ((holeEnd_ + 3) & ~3u); ++a) {
    if (a >= start_ && a < end() && data_[a - start_] != 0xFF) {
      char message[90];
      snprintf(message, sizeof(message), "grava 0x%lX, na faixa reservada do bloco de flash",
               static_cast<unsigned long>(a));
      return fail(message);
    }
  }
  finished_ = true;
  return true;
}

uint32_t SrecImage::crc() const {
  const size_t size = data_.size();
  size_t lo = holeStart_ > start_ ? holeStart_ - start_ : 0;
  size_t hi = holeEnd_ > start_ ? holeEnd_ - start_ : 0;
  if (lo > size) lo = size;
  if (hi > size) hi = size;
  if (lo >= hi) return crc32(data_.data(), size);
  uint32_t c = crc32(data_.data(), lo);
  return crc32(data_.data() + hi, size - hi, c);
}

// ---- Cliente do bootloader ------------------------------------------------

bool BootClient::fail(const char *format, ...) {
  va_list args;
  va_start(args, format);
  vsnprintf(error_, sizeof(error_), format, args);
  va_end(args);
  return false;
}

bool BootClient::exchange(uint8_t code, const uint8_t *args, size_t nArgs, uint32_t timeoutMs, Reply &reply) {
  uint8_t frame[160];
  id_ = static_cast<uint8_t>(id_ + 1);
  const uint8_t id = id_;
  const size_t size = encodeCommand(id, code, args, nArgs, frame, sizeof(frame));
  if (!size) return fail("comando grande demais");
  transport_.write(frame, size);
  const uint32_t begin = transport_.millis();
  for (;;) {
    const uint32_t elapsed = transport_.millis() - begin;
    if (elapsed >= timeoutMs) return false;
    const int value = transport_.read(timeoutMs - elapsed);
    if (value < 0) continue;
    // Resumos, rajadas e texto da aplicação podem vir misturados: só a resposta casa.
    if (parser_.feed(static_cast<uint8_t>(value)) != LinkParser::kFrame) continue;
    if (parser_.type() != kFrameReply || !parser_.stored()) continue;
    memcpy(reply_, parser_.payload(), parser_.length());
    if (parseReply(reply_, parser_.length(), reply) && reply.id == id && reply.code == code) return true;
  }
}

bool BootClient::request(uint8_t code, const uint8_t *args, size_t nArgs, uint32_t timeoutMs, Reply &reply) {
  for (unsigned attempt = 0; attempt <= retries_; ++attempt) {
    if (attempt) ++resends;
    if (exchange(code, args, nArgs, timeoutMs, reply)) return true;
  }
  return fail("sem resposta do bootloader ao comando 0x%02X depois de %u tentativas", code, retries_ + 1);
}

bool BootClient::check(const Reply &reply, const char *what) {
  return reply.status == kReplyOk || fail("%s: %s", what, statusText(reply.status));
}

bool BootClient::info(BootInfo &out) {
  Reply reply;
  if (!request(kCmdBootInfo, nullptr, 0, timeoutMs_, reply) || !check(reply, "INFO recusado")) return false;
  if (reply.length < 24) return fail("INFO do bootloader curto (%u bytes)", static_cast<unsigned>(reply.length));
  const uint8_t *d = reply.data;
  out.revision = d[0];
  out.appValid = d[1] != 0;
  out.pageSize = static_cast<uint16_t>(d[2] | (d[3] << 8));
  out.appStart = rd32(d + 4);
  out.appLimit = rd32(d + 8);
  out.maxChunk = static_cast<uint16_t>(d[12] | (d[13] << 8));
  out.flashError = d[14];
  out.holeStart = rd32(d + 16);
  out.holeEnd = rd32(d + 20);
  return true;
}

bool BootClient::enter(BootInfo &out) {
  Reply reply;
  if (exchange(kCmdBootInfo, nullptr, 0, timeoutMs_, reply) && reply.status == kReplyOk)
    return info(out);  // já está no bootloader
  // A aplicação responde "código desconhecido" ao INFO do bootloader (ou nada, se
  // estiver ocupada): pede o reinício. A placa reinicia logo depois da resposta.
  exchange(kCmdEnterBoot, nullptr, 0, timeoutMs_, reply);
  transport_.sleep(500);
  return info(out);
}

bool BootClient::crc(uint32_t address, uint32_t length, uint32_t &out) {
  uint8_t args[8];
  le32(args, address);
  le32(args + 4, length);
  Reply reply;
  if (!request(kCmdBootCrc, args, sizeof(args), timeoutMs_, reply) || !check(reply, "CRC recusado")) return false;
  if (reply.length != 4) return fail("resposta de CRC inválida");
  out = rd32(reply.data);
  return true;
}

bool BootClient::writeChunk(uint32_t address, const uint8_t *data, size_t length) {
  uint8_t args[4 + 128];
  le32(args, address);
  memcpy(args + 4, data, length);
  for (unsigned attempt = 0; attempt <= retries_; ++attempt) {
    Reply reply;
    if (!exchange(kCmdBootWrite, args, 4 + length, timeoutMs_, reply)) {
      ++resends;
      continue;
    }
    if (reply.status == kReplyFlash && attempt) {
      uint32_t board = 0;
      if (!crc(address, static_cast<uint32_t>(length), board)) return false;
      if (board == crc32(data, length)) return true;  // a 1ª tentativa gravou; só a resposta se perdeu
    }
    char what[40];
    snprintf(what, sizeof(what), "gravação em 0x%lX", static_cast<unsigned long>(address));
    return check(reply, what);
  }
  return fail("sem resposta ao gravar 0x%lX", static_cast<unsigned long>(address));
}

bool BootClient::flash(const SrecImage &image, const BootInfo &info, bool run, Progress progress, void *context) {
  if (!image.ready()) return fail("imagem não carregada");
  if (image.start() != info.appStart || image.end() > info.appLimit)
    return fail("imagem fora da área do bootloader (0x%lX..0x%lX)", static_cast<unsigned long>(info.appStart),
                static_cast<unsigned long>(info.appLimit));
  if (!info.pageSize) return fail("INFO sem tamanho de página");
  const std::vector<uint8_t> &data = image.data();
  const uint32_t pages = static_cast<uint32_t>((data.size() + info.pageSize - 1) / info.pageSize);
  if (progress) progress(context, "apagando", 0, pages);
  uint8_t args[8];
  le32(args, info.appStart);
  args[4] = static_cast<uint8_t>(pages & 0xFF);
  args[5] = static_cast<uint8_t>(pages >> 8);
  Reply reply;
  const uint32_t eraseTimeout = timeoutMs_ > 50 * pages ? timeoutMs_ : 50 * pages;
  if (!request(kCmdBootErase, args, 6, eraseTimeout, reply) || !check(reply, "apagamento")) return false;

  // Blocos de até 128 bytes, cortados na faixa reservada; blocos todo 0xFF ficam de fora.
  const uint32_t step = info.maxChunk && info.maxChunk < 128 ? info.maxChunk : 128;
  const uint32_t holeLo = info.holeStart & ~3u, holeHi = (info.holeEnd + 3) & ~3u;
  uint32_t total = 0;
  for (int pass = 0; pass < 2; ++pass) {  // 1ª passada conta, 2ª grava
    uint32_t done = 0;
    for (uint32_t offset = 0; offset < data.size(); offset += step) {
      const uint32_t address = image.start() + offset;
      const uint32_t end = address + step < image.end() ? address + step : image.end();
      const uint32_t pieces[2][2] = {{address, end < holeLo ? end : holeLo},
                                     {address > holeHi ? address : holeHi, end}};
      for (const auto &piece : pieces) {
        if (piece[0] >= piece[1]) continue;
        const uint8_t *bytes = data.data() + (piece[0] - image.start());
        const size_t length = piece[1] - piece[0];
        bool blank = true;
        for (size_t i = 0; i < length && blank; ++i) blank = bytes[i] == 0xFF;
        if (blank) continue;
        if (pass) {
          if (progress) progress(context, "gravando", done, total);
          if (!writeChunk(piece[0], bytes, length)) return false;
        }
        ++done;
      }
    }
    total = done;
  }
  if (progress) progress(context, "gravando", total, total);

  const uint32_t expected = image.crc();
  le32(args, static_cast<uint32_t>(data.size()));
  le32(args + 4, expected);
  if (!request(kCmdBootCommit, args, 8, timeoutMs_ > 2000 ? timeoutMs_ : 2000, reply)) return false;
  if (reply.status != kReplyOk) {
    BootInfo again;
    // COMMIT repetido: a 1ª vez pode ter gravado o descritor.
    if (!(reply.status == kReplyFlash && this->info(again) && again.appValid)) {
      if (reply.length == 4)
        return fail("confirmação recusada: %s (placa calculou 0x%08lX, esperado 0x%08lX)", statusText(reply.status),
                    static_cast<unsigned long>(rd32(reply.data)), static_cast<unsigned long>(expected));
      return fail("confirmação recusada: %s", statusText(reply.status));
    }
  }
  BootInfo final;
  if (!this->info(final)) return false;
  if (!final.appValid) return fail("gravação terminou mas a placa não reconhece a aplicação como válida");
  if (run && (!request(kCmdBootRun, nullptr, 0, timeoutMs_, reply) || !check(reply, "partida da aplicação")))
    return false;
  if (progress) progress(context, "pronto", 1, 1);
  return true;
}

}  // namespace prisma
