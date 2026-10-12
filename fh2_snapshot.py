"""Debug snapshots: press the DualSense mute button (or F8) while playing to save
a screenshot plus the last few seconds of what the bridge read from the game
and sent to the controller, frame by frame, into the snapshots/ folder."""
import collections
import ctypes
import json
import os
import sys
import time
import winsound

import numpy as np

try:
    import hid
except ImportError:
    hid = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "snapshots")
VK_F8 = 0x77
MUTE_BYTE, MUTE_BIT = 10, 0x04          # DualSense USB input report: mute button
HISTORY_S = 4.0


class Snapshots:
    def __init__(self):
        self.history = collections.deque()
        self.raw = collections.deque()
        self._pad = None
        self._last = bytes(64)
        self._was_down = False
        self._app = None
        if hid:
            try:
                dev = next(d for d in hid.enumerate(0x054C) if d["product_id"] in (0x0CE6, 0x0DF2))
                self._pad = hid.device()
                self._pad.open_path(dev["path"])
                self._pad.set_nonblocking(1)
            except (StopIteration, OSError):
                self._pad = None

    def _pressed(self):
        down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F8) & 0x8000)
        if self._pad:
            try:
                r = self._pad.read(64)
                while r:
                    self._last = bytes(r)
                    r = self._pad.read(64)
            except OSError:
                self._pad = None
            if len(self._last) > MUTE_BYTE and self._last[0] == 0x01:
                down = down or bool(self._last[MUTE_BYTE] & MUTE_BIT)
        edge = down and not self._was_down
        self._was_down = down
        return edge

    def record(self, frame, raw=None):
        """Add one frame of state (and optionally raw memory); save a snapshot if the
        button was just pressed."""
        now = time.monotonic()
        frame["t"] = round(now, 4)
        self.history.append(frame)
        self.raw.append(raw)
        while self.history and now - self.history[0]["t"] > HISTORY_S:
            self.history.popleft()
            self.raw.popleft()
        if self._pressed():
            return self.save()
        return None

    def _screenshot(self, path):
        try:
            from PySide6.QtGui import QGuiApplication
        except ImportError:
            return False
        if self._app is None:
            self._app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        return QGuiApplication.primaryScreen().grabWindow(0).save(path)

    def save(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = os.path.join(OUT_DIR, stamp)
        shot = self._screenshot(base + ".png")
        t_end = self.history[-1]["t"] if self.history else 0.0
        frames = [dict(f, t=round(f["t"] - t_end, 3)) for f in self.history]
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump({"saved": stamp, "screenshot": shot, "frames": frames}, fh)
        raw = [(r, f["t"]) for r, f in zip(self.raw, frames) if r and all(r)]
        if raw:
            n0, n1 = min(len(r[0][0]) for r in raw), min(len(r[0][1]) for r in raw)
            np.savez_compressed(base + ".npz",
                                t=np.array([t for _, t in raw]),
                                phys=np.frombuffer(b"".join(r[0][:n0] for r, _ in raw), np.uint8).reshape(len(raw), n0),
                                car=np.frombuffer(b"".join(r[1][:n1] for r, _ in raw), np.uint8).reshape(len(raw), n1))
        winsound.Beep(1800, 80)
        return base
