#pragma once
// COPIAR PARA include/secrets.h (não versionar segredos).
// Wi-Fi somente como estação, sem AP aberto.
#define PRISMA_WIFI_SSID "SEU_WIFI"
#define PRISMA_WIFI_PASSWORD "SENHA_DO_WIFI"
// Deixe vazios para desabilitar MQTT; informe CA do seu broker para habilitar.
#define PRISMA_MQTT_HOST ""
#define PRISMA_MQTT_PORT 8883
#define PRISMA_MQTT_USER ""
#define PRISMA_MQTT_PASSWORD ""
#define PRISMA_MQTT_CA_PEM ""
// Exemplo para uma CA real, verificada pelo administrador do broker:
// #define PRISMA_MQTT_CA_PEM R"PEM(-----BEGIN CERTIFICATE-----
// ...certificado da autoridade certificadora...
// -----END CERTIFICATE-----)PEM"
// Atualização da DEMOEM pelo navegador (POST /api/ota). Vazio ou com menos de 12
// caracteres: desligada. Use um valor longo e aleatório; a rede deve ser confiável
// (o token vai em HTTP sem TLS).
#define PRISMA_OTA_TOKEN ""
// Ganhos por canal (va vb vc ia ib ic), unidade física por contagem, copiados do
// "gain" do perfil de calibração do PC. Zeros: o painel e o MQTT mostram contagens.
// #define PRISMA_CAL_GAINS {0.0061, 0.0061, 0.0061, 0.00042, 0.00042, 0.00042}
