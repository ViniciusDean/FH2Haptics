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
    "lock_amp": 1.0,                 # strength of the lock-up judder
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
    "crash_trigger_amp": 8,          # 1-8: both triggers on a crash
    "object_trigger_amp": 4,         # 1-8: both triggers on an object hit (bollards...)
    "object_trigger_s": 0.1,
    "lightbar": True,                # tachometer on the lightbar
    "rpm_light": {
        "start": 0.70,               # share of max RPM where the light comes on
        "flash": 0.93,               # ... and where it starts flashing (shift now)
        "flash_hz": 10.0,            # flash speed, 0 = solid
        "brightness": 1.0,
        "colors": [[0, 255, 0], [255, 255, 0], [255, 0, 0]],   # low -> mid -> high
        "flash_color": [255, 0, 0],
    },
    "game_exe": "",                  # azimuth.exe, for "start with the game"
    "language": "",                  # UI language: "pt", "en" or "" (system)
    "autostart": True,               # start the bridge as soon as the window opens
    # per-effect strength, 0 = off, 1 = default, 3 = absurd (see LEVELS)
    "levels": {},
    # debug: lock both triggers solid for a moment on every object hit
    "debug_lock_on_hit": False,
    "debug_beep_on_hit": False,     # debug: short beep on the PC for every object hit
    "debug_lock_s": 1.0,
    # body haptics (DualSense actuators), synthesized from car data only
    "haptics": {
        "enabled": True,
        "volume": 1.0,                 # master volume
        "keep_device_audible": True,   # unmute / restore the DualSense speaker endpoint if something mutes it
        "device_volume": 1.0,          # ... to this Windows volume (the haptics follow it)
        "rumble": 1.0,                 # Turn 10 rumble layers (traction, bumps, hits, shift)
        "engine": 0.12,                # engine growl (kept low so it does not mask the rest)
        "engine_hz_idle": 30.0,        # growl frequency at idle ...
        "engine_hz_max": 110.0,        # ... and at the limiter
        # off asphalt, per surface class (from the game's surface id): texture amount and
        # the Turn 10 SurfaceBumpiness input (0-0.12) that drives the rumble layers
        "surfaces": {
            "1": {"name": "dirt/gravel", "texture": 0.5, "bumpiness": 0.05},
            "2": {"name": "grass", "texture": 0.3, "bumpiness": 0.025},
            "other": {"name": "unknown", "texture": 0.4, "bumpiness": 0.03},
        },
        "surface_full_speed": 20.0,    # m/s where surface effects reach full strength
        "detail": 1.0,                 # small road details on asphalt
        "detail_floor": 0.08,          # suspension speed (m/s) ignored as smooth road
        "detail_gain": 2.0,            # suspension speed above the floor -> detail amount
        "detail_offroad": 0.15,        # share of the detail layer kept off asphalt
        "texture_max": 0.6,            # cap for texture + detail, so hits always stand out
        "object_hit": 1.0,             # thump when hitting objects (bollards, fences, signs)
        "hit_duck": 1.0,               # how much the other layers drop while a hit plays (0-1)
        "tap_hz": 90.0,                # object-hit knock: frequency (picked by feel, test_taps.py #6)
        "tap_s": 0.2,                  # ... length, seconds
        "tap_square": True,            # ... square wave (stronger) instead of sine
        "tap_pulses": 1,               # ... 2 = double knock
        "hit_duck_s": 0.3,             # how long they take to come back after the hit, seconds
        "traction": 0.8,               # heavy rumble when the car loses traction (same index as R2)
        "understeer": 0.5,             # light buzz when the front tires slide
        "understeer_start": 0.4,       # front normalized slip where the buzz begins
        "abs": 0.5,                    # ABS pulse on the body
        "abs_hz": 14.0,
        "shift": 1.0,                  # gear-change knock on the body
        "hit_min": 2.0,                # impact (m/s change against the trend) that counts as a crash
        "crash": 1.0,                  # crash (walls, cars) strength
        "crash_s": 0.8,                # crash length, seconds (longer for bigger impacts)
        "crash_hold_s": 0.15,          # crash stays at full strength this long before fading
        "crash_triggers_s": 0.4,       # both triggers vibrate hard this long on a crash (0 = off)
        "landing": 0.8,                # thump when a hanging wheel lands
        "landing_speed": 2.0,          # compression speed (m/s) of a hanging wheel that counts as a landing
    },
}

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# Per-effect strength sliders: id -> (group, settings paths it scales). The level
# multiplies the configured value; "*" walks every entry of a dict.
LEVELS = {
    "brake_pedal": ("triggers", [("brake_strength",)]),
    "abs_trigger": ("triggers", [("abs_amp",)]),
    "lock_trigger": ("triggers", [("lock_amp",)]),
    "throttle": ("triggers", [("throttle_strength",)]),
    "spin_trigger": ("triggers", [("spin_amp_min",), ("spin_amp_max",)]),
    "shift_trigger": ("triggers", [("shift_amp",)]),
    "object_trigger": ("triggers", [("object_trigger_amp",)]),
    "crash_trigger": ("triggers", [("crash_trigger_amp",)]),
    "volume": ("body", [("haptics", "volume")]),
    "traction": ("body", [("haptics", "traction")]),
    "understeer": ("body", [("haptics", "understeer")]),
    "surface": ("body", [("haptics", "surfaces", "*", "texture"), ("haptics", "surfaces", "*", "bumpiness"),
                         ("haptics", "texture_max")]),
    "detail": ("body", [("haptics", "detail")]),
    "object_hit": ("body", [("haptics", "object_hit")]),
    "crash": ("body", [("haptics", "crash")]),
    "landing": ("body", [("haptics", "landing")]),
    "abs_body": ("body", [("haptics", "abs")]),
    "shift_body": ("body", [("haptics", "shift")]),
    "engine": ("body", [("haptics", "engine")]),
}
LEVEL_MAX = 3.0


