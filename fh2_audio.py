"""Synthesized body haptics for the DualSense's voice-coil actuators.

Everything is generated from car data; no game audio is captured, so radio and
music never reach the controller. Output goes to the DualSense's 4-channel
WASAPI endpoint (channels 3/4 drive the left/right actuators), which also works
wirelessly through DS5 Bridge.

Layers (each has a left and right amplitude, 0-1):
  heavy   - low sine, Turn 10's "LeftMotor" (big rumble; ~70 Hz, lower is barely felt)
  light   - high sine, Turn 10's "RightMotor" (fine buzz)
  texture - band-limited noise for road surface
  engine  - sawtooth locked to RPM
  thump   - decaying low hit (impacts, landings, gear changes)
"""
import logging
import threading

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

log = logging.getLogger("fh2.audio")


def find_dualsense():
    """Return (device index, channels) of the DualSense WASAPI output, or (None, 0)."""
    if not sd:
        return None, 0
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if a["name"] == "Windows WASAPI"), None)
    for i, dev in enumerate(sd.query_devices()):
        name = dev["name"].lower()
        if (dev["hostapi"] == wasapi and dev["max_output_channels"] >= 4
                and ("dualsense" in name or "wireless controller" in name)):
            return i, dev["max_output_channels"]
    return None, 0


class Haptics:
    RATE = 48000
    BLOCK = 480                     # 10 ms blocks
    LAYERS = ("heavy", "light", "texture", "engine")

    def __init__(self, heavy_hz=70.0, light_hz=170.0, texture_hz=(90.0, 260.0), volume=1.0):
        self.device, self.channels = find_dualsense()
        self.heavy_hz, self.light_hz = heavy_hz, light_hz
        self.volume = volume
        self._lock = threading.Lock()
        # targets set by the game thread, current values smoothed per block
        self._target = {k: [0.0, 0.0] for k in self.LAYERS}
        self._cur = {k: np.zeros(2) for k in self.LAYERS}
        self._engine_hz = 40.0
        self._thump = np.zeros(2)       # current thump envelope level per side
        self._thump_decay = 0.0
        self._phase = {"heavy": 0.0, "light": 0.0, "engine": 0.0, "thump": 0.0}
        # band-pass for texture noise (simple 2-pole resonator)
        lo, hi = texture_hz
        self._tex_state = np.zeros((2, 2))
        f0 = (lo * hi) ** 0.5
        bw = hi - lo
        r = np.exp(-np.pi * bw / self.RATE)
        self._tex_a = (2 * r * np.cos(2 * np.pi * f0 / self.RATE), -r * r)
        self._tex_g = (1 - r)
        self._rng = np.random.default_rng()
        self._stream = None

    @property
    def available(self):
        return self.device is not None

    def start(self):
        if not self.available:
            log.warning("DualSense audio endpoint not found (needs USB or DS5 Bridge).")
            return False
        self._stream = sd.OutputStream(device=self.device, samplerate=self.RATE, channels=self.channels,
                                       dtype=np.float32, blocksize=self.BLOCK, latency="low",
                                       callback=self._callback)
        self._stream.start()
        return True

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # -- control (called from the game loop) -------------------------------
    def set(self, layer, left, right):
        with self._lock:
            self._target[layer] = [max(0.0, min(1.0, left)), max(0.0, min(1.0, right))]

    def set_engine_hz(self, hz):
        self._engine_hz = max(10.0, min(200.0, hz))

    def thump(self, left, right, duration_s=0.15):
        """Fire a decaying low-frequency hit; stronger hits override weaker ones."""
        with self._lock:
            self._thump = np.maximum(self._thump, [min(1.0, left), min(1.0, right)])
            self._thump_decay = np.exp(-1.0 / max(0.02, duration_s) * self.BLOCK / self.RATE * 3.0)

    def silence(self):
        with self._lock:
            for k in self.LAYERS:
                self._target[k] = [0.0, 0.0]

    def state(self):
        """Current layer targets, engine frequency and thump level, for debugging."""
        with self._lock:
            out = {k: [round(v, 3) for v in self._target[k]] for k in self.LAYERS}
            out["thump"] = [round(float(v), 3) for v in self._thump]
        out["engine_hz"] = round(self._engine_hz, 1)
        return out

    # -- audio thread --------------------------------------------------------
    def _osc(self, name, hz, n):
        ph = self._phase[name] + np.arange(1, n + 1) * (hz / self.RATE)
        self._phase[name] = ph[-1] % 1.0
        return ph

    def _ramp(self, layer, n):
        """Linear ramp from the current to the target amplitude over one block (no pops)."""
        cur = self._cur[layer]
        tgt = np.array(self._target[layer])
        ramp = cur[:, None] + (tgt - cur)[:, None] * np.linspace(1.0 / n, 1.0, n)[None, :]
        self._cur[layer] = tgt
        return ramp                                  # shape (2, n)

    def _callback(self, out, frames, _time, status):
        n = frames
        with self._lock:
            heavy = self._ramp("heavy", n)
            light = self._ramp("light", n)
            tex = self._ramp("texture", n)
            eng = self._ramp("engine", n)
            th0 = self._thump.copy()
            self._thump *= self._thump_decay
            th1 = self._thump.copy()
            eng_hz = self._engine_hz

        s_heavy = np.sin(2 * np.pi * self._osc("heavy", self.heavy_hz, n))
        s_light = np.sin(2 * np.pi * self._osc("light", self.light_hz, n))
        ph = self._osc("engine", eng_hz, n)
        s_eng = 2.0 * (ph % 1.0) - 1.0
        s_thump = np.sin(2 * np.pi * self._osc("thump", 38.0, n))
        thump = th0[:, None] + (th1 - th0)[:, None] * np.linspace(0, 1, n)[None, :]

        noise = self._rng.uniform(-1, 1, (2, n))
        s_tex = np.empty((2, n))
        a1, a2 = self._tex_a
        for side in range(2):                         # resonant band-pass, per sample
            y1, y2 = self._tex_state[side]
            x = noise[side] * self._tex_g
            col = s_tex[side]
            for i in range(n):
                y = x[i] + a1 * y1 + a2 * y2
                col[i] = y
                y2, y1 = y1, y
            self._tex_state[side] = (y1, y2)
        s_tex *= 4.0

        mix = (heavy * s_heavy + light * s_light + tex * s_tex + eng * s_eng * 0.6 + thump * s_thump)
        mix = np.clip(mix * self.volume, -1.0, 1.0).astype(np.float32)
        out.fill(0.0)
        if self.channels >= 4:
            out[:, 2] = mix[0]
            out[:, 3] = mix[1]
