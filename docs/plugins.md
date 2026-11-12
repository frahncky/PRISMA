# Perfis e plugins de protocolos

Um perfil de dispositivo define nome, baudrate e identificador de protocolo. Abra-o por **Dados e dispositivos → Carregar perfil de dispositivo…**, com a serial desconectada. O perfil não configura nem grava firmware na placa.

Perfis incluídos:

- `examples/profiles/serial-generico.json`: PRISMA JSON v1, com amostras e estados.
- `examples/profiles/serial-csv.json`: plugin CSV, com `t,va,vb,vc` ou `t,va,vb,vc,ia,ib,ic`, em segundos, volts e ampères. Não há cabeçalho; campos ausentes de corrente devem ser omitidos em conjunto. Não suporta mensagens de estado.

O firmware de ESP32, STM32 ou outra placa deve implementar o formato e as unidades escolhidas. Selecionar o nome de uma placa não a torna automaticamente compatível.

## API de plugins instaláveis

Plugins são pacotes Python instalados pelo usuário no mesmo ambiente do PRISMA. O registro usa o grupo `prisma.protocols` dos entry points do Python. Exemplo no `pyproject.toml` de um pacote próprio:

```toml
[project.entry-points."prisma.protocols"]
meu-protocolo-v1 = "meu_pacote.protocolo:parse_message"
```

A função recebe uma linha completa `bytes` e retorna `prisma.core.protocol.Sample` ou `HardwareStatus`. Deve validar o payload e lançar `ValueError` para linhas inválidas. O leitor recompõe fragmentos antes da chamada, limita linhas a 16384 bytes e descarta os avisos além dos cinco primeiros por conexão. Plugins desse contrato atendem protocolos delimitados por newline; protocolos binários com outro enquadramento exigem um adaptador de transporte adicional.

O parser é carregado somente quando seu perfil é selecionado, nunca por varredura/importação de todos os pacotes. Não há importação arbitrária de caminho Python indicado pelo JSON. Identificadores ausentes ou duplicados são rejeitados. Plugins são código Python com as permissões do aplicativo; instalar somente pacotes revisados e confiáveis.

O plugin `csv-trifasico-v1` está incluído na distribuição e é testado com correntes opcionais, rejeição de não finitos e seleção pelo perfil. Drivers de protocolos proprietários e validação nas placas continuam dependendo de implementação e bancada específicas.
