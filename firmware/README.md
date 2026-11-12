# Firmware DEMOEM / MCF51EM256

Ainda NÃO existe firmware compilável nem gravável para o kit nesta versão.

Para a integração real, confirmar revisão da placa, compilador CodeWarrior/ColdFire V1, driver PEmicro BDM no Windows 11, e roteamento SCI via jumpers. O protocolo proposto está em ../docs/protocolo.md.

BDM Debug Interface não é uma porta serial. A presença de BDM Serial Interface no Gerenciador de Dispositivos não garante porta COM funcional. A interface atual não acessa variáveis da DEMOEM sem firmware compatível.
