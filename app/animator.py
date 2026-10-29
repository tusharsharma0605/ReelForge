"""Tiny 2D cartoon engine: characters, robots, logo mascots, icons, text, speech bubbles, punches, explosions...

Spec (all coordinates are fractions of the frame, 0..1):
{
  "background": {"style": "arena|office|city|stage|space|sky|gradient|photo", "colors": ["#hex", "#hex"]},
  "actors": [{"id": "hero", "kind": "character|robot|logo|text|icon|image", "label": "HireFast", "color": "#0A66C2",
              "x": 0.3, "y": 0.62, "size": 1.0, "expression": "happy", "facing": 1, "icon": "document", "limbs": true}],
  "actions": [{"t": 0.0, "actor": "hero", "do": "enter_left", "dur": 0.6, "x": 0.3, "y": 0.62, "text": "...", "target": "villain"}],
  "fx": [{"t": 1.2, "kind": "impact|explosion|confetti|stars|speedlines|flash|text_pop", "x": 0.6, "y": 0.5, "text": "POW!"}],
  "camera": {"zoom": "in|out|none"}
}
"""
import math
import random

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .renderer import _font, _hex, _wrap

KINDS = ["character", "robot", "logo", "text", "icon", "image"]
EXPRESSIONS = ["normal", "happy", "angry", "sad", "shocked", "dead", "smug", "crying", "evil", "scared"]
ICONS = ["document", "briefcase", "heart", "star", "money", "trophy", "check", "cross", "fire", "skull", "bolt", "phone", "laptop"]
BACKGROUNDS = ["arena", "office", "city", "stage", "space", "sky", "gradient", "photo"]
ENTER = {"enter_left", "enter_right", "enter_top", "enter_bottom", "pop_in", "drop_in", "fade_in"}
EXIT = {"exit_left", "exit_right", "run_away", "fade_out", "explode", "vanish"}
ACTIONS = sorted(ENTER | EXIT | {"move_to", "walk_to", "jump", "shake", "spin", "grow", "shrink", "wobble", "punch", "kick",
                                 "hit", "fall", "die", "faint", "say", "think", "shout", "expression", "celebrate", "laugh",
                                 "cry", "flash", "face", "point", "nod", "dance", "bow"})
FX = ["impact", "explosion", "confetti", "stars", "speedlines", "flash", "text_pop", "hearts", "smoke"]
SFX_FOR = {"enter_left": "whoosh", "enter_right": "whoosh", "enter_top": "whoosh", "enter_bottom": "whoosh",
           "exit_left": "whoosh", "exit_right": "whoosh", "run_away": "whoosh", "pop_in": "pop", "drop_in": "thud",
           "punch": "punch", "kick": "punch", "fall": "thud", "die": "thud", "faint": "thud", "explode": "explosion",
           "spin": "swoosh_up", "celebrate": "ding", "say": "pop", "shout": "pop", "think": "pop", "jump": "swoosh_up"}
SKIN = ["#F2C9A0", "#E0AC7E", "#C68642", "#8D5524", "#FFDBB4"]


