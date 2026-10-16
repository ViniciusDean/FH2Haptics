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
  thump   - decaying hit (impacts, landings, gear changes): a short noise
            'crack' on top of a ~75 Hz body, since the actuators barely
            reproduce lower frequencies
"""
import logging
import threading
import time

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
        self._click = np.zeros(2)       # onset transient level per side
        # hits are a falling 'TUM' (thump_hi -> thump_lo Hz as it decays) so they
        # feel different from the steady rumble/texture underneath
        self.thump_hi, self.thump_lo = 140.0, 55.0
        self._thump_square = False      # crashes use a square wave (much more energy)
        self.crash_hz = 80.0            # crashes: fixed, heavy frequency
        self._thump_hold = 0.0          # seconds the hit stays at full level before decaying
        self._thump_peak = 1e-6
        # ducking: while a hit plays, the other layers are held down, then come back
        self.duck_depth = 1.0           # 0..1, how much the other layers drop
        self.duck_s = 0.3               # how long they take to come back after the hold
        self._duck = 0.0
        self._duck_hold = 0.0           # seconds left at full duck
        # taps: short dry knocks for small hits (one per bollard/sign)
        self.tap_hz = 90.0
        self.tap_s = 0.2
        self.tap_square = True          # square wave: more energy than a sine at the same level
        self.tap_pulses = 1             # 2 = 'tac-tac' double knock
        self.tap_gap_s = 0.07           # time between pulses
        self._pending = []              # [seconds left, left, right] for follow-up pulses
        self._tap = np.zeros(2)
        self._phase_tap = 0.0
        self._phase = {"heavy": 0.0, "light": 0.0, "engine": 0.0, "thump": 0.0, "tap": 0.0}
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
        self.error = ""
        self.blocks = 0                 # audio blocks rendered (diagnostics)

    @property
    def available(self):
        return self.device is not None

    def start(self):
        if not self.available:
            log.warning("DualSense audio endpoint not found (needs USB or DS5 Bridge).")
            return False
        # the endpoint sometimes refuses the first open (e.g. right after another
        # program released it), so retry a few times before giving up
        for attempt in range(5):
            try:
                self._stream = sd.OutputStream(device=self.device, samplerate=self.RATE, channels=self.channels,
                                               dtype=np.float32, blocksize=self.BLOCK, latency="low",
                                               callback=self._callback)
                self._stream.start()
                return True
            except Exception as exc:                 # sounddevice.PortAudioError and friends
                self.error = f"device {self.device}: {exc}"
                self._stream = None
                time.sleep(0.5 + attempt * 0.5)
                self.device, self.channels = find_dualsense()
                if self.device is None:
                    break
        return False

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

    def thump(self, left, right, duration_s=0.15, duck=False, square=False, hold_s=0.0):
        """Fire a decaying low-frequency hit; stronger hits override weaker ones."""
        with self._lock:
            new = np.array([min(1.0, left), min(1.0, right)])
            self._click = np.maximum(self._click, new)
            if duck:
                self._duck = 1.0
                self._duck_hold = max(self._duck_hold, 0.7 * duration_s)
            if square or new.max() >= self._thump.max():
                self._thump_square = square
            self._thump = np.maximum(self._thump, new)
            self._thump_peak = max(float(self._thump.max()), 1e-6)
            self._thump_hold = max(self._thump_hold, hold_s)
            if duck:
                self._duck_hold = max(self._duck_hold, hold_s + 0.7 * duration_s)
            # level falls to ~5% after duration_s
            self._thump_decay = np.exp(-3.0 * (self.BLOCK / self.RATE) / max(0.03, duration_s))

    def tap(self, left, right):
        """A short dry knock; the other layers dip only while it plays."""
        with self._lock:
            for k in range(1, self.tap_pulses):
                self._pending.append([k * self.tap_gap_s, left, right])
            self._fire_tap(left, right)

    def _fire_tap(self, left, right):
        # caller holds self._lock
        self._tap = np.maximum(self._tap, [min(1.0, left), min(1.0, right)])
        self._duck = max(self._duck, 0.7)
        self._duck_hold = max(self._duck_hold, self.tap_s)
        self._phase["tap"] = 0.0                     # start every knock on the same edge

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
        self.blocks += 1
        n = frames
        with self._lock:
            heavy = self._ramp("heavy", n)
            light = self._ramp("light", n)
            tex = self._ramp("texture", n)
            eng = self._ramp("engine", n)
            th0 = self._thump.copy()
            if self._thump_hold > 0:
                self._thump_hold -= n / self.RATE
            else:
                self._thump *= self._thump_decay
            th1 = self._thump.copy()
            cl0 = self._click.copy()
            self._click *= 0.25                          # crack lasts ~1-2 blocks
            cl1 = self._click.copy()
            tp0 = self._tap.copy()
            self._tap *= np.exp(-3.0 * (n / self.RATE) / self.tap_s)
            tp1 = self._tap.copy()
            due = [q for q in self._pending if q[0] <= 0]
            self._pending = [q for q in self._pending if q[0] > 0]
            for q in self._pending:
                q[0] -= n / self.RATE
            for _, l, r in due:
                self._fire_tap(l, r)
            dk0 = self._duck
            if self._duck_hold > 0:
                self._duck_hold -= n / self.RATE
            else:
                self._duck *= np.exp(-3.0 * (n / self.RATE) / max(0.05, self.duck_s))
            dk1 = self._duck
            thump_hz = (self.crash_hz if self._thump_square else
                        self.thump_lo + (self.thump_hi - self.thump_lo) * min(1.0, th0.max() / self._thump_peak))
            eng_hz = self._engine_hz

        s_heavy = np.sin(2 * np.pi * self._osc("heavy", self.heavy_hz, n))
        s_light = np.sin(2 * np.pi * self._osc("light", self.light_hz, n))
        ph = self._osc("engine", eng_hz, n)
        s_eng = 2.0 * (ph % 1.0) - 1.0
        s_thump = np.sin(2 * np.pi * self._osc("thump", thump_hz, n))
        if self._thump_square:
            s_thump = np.sign(s_thump)
        ramp = np.linspace(0, 1, n)[None, :]
        thump = th0[:, None] + (th1 - th0)[:, None] * ramp
        click = (cl0[:, None] + (cl1 - cl0)[:, None] * ramp) * self._rng.uniform(-1, 1, (2, n))
        s_tap = np.sin(2 * np.pi * self._osc("tap", self.tap_hz, n))
        if self.tap_square:
            s_tap = np.sign(s_tap)
        tap = (tp0[:, None] + (tp1 - tp0)[:, None] * ramp) * s_tap

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
        s_tex *= 0.53       # normalized: texture level 1.0 ~ same RMS as a full sine (was 7.5x louder)

        duck = 1.0 - self.duck_depth * (dk0 + (dk1 - dk0) * ramp)       # (1, n)
        mix = ((heavy * s_heavy + light * s_light + tex * s_tex + eng * s_eng * 0.6) * duck
               + thump * s_thump + click + tap)
        mix = np.clip(mix * self.volume, -1.0, 1.0).astype(np.float32)
        out.fill(0.0)
        if self.channels >= 4:
            out[:, 2] = mix[0]
            out[:, 3] = mix[1]
