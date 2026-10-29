import base64
import io
import re
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".wmv"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".srt", ".pdf"}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def run_ffmpeg(args):
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-y", *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    if p.returncode:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-3000:])
    return p


def probe(path) -> dict:
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    err = p.stderr
    info = {"duration": 0.0, "width": 0, "height": 0, "has_audio": bool(re.search(r"Stream.*Audio:", err))}
    if m := re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err):
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    if m := re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", err):
        w, h = int(m[1]), int(m[2])
        rot = re.search(r"rotation of (-?[\d.]+)", err) or re.search(r"rotate\s*:\s*(-?\d+)", err)
        if rot and abs(round(float(rot[1]))) % 180 == 90:
            w, h = h, w
        info["width"], info["height"] = w, h
    return info


def load_image(path) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(path))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def video_frame(path, t: float, width=480) -> Image.Image:
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
        capture_output=True, creationflags=NO_WINDOW,
    )
    if p.returncode or not p.stdout:
        raise RuntimeError("could not read video frame")
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def make_thumbnail(path, kind, info, out: Path):
    if kind == "image":
        img = load_image(path)
    elif kind == "video":
        img = video_frame(path, min(1.0, info["duration"] / 3))
    else:
        return False
    img.thumbnail((480, 480))
    img.save(out, "JPEG", quality=82)
    return True


def preview_for_ai(path, kind, info) -> str | None:
    """Base64 JPEG the AI director can look at. Videos become a 3-frame contact sheet."""
    if kind == "image":
        img = load_image(path)
        img.thumbnail((640, 640))
    elif kind == "video":
        d = info["duration"] or 1
        frames = [video_frame(path, d * f, 360) for f in (0.15, 0.5, 0.85)]
        h = max(f.height for f in frames)
        img = Image.new("RGB", (sum(f.width for f in frames) + 8 * 2, h), (20, 20, 20))
        x = 0
        for f in frames:
            img.paste(f, (x, 0))
            x += f.width + 8
        img.thumbnail((1024, 1024))
    else:
        return None
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode()


def extract_text(path, limit=20000) -> str:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def wav_duration(path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())