# ---------------------------------------------------------------- spec normalization
def _f(v, d, lo=-2.0, hi=3.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return d


def normalize(spec: dict, duration: float = 0) -> dict:
    spec = dict(spec or {})
    bg = spec.get("background") or {}
    if isinstance(bg, str):
        bg = {"style": bg}
    bg = {"style": bg.get("style") if bg.get("style") in BACKGROUNDS else "arena", "colors": bg.get("colors") or [],
          "photo_path": bg.get("photo_path"), "query": bg.get("query")}
    actors, ids = [], set()
    for i, a in enumerate(spec.get("actors") or []):
        aid = str(a.get("id") or f"a{i}")
        if aid in ids:
            aid += str(i)
        ids.add(aid)
        actors.append({"id": aid, "kind": a.get("kind") if a.get("kind") in KINDS else "character",
                       "label": str(a.get("label") or a.get("name") or "")[:40], "color": a.get("color") or random.Random(aid).choice(
                           ["#0A66C2", "#E63946", "#2A9D8F", "#F4A261", "#7C5CFF", "#FF4D8D", "#264653"]),
                       "x": _f(a.get("x"), 0.3 + 0.4 * (i % 2), -1, 2), "y": _f(a.get("y"), 0.62, -1, 2),
                       "size": _f(a.get("size"), 1.0, 0.2, 3), "expression": a.get("expression") if a.get("expression") in EXPRESSIONS else "normal",
                       "facing": -1 if str(a.get("facing", 1)) in ("-1", "left") else 1, "icon": a.get("icon") if a.get("icon") in ICONS else "star",
                       "limbs": bool(a.get("limbs", a.get("kind") in ("logo", "image"))), "face": bool(a.get("face", True)),
                       "skin": a.get("skin") or SKIN[i % len(SKIN)], "image_path": a.get("image_path"), "hidden": bool(a.get("hidden", False)),
                       "text_color": a.get("text_color") or "#FFFFFF"})
    acts = []
    for a in spec.get("actions") or []:
        do = str(a.get("do") or a.get("action") or "").lower()
        if do not in ACTIONS or (a.get("actor") not in ids and do not in ()):
            continue
        dflt = {"say": 1.8, "think": 1.8, "shout": 1.4, "explode": 1.0, "celebrate": 1.5, "laugh": 1.2, "cry": 1.5,
                "fall": 0.6, "die": 0.7, "punch": 0.5, "kick": 0.5, "dance": 2.0}.get(do, 0.6)
        if do in ("say", "think", "shout"):
            dflt = max(1.2, len(str(a.get("text", "")).split()) * 0.33 + 0.6)
        acts.append({"t": _f(a.get("t", a.get("time")), 0, 0, 120), "actor": a.get("actor"), "do": do,
                     "dur": _f(a.get("dur", a.get("duration")), dflt, 0.05, 30), "x": a.get("x"), "y": a.get("y"),
                     "text": str(a.get("text") or "")[:120], "value": a.get("value") or a.get("expression"),
                     "to": _f(a.get("to"), 1.4, 0.1, 4), "target": a.get("target")})
    acts.sort(key=lambda a: a["t"])
    fx = [{"t": _f(f.get("t"), 0, 0, 120), "kind": f.get("kind") if f.get("kind") in FX else "impact", "x": _f(f.get("x"), 0.5, -0.5, 1.5),
           "y": _f(f.get("y"), 0.5, -0.5, 1.5), "text": str(f.get("text") or "")[:20], "dur": _f(f.get("dur"), 0, 0, 10)}
          for f in spec.get("fx") or []]
    by = {a["id"]: a for a in actors}
    for a in acts:  # automatic impact effects for punches with a target
        if a["do"] in ("punch", "kick") and a.get("target") in by:
            tgt = by[a["target"]]
            fx.append({"t": a["t"] + a["dur"] * 0.45, "kind": "impact", "x": None, "y": None, "target": tgt["id"],
                       "text": random.Random(a["t"]).choice(["POW!", "BAM!", "WHAM!", "K.O."]), "dur": 0})
    cam = spec.get("camera") or {}
    end = max([a["t"] + a["dur"] for a in acts] + [f["t"] + 1 for f in fx] + [duration, 1.5])
    return {"background": bg, "actors": actors, "actions": acts, "fx": fx,
            "camera": {"zoom": cam.get("zoom") if cam.get("zoom") in ("in", "out", "none") else "in"}, "duration": end}


def sfx_events(spec):
    ev = []
    for a in spec["actions"]:
        k = SFX_FOR.get(a["do"])
        if k:
            at = a["t"] + (a["dur"] * 0.45 if a["do"] in ("punch", "kick") else a["dur"] * 0.85 if a["do"] in ("drop_in", "fall", "die", "faint") else 0)
            ev.append((at, k, 0.35 if k == "pop" else 0.8))
    for f in spec["fx"]:
        k = {"explosion": "explosion", "confetti": "pop", "flash": "boom", "text_pop": "pop", "speedlines": "whoosh"}.get(f["kind"])
        if k:
            ev.append((f["t"], k, 0.7))
    return ev


# ---------------------------------------------------------------- easing / state
def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _out(p):
    return 1 - (1 - p) ** 3


def _inout(p):
    return 3 * p * p - 2 * p * p * p


def _back(p):
    c = 1.70158
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def _bounce(p):
    if p < 1 / 2.75:
        return 7.5625 * p * p
    if p < 2 / 2.75:
        p -= 1.5 / 2.75
        return 7.5625 * p * p + 0.75
    if p < 2.5 / 2.75:
        p -= 2.25 / 2.75
        return 7.5625 * p * p + 0.9375
    p -= 2.625 / 2.75
    return 7.5625 * p * p + 0.984375


def actor_state(actor, acts, t):
    s = {"x": actor["x"], "y": actor["y"], "scale": 1.0, "rot": 0.0, "alpha": 1.0, "visible": not actor["hidden"],
         "expr": actor["expression"], "arm": 0.0, "arms_up": False, "walk": None, "bubble": None, "flash": 0.0,
         "facing": actor["facing"], "dx": 0.0, "dy": 0.0, "exploded": False, "tears": False, "leg_kick": 0.0}
    mine = [a for a in acts if a["actor"] == actor["id"]]
    if mine and mine[0]["do"] in ENTER and not actor["hidden"]:
        s["visible"] = False
    for a in mine:
        if t < a["t"]:
            break
        p = _clamp((t - a["t"]) / a["dur"])
        do = a["do"]
        tx = _f(a["x"], s["x"], -1, 2) if a["x"] is not None else s["x"]
        ty = _f(a["y"], s["y"], -1, 2) if a["y"] is not None else s["y"]
        if do in ENTER:
            s["visible"] = True
            if do == "enter_left":
                s["x"] = -0.35 + (tx + 0.35) * _out(p)
                s["walk"] = t * 9 if p < 1 else None
            elif do == "enter_right":
                s["x"] = 1.35 + (tx - 1.35) * _out(p)
                s["walk"] = t * 9 if p < 1 else None
            elif do == "enter_top":
                s["y"] = -0.4 + (ty + 0.4) * _out(p)
            elif do == "enter_bottom":
                s["y"] = 1.4 + (ty - 1.4) * _out(p)
            elif do == "drop_in":
                s["y"] = -0.4 + (ty + 0.4) * _bounce(p)
            elif do == "pop_in":
                s["scale"] = max(0.01, _back(p))
            elif do == "fade_in":
                s["alpha"] = p
            if do in ("enter_left", "enter_right"):
                s["y"] = ty
            elif do in ("enter_top", "enter_bottom", "drop_in"):
                s["x"] = tx
            else:
                s["x"], s["y"] = tx, ty
        elif do in ("move_to", "walk_to"):
            e = _inout(p)
            s["x"], s["y"] = s["x"] + (tx - s["x"]) * e, s["y"] + (ty - s["y"]) * e
            if p < 1:
                s["walk"] = t * 10
                if tx != actor["x"]:
                    s["facing"] = 1 if tx > s["x"] else -1
        elif do in ("exit_left", "exit_right", "run_away"):
            dest = -0.4 if do == "exit_left" or (do == "run_away" and s["facing"] < 0) else 1.4
            s["x"] = s["x"] + (dest - s["x"]) * (p ** 2)
            s["walk"] = t * 14
            if do == "run_away":
                s["expr"] = "scared"
            if p >= 1:
                s["visible"] = False
        elif do == "fade_out":
            s["alpha"] *= 1 - p
            if p >= 1:
                s["visible"] = False
        elif do in ("explode", "vanish"):
            if p > 0.08:
                s["visible"] = False
                s["exploded"] = do == "explode"
            else:
                s["scale"] *= 1 + p * 3
                s["flash"] = 1
        elif do == "jump":
            s["dy"] -= 0.09 * math.sin(math.pi * p)
        elif do == "shake":
            s["dx"] += math.sin(t * 60) * 0.012 * (1 - p)
        elif do == "spin":
            s["rot"] += 360 * _inout(p)
        elif do in ("grow", "shrink"):
            to = a["to"] if do == "grow" else min(a["to"], 0.6)
            s["scale"] *= 1 + (to - 1) * _out(p)
        elif do == "wobble":
            s["rot"] += math.sin(p * math.pi * 6) * 12 * (1 - p)
        elif do in ("punch", "kick", "point"):
            if do == "point":
                s["arm"] = _out(min(1, p * 3)) * 0.8
            else:
                if p < 0.3:
                    s["arm"] = -0.4 * (p / 0.3)
                elif p < 0.5:
                    s["arm"] = -0.4 + 1.4 * ((p - 0.3) / 0.2)
                elif p < 0.8:
                    s["arm"] = 1.0
                else:
                    s["arm"] = 1 - (p - 0.8) / 0.2
                s["dx"] += s["facing"] * 0.04 * max(0, s["arm"])
                if do == "kick":
                    s["leg_kick"], s["arm"] = max(0, s["arm"]), 0
                if p < 1 and s["expr"] in ("normal", "happy"):
                    s["expr"] = "angry"
        elif do == "hit":
            k = math.sin(math.pi * min(1, p * 1.2))
            s["dx"] -= s["facing"] * 0.07 * k
            s["rot"] -= s["facing"] * 18 * k
            if p < 1:
                s["expr"] = "shocked"
        elif do in ("fall", "die", "faint"):
            e = _bounce(p) if do != "faint" else _inout(p)
            s["rot"] += -s["facing"] * 90 * e
            s["dy"] += 0.08 * e
            if p > 0.2:
                s["expr"] = "dead"
        elif do in ("say", "think", "shout"):
            if p < 1:
                s["bubble"] = {"text": a["text"], "kind": do, "p": p}
        elif do == "expression":
            s["expr"] = a["value"] if a["value"] in EXPRESSIONS else s["expr"]
        elif do == "celebrate":
            if p < 1:
                s["arms_up"] = True
                s["dy"] -= 0.05 * abs(math.sin(p * math.pi * 3))
                s["expr"] = "happy"
        elif do == "dance":
            if p < 1:
                s["rot"] += math.sin(t * 8) * 10
                s["dy"] -= 0.03 * abs(math.sin(t * 8))
                s["arms_up"] = int(t * 4) % 2 == 0
                s["walk"] = t * 8
        elif do == "laugh":
            if p < 1:
                s["dy"] += math.sin(t * 40) * 0.006
                s["expr"] = "happy"
        elif do == "cry":
            if p < 1:
                s["expr"], s["tears"] = "crying", True
        elif do == "flash":
            s["flash"] = max(s["flash"], 1 - p)
        elif do == "face":
            s["facing"] = -1 if str(a["value"]) in ("-1", "left") else 1
        elif do == "nod":
            s["rot"] += math.sin(p * math.pi * 4) * 6 * (1 - p)
        elif do == "bow":
            s["rot"] += s["facing"] * 25 * math.sin(math.pi * p)
    return s


# ---------------------------------------------------------------- drawing actors
def _shade(c, k):
    r, g, b = _hex(c)
    return tuple(int(max(0, min(255, v * k))) for v in (r, g, b))


def _line(d, p1, p2, w, fill):
    d.line([p1, p2], fill=fill, width=int(w))
    r = w / 2
    for x, y in (p1, p2):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _face(d, cx, cy, r, expr, robot=False, eye_color=None):
    ink = (25, 25, 30)
    ex, ey, er = r * 0.38, cy - r * 0.08, r * 0.14
    if robot:
        col = (255, 70, 70) if expr in ("angry", "evil") else (90, 90, 90) if expr == "dead" else eye_color or (80, 230, 255)
        for sx in (-1, 1):
            x = cx + sx * ex
            if expr == "dead":
                _line(d, (x - er, ey - er), (x + er, ey + er), r * 0.07, ink)
                _line(d, (x - er, ey + er), (x + er, ey - er), r * 0.07, ink)
            else:
                h = er * (0.4 if expr in ("happy", "smug") else 1.3 if expr in ("shocked", "scared") else 0.9)
                d.rounded_rectangle([x - er * 1.2, ey - h, x + er * 1.2, ey + h], radius=int(er * 0.4), fill=col)
        my = cy + r * 0.42
        for k in range(5):
            x = cx - r * 0.4 + k * r * 0.2
            d.line([(x, my - r * 0.08), (x, my + r * 0.08)], fill=ink, width=max(2, int(r * 0.05)))
        if expr in ("angry", "evil"):
            for sx in (-1, 1):
                _line(d, (cx + sx * ex * 1.6, ey - er * 2.2), (cx + sx * ex * 0.4, ey - er * 1.3), r * 0.08, ink)
        return
    for sx in (-1, 1):
        x = cx + sx * ex
        if expr == "dead":
            _line(d, (x - er, ey - er), (x + er, ey + er), r * 0.07, ink)
            _line(d, (x - er, ey + er), (x + er, ey - er), r * 0.07, ink)
        elif expr == "happy":
            d.arc([x - er * 1.2, ey - er * 0.6, x + er * 1.2, ey + er * 1.6], 200, 340, fill=ink, width=max(2, int(r * 0.07)))
        elif expr in ("shocked", "scared"):
            d.ellipse([x - er * 1.5, ey - er * 1.5, x + er * 1.5, ey + er * 1.5], fill=(255, 255, 255), outline=ink, width=max(2, int(r * 0.04)))
            d.ellipse([x - er * 0.5, ey - er * 0.5, x + er * 0.5, ey + er * 0.5], fill=ink)
        elif expr == "smug":
            d.chord([x - er, ey - er, x + er, ey + er], 0, 180, fill=ink)
        else:
            d.ellipse([x - er, ey - er, x + er, ey + er], fill=ink)
            d.ellipse([x - er * 0.2, ey - er * 0.7, x + er * 0.35, ey - er * 0.15], fill=(255, 255, 255))
        if expr in ("angry", "evil"):
            _line(d, (cx + sx * ex * 1.7, ey - er * 2.4), (cx + sx * ex * 0.45, ey - er * 1.3), r * 0.08, ink)
        if expr in ("sad", "crying", "scared"):
            _line(d, (cx + sx * ex * 1.6, ey - er * 1.4), (cx + sx * ex * 0.5, ey - er * 2.2), r * 0.07, ink)
    my, mw = cy + r * 0.45, r * 0.38
    w = max(2, int(r * 0.07))
    if expr in ("happy", "evil"):
        d.chord([cx - mw, my - mw * 0.6, cx + mw, my + mw * 0.7], 0, 180, fill=ink)
        if expr == "evil":
            for k in range(4):
                x = cx - mw * 0.7 + k * mw * 0.45
                d.polygon([(x, my + 2), (x + mw * 0.2, my + 2), (x + mw * 0.1, my + mw * 0.3)], fill=(255, 255, 255))
        else:
            d.chord([cx - mw * 0.5, my + mw * 0.1, cx + mw * 0.5, my + mw * 0.7], 0, 180, fill=(230, 90, 100))
    elif expr in ("shocked", "scared"):
        d.ellipse([cx - mw * 0.35, my - mw * 0.3, cx + mw * 0.35, my + mw * 0.5], fill=ink)
    elif expr in ("sad", "crying"):
        d.arc([cx - mw * 0.8, my, cx + mw * 0.8, my + mw * 1.0], 200, 340, fill=ink, width=w)
    elif expr == "angry":
        d.rounded_rectangle([cx - mw * 0.7, my, cx + mw * 0.7, my + mw * 0.35], radius=3, fill=(255, 255, 255), outline=ink, width=w)
    elif expr == "dead":
        pts = [(cx - mw + k * mw / 3, my + (mw * 0.12 if k % 2 else -mw * 0.12)) for k in range(7)]
        d.line(pts, fill=ink, width=w)
    elif expr == "smug":
        d.arc([cx - mw * 0.2, my - mw * 0.5, cx + mw * 0.9, my + mw * 0.3], 20, 150, fill=ink, width=w)
    else:
        d.arc([cx - mw * 0.6, my - mw * 0.3, cx + mw * 0.6, my + mw * 0.4], 20, 160, fill=ink, width=w)


def _limbs(d, s, st, color, shoulder_y, hip_y, half_w, skin, facing):
    ink = (25, 25, 30)
    lw = s * 0.09
    walk = st["walk"]
    swing = math.sin(walk) * 0.16 * s if walk is not None else 0
    for k, sx in enumerate((-1, 1)):
        hip = (sx * s * 0.14, hip_y)
        foot = (sx * s * 0.2 + (swing if k else -swing), hip_y + s * 0.5)
        if st["leg_kick"] and sx == facing:
            foot = (facing * s * (0.25 + 0.6 * st["leg_kick"]), hip_y + s * 0.2)
        _line(d, hip, foot, lw * 1.1, ink)
        d.ellipse([foot[0] - s * 0.1 + facing * s * 0.03, foot[1] - s * 0.05, foot[0] + s * 0.1 + facing * s * 0.05, foot[1] + s * 0.06], fill=ink)
    for sx in (-1, 1):
        sh = (sx * half_w, shoulder_y)
        if st["arms_up"]:
            hand = (sx * s * 0.55, shoulder_y - s * 0.55)
        elif sx == facing and st["arm"] != 0:
            ext = st["arm"]
            hand = (sx * (half_w + s * 0.15 + s * 0.75 * max(0, ext) + s * 0.2 * min(0, ext)), shoulder_y + s * 0.02)
        else:
            hand = (sx * (half_w + s * 0.18) - (swing * 0.6 if sx > 0 else -swing * 0.6), shoulder_y + s * 0.42)
        _line(d, sh, hand, lw, _shade(color, 0.85))
        fist = s * (0.11 if (sx == facing and st["arm"] > 0.3) else 0.08)
        d.ellipse([hand[0] - fist, hand[1] - fist, hand[0] + fist, hand[1] + fist], fill=skin or _shade(color, 0.7), outline=ink, width=max(2, int(s * 0.02)))


def _icon(d, kind, cx, cy, r, color):
    ink = (25, 25, 30)
    c = _hex(color)
    w = max(3, int(r * 0.08))
    if kind == "document":
        d.rounded_rectangle([cx - r * 0.7, cy - r, cx + r * 0.7, cy + r], radius=int(r * 0.1), fill=(250, 250, 250), outline=ink, width=w)
        for k in range(5):
            y = cy - r * 0.6 + k * r * 0.3
            d.line([(cx - r * 0.45, y), (cx + r * (0.45 if k % 2 == 0 else 0.15), y)], fill=c, width=w)
    elif kind == "briefcase":
        d.rounded_rectangle([cx - r * 0.35, cy - r * 0.8, cx + r * 0.35, cy - r * 0.4], radius=int(r * 0.1), outline=ink, width=w)
        d.rounded_rectangle([cx - r, cy - r * 0.5, cx + r, cy + r * 0.7], radius=int(r * 0.15), fill=c, outline=ink, width=w)
    elif kind == "heart":
        d.ellipse([cx - r, cy - r * 0.8, cx, cy + r * 0.2], fill=c)
        d.ellipse([cx, cy - r * 0.8, cx + r, cy + r * 0.2], fill=c)
        d.polygon([(cx - r * 0.97, cy - r * 0.1), (cx + r * 0.97, cy - r * 0.1), (cx, cy + r)], fill=c)
    elif kind in ("star", "trophy"):
        if kind == "trophy":
            d.rectangle([cx - r * 0.15, cy + r * 0.2, cx + r * 0.15, cy + r * 0.65], fill=(230, 180, 40))
            d.rounded_rectangle([cx - r * 0.5, cy + r * 0.6, cx + r * 0.5, cy + r * 0.85], radius=4, fill=(120, 80, 30))
            d.chord([cx - r * 0.75, cy - r * 0.9, cx + r * 0.75, cy + r * 0.45], 0, 180, fill=(250, 200, 50), outline=ink, width=w)
            d.rectangle([cx - r * 0.75, cy - r * 0.9, cx + r * 0.75, cy - r * 0.25], fill=(250, 200, 50))
        else:
            pts = [(cx + r * (1 if k % 2 == 0 else 0.45) * math.cos(math.pi / 2 + k * math.pi / 5),
                    cy - r * (1 if k % 2 == 0 else 0.45) * math.sin(math.pi / 2 + k * math.pi / 5)) for k in range(10)]
            d.polygon(pts, fill=c, outline=ink)
    elif kind == "money":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 200, 50), outline=(150, 110, 20), width=w)
        d.text((cx, cy), "$", font=_font("bold", int(r * 1.3)), anchor="mm", fill=(150, 110, 20))
    elif kind in ("check", "cross"):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(43, 214, 123) if kind == "check" else (230, 57, 70))
        if kind == "check":
            d.line([(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)], fill=(255, 255, 255), width=int(r * 0.18))
        else:
            d.line([(cx - r * 0.4, cy - r * 0.4), (cx + r * 0.4, cy + r * 0.4)], fill=(255, 255, 255), width=int(r * 0.18))
            d.line([(cx - r * 0.4, cy + r * 0.4), (cx + r * 0.4, cy - r * 0.4)], fill=(255, 255, 255), width=int(r * 0.18))
    elif kind == "fire":
        d.ellipse([cx - r * 0.7, cy - r * 0.2, cx + r * 0.7, cy + r], fill=(255, 120, 30))
        d.polygon([(cx - r * 0.7, cy + r * 0.3), (cx, cy - r), (cx + r * 0.7, cy + r * 0.3)], fill=(255, 120, 30))
        d.ellipse([cx - r * 0.35, cy + r * 0.2, cx + r * 0.35, cy + r * 0.9], fill=(255, 220, 60))
    elif kind == "skull":
        d.ellipse([cx - r * 0.8, cy - r, cx + r * 0.8, cy + r * 0.5], fill=(240, 240, 235), outline=ink, width=w)
        d.rectangle([cx - r * 0.45, cy + r * 0.3, cx + r * 0.45, cy + r * 0.8], fill=(240, 240, 235), outline=ink, width=w)
        for sx in (-1, 1):
            d.ellipse([cx + sx * r * 0.35 - r * 0.22, cy - r * 0.35, cx + sx * r * 0.35 + r * 0.22, cy + r * 0.05], fill=ink)
    elif kind == "bolt":
        d.polygon([(cx + r * 0.2, cy - r), (cx - r * 0.6, cy + r * 0.1), (cx - r * 0.05, cy + r * 0.1), (cx - r * 0.25, cy + r),
                   (cx + r * 0.6, cy - r * 0.15), (cx + r * 0.05, cy - r * 0.15)], fill=(255, 215, 0), outline=ink)
    elif kind in ("phone", "laptop"):
        if kind == "phone":
            d.rounded_rectangle([cx - r * 0.5, cy - r, cx + r * 0.5, cy + r], radius=int(r * 0.15), fill=(30, 30, 35))
            d.rounded_rectangle([cx - r * 0.42, cy - r * 0.85, cx + r * 0.42, cy + r * 0.8], radius=int(r * 0.08), fill=c)
        else:
            d.rounded_rectangle([cx - r * 0.85, cy - r * 0.7, cx + r * 0.85, cy + r * 0.35], radius=int(r * 0.08), fill=(30, 30, 35))
            d.rectangle([cx - r * 0.75, cy - r * 0.6, cx + r * 0.75, cy + r * 0.25], fill=c)
            d.polygon([(cx - r, cy + r * 0.4), (cx + r, cy + r * 0.4), (cx + r * 1.1, cy + r * 0.6), (cx - r * 1.1, cy + r * 0.6)], fill=(70, 70, 80))


