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