def _scale(node, path, k):
    head, rest = path[0], path[1:]
    keys = list(node) if head == "*" else [head]
    for key in keys:
        if rest:
            _scale(node[key], rest, k)
        elif isinstance(node[key], (int, float)) and not isinstance(node[key], bool):
            node[key] = node[key] * k


def effective(cfg):
    """The config the effects run on: the stored values scaled by the levels."""
    eff = json.loads(json.dumps(cfg))
    for name, (_, paths) in LEVELS.items():
        k = max(0.0, min(LEVEL_MAX, float(cfg.get("levels", {}).get(name, 1.0))))
        if k != 1.0:
            for path in paths:
                _scale(eff, path, k)
    return eff


def save_settings(cfg):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


def load_settings():
    """Defaults overlaid with settings.json; new keys are written back to the file."""
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            user = json.load(fh)
    except FileNotFoundError:
        user = {}
    except (OSError, ValueError):
        return cfg
    for key, val in user.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    if cfg != user:
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
        except OSError:
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


def _ramp(x, a, b):
    return max(0.0, min(1.0, (x - a) / (b - a))) if b > a else float(x >= a)


def traction_loss(pkt, c):
    """0..1: the bigger of driven-wheel spin and the car sliding sideways."""
    spin = max(getattr(pkt, "spin_slip", [0.0]))
    slide = getattr(pkt, "slide_deg", 0.0)
    return max(_ramp(spin, c["spin_start"], c["spin_full"]),
               _ramp(slide, c["slide_start_deg"], c["slide_full_deg"]))


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(round(v))))


def _profile(zones, scale):
    return [_clamp(z * scale, 0, 8) for z in zones]


