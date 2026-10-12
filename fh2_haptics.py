"""Forza Horizon 2 (Azimuth) -> DualSense adaptive triggers via DualSenseY.

Reads the player car's physics straight from azimuth.exe's memory, builds the
same telemetry frame HorizonHaptics computes effects from, runs HorizonHaptics'
own effect logic (with your saved HorizonHaptics settings), and sends the
result to DualSenseY over its DSX-compatible UDP port (6969), so DSY keeps
owning the controller and the Xbox emulation.

Memory layout found for Azimuth 0.9.7 + FH2 1.0.0.64 (image at 0x140000000).
"""
import json
import math
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HH_DIR = os.environ.get("HORIZONHAPTICS_DIR") or os.path.join(HERE, "..", "HorizonHaptics")
sys.path.insert(0, os.path.abspath(HH_DIR))
sys.path.insert(0, HERE)

from GameParsers.forza_parser import DataPacket
from fh2_effects import FH2Parser
from fh2_audio import Haptics
from fh2_rumble import Rumble
from fh2_snapshot import Snapshots
from Config import BrakeSettings, GearSettings, SurfaceSettings, ThrottleSettings, TachometerSettings
import preferences
from mem import Proc, find_pid

# --- FH2 memory map -------------------------------------------------------
PLAYER_ROOT = 0x14365AE10      # static -> object; object+0x1E8 -> player ForzaCar
ROOT_CAR_OFF = 0x1E8
FORZACAR_VT = 0x142C5CB80
PHYS_VT = 0x142EB5E18
CAR_PHYS = 0x4C08              # ForzaCar -> car physics state
CAR_RPM = 0x5BEC               # ForzaCar: engine rpm (float)
BLK = 0xB00                    # physics block read from phys+BLK
BLK_LEN = 0x1B00
P_GEAR = 0xBA4                 # int32
P_POS = 0xD30                  # vec3 world position
P_VEL = 0xD40                  # vec3 world velocity (m/s)
P_THROTTLE, P_BRAKE, P_STEER, P_HANDBRAKE = 0xDF8, 0xDFC, 0xE00, 0xE08
P_SPEED = 0xE28                # m/s
P_ROT = 0xE70                  # 3 rows of vec4: right, up, forward
P_ABS = 0xDBC                  # int32, non-zero while ABS is acting
P_OBJ_HIT = 0xE0C              # int32, 1 for one frame when the car hits an object (bollards, signs...)
P_OBJ_COUNT = 0x11AC           # int32, object-contact counter (steps up on every contact)
P_WHEEL_OMEGA = 0x11BC         # rad/s, 4 wheels in order FL, FR, RR, RL, stride 0x4B0
WHEEL_STRIDE = 0x4B0
DUMP_PHYS = 0x2600                # debug snapshots: physics state bytes kept per frame
DUMP_CAR_OFF, DUMP_CAR = 0x4000, 0x2000   # ... and this slice of ForzaCar
W_LONG_SLIP = 0x1E0            # from wheel omega: signed longitudinal slip (+ spin, - lock)
W_SLIP = 0x280                 # from wheel omega: normalized slip (Turn 10's haptics input)
W_SUSP = -0xC                  # from wheel omega: suspension position, m (-0.24 extended .. -0.02 compressed)
W_SURF = 0x144                 # from wheel omega: int surface id under the tire; id >> 8 is the
                               # surface class (0 asphalt, 1 dirt/gravel, 2 grass), e.g. 12, 268, 524

# --- DualSenseY / DSX UDP --------------------------------------------------
DSX_ADDR = ("127.0.0.1", 6969)
# DSY's native Sony trigger modes (DualSenseY-v2 source/udp.cpp)
SONY_OFF, SONY_FEEDBACK, SONY_WEAPON, SONY_VIBRATION = 20, 21, 22, 23
SONY_SLOPE, SONY_MULTI_FEEDBACK, SONY_MULTI_VIBRATION = 24, 25, 26
DSX_NORMAL = 0                                         # hands the trigger back to DSY


def _unpack_zones(p):
    """Inverse of HorizonHaptics' triggers._pack_zones: 10 zone strengths 0-8."""
    active = p[0] | p[1] << 8
    strength = p[2] | p[3] << 8 | p[4] << 16 | p[5] << 24
    return [((strength >> (3 * i)) & 7) + 1 if active >> i & 1 else 0 for i in range(10)]