def draw_actor(actor, st, unit, images):
    """Returns (RGBA sprite, anchor offset) drawn at 2x then reduced for anti-aliasing."""
    s = unit * actor["size"] * 2
    C = int(s * 1.7)
    img = Image.new("RGBA", (C * 2, C * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (25, 25, 30)
    color = actor["color"]
    fc = _hex(color)
    kind = actor["kind"]
    f = st["facing"]

    def P(x, y):
        return (C + x, C + y)

    class T:
        @staticmethod
        def tr(box):
            return [box[0] + C, box[1] + C, box[2] + C, box[3] + C]

    if kind == "character":
        head_r = s * 0.32
        _limbs_on(img, s, st, color, -s * 0.3, s * 0.33, s * 0.31, _hex(actor["skin"]), f, C)
        d.rounded_rectangle(T.tr([-s * 0.32, -s * 0.42, s * 0.32, s * 0.38]), radius=int(s * 0.14), fill=fc, outline=ink, width=max(3, int(s * 0.025)))
        if actor["label"]:
            fnt = _font("bold", int(s * 0.13))
            lbl = actor["label"][:10]
            while d.textlength(lbl, font=fnt) > s * 0.56 and fnt.size > 10:
                fnt = _font("bold", int(fnt.size * 0.85))
            d.text(P(0, -s * 0.05), lbl, font=fnt, anchor="mm", fill=_hex(actor["text_color"]))
        hx, hy = 0, -s * 0.74
        d.ellipse(T.tr([hx - head_r, hy - head_r, hx + head_r, hy + head_r]), fill=_hex(actor["skin"]), outline=ink, width=max(3, int(s * 0.025)))
        d.chord(T.tr([hx - head_r * 1.02, hy - head_r * 1.08, hx + head_r * 1.02, hy + head_r * 0.2]), 180, 360, fill=_shade(color, 0.45))
        _face(d, C + hx + f * head_r * 0.08, C + hy + head_r * 0.12, head_r * 0.95, st["expr"])
    elif kind == "robot":
        _limbs_on(img, s, st, "#9AA3AD", -s * 0.3, s * 0.33, s * 0.33, (150, 158, 168), f, C)
        d.rounded_rectangle(T.tr([-s * 0.34, -s * 0.42, s * 0.34, s * 0.38]), radius=int(s * 0.06), fill=fc, outline=ink, width=max(3, int(s * 0.025)))
        if actor["label"]:
            fnt = _font("bold", int(s * 0.17))
            d.text(P(0, -s * 0.03), actor["label"][:8], font=fnt, anchor="mm", fill=_hex(actor["text_color"]))
        hy = -s * 0.75
        d.line([P(0, hy - s * 0.3), P(0, hy - s * 0.48)], fill=ink, width=max(3, int(s * 0.03)))
        d.ellipse(T.tr([-s * 0.06, hy - s * 0.56, s * 0.06, hy - s * 0.44]), fill=(255, 70, 70))
        d.rounded_rectangle(T.tr([-s * 0.36, hy - s * 0.3, s * 0.36, hy + s * 0.27]), radius=int(s * 0.08), fill=(170, 178, 188), outline=ink, width=max(3, int(s * 0.025)))
        _face(d, C, C + hy, s * 0.3, st["expr"], robot=True)
    elif kind in ("logo", "image"):
        bw = s * 0.62
        cy = -s * 0.35
        if actor["limbs"]:
            _limbs_on(img, s, st, color, cy + s * 0.05, cy + bw * 0.9, bw * 0.95, None, f, C)
        if kind == "image" and actor.get("image_path") in images:
            logo = images[actor["image_path"]]
            logo = ImageOps.contain(logo, (int(bw * 2), int(bw * 2)))
            img.alpha_composite(logo, (int(C - logo.width / 2), int(C + cy - logo.height / 2)))
            top = cy - logo.height / 2
        else:
            d.rounded_rectangle(T.tr([-bw, cy - bw, bw, cy + bw]), radius=int(bw * 0.35), fill=fc, outline=_shade(color, 0.55), width=max(4, int(s * 0.035)))
            lbl = actor["label"] or "LOGO"
            fnt = _font("bold", int(bw * (0.9 if len(lbl) <= 3 else 0.55)))
            while d.textlength(lbl, font=fnt) > bw * 1.75 and fnt.size > 12:
                fnt = _font("bold", int(fnt.size * 0.88))
            d.text(P(0, cy + bw * (0.3 if actor["face"] else 0)), lbl, font=fnt, anchor="mm", fill=_hex(actor["text_color"]))
            top = cy - bw
        if actor["face"]:
            _face(d, C, C + top + bw * 0.55, bw * 0.55, st["expr"])
    elif kind == "icon":
        _icon(d, actor["icon"], C, C - s * 0.2, s * 0.6, color)
        if actor["face"] and actor["icon"] in ("document", "briefcase", "heart", "money", "phone", "laptop"):
            _face(d, C, C - s * 0.3, s * 0.4, st["expr"])
    elif kind == "text":
        fnt = _font("bold", int(s * 0.5))
        lines = _wrap(d, actor["label"], fnt, s * 4)
        for i, l in enumerate(lines[:3]):
            d.text(P(0, -s * 0.2 + (i - (len(lines) - 1) / 2) * s * 0.6), l, font=fnt, anchor="mm", fill=fc,
                   stroke_width=max(3, int(s * 0.04)), stroke_fill=ink)
    if st["tears"]:
        for sx in (-1, 1):
            x, y = C + sx * s * 0.12, C - s * 0.65 + (st["walk"] or 0) % 1
            d.ellipse([x - s * 0.04, y, x + s * 0.04, y + s * 0.12], fill=(90, 170, 255))
    if st["flash"] > 0:
        a = img.split()[-1]
        white = Image.new("RGBA", img.size, (255, 255, 255, 0))
        white.putalpha(a.point(lambda v: int(v * st["flash"])))
        img.alpha_composite(white)
    return img.reduce(2)


def _limbs_on(img, s, st, color, shoulder_y, hip_y, half_w, skin, facing, C):
    _limbs(_Shift(ImageDraw.Draw(img), C), s, st, color, shoulder_y, hip_y, half_w, skin, facing)


class _Shift:
    """ImageDraw proxy that offsets all coordinates by (C, C)."""

    def __init__(self, d, C):
        self.d, self.C = d, C

    def _p(self, pts):
        if isinstance(pts[0], (tuple, list)):
            return [(x + self.C, y + self.C) for x, y in pts]
        return [v + self.C for v in pts]

    def line(self, pts, **kw):
        self.d.line(self._p(pts), **kw)

    def ellipse(self, box, **kw):
        self.d.ellipse(self._p(box), **kw)


# ---------------------------------------------------------------- backgrounds
def background(bg, W, H, rng):
    style = bg["style"]
    cols = [c for c in bg.get("colors") or [] if isinstance(c, str) and c.startswith("#")]
    if style == "photo" and bg.get("photo_path"):
        try:
            from .media import load_image

            img = ImageOps.fit(load_image(bg["photo_path"]), (W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(3))
            return Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
        except Exception:
            style = "gradient"
    def grad(c1, c2):
        a, b = np.array(_hex(c1), float), np.array(_hex(c2), float)
        t = np.linspace(0, 1, H)[:, None, None]
        return Image.fromarray(np.broadcast_to(a + (b - a) * t, (H, W, 3)).astype(np.uint8))

    if style == "arena":
        c1, c2 = (cols + ["#FFB703", "#FB8500"])[:2]
        img = Image.new("RGB", (W, H), _hex(c1))
        d = ImageDraw.Draw(img)
        cx, cy, R = W / 2, H * 0.45, max(W, H) * 1.5
        for k in range(24):
            if k % 2:
                a0, a1 = k * math.pi / 12, (k + 1) * math.pi / 12
                d.polygon([(cx, cy), (cx + R * math.cos(a0), cy + R * math.sin(a0)), (cx + R * math.cos(a1), cy + R * math.sin(a1))], fill=_hex(c2))
        return _vignette(img, 0.55)
    if style == "office":
        img = grad(*(cols + ["#DDE6F0", "#B8C7D9"])[:2])
        d = ImageDraw.Draw(img)
        floor = H * 0.72
        for k, x in enumerate((W * 0.12, W * 0.58)):
            d.rectangle([x, H * 0.14, x + W * 0.3, H * 0.42], fill=(160, 200, 235), outline=(90, 100, 115), width=8)
            d.line([(x + W * 0.15, H * 0.14), (x + W * 0.15, H * 0.42)], fill=(90, 100, 115), width=6)
        d.rectangle([0, floor, W, H], fill=(120, 95, 80))
        d.rectangle([0, floor - 10, W, floor], fill=(90, 70, 60))
        d.rectangle([W * 0.6, floor - H * 0.12, W * 0.98, floor - H * 0.1], fill=(150, 110, 80))
        d.rectangle([W * 0.75, floor - H * 0.2, W * 0.9, floor - H * 0.12], fill=(40, 40, 50))
        return _vignette(img, 0.3)
    if style == "city":
        img = grad(*(cols + ["#0B1026", "#3A2D6B"])[:2])
        d = ImageDraw.Draw(img)
        d.ellipse([W * 0.7, H * 0.08, W * 0.85, H * 0.08 + W * 0.15], fill=(245, 240, 210))
        x = 0
        while x < W:
            bw, bh = rng.randint(W // 10, W // 5), rng.randint(int(H * 0.15), int(H * 0.45))
            top = H * 0.78 - bh
            d.rectangle([x, top, x + bw, H], fill=(18, 20, 40))
            for wy in range(int(top + 20), int(H * 0.78), 34):
                for wx in range(x + 12, x + bw - 12, 26):
                    if rng.random() < 0.35:
                        d.rectangle([wx, wy, wx + 12, wy + 16], fill=(255, 214, 120))
            x += bw + rng.randint(4, 20)
        d.rectangle([0, H * 0.78, W, H], fill=(25, 25, 35))
        return img
    if style == "stage":
        img = Image.new("RGB", (W, H), _hex((cols + ["#120A1F"])[0]))
        spot = Image.new("L", (W, H), 0)
        ImageDraw.Draw(spot).polygon([(W * 0.42, 0), (W * 0.58, 0), (W * 0.95, H * 0.8), (W * 0.05, H * 0.8)], fill=110)
        ImageDraw.Draw(spot).ellipse([W * 0.05, H * 0.72, W * 0.95, H * 0.88], fill=150)
        spot = spot.filter(ImageFilter.GaussianBlur(W * 0.04))
        img = Image.composite(Image.new("RGB", (W, H), (255, 240, 200)), img, spot)
        ImageDraw.Draw(img).rectangle([0, H * 0.82, W, H], fill=(40, 20, 30))
        return img
    if style == "space":
        img = grad(*(cols + ["#02010A", "#1B1440"])[:2])
        d = ImageDraw.Draw(img)
        for _ in range(260):
            x, y, r = rng.random() * W, rng.random() * H, rng.random() * 3 + 0.5
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
        d.ellipse([-W * 0.3, H * 0.78, W * 1.3, H * 1.6], fill=(70, 60, 110))
        return img
    if style == "sky":
        img = grad(*(cols + ["#5EC8FF", "#CFF1FF"])[:2])
        d = ImageDraw.Draw(img)
        for _ in range(5):
            x, y = rng.random() * W, rng.random() * H * 0.5
            for k in range(4):
                r = W * 0.06 + rng.random() * W * 0.05
                d.ellipse([x + k * r * 0.8 - r, y - r * 0.6, x + k * r * 0.8 + r, y + r * 0.6], fill=(255, 255, 255))
        d.ellipse([-W * 0.4, H * 0.74, W * 1.4, H * 1.4], fill=(110, 200, 90))
        return img
    from .designer import _blobs, _gradient

    c1, c2 = (cols + ["#1A1A2E", "#4A2C6F"])[:2]
    return _blobs(_gradient(W, H, c1, c2, 0.3), "#FF4D8D", rng)


def _vignette(img, k):
    W, H = img.size
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    m = np.clip(1 - k * np.clip(r - 0.5, 0, None), 0, 1)[..., None]
    return Image.fromarray((np.asarray(img).astype(float) * m).astype(np.uint8))


# ---------------------------------------------------------------- fx + bubbles
def _burst(d, cx, cy, r, text, p):
    pts = []
    for k in range(24):
        rr = r * (1 if k % 2 == 0 else 0.62) * (1 + 0.08 * math.sin(k * 7))
        a = k * math.pi / 12
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=(255, 230, 0), outline=(220, 30, 40))
    d.polygon([(cx + (x - cx) * 0.75, cy + (y - cy) * 0.75) for x, y in pts], fill=(255, 140, 0))
    if text:
        f = _font("bold", int(r * 0.45))
        d.text((cx, cy), text, font=f, anchor="mm", fill=(255, 255, 255), stroke_width=max(3, int(r * 0.05)), stroke_fill=(150, 0, 20))


def draw_fx(frame, fx, t, W, H, actors_pos, u):
    d = ImageDraw.Draw(frame, "RGBA")
    for i, f in enumerate(fx):
        dt = t - f["t"]
        if dt < 0:
            continue
        x, y = f["x"], f["y"]
        if f.get("target") in actors_pos:
            x, y = actors_pos[f["target"]]
            y -= 0.08
        if x is None:
            continue
        cx, cy = x * W, y * H
        rng = random.Random(i * 101)
        kind = f["kind"]
        if kind == "impact" and dt < 0.6:
            p = dt / 0.6
            _burst(d, cx, cy, u * (0.45 + 0.25 * _out(min(1, p * 3))) * (1 - max(0, p - 0.7) * 2), f.get("text") or "POW!", p)
        elif kind == "explosion" and dt < 1.4:
            p = dt / 1.4
            if dt < 0.12:
                d.rectangle([0, 0, W, H], fill=(255, 255, 255, int(200 * (1 - dt / 0.12))))
            for k in range(26):
                a, sp = rng.random() * math.tau, rng.uniform(0.5, 1.6)
                dist = u * 2.2 * sp * _out(p)
                r = u * rng.uniform(0.12, 0.35) * (1 - p) + 2
                col = rng.choice([(255, 200, 40), (255, 120, 20), (230, 50, 30), (90, 90, 90)])
                px, py = cx + math.cos(a) * dist, cy + math.sin(a) * dist + u * 0.8 * p * p
                d.ellipse([px - r, py - r, px + r, py + r], fill=col + (int(255 * (1 - p)),))
            r = u * 1.2 * _out(min(1, p * 2))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 120, int(160 * (1 - p))))
        elif kind == "smoke" and dt < 2.0:
            p = dt / 2
            for k in range(10):
                r = u * (0.2 + 0.6 * p) * rng.uniform(0.6, 1.2)
                px, py = cx + rng.uniform(-1, 1) * u * 0.6, cy - u * 1.2 * p * rng.uniform(0.5, 1.2)
                d.ellipse([px - r, py - r, px + r, py + r], fill=(120, 120, 130, int(140 * (1 - p))))
        elif kind == "confetti" and dt < 3.0:
            for k in range(90):
                px = rng.random() * W + math.sin(dt * 3 + k) * 20
                py = -50 + (dt * rng.uniform(0.25, 0.55) + rng.random() * 0.2) * H
                c = rng.choice([(255, 77, 141), (124, 92, 255), (255, 212, 0), (43, 214, 123), (0, 229, 255)])
                s = rng.uniform(8, 18)
                ang = dt * rng.uniform(2, 8)
                d.polygon([(px + s * math.cos(ang + q * math.pi / 2), py + s * 0.5 * math.sin(ang + q * math.pi / 2)) for q in range(4)], fill=c)
        elif kind == "hearts" and dt < 2.0:
            p = dt / 2
            for k in range(8):
                px, py = cx + rng.uniform(-1, 1) * u * 0.8, cy - u * 1.5 * p * rng.uniform(0.6, 1.3)
                _icon(d, "heart", px, py, u * 0.12, "#FF4D8D")
        elif kind == "stars" and dt < 1.8:
            for k in range(5):
                a = dt * 5 + k * math.tau / 5
                _icon(d, "star", cx + math.cos(a) * u * 0.45, cy - u * 0.2 + math.sin(a) * u * 0.12, u * 0.08, "#FFD400")
        elif kind == "speedlines" and dt < (f["dur"] or 0.8):
            for k in range(40):
                a = rng.random() * math.tau
                r0, r1 = max(W, H) * rng.uniform(0.35, 0.5), max(W, H) * 0.8
                d.line([(W / 2 + math.cos(a) * r0, H / 2 + math.sin(a) * r0), (W / 2 + math.cos(a) * r1, H / 2 + math.sin(a) * r1)],
                       fill=(255, 255, 255, 170), width=rng.randint(3, 9))
        elif kind == "flash" and dt < 0.35:
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, int(230 * (1 - dt / 0.35))))
        elif kind == "text_pop" and dt < (f["dur"] or 1.5):
            dur = f["dur"] or 1.5
            sc = _back(min(1, dt / 0.35)) * (1 if dt < dur - 0.25 else max(0, (dur - dt) / 0.25))
            fnt = _font("bold", max(10, int(u * 0.55 * sc)))
            d.text((cx, cy), f.get("text") or "WOW!", font=fnt, anchor="mm", fill=(255, 230, 0),
                   stroke_width=max(3, int(u * 0.05 * sc)), stroke_fill=(20, 20, 20))


