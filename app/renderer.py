"""Turns an edit plan (JSON) into a finished MP4 using Pillow + FFmpeg."""
import math
import re
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from . import tts
from .media import FFMPEG, NO_WINDOW, load_image, run_ffmpeg

FPS = 30
ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FILTERS = {
    "none": "",
    "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08,eq=saturation=1.1",
    "cool": "colorbalance=rs=-0.06:bs=0.08,eq=saturation=1.05",
    "bw": "hue=s=0,eq=contrast=1.12",
    "vivid": "eq=saturation=1.35:contrast=1.08",
    "cinematic": "eq=contrast=1.12:saturation=0.88,colorbalance=rs=-0.05:bs=0.05:rh=0.06:bh=-0.04,vignette=angle=PI/5",
    "vintage": "curves=preset=vintage,vignette=angle=PI/4",
}
MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"]
TRANSITIONS = ["none", "fade", "fadeblack", "fadewhite", "dissolve", "slideleft", "slideright", "slideup",
               "slidedown", "wipeleft", "wiperight", "circleopen", "circleclose", "radial", "smoothleft",
               "smoothright", "zoomin", "pixelize", "hblur", "squeezev"]
TEXT_STYLES = ["bold", "box", "minimal", "neon"]
WHOOSH_TRANSITIONS = {"slideleft", "slideright", "slideup", "slidedown", "wipeleft", "wiperight", "smoothleft", "smoothright",
                      "zoomin", "circleopen", "circleclose", "radial", "squeezev", "pixelize", "hblur"}
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS)]
FONTS = {
    "bold": ["seguibl.ttf", "impact.ttf", "arialbd.ttf"],
    "box": ["segoeuib.ttf", "arialbd.ttf"],
    "minimal": ["segoeui.ttf", "arial.ttf"],
    "neon": ["seguibl.ttf", "arialbd.ttf"],
}


# ---------------------------------------------------------------- text overlays
def _font(style, size):
    for name in FONTS.get(style, FONTS["bold"]):
        try:
            return ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _hex(c, default=(255, 204, 0)):
    try:
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _wrap(draw, text, font, maxw):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            test = f"{cur} {word}".strip()
            if draw.textlength(test, font=font) <= maxw or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


