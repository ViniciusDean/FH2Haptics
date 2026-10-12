"""Plays each haptics layer in turn so it can be felt on the controller.

Usage: test_haptics.py [step numbers...]   e.g. test_haptics.py 6 7
"""
import sys
import time
import winsound

from fh2_audio import Haptics

h = Haptics()
if not h.start():
    raise SystemExit("DualSense audio endpoint not found (needs USB or DS5 Bridge).")
print("device", h.device, "channels", h.channels, flush=True)

STEPS = [
    ("1: heavy rumble, both sides", lambda: h.set("heavy", 0.8, 0.8)),
    ("2: heavy rumble, LEFT only", lambda: h.set("heavy", 0.8, 0.0)),
    ("3: heavy rumble, RIGHT only", lambda: h.set("heavy", 0.0, 0.8)),
    ("4: light buzz", lambda: h.set("light", 0.6, 0.6)),
    ("5: road texture", lambda: h.set("texture", 0.7, 0.7)),
    ("6: engine 30 -> 120 Hz", None),
    ("7: impacts", None),
]

only = {int(a) for a in sys.argv[1:]}
for i, (name, start) in enumerate(STEPS, 1):
    if only and i not in only:
        continue
    print(name, flush=True)
    for _ in range(i):
        winsound.Beep(1000, 100)
        time.sleep(0.06)
    if start:
        start()
        time.sleep(3)
    elif i == 6:
        h.set("engine", 0.5, 0.5)
        for k in range(60):
            h.set_engine_hz(30 + k * 1.5)
            time.sleep(0.05)
    else:
        for side in ((1, 1), (1, 0.2), (0.2, 1)):
            h.thump(*side, duration_s=0.2)
            time.sleep(1)
    h.silence()
    time.sleep(1)
h.stop()
print("done")
