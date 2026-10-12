# FH2 Haptics

Gatilhos adaptativos do DualSense para o **Forza Horizon 2** rodando no PC pelo **[Azimuth](https://almost-there-games.itch.io/azimuth)**.

O FH2 nunca teve telemetria "Data Out". Este projeto lê a física do carro direto da memória do `azimuth.exe` (somente leitura, nenhum arquivo do jogo é alterado) e transforma isso em efeitos no L2/R2, enviados ao **[DualSenseY](https://github.com/WujekFoliarz/DualSenseY-v2)**, que continua cuidando da emulação de controle de Xbox.

> *English: DualSense adaptive-trigger effects for Forza Horizon 2 running through the Azimuth launcher. Reads the player car's physics from `azimuth.exe` memory (read-only) and drives the triggers through DualSenseY's DSX-compatible UDP API.*

## Efeitos

| Gatilho | Situação | Efeito |
|---|---|---|
| L2 | Freio normal | Pedal progressivo: endurece ao longo do curso |
| L2 | ABS atuando (flag do próprio jogo) | Pulsação de ABS com o fundo do curso firme |
| L2 | Roda travada sem ABS | Pedal cede e treme, na intensidade da curva original da Turn 10 |
| R2 | Normal | Resistência leve e progressiva |
| R2 | Roda patinando ou traseira saindo de lado | Vibra mais forte e mais rápido quanto maior a perda de tração, e o gatilho fica mais leve |
| R2 | Troca de marcha | Tranco curto |
| L2/R2 | Batidas | Tranco forte |
| Lightbar | — | Conta-giros (verde → vermelho, pisca no corte) |

Dados usados: velocidade, RPM, marcha, acelerador, freio, freio de mão, volante, vetor de velocidade, orientação, flag de ABS e o escorregamento normalizado de cada pneu, calculado pelo próprio jogo. As curvas de vibração de travamento seguem o `media/ControllerHaptics.xml` do jogo, que é a configuração dos impulse triggers do Xbox One.

## Requisitos

- Windows 10/11
- Forza Horizon 2 **1.0.0.64**, dump da **sua própria cópia**, rodando no **Azimuth 0.9.7**
- DualSense **no cabo USB**
- [DualSenseY](https://github.com/WujekFoliarz/DualSenseY-v2) aberto, com o servidor UDP na porta **6969** (padrão)
- [HorizonHaptics](https://github.com/haritha99ch/HorizonHaptics) clonado **na mesma pasta pai** deste projeto. A lógica base de efeitos e a lightbar vêm dele. Rode o `run.bat` dele uma vez para criar o `.venv` e depois **feche-o**, porque ele escreve no controle direto e brigaria com o DSY.

```
Documents\
├── HorizonHaptics\   ← github.com/haritha99ch/HorizonHaptics
└── FH2Haptics\       ← este repositório
```

Se o HorizonHaptics estiver em outro lugar, defina a variável `HORIZONHAPTICS_DIR`.

## Uso

1. Abra o DualSenseY e o jogo pelo Azimuth.
2. Dê dois cliques em `run.bat`.
3. O console mostra velocidade, RPM, marcha, derrapagem e qual efeito está ativo.

`test_modes.py` testa os modos de gatilho do DSY um por um, para confirmar que a comunicação funciona.

## Ajustes

Na primeira execução é criado um `settings.json` com todos os parâmetros. Estes são os principais:

- `brake_profile`: dureza do pedal do freio, zona por zona (0–8, do topo ao fundo do curso)
- `abs_freq`, `abs_amp`, `abs_wall`: pulsação do ABS
- `spin_start` / `spin_full`: patinada de roda onde a vibração do R2 começa e onde atinge o máximo
- `slide_start_deg` / `slide_full_deg`: ângulo de derrapagem lateral onde a vibração começa e onde atinge o máximo
- `spin_amp_min` / `spin_amp_max`, `spin_freq_min` / `spin_freq_max`: força e frequência da vibração do R2
- `shift_kick`: liga ou desliga o tranco de troca de marcha

A intensidade geral e a lightbar seguem as configurações salvas do HorizonHaptics (`~/.config/horizonhaptics/settings.json`).

## Como funciona

- O Azimuth carrega o executável do FH2 no endereço fixo `0x140000000`. Um ponteiro estático (`0x14365AE10 → +0x1E8`) leva ao objeto `ForzaCar` do jogador. Os tipos são validados pelas vtables do RTTI, e o ponteiro `+0x4C08` leva ao estado de física.
- Os deslocamentos foram achados por RTTI, correlação com a posição real dos gatilhos e análise de gravações. Estão todos comentados no topo de `fh2_haptics.py`.
- Os efeitos são enviados nos modos nativos da Sony que o DSY aceita pelo UDP: `MULTIPLE_POSITION_FEEDBACK`, `MULTIPLE_POSITION_VIBRATION` e `VIBRATION`.

Outras versões do jogo ou do Azimuth provavelmente mudam os endereços.

## Créditos

- **[Azimuth](https://almost-there-games.itch.io/azimuth)**, de Almost There Games: o launcher que roda o FH2 de Xbox One no PC. Sem ele nada disso existe.
- **[DualSenseY](https://github.com/WujekFoliarz/DualSenseY-v2)**, de WujekFoliarz: emulação de controle e a API UDP usada para controlar os gatilhos.
- **[HorizonHaptics](https://github.com/haritha99ch/HorizonHaptics)**, de Haritha Rathnayake (MIT): lógica base de efeitos, lightbar e configurações.
- **Turn 10 / Playground Games**: curvas originais de vibração dos gatilhos (`ControllerHaptics.xml`).

## Aviso

Projeto de fãs, sem afiliação com Microsoft, Playground Games, Turn 10, Almost There Games ou os autores do DualSenseY. Nenhum arquivo do jogo é distribuído aqui. Use apenas com uma cópia que você possui. Forza Horizon é marca registrada da Microsoft.

## Licença

[MIT](LICENSE)