def to_dsx(frame):
    """Translate a HorizonHaptics HID trigger frame into the matching Sony mode.

    Frames already in DSX form ("dsx", [mode, *params]) pass straight through.
    """
    mode, p = frame[0], frame[1]
    if mode == "dsx":
        return list(p)
    if mode == 0x01:                                   # rigid(0, force)
        f = p[1] if p[1] <= 8 else round(p[1] / 255 * 8)
        return [SONY_FEEDBACK, 0, f] if f > 0 else [SONY_OFF]
    if mode == 0x21:                                   # per-zone feedback
        zones = _unpack_zones(p)
        return [SONY_MULTI_FEEDBACK, *zones] if any(zones) else [SONY_OFF]
    if mode == 0x06:                                   # vibration(freq, amp)
        freq, amp = p
        if freq <= 0 or amp <= 0:
            return [SONY_OFF]
        return [SONY_VIBRATION, 0, max(1, min(8, round(amp / 255 * 8))), freq]
    if mode == 0x26:                                   # vibration with resistance wall
        return [SONY_MULTI_VIBRATION, max(1, p[6]), *_unpack_zones(p)]
    return [SONY_OFF]                                  # 0x05 off / unknown


class DSY:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last = {}
        self.refresh_at = 0.0

    def _send(self, instr):
        try:
            self.sock.sendto(json.dumps({"instructions": instr}).encode(), DSX_ADDR)
        except OSError:
            pass

    def update(self, l2, r2, rgb):
        now = time.monotonic()
        state = {"l": to_dsx(l2), "r": to_dsx(r2), "rgb": list(rgb)}
        refresh = now >= self.refresh_at
        instr = [{"type": 1, "parameters": [0, side, *state[k]]}
                 for k, side in (("l", 1), ("r", 2)) if refresh or state[k] != self.last.get(k)]
        if refresh or state["rgb"] != self.last.get("rgb"):
            instr.append({"type": 2, "parameters": [0, *rgb]})
        if instr:
            self._send(instr)
        self.last = state
        if refresh:
            self.refresh_at = now + 1.0

    def release(self):
        self._send([{"type": 1, "parameters": [0, 1, DSX_NORMAL]},
                    {"type": 1, "parameters": [0, 2, DSX_NORMAL]}])
        self.last = {}


