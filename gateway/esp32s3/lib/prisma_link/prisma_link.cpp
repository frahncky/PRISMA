#include "prisma_link.h"

#include <math.h>
#include <string.h>

namespace prisma {
namespace {

uint16_t rd16(const uint8_t *p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }
uint32_t rd32(const uint8_t *p) {
  return static_cast<uint32_t>(rd16(p)) | (static_cast<uint32_t>(rd16(p + 2)) << 16);
}
uint64_t rd64(const uint8_t *p) {
  return static_cast<uint64_t>(rd32(p)) | (static_cast<uint64_t>(rd32(p + 4)) << 32);
}

// Produto 64 × 64 → 128 bits, para n·Σx² − (Σx)² sem perder precisão em double.
struct U128 {
  uint64_t hi, lo;
};
U128 mul(uint64_t a, uint64_t b) {
  const uint64_t a0 = a & 0xFFFFFFFFu, a1 = a >> 32, b0 = b & 0xFFFFFFFFu, b1 = b >> 32;
  const uint64_t p00 = a0 * b0, p01 = a0 * b1, p10 = a1 * b0, p11 = a1 * b1;
  const uint64_t middle = (p00 >> 32) + (p01 & 0xFFFFFFFFu) + (p10 & 0xFFFFFFFFu);
  return {p11 + (p01 >> 32) + (p10 >> 32) + (middle >> 32), (middle << 32) | (p00 & 0xFFFFFFFFu)};
}
bool less(const U128 &a, const U128 &b) { return a.hi < b.hi || (a.hi == b.hi && a.lo < b.lo); }
U128 sub(const U128 &a, const U128 &b) { return {a.hi - b.hi - (a.lo < b.lo ? 1 : 0), a.lo - b.lo}; }
double toDouble(const U128 &v) { return ldexp(static_cast<double>(v.hi), 64) + static_cast<double>(v.lo); }
// a − b com sinal, em double.
double difference(const U128 &a, const U128 &b) {
  return less(a, b) ? -toDouble(sub(b, a)) : toDouble(sub(a, b));
}

}  // namespace

uint16_t crc16Update(uint16_t crc, uint8_t value) {
  uint32_t c = crc ^ (static_cast<uint32_t>(value) << 8);
  for (int bit = 0; bit < 8; ++bit) c = (c & 0x8000u) ? ((c << 1) ^ 0x1021u) : (c << 1);
  return static_cast<uint16_t>(c);
}

uint16_t crc16(const uint8_t *data, size_t length) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < length; ++i) crc = crc16Update(crc, data[i]);
  return crc;
}

void LinkParser::textByte(uint8_t value) {
  if (value == '\r') return;
  if (discard_) return;
  if (lineLength_ < kMaxLine) {
    line_[lineLength_++] = static_cast<char>(value);
  } else {
    ++longLines;
    lineLength_ = 0;
    discard_ = true;
  }
}

LinkParser::Event LinkParser::feed(uint8_t value) {
  switch (state_) {
    case kText:
      if (lineDone_) {  // a linha entregue valeu até este byte
        lineDone_ = false;
        lineLength_ = 0;
      }
      if (value == 0xA5) {
        state_ = kSync2;
      } else if (value == '\n') {
        const bool complete = !discard_ && lineLength_ > 0;
        discard_ = false;
        if (complete) {
          line_[lineLength_] = '\0';
          lineDone_ = true;
          return kLine;
        }
        lineLength_ = 0;
      } else {
        textByte(value);
      }
      break;
    case kSync2:
      if (value == 0x5A) {
        // Texto antes do sincronismo é descartado (como no PC).
        lineLength_ = 0;
        discard_ = false;
        state_ = kType;
      } else if (value != 0xA5) {
        state_ = kText;  // JSON é ASCII: um A5 solto é ruído
        return feed(value);
      }
      break;
    case kType:
      type_ = value;
      crc_ = crc16Update(0xFFFF, value);
      state_ = kLenL;
      break;
    case kLenL:
      length_ = value;
      crc_ = crc16Update(crc_, value);
      state_ = kLenH;
      break;
    case kLenH:
      length_ = static_cast<uint16_t>(length_ | (value << 8));
      if (length_ > kMaxFramePayload) {
        ++badHeaders;
        discard_ = true;  // até a próxima linha ou sincronismo
        state_ = kText;
        break;
      }
      crc_ = crc16Update(crc_, value);
      pos_ = 0;
      state_ = length_ ? kPayload : kCrcL;
      break;
    case kPayload:
      if (pos_ < kMaxStored) payload_[pos_] = value;
      crc_ = crc16Update(crc_, value);
      if (++pos_ >= length_) state_ = kCrcL;
      break;
    case kCrcL:
      receivedCrc_ = value;
      state_ = kCrcH;
      break;
    case kCrcH:
      receivedCrc_ = static_cast<uint16_t>(receivedCrc_ | (value << 8));
      state_ = kText;
      if (receivedCrc_ == crc_) {
        ++frames;
        return kFrame;
      }
      ++crcErrors;
      break;
  }
  return kNone;
}

