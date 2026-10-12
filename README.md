# FH2 Haptics

DualSense adaptive-trigger effects for **Forza Horizon 2** running on PC through **[Azimuth](https://almost-there-games.itch.io/azimuth)**.

FH2 never had "Data Out" telemetry. This project reads the player car's physics straight from `azimuth.exe` memory (read-only; no game file is modified) and turns it into L2/R2 effects, sent to **[DualSenseY](https://github.com/WujekFoliarz/DualSenseY-v2)**, which keeps handling the Xbox controller emulation.

## Effects

| Trigger | Situation | Effect |
|---|---|---|
| L2 | Normal braking | Progressive pedal that stiffens along the travel |
| L2 | ABS active (the game's own ABS flag) | ABS pulsing with a firm wall at the bottom of the travel |
| L2 | Wheel locked, no ABS | Pedal gives way and judders, following Turn 10's original curve |
| R2 | Normal | Light progressive resistance |
| R2 | Wheelspin or rear stepping out | Stronger and faster vibration as traction loss grows; the trigger gets lighter |
| R2 | Gear change | Short kick |
| L2/R2 | Collisions | Hard jolt |
| Lightbar | — | Tachometer (green → red, flashes at the limiter) |

Data used: speed, RPM, gear, throttle, brake, handbrake, steering, velocity vector, orientation, ABS flag, and each tire's normalized slip as computed by the game itself. The lock-up vibration curves follow the game's `media/ControllerHaptics.xml`, which is the Xbox One impulse-trigger configuration.

## Requirements

- Windows 10/11
- Forza Horizon 2 **1.0.0.64**, dumped from **your own copy**, running on **Azimuth 0.9.7**
- DualSense **over USB**, or **wireless through an adapter that shows up as USB**. I use **[DS5 Bridge](https://github.com/SundayMoments/DS5_Bridge)** on a **Raspberry Pi Pico 2 W**. Over plain Windows Bluetooth, audio haptics don't work because they need USB mode.
- [DualSenseY](https://github.com/WujekFoliarz/DualSenseY-v2) running with its UDP server on port **6969** (default)
- [HorizonHaptics](https://github.com/haritha99ch/HorizonHaptics) cloned **next to this project**. The base effect logic and the lightbar come from it. Run its `run.bat` once to create the `.venv`, then **close it**: it writes to the controller directly and would fight with DSY.

```
Documents\
├── HorizonHaptics\   ← github.com/haritha99ch/HorizonHaptics
└── FH2Haptics\       ← this repository
```

If HorizonHaptics lives somewhere else, set the `HORIZONHAPTICS_DIR` environment variable.

## Usage

1. Start DualSenseY and the game through Azimuth.
2. Double-click `run.bat`.
3. The console shows speed, RPM, gear, slip and the active effect.

`test_modes.py` plays each DSY trigger mode in turn, to check that the connection works.

## Tuning

A `settings.json` with every parameter is created on the first run. The main ones:

- `brake_profile`: brake pedal stiffness, zone by zone (0–8, top to bottom of the travel)
- `abs_freq`, `abs_amp`, `abs_wall`: ABS pulsing
- `spin_start` / `spin_full`: wheelspin where the R2 vibration starts and where it reaches full strength
- `slide_start_deg` / `slide_full_deg`: sideways slide angle where the vibration starts and where it reaches full strength
- `spin_amp_min` / `spin_amp_max`, `spin_freq_min` / `spin_freq_max`: R2 vibration strength and frequency
- `shift_kick`: turns the gear-change kick on or off

Overall intensity and the lightbar follow HorizonHaptics' saved settings (`~/.config/horizonhaptics/settings.json`).

## How it works

- Azimuth maps the FH2 executable at the fixed address `0x140000000`. A static pointer (`0x14365AE10 → +0x1E8`) leads to the player's `ForzaCar` object. Types are validated through their RTTI vtables, and `+0x4C08` leads to the physics state.
- Offsets were found through RTTI, correlation with the real trigger positions, and analysis of recorded driving. They are all documented at the top of `fh2_haptics.py`.
- Effects are sent in the native Sony modes DSY accepts over UDP: `MULTIPLE_POSITION_FEEDBACK`, `MULTIPLE_POSITION_VIBRATION` and `VIBRATION`.

Other game or Azimuth versions will most likely move the addresses.

## Credits

- **[Azimuth](https://almost-there-games.itch.io/azimuth)** by Almost There Games: the launcher that runs the Xbox One version of FH2 on PC. None of this exists without it.
- **[DualSenseY](https://github.com/WujekFoliarz/DualSenseY-v2)** by WujekFoliarz: controller emulation and the UDP API used to drive the triggers.
- **[DS5 Bridge](https://github.com/SundayMoments/DS5_Bridge)** by SundayMoments (based on [DS5Dongle](https://github.com/awalol/DS5Dongle) by awalol): Raspberry Pi Pico 2 W wireless adapter that makes the DualSense work as if it were on USB.
- **[HorizonHaptics](https://github.com/haritha99ch/HorizonHaptics)** by Haritha Rathnayake (MIT): base effect logic, lightbar and settings.
- **Turn 10 / Playground Games**: the original trigger vibration curves (`ControllerHaptics.xml`).

## Disclaimer

Fan project, not affiliated with Microsoft, Playground Games, Turn 10, Almost There Games, or the authors of DualSenseY and DS5 Bridge. No game files are distributed here. Only use it with a copy you own. Forza Horizon is a trademark of Microsoft.

## License

[MIT](LICENSE)