class FH2:
    def __init__(self):
        self.p = None
        self.car = None
        self.keep_raw = False
        self.raw_dump = None
        self._reset_car()

    def _reset_car(self):
        self.max_rpm = 6000.0
        self.prev_sig = None
        self.prev_vel = None
        self.prev_t = 0.0
        self.last_change = 0.0
        self.acc = [0.0, 0.0, 0.0]
        self.prev_susp = None
        self.susp_ext = None
        self.landing = (0.0, 0.0)
        self.dv_avg = [0.0, 0.0, 0.0]
        self.road = (0.0, 0.0)
        self.obj_count = None

    def _resolve(self):
        p = self.p
        root = p.q(PLAYER_ROOT)
        car = p.q(root + ROOT_CAR_OFF) if root else None
        if not car or p.q(car) != FORZACAR_VT:
            return None, None
        phys = p.q(car + CAR_PHYS)
        if not phys or p.q(phys) != PHYS_VT:
            return None, None
        return car, phys

    def read(self):
        """Return a DataPacket, or None when azimuth.exe isn't running."""
        if self.p is None:
            pid = find_pid("azimuth.exe")
            if not pid:
                return None
            self.p = Proc(pid)
        car, phys = self._resolve()
        if car is None:
            if find_pid("azimuth.exe") != self.p.pid:
                self.p = None
                return None
            return DataPacket()
        if car != self.car:
            self.car = car
            self._reset_car()
        raw = self.p.read(phys + BLK, BLK_LEN)
        rb = self.p.read(car + CAR_RPM, 4)
        if self.keep_raw:                                # debug snapshots: raw memory per frame
            self.raw_dump = (self.p.read(phys, DUMP_PHYS) or b"", self.p.read(car + DUMP_CAR_OFF, DUMP_CAR) or b"")
        if not raw or len(raw) < BLK_LEN or not rb:
            return DataPacket()

        now = time.monotonic()
        f = lambda o: struct.unpack_from("<f", raw, o - BLK)[0]
        v3 = lambda o: (f(o), f(o + 4), f(o + 8))
        dot = lambda a, b: a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

        sig = raw[P_POS - BLK:P_POS - BLK + 28]          # position + velocity
        fresh = sig != self.prev_sig
        self.prev_sig = sig
        if fresh:
            self.last_change = now
        running = now - self.last_change < 0.6           # frozen => paused / menu

        vel = v3(P_VEL)
        right, up, fwd = v3(P_ROT), v3(P_ROT + 0x10), v3(P_ROT + 0x20)
        speed = f(P_SPEED)
        rpm = struct.unpack("<f", rb)[0]
        thr, brk, steer, hb = f(P_THROTTLE), f(P_BRAKE), f(P_STEER), f(P_HANDBRAKE)
        gear = struct.unpack_from("<i", raw, P_GEAR - BLK)[0]

        # local acceleration + impact size from the velocity change of one physics step
        smash = 0.0
        dt = max(1 / 120, min(0.1, now - self.prev_t))
        if fresh and self.prev_vel is not None:
            dv = [a - b for a, b in zip(vel, self.prev_vel)]
            dvm = math.sqrt(dot(dv, dv))
            if dvm < 60:                                   # ignore teleports / resets
                # impact = how far this step's velocity change departs from the
                # recent trend, so normal braking/cornering doesn't count as a hit
                jerk = [a - b for a, b in zip(dv, self.dv_avg)]
                smash = math.sqrt(dot(jerk, jerk))
                self.dv_avg = [0.7 * a + 0.3 * b for a, b in zip(self.dv_avg, dv)]
                loc = (dot(dv, right) / dt, dot(dv, up) / dt, dot(dv, fwd) / dt)
                self.acc = [0.6 * a + 0.4 * b for a, b in zip(self.acc, loc)]
        if fresh:
            self.prev_vel, self.prev_t = vel, now

        if self.max_rpm < rpm < 20000:
            self.max_rpm = rpm

        # the game's own per-wheel normalized slip; the sign of the longitudinal
        # slip tells a locking wheel (braking) from a spinning one (throttle)
        slips, lock, spin = [], [], []
        for w in range(4):
            wb = P_WHEEL_OMEGA + w * WHEEL_STRIDE
            s, lon = f(wb + W_SLIP), f(wb + W_LONG_SLIP)
            s = s if 0.0 <= s < 50.0 else 0.0
            slips.append(s)
            lock.append(s if lon < 0 else 0.0)
            spin.append(s if lon > 0 else 0.0)
        fl, fr, rr, rl = slips

        # landings: a wheel that was hanging near full extension compresses fast.
        # Reported per side (left = FL+RL, right = FR+RR) as compression speed, m/s
        susp = [f(P_WHEEL_OMEGA + w * WHEEL_STRIDE + W_SUSP) for w in range(4)]
        if fresh:
            self.landing = (0.0, 0.0)
            if self.prev_susp is not None:
                if self.susp_ext is None:
                    self.susp_ext = list(susp)
                self.susp_ext = [min(e, x) for e, x in zip(self.susp_ext, susp)]
                hit = [(a - b) / dt if b < e + 0.03 else 0.0
                       for a, b, e in zip(susp, self.prev_susp, self.susp_ext)]
                self.landing = (max(hit[0], hit[3]), max(hit[1], hit[2]))
                # small road detail: how fast the suspension is moving, per side
                rate = [abs(a - b) / dt for a, b in zip(susp, self.prev_susp)]
                self.road = (max(rate[0], rate[3]), max(rate[1], rate[2]))
            self.prev_susp = susp

        surf = [struct.unpack_from("<i", raw, P_WHEEL_OMEGA + w * WHEEL_STRIDE + W_SURF - BLK)[0] for w in range(4)]

        # object hits (bollards, fences, signs): the game's one-frame flag or a new contact
        count = struct.unpack_from("<i", raw, P_OBJ_COUNT - BLK)[0]
        obj_hit = struct.unpack_from("<i", raw, P_OBJ_HIT - BLK)[0] == 1 or (
            self.obj_count is not None and count > self.obj_count)
        self.obj_count = count
        if obj_hit:
            smash = max(smash, 4.0)                        # also gives the triggers a jolt

        pkt = DataPacket(
            is_race_on=running,
            acceleration_x=self.acc[0], acceleration_z=self.acc[2],
            tire_combined_slip_fl=fl, tire_combined_slip_fr=fr,
            tire_combined_slip_rl=rl, tire_combined_slip_rr=rr,
            current_engine_rpm=rpm, engine_idle_rpm=800.0, engine_max_rpm=self.max_rpm,
            speed=speed, speed_kmh=speed * 3.6,
            accel=max(0, min(255, int(thr * 255))), brake=max(0, min(255, int(brk * 255))),
            hand_brake=255 if hb > 0.5 else 0, gear=max(0, min(255, gear)),
            steer=max(-127, min(127, int(steer * 127))),
            smashable_vel_diff=smash,
            four_wheel_slip=(fl + fr + rl + rr) / 4, front_slip=(fl + fr) / 2, rear_slip=(rl + rr) / 2,
        )
        pkt.abs_active = struct.unpack_from("<i", raw, P_ABS - BLK)[0] != 0
        pkt.lock_slip, pkt.spin_slip = lock, spin
        pkt.landing = self.landing
        pkt.surface = surf
        pkt.surf_class = [s >> 8 if s > 0 else 0 for s in surf]
        pkt.road_l, pkt.road_r = self.road
        pkt.obj_hit = obj_hit
        # body slip angle (deg): how much the car is sliding sideways
        v_lat, v_long = dot(vel, right), dot(vel, fwd)
        pkt.slide_deg = math.degrees(math.atan2(abs(v_lat), abs(v_long))) if speed > 3 else 0.0
        return pkt


