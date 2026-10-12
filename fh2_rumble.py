"""Turns car data into body-haptics layers.

The rumble part follows Turn 10's own controller rumble design from the game's
media/ControllerRumble.xml (<Controller> profile): LeftMotor is rendered as the
heavy layer, RightMotor as the light one. Engine growl, road texture, ABS and
landing thumps are extra layers on top.
"""
import time

from fh2_effects import DEFAULTS, curve, traction_loss

# (x, y) points from ControllerRumble.xml, <Controller> profile
TRACTION_FRONT = {"heavy": ((1.4, 0.0), (2.2, 0.20), (3.0, 0.40)),
                  "light": ((0.7, 0.0), (1.4, 0.10), (3.0, 0.40))}
TRACTION_REAR = {"heavy": ((1.4, 0.0), (2.25, 0.18), (3.0, 0.35))}
BUMPINESS = {"heavy": ((0.0, 0.0), (0.01, 0.10), (0.12, 0.40)),
             "light": ((0.0, 0.0), (0.055, 0.0), (0.12, 0.20))}
WORLD_HIT = {"heavy": ((20.0, 0.0), (1.0, 0.8), (375.0, 1.6)),      # x0 > x1 in the file; see _hit()
             "light": ((0.0, 0.0), (1.0, 0.8), (375.0, 1.6))}
WORLD_HIT_TIME = ((0.0, 0.5), (25.0, 0.4), (500.0, 0.78))
SHIFT_LIGHT = 0.4



def _hit(x, pts):
    (x0, _), (x1, y1), (x2, y2) = pts
    if x <= 0:
        return 0.0
    if x <= x1:
        return y1 * x / x1
    return curve(x, ((x1 * 0.999, 0.0), (x1, y1), (x2, y2)))