size_t encodeCommand(uint8_t id, uint8_t code, const uint8_t *args, size_t nArgs, uint8_t *out,
                     size_t capacity) {
  const size_t length = 2 + nArgs;
  const size_t total = 5 + length + 2;
  if (total > capacity || length > 0xFFFF) return 0;
  out[0] = 0xA5;
  out[1] = 0x5A;
  out[2] = kFrameCommand;
  out[3] = static_cast<uint8_t>(length & 0xFF);
  out[4] = static_cast<uint8_t>(length >> 8);
  out[5] = id;
  out[6] = code;
  if (nArgs) memcpy(out + 7, args, nArgs);
  const uint16_t crc = crc16(out + 2, 3 + length);
  out[5 + length] = static_cast<uint8_t>(crc & 0xFF);
  out[6 + length] = static_cast<uint8_t>(crc >> 8);
  return total;
}

bool remoteCommandAllowed(uint8_t code) { return code >= 0x01 && code <= 0x03; }

size_t CommandGate::feed(uint8_t value, uint8_t *out, size_t capacity) {
  if (parser_.feed(value) != LinkParser::kFrame) return 0;
  const uint16_t length = parser_.length();
  if (parser_.type() != kFrameCommand || length < 2 || length > kMaxRemoteCommandPayload ||
      !remoteCommandAllowed(parser_.payload()[1])) {
    ++rejected;
    return 0;
  }
  const uint8_t *p = parser_.payload();
  const size_t size = encodeCommand(p[0], p[1], p + 2, length - 2u, out, capacity);
  if (size) ++accepted;
  return size;
}

bool parseReply(const uint8_t *payload, size_t length, Reply &out) {
  if (length < 3) return false;
  out.id = payload[0];
  out.code = payload[1];
  out.status = payload[2];
  out.data = payload + 3;
  out.length = length - 3;
  return true;
}

bool parseSummary(const uint8_t *p, size_t length, Summary &s) {
  constexpr size_t kHeader = 20;  // <IIIBBHI
  if (length < kHeader) return false;
  s.seq = rd32(p);
  s.fsMhz = rd32(p + 4);
  s.n = rd32(p + 8);
  s.mask = p[12];
  s.flags = p[13];
  s.cycles = rd16(p + 14);
  s.periodQ8 = rd32(p + 16);
  if (s.mask == 0x07) {
    s.channels = 3;
  } else if (s.mask == 0x3F) {
    s.channels = 6;
  } else {
    return false;
  }
  if (s.n < 2 || s.fsMhz < 1000u || s.fsMhz > 1000000000u) return false;
  if (length != kHeader + 12u * s.channels + (s.channels == 6 ? 24u : 0u)) return false;
  const uint8_t *q = p + kHeader;
  for (unsigned ch = 0; ch < s.channels; ++ch, q += 12) {
    s.sum[ch] = rd32(q);
    s.sumsq[ch] = rd64(q + 4);
  }
  for (unsigned ph = 0; ph < 3; ++ph) s.sumvi[ph] = s.channels == 6 ? rd64(q + 8 * ph) : 0;
  return true;
}

double Summary::frequencyHz() const {
  return synced() ? (cycles - 1) * fsHz() * 256.0 / periodQ8 : NAN;
}

double Summary::acRms(unsigned ch) const {
  if (ch >= channels) return NAN;
  const double variance = difference(mul(n, sumsq[ch]), mul(sum[ch], sum[ch]));
  return sqrt(variance > 0 ? variance : 0.0) / n;
}

double Summary::active(unsigned phase) const {
  if (!hasCurrents() || phase > 2) return NAN;
  return difference(mul(n, sumvi[phase]), mul(sum[phase], sum[phase + 3])) /
         (static_cast<double>(n) * n);
}

Measurement measure(const Summary &s, const Gains &gains) {
  Measurement m;
  m.valid = true;
  m.seq = s.seq;
  m.durationS = s.durationS();
  m.frequencyHz = s.frequencyHz();
  m.currents = s.hasCurrents();
  m.calibratedV = gains.voltages();
  m.calibratedI = m.calibratedV && gains.currents();
  for (unsigned p = 0; p < 3; ++p) {
    m.vrms[p] = s.acRms(p) * (m.calibratedV ? gains.channel[p] : 1.0);
    if (m.currents) {
      const double gi = m.calibratedI ? gains.channel[p + 3] : 1.0;
      m.irms[p] = s.acRms(p + 3) * gi;
      m.power[p] = s.active(p) * (m.calibratedI ? gains.channel[p] * gi : 1.0);
    }
  }
  return m;
}

}  // namespace prisma
