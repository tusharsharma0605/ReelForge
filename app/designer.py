"""Procedurally designed 'motion graphics' cards (title, stat, quote, list, text) rendered with Pillow + numpy."""
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .renderer import _font, _hex, _wrap

LAYOUTS = ["title", "stat", "quote", "list", "text"]
PALETTES = [("#0F0C29", "#302B63", "#FF4D8D"), ("#141E30", "#243B55", "#FFD400"), ("#1A2980", "#26D0CE", "#FFFFFF"),
            ("#232526", "#414345", "#00E5FF"), ("#42275A", "#734B6D", "#FFD6A5"), ("#0B486B", "#F56217", "#FFFFFF"),
            ("#000000", "#434343", "#E8C07D"), ("#11998E", "#38EF7D", "#0B0B10")]


def _gradient(w, h, c1, c2, angle_seed):
    a, b = np.array(_hex(c1), float), np.array(_hex(c2), float)
    yy, xx = np.mgrid[0:h, 0:w]
    t = (xx / w * angle_seed + yy / h * (1 - angle_seed))
    t = (t - t.min()) / max(t.max() - t.min(), 1e-6)
    arr = a + (b - a) * t[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def _blobs(img, accent, rng):
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = _hex(accent)
    for _ in range(3):
        r = rng.randint(int(min(w, h) * 0.18), int(min(w, h) * 0.42))
        x, y = rng.randint(-r // 2, w), rng.randint(-r // 2, h)
        d.ellipse([x - r, y - r, x + r, y + r], fill=acc + (rng.randint(40, 80),))
    layer = layer.filter(ImageFilter.GaussianBlur(min(w, h) * 0.08))
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    grain = Image.effect_noise((w // 2, h // 2), 18).resize((w, h)).convert("L")
    out = Image.composite(out, Image.new("RGBA", (w, h), (0, 0, 0, 255)), grain.point(lambda v: 255 - max(0, v - 128) // 6))
    return out.convert("RGB")


def _block(draw, text, font, maxw, x, y, fill, line_gap=1.18, align="center", shadow=True):
    lines = _wrap(draw, text, font, maxw)
    size = font.size
    for i, line in enumerate(lines):
        yy = y + i * size * line_gap
        anchor = "mt" if align == "center" else "lt"
        if shadow:
            draw.text((x, yy + size * 0.05), line, font=font, anchor=anchor, fill=(0, 0, 0, 120))
        draw.text((x, yy), line, font=font, anchor=anchor, fill=fill)
    return y + len(lines) * size * line_gap


def _fit_font(draw, text, style, start, maxw, max_lines):
    size = start
    while size > 24:
        f = _font(style, size)
        lines = _wrap(draw, text, f, maxw)
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= maxw for l in lines):
            return f
        size = int(size * 0.9)
    return _font(style, size)


def render_card(card: dict, W: int, H: int, out, margin=1.18):
    """Card is rendered at W*margin x H*margin so the Ken Burns crop never cuts content (safe area = 76%)."""
    w, h = int(W * margin), int(H * margin)
    rng = random.Random(str(card))
    pal = rng.choice(PALETTES)
    bg = card.get("bg") if isinstance(card.get("bg"), list) and len(card["bg"]) == 2 else pal[:2]
    accent = card.get("accent") or pal[2]
    img = _blobs(_gradient(w, h, bg[0], bg[1], rng.random()), accent, rng)
    d = ImageDraw.Draw(img, "RGBA")
    acc = _hex(accent)
    u = min(W, H)
    safe_w = int(W * 0.78)
    cx, top = w / 2, (h - H) / 2 + H * 0.12
    layout = card.get("layout") if card.get("layout") in LAYOUTS else "text"
    head = str(card.get("headline") or "").strip()
    sub = str(card.get("subtext") or "").strip()
    items = [str(i) for i in (card.get("items") or [])][:6]
    white = (255, 255, 255, 255)
    soft = (235, 235, 245, 220)

    if layout == "title":
        f = _fit_font(d, head, "bold", int(u * 0.13), safe_w, 4)
        fs = _font("minimal", int(u * 0.045))
        lines = len(_wrap(d, head, f, safe_w))
        block = lines * f.size * 1.18 + (fs.size * 3 if sub else 0)
        y = (h - block) / 2
        d.rounded_rectangle([cx - u * 0.08, y - u * 0.06, cx + u * 0.08, y - u * 0.045], radius=6, fill=acc + (255,))
        y = _block(d, head.upper(), f, safe_w, cx, y, white)
        if sub:
            _block(d, sub, fs, safe_w, cx, y + fs.size * 0.8, soft)
    elif layout == "stat":
        f = _fit_font(d, head, "bold", int(u * 0.3), safe_w, 1)
        fs = _fit_font(d, sub, "box", int(u * 0.06), safe_w, 3)
        y = h / 2 - f.size * 0.75
        d.text((cx, y), head, font=f, anchor="mt", fill=acc + (255,))
        if sub:
            _block(d, sub, fs, safe_w, cx, y + f.size * 1.15, white)
    elif layout == "quote":
        fq = _font("bold", int(u * 0.3))
        f = _fit_font(d, head, "box", int(u * 0.075), safe_w, 6)
        lines = len(_wrap(d, head, f, safe_w))
        y = h / 2 - lines * f.size * 1.25 / 2
        d.text((cx, y - u * 0.05), "\u201C", font=fq, anchor="mb", fill=acc + (230,))
        y = _block(d, head, f, safe_w, cx, y, white, 1.25)
        if sub:
            fs = _font("minimal", int(u * 0.042))
            _block(d, "\u2014 " + sub, fs, safe_w, cx, y + fs.size, soft)
    elif layout == "list":
        f = _fit_font(d, head, "bold", int(u * 0.085), safe_w, 2)
        y = _block(d, head, f, safe_w, cx, top + H * 0.05, white)
        fi = _font("box", int(u * (0.06 if len(items) <= 4 else 0.05)))
        left = (w - safe_w) / 2
        y += fi.size * 1.2
        for k, it in enumerate(items):
            d.ellipse([left, y + fi.size * 0.25, left + fi.size * 0.55, y + fi.size * 0.8], fill=acc + (255,))
            y = _block(d, it, fi, safe_w - fi.size, left + fi.size * 0.95, y, white, 1.15, align="left") + fi.size * 0.55
    else:
        f = _fit_font(d, head, "box", int(u * 0.09), safe_w, 6)
        lines = len(_wrap(d, head, f, safe_w))
        y = h / 2 - lines * f.size * 1.2 / 2
        y = _block(d, head, f, safe_w, cx, y, white, 1.2)
        d.rounded_rectangle([cx - u * 0.06, y + u * 0.03, cx + u * 0.06, y + u * 0.042], radius=5, fill=acc + (255,))
        if sub:
            fs = _font("minimal", int(u * 0.045))
            _block(d, sub, fs, safe_w, cx, y + u * 0.08, soft)
    img.save(out)
    return out