def main():
    t, b, g, s, tach = ThrottleSettings(), BrakeSettings(), GearSettings(), SurfaceSettings(), TachometerSettings()
    preferences.load(t, b, g, s, tach)
    parser = FH2Parser(t, b, g, s, tach)
    game, dsy = FH2(), DSY()
    hcfg = parser.cfg["haptics"]
    haptics = rumble = None
    if hcfg["enabled"]:
        haptics = Haptics(volume=hcfg["volume"])
        if haptics.start():
            rumble = Rumble(haptics, hcfg, parser.cfg)
            print("Body haptics: on (DualSense audio device", haptics.device, ")")
        else:
            print("Body haptics: DualSense audio device not found (needs USB or DS5 Bridge), triggers only")
    snaps = Snapshots()
    game.keep_raw = True
    print("FH2 Haptics: waiting for azimuth.exe ... (Ctrl+C to quit)")
    print("Debug: press the DualSense mute button or F8 to save a snapshot")
    last_print = 0.0
    idle = False
    try:
        while True:
            pkt = game.read()
            if pkt is None:
                if not idle:
                    dsy.release()
                    if haptics:
                        haptics.silence()
                    idle = True
                time.sleep(2)
                continue
            idle = False
            parser.debug = ""
            l2, r2, r, gg, bb = parser.compute(pkt)[:5]
            dsy.update(l2, r2, (r, gg, bb))
            if rumble:
                rumble.update(pkt)
            saved = snaps.record({
                "on": pkt.is_race_on, "kmh": round(pkt.speed_kmh, 1), "rpm": round(pkt.current_engine_rpm),
                "gear": pkt.gear, "thr": pkt.accel, "brk": pkt.brake, "hb": pkt.hand_brake,
                "slip": [round(x, 3) for x in (pkt.tire_combined_slip_fl, pkt.tire_combined_slip_fr,
                                               pkt.tire_combined_slip_rl, pkt.tire_combined_slip_rr)],
                "slide_deg": round(getattr(pkt, "slide_deg", 0.0), 1),
                "abs": getattr(pkt, "abs_active", False),
                "impact": round(pkt.smashable_vel_diff, 2),
                "landing": [round(x, 2) for x in getattr(pkt, "landing", (0.0, 0.0))],
                "surface": getattr(pkt, "surface", None), "obj_hit": getattr(pkt, "obj_hit", False),
                "road": [round(getattr(pkt, "road_l", 0.0), 3), round(getattr(pkt, "road_r", 0.0), 3)],
                "L2": dsy.last.get("l"), "R2": dsy.last.get("r"), "effect": parser.debug.strip(" |"),
                "body": haptics.state() if rumble else None,
            }, game.raw_dump)
            if saved:
                print(f"\nsnapshot saved: {saved}.png / .json")
            now = time.monotonic()
            if now - last_print > 0.5:
                last_print = now
                st = "ON " if pkt.is_race_on else "off"
                print(f"\r[{st}] {pkt.speed_kmh:6.1f} km/h  {pkt.current_engine_rpm:5.0f}/{game.max_rpm:5.0f} rpm  "
                      f"gear {pkt.gear}  thr {pkt.accel:3d} brk {pkt.brake:3d}  "
                      f"slip F {pkt.front_slip:4.2f} R {pkt.rear_slip:4.2f}  "
                      f"{'ABS ' if getattr(pkt, 'abs_active', False) else ''}{parser.debug:<28}"
                      + (" | body " + " ".join(f"{k} {v:.2f}" for k, v in rumble.levels.items()) if rumble else ""),
                      end="", flush=True)
            time.sleep(1 / 120)
    except KeyboardInterrupt:
        pass
    finally:
        dsy.release()
        if haptics:
            haptics.stop()
        print("\nbye")


if __name__ == "__main__":
    main()
