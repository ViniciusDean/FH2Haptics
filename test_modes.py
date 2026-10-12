"""Cycles the DSY Sony trigger modes so they can be felt one by one."""
import json
import socket
import time
import winsound

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send(side, *params):
    s.sendto(json.dumps({"instructions": [{"type": 1, "parameters": [0, side, *params]}]}).encode(),
             ("127.0.0.1", 6969))


TESTS = [
    ("1: R2 - rising resistance (10 zones, weak -> strong)", 2, [25, 0, 1, 2, 3, 4, 5, 6, 7, 8, 8]),
    ("2: L2 - ABS vibration (zones pulsing, firm bottom)", 1, [26, 20, 3, 3, 3, 3, 3, 3, 3, 8, 8, 8]),
    ("3: R2 - plain 30 Hz vibration", 2, [23, 0, 6, 30]),
    ("4: L2 - progressive pedal (slope)", 1, [24, 0, 9, 1, 8]),
]

for rnd in range(2):
    for i, (name, side, params) in enumerate(TESTS, 1):
        print(name, flush=True)
        for _ in range(i):
            winsound.Beep(1000, 120)
            time.sleep(0.08)
        send(side, *params)
        time.sleep(6)
        send(side, 0)
        time.sleep(1)
print("done")
