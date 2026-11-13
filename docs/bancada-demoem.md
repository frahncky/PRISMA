# Integração e aceitação da DEMOEM

A placa pertence ao usuário, mas não está disponível nesta sessão. Nenhum teste físico foi executado. Este roteiro define a evidência necessária para concluir as fases de hardware; os campos em aberto não são valores recomendados.


> Para o detalhamento de alimentação, entradas de sensores, SCI/UART, ligação da tela touch, bateria recarregável e gateway IoT, veja o [guia de ligações da DEMOEM](ligacoes-hardware-demoem.md). Ele distingue recursos confirmados da placa de integrações propostas.

## 1. Identificar a bancada

No Windows conectado à placa, sem instalar nem trocar drivers automaticamente:

```powershell
.\scripts\diagnostico_windows.ps1 -OutputPath .\diagnostico-prisma.json
```

O JSON inclui dispositivos USB, VID/PID nos identificadores PnP, portas COM e versões dos drivers. A opção **Dados e dispositivos → Salvar diagnóstico serial/USB…** também coleta os metadados das portas visíveis ao aplicativo, em qualquer sistema suportado pelo pyserial.

Registrar localmente:

| Campo | Valor observado / evidência |
| --- | --- |
| Modelo e revisão da PCB | A identificar na serigrafia |
| MCU e encapsulamento | A confirmar na placa |
| Manual e esquemático correspondentes à revisão | A obter |
| VID/PID de BDM e da interface serial | A coletar pelo diagnóstico |
| Driver PEmicro e versão | A coletar pelo diagnóstico |
| CodeWarrior, compilador e versão | A identificar na instalação |
| Gravador/probe e número de série | A identificar |
| Tensão de alimentação e nível lógico da SCI | A confirmar no manual |

Um dispositivo BDM detectado não comprova uma porta COM. Não usar VID/PID de outros kits como identificação desta placa.

## 2. Confirmar ligações antes do port de firmware

Não existe mapa de pinos aprovado nesta versão. Preencher esta tabela a partir do manual da revisão efetiva, com número da página e posição dos jumpers:

| Função | Pino/conector | Jumper | Referência no manual |
| --- | --- | --- | --- |
| SCI TX / RX / GND | Pendente | Pendente | Pendente |
| ADC Va / Vb / Vc | Pendente | Pendente | Pendente |
| ADC Ia / Ib / Ic, se presentes | Pendente | Pendente | Pendente |
| LEDs e GPIO de leitura | Pendente | Pendente | Pendente |
| LCD | Pendente | Pendente | Pendente |
| Clock e referência ADC | Pendente | Pendente | Pendente |
| BDM e alimentação do probe | Pendente | Pendente | Pendente |

Confirmar sensores, escala ADC, offset, filtros anti-aliasing, sincronização entre canais e isolamento. Não conectar a rede elétrica diretamente ao MCU. Usar primeiro sinais de baixa tensão de um gerador de bancada compatível com os limites do circuito.

## 3. Portar e compilar

O encoder C e a aplicação em `firmware/src/` são compiláveis no computador. O port `firmware/ports/mcf51em256_port.example.c` está bloqueado com `#error` até que a HAL real seja implementada. Ele não configura registradores, não assume pinagem e não produz uma imagem gravável por si só.

1. Criar o projeto MCF51EM256 na versão licenciada do CodeWarrior disponível na bancada, com BSP, startup e linker correspondentes.
2. Implementar `prisma_hal_init`, `prisma_hal_next`, `prisma_hal_write` e `prisma_hal_status` conforme `firmware/include/prisma_hal.h`.
3. Conferir a disponibilidade de C99, `stdint.h` e `vsnprintf` na biblioteca do compilador; adaptar o encoder se necessário.
4. Usar timer de hardware e amostragem sincronizada. `time_ms` deve ser crescente; reiniciar a sessão antes de seu rollover de aproximadamente 49,7 dias ou após reset da placa.
5. Medir o tamanho real das mensagens e a capacidade da SCI. Não selecionar uma taxa de amostragem apenas pela taxa do modo demo.
6. Compilar no IDE e conferir MCU, linker, memória, warnings e símbolos de depuração.
7. Só então preencher o projeto JSON da toolchain e testar a execução pelo PRISMA.

## 4. Orçamento da serial

A capacidade aproximada em 8N1 é `baudrate / 10` bytes/s. A 115200 baud, são cerca de 11520 bytes/s antes de folgas e mensagens de estado. Uma linha de 140 bytes a 200 amostras/s exigiria 28000 bytes/s e não cabe nesse enlace.

Para analisar h15 de 60 Hz, a amostragem deve superar 1800 amostras/s. A taxa de 2400 amostras/s do demo **não comprova viabilidade de JSON pela SCI da DEMOEM**. Dependendo dos canais e da taxa de baud validada, será necessário um transporte binário/blocos, redução de canais ou outro enlace. Nunca decimar sem filtro anti-aliasing. Se o firmware não sustentar a transmissão, registrar perdas e corrigir o transporte antes de aceitar as medições.

## 5. Aceitação física

- [ ] Identificação da revisão, drivers, toolchain e probe documentada.
- [ ] SCI validada com mensagens completas, timestamps crescentes e ausência de perdas na taxa declarada.
- [ ] ADC comparado com referência conhecida em pelo menos três pontos por canal.
- [ ] Frequência de 50/60 Hz e amplitudes comparadas com instrumento de referência.
- [ ] LEDs/GPIO/ADC/LCD comparados com o estado observado na placa; a tela apenas reproduz a telemetria recebida.
- [ ] Histórico CSV/SQLite com dados reais, origem e coeficientes de calibração conferidos.
- [ ] Build ColdFire reproduzível e mapa de memória revisado.
- [ ] Backup do firmware anterior, se permitido e suportado pelo probe, e plano de recuperação definidos.
- [ ] Gravação PEmicro executada com confirmação e firmware reiniciado corretamente.
- [ ] Breakpoint, pausa, continuação e registradores conferidos na sessão real de depuração.
- [ ] Relatório local com data, versões, comandos, hashes, resultados e limitações.

Somente após anexar essas evidências devem ser encerradas as pendências físicas do roadmap. Não guardar licenças, credenciais, firmwares proprietários ou números de série em um repositório público.