def draw_bubble(frame, text, kind, p, ax, ay, W, H, u):
    d = ImageDraw.Draw(frame, "RGBA")
    sc = _back(min(1, p * 6)) if p < 0.9 else max(0, (1 - p) / 0.1)
    if sc <= 0.02:
        return
    fnt = _font("bold", max(12, int(u * (0.2 if kind != "shout" else 0.24) * sc)))
    maxw = W * 0.62
    lines = _wrap(d, text, fnt, maxw)[:4]
    lh = fnt.size * 1.2
    tw = max(d.textlength(l, font=fnt) for l in lines) if lines else 0
    bw, bh = tw + fnt.size * 1.4, lh * len(lines) + fnt.size * 0.9
    bx = min(max(ax - bw / 2, W * 0.03), W * 0.97 - bw)
    by = max(H * 0.05, ay - bh - u * 0.25)
    fill = (255, 255, 255, 245) if kind != "shout" else (255, 236, 70, 250)
    ink = (20, 20, 25)
    if kind == "think":
        for k, r in enumerate((u * 0.05, u * 0.08)):
            cx, cy = ax + (bx + bw / 2 - ax) * (0.3 + 0.3 * k), ay - u * 0.15 - k * u * 0.12
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=ink, width=4)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh / 2), fill=fill, outline=ink, width=5)
    else:
        tail_x = min(max(ax, bx + bw * 0.2), bx + bw * 0.8)
        d.polygon([(tail_x - u * 0.08, by + bh - 4), (tail_x + u * 0.08, by + bh - 4), (ax, ay - u * 0.12)], fill=fill, outline=ink)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(min(bh / 2, u * 0.12)), fill=fill, outline=ink, width=5)
        d.polygon([(tail_x - u * 0.075, by + bh - 6), (tail_x + u * 0.075, by + bh - 6), (ax, ay - u * 0.14)], fill=fill)
    for i, l in enumerate(lines):
        d.text((bx + bw / 2, by + fnt.size * 0.45 + i * lh), l, font=fnt, anchor="mt", fill=ink)