class Rumble:
    def __init__(self, haptics, cfg, trigger_cfg):
        self.h = haptics
        self.cfg = dict(DEFAULTS["haptics"])
        self.cfg.update(cfg or {})
        self.tcfg = trigger_cfg
        self._last_gear = 0
        self._prev_susp = None
        self.levels = {}

    def update(self, pkt):
        c, h = self.cfg, self.h
        if not pkt.is_race_on:
            h.silence()
            self._prev_susp = None
            self.levels = {}
            return
        rm = c["rumble"]
        now = time.monotonic()

        # tire traction: Turn 10's curves only start at big slips, so the same
        # traction-loss index the R2 uses (wheelspin or sliding) also drives the
        # heavy layer, and front slip (understeer) drives the light one
        fl, fr, rl, rr = (pkt.tire_combined_slip_fl, pkt.tire_combined_slip_fr,
                          pkt.tire_combined_slip_rl, pkt.tire_combined_slip_rr)
        loss = traction_loss(pkt, self.tcfg) * c["traction"]
        heavy_l = max(curve(fl, TRACTION_FRONT["heavy"]) + curve(rl, TRACTION_REAR["heavy"]), loss)
        heavy_r = max(curve(fr, TRACTION_FRONT["heavy"]) + curve(rr, TRACTION_REAR["heavy"]), loss)

        def under(x):
            ramp = min(1.0, max(0.0, (x - c["understeer_start"]) / 0.6))
            return max(curve(x, TRACTION_FRONT["light"]), ramp * c["understeer"])

        light_l, light_r = under(fl), under(fr)

        # surface: off asphalt (grass, dirt...) a rough texture plus Turn 10's
        # bumpiness rumble, growing with speed; on asphalt only the small details
        # from fast suspension movement
        pace = min(1.0, pkt.speed / c["surface_full_speed"])
        cls = getattr(pkt, "surf_class", [0, 0, 0, 0])            # FL, FR, RR, RL

        def surface(wheels):
            # strongest surface under that side's wheels -> (texture, Turn 10 bumpiness)
            best = (0.0, 0.0)
            for w in wheels:
                k = cls[w]
                if k:
                    s = c["surfaces"].get(str(k), c["surfaces"]["other"])
                    best = max(best, (s["texture"], s["bumpiness"]))
            return best

        (tx_l, bp_l), (tx_r, bp_r) = surface((0, 3)), surface((1, 2))
        bump_l, bump_r = bp_l * pace, bp_r * pace
        heavy_l += curve(bump_l, BUMPINESS["heavy"])
        heavy_r += curve(bump_r, BUMPINESS["heavy"])
        light_l += curve(bump_l, BUMPINESS["light"])
        light_r += curve(bump_r, BUMPINESS["light"])
        detail = lambda rate: min(1.0, max(0.0, rate - c["detail_floor"]) * c["detail_gain"])
        # on asphalt the detail layer carries the small bumps; off it the surface
        # texture already does, so the detail is only allowed to add a little
        det_l = detail(getattr(pkt, "road_l", 0.0)) * c["detail"] * (1.0 if not tx_l else c["detail_offroad"])
        det_r = detail(getattr(pkt, "road_r", 0.0)) * c["detail"] * (1.0 if not tx_r else c["detail_offroad"])
        tex_l = min(1.0, tx_l * pace + det_l)
        tex_r = min(1.0, tx_r * pace + det_r)
        h.set("texture", tex_l, tex_r)

        # ABS pulse on the body
        if getattr(pkt, "abs_active", False) and pkt.brake > 25:
            on = (now * c["abs_hz"]) % 1.0 < 0.5
            heavy_l += c["abs"] * on
            heavy_r += c["abs"] * on

        h.set("heavy", heavy_l * rm, heavy_r * rm)
        h.set("light", light_l * rm, light_r * rm)

        # collisions (Turn 10 CarToWorld curves), directional
        if pkt.smashable_vel_diff > c["hit_min"]:
            x = pkt.smashable_vel_diff * c["hit_scale"]
            amp = min(1.0, _hit(x, WORLD_HIT["heavy"])) * rm
            dur = curve(x, WORLD_HIT_TIME)
            side = pkt.acceleration_x
            left = amp * (1.0 if side <= 5 else 0.4)
            right = amp * (1.0 if side >= -5 else 0.4)
            h.thump(left, right, dur)

        # object hits (bollards, fences, signs): the game's own contact flag
        if getattr(pkt, "obj_hit", False):
            amp = min(1.0, 0.45 + pkt.speed / 60.0) * c["object_hit"]
            h.thump(amp, amp, 0.2)

        # landings: a hanging wheel compressing fast
        sl, sr = getattr(pkt, "landing", (0.0, 0.0))
        if max(sl, sr) > c["landing_speed"]:
            k = c["landing"]
            h.thump(min(1.0, sl / (2 * c["landing_speed"])) * k,
                    min(1.0, sr / (2 * c["landing_speed"])) * k, 0.15)

        # gear change (Turn 10 OnShift: light motor 0.4)
        if self._last_gear > 0 and pkt.gear > 0 and pkt.gear != self._last_gear and pkt.speed > 2:
            h.thump(SHIFT_LIGHT * rm, SHIFT_LIGHT * rm, 0.08)
        self._last_gear = pkt.gear

        # engine growl
        span = max(1.0, pkt.engine_max_rpm - pkt.engine_idle_rpm)
        ratio = max(0.0, min(1.0, (pkt.current_engine_rpm - pkt.engine_idle_rpm) / span))
        h.set_engine_hz(c["engine_hz_idle"] + (c["engine_hz_max"] - c["engine_hz_idle"]) * ratio)
        eng = c["engine"] * (0.25 + 0.5 * pkt.accel / 255 + 0.25 * ratio)
        h.set("engine", eng, eng)

        self.levels = {"heavy": max(heavy_l, heavy_r) * rm, "light": max(light_l, light_r) * rm,
                       "tex": max(tex_l, tex_r), "loss": loss, "eng": eng}