class FH2Parser(Parser):
    """Overrides the L2/R2 logic; the lightbar stays HorizonHaptics'."""

    def __init__(self, *args, cfg=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = cfg if cfg is not None else effective(load_settings())
        self._kick_until = 0.0
        self._lock_until = 0.0
        self._crash_until = 0.0
        self._object_until = 0.0
        self._last_gear = 0
        self.debug = ""

    def compute(self, pkt):
        h = self.cfg["haptics"]
        if pkt.is_race_on and pkt.smashable_vel_diff > h["hit_min"] and not getattr(pkt, "obj_hit", False):
            self._crash_until = time.monotonic() + h["crash_triggers_s"]
        if getattr(pkt, "obj_hit", False):
            self._object_until = time.monotonic() + self.cfg["object_trigger_s"]
            if self.cfg["debug_lock_on_hit"]:
                self._lock_until = time.monotonic() + self.cfg["debug_lock_s"]
        if self.cfg["shift_kick"] and pkt.is_race_on:
            if self._last_gear > 0 and pkt.gear > 0 and pkt.gear != self._last_gear and pkt.speed > 2:
                self._kick_until = time.monotonic() + self.cfg["shift_ms"] / 1000
            self._last_gear = pkt.gear
        return super().compute(pkt)

    # -- L2 --------------------------------------------------------------
    def _tachometer_color(self, pkt):
        """RPM light: off below 'start', low->mid->high colors up to 'flash', then flashing."""
        c = self.cfg
        L = c["rpm_light"]
        if not c["lightbar"] or not pkt.is_race_on or pkt.engine_max_rpm <= 0:
            return 0, 0, 0
        ratio = pkt.current_engine_rpm / pkt.engine_max_rpm
        start, flash = L["start"], max(L["start"] + 0.01, L["flash"])
        if ratio < start:
            return 0, 0, 0
        if ratio >= flash:
            if L["flash_hz"] > 0 and int(time.monotonic() * L["flash_hz"] * 2) % 2:
                return 0, 0, 0
            rgb = L["flash_color"]
        else:
            t = (ratio - start) / (flash - start)
            lo, mid, hi = L["colors"]
            a, b, u = (lo, mid, t * 2) if t < 0.5 else (mid, hi, t * 2 - 1)
            rgb = [x + (y - x) * u for x, y in zip(a, b)]
        k = max(0.0, min(1.0, L["brightness"]))
        return tuple(_clamp(v * k, 0, 255) for v in rgb)

    def _hits(self, side):
        """Crash / object-hit / debug-lock effects shared by both triggers, or None."""
        c, now = self.cfg, time.monotonic()
        if now < self._lock_until:
            self.debug += f" | {side} LOCK(hit)"
            return ("dsx", [MULTI_FEEDBACK] + [8] * 10)
        if now < self._crash_until and c["crash_trigger_amp"] > 0:
            self.debug += f" | {side} CRASH"
            return ("dsx", [VIBRATION, 0, _clamp(c["crash_trigger_amp"], 1, 8), 30])
        if now < self._object_until and c["object_trigger_amp"] > 0:
            self.debug += f" | {side} HIT"
            return ("dsx", [VIBRATION, 0, _clamp(c["object_trigger_amp"], 1, 8), 40])
        return None

    def _l2(self, pkt):
        c = self.cfg
        hit = self._hits("L2")
        if hit is not None:
            return hit
        pedal = _profile(c["brake_profile"], c["brake_strength"] * self.brake.intensity / 0.8)
        braking = pkt.brake > 25
        lock = max(getattr(pkt, "lock_slip", [0.0]))

        if braking and getattr(pkt, "abs_active", False) and c["abs_amp"] > 0:
            amp = _clamp(c["abs_amp"] * self.brake.intensity / 0.8, 1, 8)
            wall = _clamp(c["abs_wall"], 0, 9)
            zones = [amp] * (10 - wall) + [8] * wall
            self.debug = "L2 ABS"
            return ("dsx", [MULTI_VIBRATION, _clamp(c["abs_freq"], 1, 255), *zones])

        if braking and lock >= c["lock_slip"] and c["lock_amp"] > 0:
            y = curve(lock, BRAKE_LOCK_CURVE)
            amp = _clamp(max(y, 0.2) / 0.9 * 8 * c["lock_amp"], 1, 8)
            zones = [max(c["lock_pedal"], amp if i < 7 else c["lock_pedal"]) for i in range(10)]
            self.debug = f"L2 LOCKED {lock:.1f}"
            return ("dsx", [MULTI_VIBRATION, _clamp(c["lock_freq"], 1, 255), *zones])

        self.debug = "L2 pedal"
        return ("dsx", [MULTI_FEEDBACK, *pedal]) if any(pedal) else ("dsx", [OFF])

    # -- R2 --------------------------------------------------------------
    def _r2(self, pkt):
        c = self.cfg
        hit = self._hits("R2")
        if hit is not None:
            return hit
        if time.monotonic() < self._kick_until and c["shift_amp"] > 0:
            return ("dsx", [VIBRATION, 0, _clamp(c["shift_amp"], 1, 8), 30])

        base = _profile(c["throttle_profile"], c["throttle_strength"] * self.throttle.intensity / 0.7)
        spin = max(getattr(pkt, "spin_slip", [0.0]))
        slide = getattr(pkt, "slide_deg", 0.0)
        loss = traction_loss(pkt, c)
        if pkt.accel >= c["spin_min_throttle"] * 255 and loss > 0.0 and c["spin_amp_max"] > 0:
            amp = _clamp(c["spin_amp_min"] + (c["spin_amp_max"] - c["spin_amp_min"]) * loss, 1, 8)
            freq = c["spin_freq_min"] + (c["spin_freq_max"] - c["spin_freq_min"]) * loss
            light = 1.0 - c["spin_light"] * loss
            zones = [max(amp, _clamp(b * light, 0, 8)) for b in base]
            self.debug += f" | R2 SPIN {loss:.2f} ({spin:.2f}/{slide:.0f}°)"
            return ("dsx", [MULTI_VIBRATION, _clamp(freq, 1, 255), *zones])

        self.debug += " | R2 normal"
        return ("dsx", [MULTI_FEEDBACK, *base]) if any(base) else ("dsx", [OFF])
