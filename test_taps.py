"""Plays several 'object hit' tap variants over a dirt-like texture so the best
one can be picked by feel. Each variant starts with N beeps and plays 3 taps."""
import time
import winsound

from fh2_audio import Haptics

VARIANTS = [
    # (name, hz, seconds, square, pulses)
    ("1: current - sine 180 Hz, 80 ms", 180.0, 0.08, False, 1),
    ("2: square 180 Hz, 120 ms", 180.0, 0.12, True, 1),
    ("3: square 120 Hz, 150 ms", 120.0, 0.15, True, 1),
    ("4: double knock, square 160 Hz", 160.0, 0.07, True, 2),
    ("5: square 250 Hz, 100 ms (sharp)", 250.0, 0.10, True, 1),
    ("6: square 90 Hz, 200 ms (heavy)", 90.0, 0.20, True, 1),
]

h = Haptics()
if not h.start():
    raise SystemExit("DualSense audio endpoint not found (needs USB or DS5 Bridge).")
h.set("texture", 0.45, 0.45)               # background like driving on dirt
time.sleep(1.0)
for i, (name, hz, dur, square, pulses) in enumerate(VARIANTS, 1):
    print(name, flush=True)
    for _ in range(i):
        winsound.Beep(1000, 100)
        time.sleep(0.06)
    time.sleep(0.6)
    h.tap_hz, h.tap_s, h.tap_square, h.tap_pulses = hz, dur, square, pulses
    for _ in range(3):
        h.tap(1.0, 1.0)
        time.sleep(0.8)
    time.sleep(0.8)
h.silence()
time.sleep(0.3)
h.stop()
print("done")