# ---------------------------------------------------------------- main loop
def render(spec, W, H, n_frames, fps, write, t_start=0.0):
    rng = random.Random(7)
    bg = background(spec["background"], W, H, rng)
    u = min(W, H) * 0.24
    images = {}
    for a in spec["actors"]:
        if a["kind"] == "image" and a.get("image_path"):
            try:
                from .media import load_image

                im = Image.open(a["image_path"]).convert("RGBA")
                images[a["image_path"]] = im
            except Exception:
                a["kind"] = "logo"
    cache = {}
    shakes = [a["t"] + a["dur"] * 0.45 for a in spec["actions"] if a["do"] in ("punch", "kick")] + \
             [f["t"] for f in spec["fx"] if f["kind"] in ("explosion", "impact")] + \
             [a["t"] for a in spec["actions"] if a["do"] == "explode"]
    zoom = spec["camera"]["zoom"]
    for i in range(n_frames):
        t = t_start + i / fps
        frame = bg.copy()
        states = [(a, actor_state(a, spec["actions"], t)) for a in spec["actors"]]
        pos = {}
        for a, st in sorted(states, key=lambda x: x[1]["y"]):
            pos[a["id"]] = (st["x"] + st["dx"], st["y"] + st["dy"] - 0.12 * a["size"])
            if not st["visible"] or st["alpha"] <= 0.01:
                continue
            key = (a["id"], st["expr"], round(st["arm"], 2), st["arms_up"], None if st["walk"] is None else round(math.sin(st["walk"]), 2),
                   st["facing"], round(st["flash"], 2), st["tears"], round(st["leg_kick"], 2))
            spr = cache.get(key)
            if spr is None:
                spr = draw_actor(a, st, u, images)
                if len(cache) > 400:
                    cache.clear()
                cache[key] = spr
            if st["scale"] != 1 or st["rot"]:
                sc = max(0.01, st["scale"])
                spr = spr.resize((max(1, int(spr.width * sc)), max(1, int(spr.height * sc))), Image.Resampling.BILINEAR)
                if st["rot"]:
                    spr = spr.rotate(st["rot"], resample=Image.Resampling.BICUBIC, expand=True)
            if st["alpha"] < 1:
                spr = spr.copy()
                spr.putalpha(spr.split()[-1].point(lambda v: int(v * st["alpha"])))
            cx, cy = (st["x"] + st["dx"]) * W, (st["y"] + st["dy"]) * H
            frame.paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)), spr)
        draw_fx(frame, spec["fx"], t, W, H, pos, u)
        for a, st in states:
            if st["bubble"] and st["visible"]:
                ax, ay = (st["x"] + st["dx"]) * W, (st["y"] + st["dy"]) * H - 1.15 * u * a["size"] * st["scale"]
                draw_bubble(frame, st["bubble"]["text"], st["bubble"]["kind"], st["bubble"]["p"], ax, ay, W, H, u)
        arr = np.asarray(frame)
        z = 1.0 + (0.06 * t / max(1, n_frames / fps) if zoom == "in" else 0.06 * (1 - t / max(1, n_frames / fps)) if zoom == "out" else 0)
        sx = sum(math.sin((t - s0) * 70) * 18 * (1 - (t - s0) / 0.3) for s0 in shakes if 0 <= t - s0 < 0.3)
        sy = sum(math.cos((t - s0) * 55) * 14 * (1 - (t - s0) / 0.3) for s0 in shakes if 0 <= t - s0 < 0.3)
        if z != 1 or sx or sy:
            M = np.float32([[z, 0, (1 - z) * W / 2 + sx], [0, z, (1 - z) * H / 2 + sy]])
            arr = cv2.warpAffine(arr, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        write(np.ascontiguousarray(arr).tobytes())


def preview(spec, W, H, out):
    spec = normalize(spec)
    frames = []
    render(spec, W, H, 1, 30, frames.append, t_start=spec["duration"] * 0.55)
    Image.frombytes("RGB", (W, H), frames[0]).save(out)
