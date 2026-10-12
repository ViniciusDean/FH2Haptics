"""FH2-specific L2/R2 effects built on HorizonHaptics' Parser.

Uses the data the game itself exposes (ABS-active flag, per-wheel normalized
slip) and Turn 10's own impulse-trigger curves from media/ControllerHaptics.xml,
and outputs DualSense effects in DSY's native Sony modes.
"""
import json
import os
import time

from GameParsers.parser import Parser

# DSY native Sony modes
OFF, MULTI_FEEDBACK, MULTI_VIBRATION, VIBRATION = 20, 25, 26, 23

# Turn 10 impulse-trigger curves (media/ControllerHaptics.xml): (x, y) points
BRAKE_LOCK_CURVE = ((1.5, 0.0), (2.6, 0.56), (3.0, 0.9))       # BrakingSlipRatioEnd

DEFAULTS = {
    # L2 pedal: resistance per zone (0-8), from top of travel to the bottom
    "brake_profile": [0, 1, 1, 2, 3, 4, 5, 6, 7, 8],
    "brake_strength": 1.0,           # scales the whole pedal profile
    "abs_freq": 22,                  # Hz of the ABS pulse
    "abs_amp": 5,                    # 1-8 vibration under ABS
    "abs_wall": 3,                   # bottom zones that stay firm under ABS
    "lock_slip": 1.5,                # normalized slip where a wheel counts as locked (no ABS)
    "lock_freq": 12,                 # Hz, coarse judder while locked
    "lock_pedal": 1,                 # pedal resistance while locked (pedal "gives")
    # R2
    "throttle_profile": [0, 0, 1, 1, 1, 2, 2, 2, 3, 3],
    "throttle_strength": 1.0,
    # R2 traction loss = max(wheelspin, sideways slide), each mapped 0..1
    "spin_start": 0.25,              # driven-wheel normalized slip where vibration begins
    "spin_full": 1.2,                # ... and where it is at full strength
    "slide_start_deg": 5.0,          # rear sliding sideways: angle where vibration begins
    "slide_full_deg": 20.0,          # ... and where it is at full strength
    "spin_min_throttle": 0.15,       # only while on the throttle
    "spin_amp_min": 2,               # vibration amplitude (1-8) at the start
    "spin_amp_max": 8,               # ... and at full traction loss
    "spin_freq_min": 18,             # Hz at the start
    "spin_freq_max": 50,             # Hz at full traction loss
    "spin_light": 0.4,               # how much lighter R2 gets under wheelspin (0-1)
    "shift_kick": True,              # short R2 kick on gear change (Turn 10 OnShift)
    "shift_amp": 6,
    "shift_ms": 70,
}

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def load_settings():
    cfg = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULTS, fh, indent=2)
    except (OSError, ValueError):
        pass
    return cfg


def curve(x, pts):
    (x0, y0), (x1, y1), (x2, y2) = pts
    if x <= x0:
        return y0
    if x <= x1:
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    if x <= x2:
        return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return y2


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(round(v))))


def _profile(zones, scale):
    return [_clamp(z * scale, 0, 8) for z in zones]


class FH2Parser(Parser):
    """Overrides the L2/R2 logic; collision, lightbar etc. stay HorizonHaptics'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = load_settings()
        self._kick_until = 0.0
        self._last_gear = 0
        self.debug = ""

    def compute(self, pkt):
        if self.cfg["shift_kick"] and pkt.is_race_on:
            if self._last_gear > 0 and pkt.gear > 0 and pkt.gear != self._last_gear and pkt.speed > 2:
                self._kick_until = time.monotonic() + self.cfg["shift_ms"] / 1000
            self._last_gear = pkt.gear
        return super().compute(pkt)

    # -- L2 --------------------------------------------------------------
    def _l2(self, pkt):
        c = self.cfg
        burst = self._collision_burst()
        if burst is not None:
            return burst
        pedal = _profile(c["brake_profile"], c["brake_strength"] * self.brake.intensity / 0.8)
        braking = pkt.brake > 25
        lock = max(getattr(pkt, "lock_slip", [0.0]))

        if braking and getattr(pkt, "abs_active", False):
            amp = _clamp(c["abs_amp"] * self.brake.intensity / 0.8, 1, 8)
            wall = _clamp(c["abs_wall"], 0, 9)
            zones = [amp] * (10 - wall) + [8] * wall
            self.debug = "L2 ABS"
            return ("dsx", [MULTI_VIBRATION, _clamp(c["abs_freq"], 1, 255), *zones])

        if braking and lock >= c["lock_slip"]:
            y = curve(lock, BRAKE_LOCK_CURVE)
            amp = _clamp(max(y, 0.2) / 0.9 * 8, 1, 8)
            zones = [max(c["lock_pedal"], amp if i < 7 else c["lock_pedal"]) for i in range(10)]
            self.debug = f"L2 LOCKED {lock:.1f}"
            return ("dsx", [MULTI_VIBRATION, _clamp(c["lock_freq"], 1, 255), *zones])

        self.debug = "L2 pedal"
        return ("dsx", [MULTI_FEEDBACK, *pedal]) if any(pedal) else ("dsx", [OFF])

    # -- R2 --------------------------------------------------------------
    def _r2(self, pkt):
        c = self.cfg
        burst = self._collision_burst()
        if burst is not None:
            return burst
        if time.monotonic() < self._kick_until:
            return ("dsx", [VIBRATION, 0, _clamp(c["shift_amp"], 1, 8), 30])

        base = _profile(c["throttle_profile"], c["throttle_strength"] * self.throttle.intensity / 0.7)
        spin = max(getattr(pkt, "spin_slip", [0.0]))
        slide = getattr(pkt, "slide_deg", 0.0)
        ramp = lambda x, a, b: max(0.0, min(1.0, (x - a) / (b - a))) if b > a else float(x >= a)
        loss = max(ramp(spin, c["spin_start"], c["spin_full"]),
                   ramp(slide, c["slide_start_deg"], c["slide_full_deg"]))
        if pkt.accel >= c["spin_min_throttle"] * 255 and loss > 0.0:
            amp = _clamp(c["spin_amp_min"] + (c["spin_amp_max"] - c["spin_amp_min"]) * loss, 1, 8)
            freq = c["spin_freq_min"] + (c["spin_freq_max"] - c["spin_freq_min"]) * loss
            light = 1.0 - c["spin_light"] * loss
            zones = [max(amp, _clamp(b * light, 0, 8)) for b in base]
            self.debug += f" | R2 SPIN {loss:.2f} ({spin:.2f}/{slide:.0f}°)"
            return ("dsx", [MULTI_VIBRATION, _clamp(freq, 1, 255), *zones])

        self.debug += " | R2 normal"
        return ("dsx", [MULTI_FEEDBACK, *base]) if any(base) else ("dsx", [OFF])