def render_text_png(text, W, H, position, style, accent, out: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = (text or "").strip()
    if not text:
        img.save(out)
        return
    draw = ImageDraw.Draw(img)
    maxw = int(W * 0.84)
    size = int(min(W, H) * (0.058 if style == "minimal" else 0.082))
    while True:
        font = _font(style, size)
        lines = _wrap(draw, text, font, maxw)
        if (len(lines) <= 4 and all(draw.textlength(l, font=font) <= maxw for l in lines)) or size <= 26:
            break
        size = int(size * 0.88)
    line_h = int(size * 1.22)
    block_h = line_h * len(lines)
    y0 = {"top": H * 0.12, "center": (H - block_h) / 2}.get(position, H * 0.79 - block_h)
    acc = _hex(accent)
    stroke = max(2, size // 13)

    if style in ("bold", "minimal", "neon"):
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        glow = acc + (255,) if style == "neon" else (0, 0, 0, 170)
        for i, line in enumerate(lines):
            sd.text((W / 2, y0 + i * line_h + size * 0.06), line, font=font, anchor="mt", fill=glow,
                    stroke_width=stroke * (2 if style == "neon" else 1), stroke_fill=glow)
        shadow = shadow.filter(ImageFilter.GaussianBlur(size * (0.28 if style == "neon" else 0.09)))
        img.alpha_composite(shadow)
        if style == "neon":
            img.alpha_composite(shadow)
    for i, line in enumerate(lines):
        y = y0 + i * line_h
        if style == "box":
            w = draw.textlength(line, font=font)
            pad = size * 0.32
            draw.rounded_rectangle([W / 2 - w / 2 - pad, y - pad * 0.45, W / 2 + w / 2 + pad, y + size * 1.08 + pad * 0.3],
                                   radius=int(size * 0.25), fill=acc + (240,))
            lum = 0.299 * acc[0] + 0.587 * acc[1] + 0.114 * acc[2]
            draw.text((W / 2, y), line, font=font, anchor="mt", fill=(15, 15, 15) if lum > 150 else (255, 255, 255))
        elif style == "neon":
            draw.text((W / 2, y), line, font=font, anchor="mt", fill=(255, 255, 255), stroke_width=max(1, stroke // 2), stroke_fill=acc)
        elif style == "minimal":
            draw.text((W / 2, y), line, font=font, anchor="mt", fill=(255, 255, 255))
        else:
            draw.text((W / 2, y), line, font=font, anchor="mt", fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0))
    img.save(out)


def _text_chain(dur):
    return (f"format=rgba,fade=t=in:st=0.12:d=0.35:alpha=1,"
            f"fade=t=out:st={max(0.5, dur - 0.45):.3f}:d=0.3:alpha=1")


# ---------------------------------------------------------------- framing helpers
def _needs_blurfit(sw, sh, W, H, fit):
    if fit == "cover":
        return False
    if fit == "contain":
        return True
    r = (sw / max(sh, 1)) / (W / H)
    return not (0.75 < r < 1.33)


def _compose_base(img, bw, bh, fit):
    if not _needs_blurfit(img.width, img.height, bw, bh, fit):
        return ImageOps.fit(img, (bw, bh), Image.Resampling.LANCZOS)
    bg = ImageOps.fit(img, (max(8, bw // 8), max(8, bh // 8)), Image.Resampling.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(4)).resize((bw, bh), Image.Resampling.BICUBIC)
    bg = ImageEnhance.Brightness(bg).enhance(0.6)
    fg = ImageOps.contain(img, (bw, bh), Image.Resampling.LANCZOS)
    bg.paste(fg, ((bw - fg.width) // 2, (bh - fg.height) // 2))
    return bg


def _crop(motion, p, W, H, bw, bh):
    m = bw / W
    if motion == "zoom_in":
        s = m - (m - 1) * p
    elif motion == "zoom_out":
        s = 1 + (m - 1) * p
    elif motion == "static":
        s = (1 + m) / 2
    else:
        s = 1.0
    cw, ch = s * W, s * H
    x0, y0 = (bw - cw) / 2, (bh - ch) / 2
    if motion == "pan_left":
        x0 = (bw - cw) * (1 - p)
    elif motion == "pan_right":
        x0 = (bw - cw) * p
    elif motion == "pan_up":
        y0 = (bh - ch) * (1 - p)
    elif motion == "pan_down":
        y0 = (bh - ch) * p
    return s, x0, y0


# ---------------------------------------------------------------- captions (word-by-word, Instagram style)
def caption_overlays(words, offset, W, H, accent, workdir: Path, idx, end, low=False):
    """One PNG per spoken word: the current 1-3 word group with the active word highlighted."""
    if not words:
        return []
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 3 or re.search(r"[.!?,;:]$", w["word"]) or sum(len(x["word"]) for x in cur) > 14:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    acc = _hex(accent, (255, 214, 0))
    size = int(min(W, H) * 0.085)
    font = _font("bold", size)
    y = H * ((0.8 if low else 0.69) if H > W else (0.86 if low else 0.8))
    out = []
    for g, grp in enumerate(groups):
        g_end = groups[g + 1][0]["start"] if g + 1 < len(groups) else min(end - offset, grp[-1]["end"] + 0.6)
        toks = [re.sub(r"[.,;:]$", "", w["word"]).upper() for w in grp]
        for k, w in enumerate(grp):
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            f = font
            total = sum(d.textlength(t, font=f) for t in toks) + size * 0.3 * (len(toks) - 1)
            while total > W * 0.9 and f.size > 30:
                f = _font("bold", int(f.size * 0.9))
                total = sum(d.textlength(t, font=f) for t in toks) + f.size * 0.3 * (len(toks) - 1)
            x = (W - total) / 2
            for j, t in enumerate(toks):
                tw = d.textlength(t, font=f)
                if j == k:
                    pad = f.size * 0.14
                    d.rounded_rectangle([x - pad, y - pad * 0.6, x + tw + pad, y + f.size * 1.08], radius=int(f.size * 0.2), fill=acc + (255,))
                    lum = 0.299 * acc[0] + 0.587 * acc[1] + 0.114 * acc[2]
                    d.text((x, y), t, font=f, fill=(15, 15, 15) if lum > 150 else (255, 255, 255))
                else:
                    d.text((x, y), t, font=f, fill=(255, 255, 255), stroke_width=max(3, f.size // 11), stroke_fill=(0, 0, 0))
                x += tw + f.size * 0.3
            p = workdir / f"cap{idx}_{g}_{k}.png"
            img.save(p)
            t0 = offset + (grp[0]["start"] if k == 0 else w["start"])
            t1 = offset + (grp[k + 1]["start"] if k + 1 < len(grp) else g_end)
            out.append({"png": p, "t0": t0, "t1": max(t1, t0 + 0.05)})
    return out


# ---------------------------------------------------------------- segments
def _prep_overlays(overlays, dur):
    """Load overlay PNGs once, cropped to their visible area, premultiplied for fast numpy blending."""
    out = []
    for o in overlays:
        img = Image.open(o["png"]).convert("RGBA")
        box = img.getbbox()
        if not box:
            continue
        a = np.asarray(img.crop(box)).astype(np.float32)
        alpha = a[..., 3:] / 255.0
        out.append({"x": box[0], "y": box[1], "rgb": a[..., :3] * alpha, "alpha": alpha, "fade": o.get("fade"),
                    "t0": o.get("t0", 0.0), "t1": o.get("t1", dur)})
    return out


def _composite(frame, overlays, t, dur):
    for o in overlays:
        if not (o["t0"] <= t < o["t1"]):
            continue
        k = 1.0
        if o["fade"]:
            k = min(1.0, max(0.0, (t - 0.12) / 0.35), max(0.0, (dur - 0.15 - t) / 0.3))
            if k <= 0:
                continue
        h, w = o["alpha"].shape[:2]
        region = frame[o["y"]:o["y"] + h, o["x"]:o["x"] + w]
        h, w = region.shape[:2]
        a = o["alpha"][:h, :w] * k
        region[:] = (region * (1 - a) + o["rgb"][:h, :w] * k).astype(np.uint8)
    return frame


def _pipe_segment(frames, n, W, H, overlays, out: Path):
    """frames: generator of HxWx3 uint8 arrays. Overlays are blended in numpy, then the frame is encoded."""
    dur = n / FPS
    ovs = _prep_overlays(overlays, dur)
    cmd = [FFMPEG, "-hide_banner", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-frames:v", str(n), *ENC, str(out)]
    log = out.with_suffix(".log")
    with open(log, "wb") as errf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errf, creationflags=NO_WINDOW)
        try:
            for i, fr in enumerate(frames):
                if i >= n:
                    break
                if ovs:
                    fr = _composite(np.array(fr, copy=True), ovs, i / FPS, dur)
                proc.stdin.write(np.ascontiguousarray(fr).tobytes())
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        rc = proc.wait()
    if rc:
        raise RuntimeError("ffmpeg (segment) failed:\n" + log.read_text(errors="replace")[-2500:])
    return dur


def _graded(img: Image.Image, flt, workdir: Path):
    """Apply an ffmpeg colour grade to a still image once (instead of per frame)."""
    if not flt:
        return img
    src, dst = workdir / "grade_in.png", workdir / "grade_out.png"
    img.save(src)
    run_ffmpeg(["-i", src, "-vf", flt, "-frames:v", 1, dst])
    return Image.open(dst).convert("RGB")


def render_image_segment(scene, asset, W, H, overlays, out: Path):
    n = max(2, round(scene["duration"] * FPS))
    m = 1.18
    base = _compose_base(load_image(asset["path"]), int(W * m), int(H * m), scene.get("fit", "auto"))
    base = _graded(base, FILTERS.get(scene["filter"], ""), out.parent)
    bw, bh = base.size
    arr = np.asarray(base)

    def frames():
        for i in range(n):
            t = i / (n - 1)
            p = 0.5 * t + 0.5 * (0.5 - 0.5 * math.cos(math.pi * t))
            s, x0, y0 = _crop(scene["motion"], p, W, H, bw, bh)
            yield cv2.warpAffine(arr, np.float32([[s, 0, x0], [0, s, y0]]), (W, H),
                                 flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)

    return _pipe_segment(frames(), n, W, H, overlays, out), []


def render_anim_segment(scene, asset, W, H, overlays, out: Path):
    import queue
    import threading

    from . import animator

    spec = scene["_anim"]
    n = max(2, round(scene["duration"] * FPS))
    q = queue.Queue(maxsize=8)

    err = []

    def produce():
        try:
            animator.render(spec, W, H, n, FPS, lambda b: q.put(np.frombuffer(b, np.uint8).reshape(H, W, 3)))
        except Exception as e:
            err.append(e)
        finally:
            q.put(None)

    def frames():
        while (fr := q.get()) is not None:
            yield fr

    threading.Thread(target=produce, daemon=True).start()
    dur = _pipe_segment(frames(), n, W, H, overlays, out)
    if err:
        raise RuntimeError(f"Animation scene failed: {err[0]}") from err[0]
    return dur, animator.sfx_events(spec)


def render_video_segment(scene, asset, W, H, overlays, out: Path):
    n = max(2, round(scene["duration"] * FPS))
    dur = n / FPS
    speed = scene["speed"]
    start = scene["start"]
    if _needs_blurfit(asset["width"] or W, asset["height"] or H, W, H, scene.get("fit", "auto")):
        fit = (f"split[ba][fa];[ba]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
               f"crop={W // 4}:{H // 4},boxblur=10:2,scale={W}:{H},eq=brightness=-0.12[bg];"
               f"[fa]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
               f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    else:
        fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    flt = FILTERS.get(scene["filter"], "")
    vf = (f"{fit},setpts=(PTS-STARTPTS)/{speed},fps={FPS}{',' + flt if flt else ''},"
          f"tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},format=rgb24")
    dec = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur * speed + 0.5:.3f}",
                            "-i", asset["path"], "-filter_complex", vf, "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = W * H * 3

    def frames():
        last = None
        for _ in range(n):
            buf = dec.stdout.read(size)
            if len(buf) < size:
                if last is None:
                    raise RuntimeError(f"Could not decode video clip {asset.get('name')}")
                yield last
                continue
            last = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            yield last

    try:
        return _pipe_segment(frames(), n, W, H, overlays, out), []
    finally:
        dec.kill()


# ---------------------------------------------------------------- assembly
def post_filter(plan, W, H):
    look = plan.get("look") or {}
    f = []
    if look.get("grain"):
        f.append("noise=alls=9:allf=t")
    if look.get("letterbox"):
        bar = int(H * 0.085) if H >= W else max(0, int((H - W / 2.39) / 2))
        f.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")
    return ",".join(f)


def concat_xfade(segs, durs, trans, tdurs, out: Path, post=""):
    if len(segs) == 1:
        if post:
            run_ffmpeg(["-i", segs[0], "-vf", post, *ENC, out])
        else:
            shutil.copy(segs[0], out)
        return [0.0], durs[0]
    args, parts = [], []
    for i, s in enumerate(segs):
        args += ["-i", s]
        parts.append(f"[{i}:v]settb=AVTB,fps={FPS},format=yuv420p[v{i}]")
    starts, L, prev = [0.0], durs[0], "v0"
    for k in range(1, len(segs)):
        d = tdurs[k]
        off = L - d
        parts.append(f"[{prev}][v{k}]xfade=transition={trans[k]}:duration={d:.3f}:offset={off:.3f}[x{k}]")
        starts.append(off)
        L = L + durs[k] - d
        prev = f"x{k}"
    if post:
        parts.append(f"[{prev}]{post}[pf]")
        prev = "pf"
    run_ffmpeg([*args, "-filter_complex", ";".join(parts), "-map", f"[{prev}]", *ENC, out])
    return starts, L


def mix_audio(video: Path, total, sources, music, out: Path):
    args = ["-i", video, "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    fc, voices, others = [], [], []
    idx = 2
    fmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
    for s in sources:
        ms = int(s["at"] * 1000)
        if s["kind"] == "clip":
            args += ["-ss", f"{s['start']:.3f}", "-t", f"{s['dur'] * s['speed'] + 0.2:.3f}", "-i", s["path"]]
            tempo = f",atempo={s['speed']}" if abs(s["speed"] - 1) > 0.01 else ""
            chain = (f"{fmt}{tempo},atrim=0:{s['dur']:.3f},afade=t=in:d=0.15,"
                     f"afade=t=out:st={max(0, s['dur'] - 0.35):.3f}:d=0.35")
            others.append(f"a{idx}")
        elif s["kind"] == "bed":
            args += ["-i", s["path"]]
            chain = fmt
            others.append(f"a{idx}")
        else:
            args += ["-i", s["path"]]
            chain = fmt
            voices.append(f"a{idx}")
        fc.append(f"[{idx}:a]{chain},volume={s['volume']:.2f},adelay={ms}:all=1[a{idx}]")
        idx += 1
    if voices:
        if len(voices) > 1:
            fc.append("".join(f"[{v}]" for v in voices) + f"amix=inputs={len(voices)}:normalize=0[vo]")
        else:
            fc.append(f"[{voices[0]}]anull[vo]")
    if music:
        args += ["-stream_loop", "-1", "-i", music["path"]]
        fc.append(f"[{idx}:a]{fmt},atrim=0:{total:.3f},afade=t=in:d=0.8,"
                  f"afade=t=out:st={max(0, total - 2):.3f}:d=2,volume={music['volume']:.2f}[mu]")
        if voices:
            fc.append("[vo]asplit=2[vo][vsc]")
            fc.append("[mu][vsc]sidechaincompress=threshold=0.03:ratio=8:attack=30:release=450[mu2]")
            others.append("mu2")
        else:
            others.append("mu")
    mix = ["1:a"] + (["vo"] if voices else []) + others
    fc.append("".join(f"[{m}]" for m in mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
              f"alimiter=limit=0.95[aout]")
    run_ffmpeg([*args, "-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", out])


def render(plan: dict, assets: dict, workdir: Path, out: Path, progress=lambda pct, msg: None):
    workdir.mkdir(parents=True, exist_ok=True)
    W, H = ASPECTS.get(plan["aspect"], ASPECTS["9:16"])
    scenes = plan["scenes"]
    if not scenes:
        raise ValueError("The plan has no scenes")

    from . import animator, audio

    for s in scenes:
        a = assets[s["asset_id"]]
        if a["kind"] == "anim":
            s["_anim"] = animator.normalize(a.get("anim") or {}, s["duration"])
            s["duration"] = max(s["duration"], s["_anim"]["duration"] + 0.3)

    narr = {}
    vo = plan.get("voiceover", {})
    if vo.get("enabled"):
        progress(5, "Recording voiceover")
        idxs = [i for i, s in enumerate(scenes) if s.get("narration", "").strip()]
        items = [{"text": scenes[i]["narration"], "path": str(workdir / f"vo{i}.wav"), "voice": vo.get("voice", ""),
                  "rate": int(vo.get("rate", 0))} for i in idxs]
        for i, it, (d, words) in zip(idxs, items, tts.synthesize(items, workdir, lambda m: progress(6, m))):
            narr[i] = (it["path"], d, words)
            lead = scenes[i]["transition_duration"] if i else 0
            scenes[i]["duration"] = max(scenes[i]["duration"], round(d + lead + 0.45, 2))

    for k, s in enumerate(scenes):
        if k == 0 or s["transition"] == "none":
            s["_t"], s["_td"] = "fade", 2 / FPS
        else:
            s["_t"] = s["transition"]
            s["_td"] = max(2 / FPS, min(s["transition_duration"], 0.4 * min(s["duration"], scenes[k - 1]["duration"])))

    karaoke = plan.get("captions", "karaoke") == "karaoke"
    accent = plan.get("accent_color", "#FFCC00")
    segs, durs, seg_sfx = [], [], []
    for i, s in enumerate(scenes):
        progress(10 + int(70 * i / len(scenes)), f"Rendering scene {i + 1}/{len(scenes)}")
        a = assets[s["asset_id"]]
        overlays = []
        caps = []
        if karaoke and i in narr:
            lead = (s["_td"] if i else 0) + 0.15
            caps = caption_overlays(narr[i][2], lead, W, H, accent, workdir, i, s["duration"], low=a["kind"] == "anim")
        text = s.get("text", "").strip()
        if caps and text and (text.rstrip(".") in s["narration"] or s["narration"].startswith(text.rstrip(". ").rstrip("."))):
            text = ""
        if text:
            tp = workdir / f"text{i}.png"
            pos = "top" if caps and s.get("text_position", "bottom") != "top" else s.get("text_position", "bottom")
            render_text_png(text, W, H, pos, plan.get("text_style", "bold"), accent, tp)
            overlays.append({"png": tp, "fade": True})
        overlays += caps
        seg = workdir / f"seg{i}.mp4"
        fn = {"image": render_image_segment, "anim": render_anim_segment}.get(a["kind"], render_video_segment)
        d, ev = fn(s, a, W, H, overlays, seg)
        durs.append(d)
        seg_sfx.append(ev + [(float(x.get("t", 0)), x.get("kind"), float(x.get("gain", 0.7)))
                             for x in s.get("sfx") or [] if isinstance(x, dict) and x.get("kind") in audio.SFX])
        if text and not ev:
            seg_sfx[-1].append((0.15, "pop", 0.25))
        segs.append(seg)

    progress(82, "Stitching transitions")
    silent = workdir / "video.mp4"
    starts, total = concat_xfade(segs, durs, [s["_t"] for s in scenes], [s["_td"] for s in scenes], silent,
                                 post_filter(plan, W, H))

    progress(90, "Scoring music & sound effects")
    sources = []
    if plan.get("sfx", True):
        events = []
        for k, s in enumerate(scenes):
            if k and s["_t"] in WHOOSH_TRANSITIONS:
                events.append((starts[k] - 0.12, "whoosh", 0.45))
            elif k and s["_t"] in ("fadeblack", "fadewhite") and (plan.get("look") or {}).get("letterbox"):
                events.append((starts[k] + s["_td"] / 2, "boom", 0.35))
            events += [(starts[k] + t, kind, g) for t, kind, g in seg_sfx[k]]
        if events:
            sources.append({"kind": "bed", "path": audio.sfx_track(events, total, workdir / "sfx.wav"), "at": 0, "volume": 1.0})
    for i, s in enumerate(scenes):
        a = assets[s["asset_id"]]
        if a["kind"] == "video" and s.get("keep_audio") and a.get("has_audio") and s.get("audio_volume", 1) > 0:
            sources.append({"kind": "clip", "path": a["path"], "start": s["start"], "dur": durs[i],
                            "speed": s["speed"], "at": starts[i], "volume": s.get("audio_volume", 1.0)})
        if i in narr:
            sources.append({"kind": "voice", "path": narr[i][0], "at": starts[i] + (s["_td"] if i else 0) + 0.15,
                            "volume": 1.0})
    music = None
    mus = plan.get("music") or {}
    if mus.get("asset_id") in assets:
        music = {"path": assets[mus["asset_id"]]["path"], "volume": float(mus.get("volume", 0.35))}
    elif mus.get("generate") in audio.MOODS:
        progress(93, f"Composing {mus['generate']} soundtrack")
        music = {"path": audio.music(mus["generate"], total + 0.5, workdir / "music.wav"), "volume": float(mus.get("volume", 0.35))}
    progress(96, "Mixing audio")
    mix_audio(silent, total, sources, music, out)
    progress(100, "Done")
    return total
