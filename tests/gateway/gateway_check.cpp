// Programa de teste do núcleo do gateway (gateway/esp32s3/lib/prisma_link), no PC.
//   gateway_check parse <arquivo>       eventos do LinkParser + resumos medidos
//   gateway_check srec <arquivo.s19>    imagem montada do S19 (em pedaços de 7 bytes)
//   gateway_check gate <arquivo>        comandos que o filtro da rede deixa passar
//   gateway_check flash <s19> <modo>    atualização contra a placa simulada (flash apagada)
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "board_sim.h"
#include "prisma_link.h"
#include "prisma_ota.h"

namespace {

std::vector<uint8_t> readFile(const char *path) {
  std::vector<uint8_t> data;
  FILE *f = fopen(path, "rb");
  if (!f) return data;
  int c;
  while ((c = fgetc(f)) != EOF) data.push_back(static_cast<uint8_t>(c));
  fclose(f);
  return data;
}

void number(const char *name, double value) {
  if (isnan(value)) printf(" %s=nan", name);
  else printf(" %s=%.17g", name, value);
}

int parse(const char *path) {
  const std::vector<uint8_t> data = readFile(path);
  prisma::LinkParser parser;
  prisma::Gains gains;
  for (int ch = 0; ch < 6; ++ch) gains.channel[ch] = getenv("GAINS") ? 0.5 + 0.25 * ch : 0.0;
  for (uint8_t byte : data) {
    switch (parser.feed(byte)) {
      case prisma::LinkParser::kLine:
        printf("line %s\n", parser.line());
        break;
      case prisma::LinkParser::kFrame: {
        printf("frame type=%u len=%u stored=%d\n", parser.type(), parser.length(), parser.stored() ? 1 : 0);
        prisma::Summary s;
        if (parser.type() == prisma::kFrameSummary && parser.stored() &&
            prisma::parseSummary(parser.payload(), parser.length(), s)) {
          const prisma::Measurement m = prisma::measure(s, gains);
          printf("summary seq=%u ch=%u", m.seq, s.channels);
          number("f", m.frequencyHz);
          number("dur", m.durationS);
          for (int p = 0; p < 3; ++p) {
            char key[8];
            snprintf(key, sizeof(key), "v%d", p);
            number(key, m.vrms[p]);
          }
          if (m.currents) {
            for (int p = 0; p < 3; ++p) {
              char key[8];
              snprintf(key, sizeof(key), "i%d", p);
              number(key, m.irms[p]);
              snprintf(key, sizeof(key), "p%d", p);
              number(key, m.power[p]);
            }
          }
          printf(" calv=%d cali=%d\n", m.calibratedV ? 1 : 0, m.calibratedI ? 1 : 0);
        }
        break;
      }
      default:
        break;
    }
  }
  printf("counters frames=%u crc=%u bad=%u long=%u\n", parser.frames, parser.crcErrors, parser.badHeaders,
         parser.longLines);
  return 0;
}

int gate(const char *path) {
  const std::vector<uint8_t> data = readFile(path);
  prisma::CommandGate filter;
  uint8_t frame[64];
  for (uint8_t byte : data) {
    const size_t n = filter.feed(byte, frame, sizeof(frame));
    if (!n) continue;
    printf("pass ");
    for (size_t i = 0; i < n; ++i) printf("%02X", frame[i]);
    printf("\n");
  }
  printf("counters accepted=%u rejected=%u crc=%u\n", filter.accepted, filter.rejected, filter.crcErrors());
  return 0;
}

bool loadImage(const char *path, prisma::SrecImage &image) {
  const std::vector<uint8_t> data = readFile(path);
  const char *text = reinterpret_cast<const char *>(data.data());
  for (size_t i = 0; i < data.size(); i += 7) {
    if (!image.feed(text + i, data.size() - i < 7 ? data.size() - i : 7)) break;
  }
  return image.finish();
}

int srec(const char *path) {
  prisma::SrecImage image;
  if (!loadImage(path, image)) {
    printf("error %s\n", image.error());
    return 0;
  }
  printf("ok start=%u end=%u crc=%u size=%u\n", image.start(), image.end(), image.crc(),
         static_cast<unsigned>(image.data().size()));
  return 0;
}

// Transporte ligado à placa simulada, com relógio simulado.
class SimTransport : public prisma::BootTransport {
 public:
  void write(const uint8_t *data, size_t length) override {
    for (size_t i = 0; i < length; ++i) sim_feed(data[i]);
    ++writes;
  }
  int read(uint32_t timeoutMs) override {
    const int value = sim_read();
    if (value < 0) now += timeoutMs;  // nada vem: o prazo passa
    return value;
  }
  uint32_t millis() override { return now; }
  void sleep(uint32_t ms) override { now += ms; }
  uint32_t now = 0;
  unsigned writes = 0;
};

void progress(void *context, const char *stage, uint32_t done, uint32_t total) {
  std::string *last = static_cast<std::string *>(context);
  char text[64];
  snprintf(text, sizeof(text), "%s %u/%u", stage, done, total);
  *last = text;
}

int flash(const char *path, const char *mode) {
  sim_erase_all();
  sim_start(mode);
  prisma::SrecImage image;
  if (!loadImage(path, image)) {
    printf("error %s\n", image.error());
    return 0;
  }
  SimTransport transport;
  prisma::BootClient client(transport, 300, 4);
  prisma::BootInfo info;
  if (!client.enter(info)) {
    printf("fail %s\n", client.error());
    return 0;
  }
  printf("info rev=%u valid=%d page=%u start=%u limit=%u chunk=%u hole=%u-%u\n", info.revision,
         info.appValid ? 1 : 0, info.pageSize, info.appStart, info.appLimit, info.maxChunk, info.holeStart,
         info.holeEnd);
  std::string last;
  if (!client.flash(image, info, true, progress, &last)) {
    printf("fail %s\n", client.error());
    return 0;
  }
  unsigned matches = 0;
  for (size_t i = 0; i < image.data().size(); ++i) {
    const unsigned long a = image.start() + i - 0x20000UL;
    const bool hole = a >= 0x3FE && a < 0x410;
    if (hole || sim_flash_at(a) == image.data()[i]) ++matches;
  }
  printf("ok resends=%u running=%d valid=%d match=%d hole_writes=%lu trim=%u opt=%u last=%s\n", client.resends,
         sim_in_app(), sim_app_valid(), matches == image.data().size() ? 1 : 0, sim_hole_writes(),
         sim_flash_at(0x3FE), sim_flash_at(0x40F), last.c_str());
  return 0;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc >= 3 && strcmp(argv[1], "parse") == 0) return parse(argv[2]);
  if (argc >= 3 && strcmp(argv[1], "gate") == 0) return gate(argv[2]);
  if (argc >= 3 && strcmp(argv[1], "srec") == 0) return srec(argv[2]);
  if (argc >= 4 && strcmp(argv[1], "flash") == 0) return flash(argv[2], argv[3]);
  fprintf(stderr, "uso: gateway_check parse|gate|srec|flash ...\n");
  return 2;
}
