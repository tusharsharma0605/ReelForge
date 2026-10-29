"""Procedural, royalty-free soundtrack + sound effects (pure numpy, no downloads)."""
import wave

import numpy as np

SR = 44100
MOODS = ["cinematic", "upbeat", "calm", "dramatic", "quirky"]
SFX = ["whoosh", "punch", "boom", "explosion", "pop", "ding", "riser", "thud", "swoosh_up", "glitch"]


def _midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def _t(sec):
    return np.arange(int(sec * SR)) / SR


def _env(n, a=0.01, d=0.1, s=0.7, r=0.2, length=None):
    """ADSR envelope (seconds) for n samples."""
    length = length or n / SR
    t = np.arange(n) / SR
    e = np.where(t < a, t / max(a, 1e-4), np.where(t < a + d, 1 - (1 - s) * (t - a) / max(d, 1e-4), s))
    rel_start = max(0, length - r)
    return e * np.clip(1 - (t - rel_start) / max(r, 1e-4), 0, 1)


def _tone(freq, sec, harmonics=6, detune=0.0, bright=1.0):
    t = _t(sec)
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        amp = (1 / k) ** (1.6 - 0.6 * bright)
        out += amp * np.sin(2 * np.pi * freq * k * t * (1 + detune) + k)
    return out / 1.8


def _pluck(freq, sec, decay=4.0, harmonics=4):
    t = _t(sec)
    out = sum((0.7 ** k) * np.sin(2 * np.pi * freq * (k + 1) * t) * np.exp(-t * decay * (1 + k * 0.6)) for k in range(harmonics))
    return out * np.minimum(1, t / 0.003)


def _filter(x, lo=0, hi=SR / 2):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    m = np.ones_like(f)
    if lo:
        m *= 1 / (1 + (lo / np.maximum(f, 1)) ** 4)
    if hi < SR / 2:
        m *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * m, len(x))


def _noise(sec, seed=0):
    return np.random.default_rng(seed).standard_normal(int(sec * SR))


def _kick(sec=0.35):
    t = _t(sec)
    f = 45 + 90 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * 1.1


def _snare(sec=0.2, seed=1):
    t = _t(sec)
    return (_filter(_noise(sec, seed), 900, 7000) * 0.6 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 22)


def _hat(sec=0.05, seed=2):
    return _filter(_noise(sec, seed), 7000) * np.exp(-_t(sec) * 90) * 0.5


def _boom(sec=1.6, seed=3):
    t = _t(sec)
    f = 32 + 60 * np.exp(-t * 5)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2)
    return np.tanh(1.6 * (body + _filter(_noise(sec, seed), 0, 900) * np.exp(-t * 9) * 0.5))


def _add(buf, x, at, gain=1.0):
    i = int(at * SR)
    if i >= len(buf) or i < 0:
        return
    n = min(len(x), len(buf) - i)
    buf[i:i + n] += x[:n] * gain


PROGRESSIONS = {
    "cinematic": ([57, 53, 48, 55], 70, "minor"),   # Am F C G
    "upbeat": ([48, 55, 57, 53], 118, "major"),     # C G Am F
    "calm": ([53, 48, 55, 57], 76, "major"),        # F C G Am
    "dramatic": ([50, 46, 53, 48], 96, "minor"),    # Dm Bb F C
    "quirky": ([48, 53, 55, 48], 112, "major"),     # C F G C
}


def _chord(root, quality):
    return [root, root + (3 if root % 12 in (9, 2, 4) else 4), root + 7]


def music(mood: str, seconds: float, path, seed=7):
    mood = mood if mood in PROGRESSIONS else "cinematic"
    prog, bpm, quality = PROGRESSIONS[mood]
    beat = 60 / bpm
    bar = beat * 4
    total = seconds + 2
    L = np.zeros(int(total * SR))
    R = np.zeros(int(total * SR))
    rng = np.random.default_rng(seed)
    nbars = int(np.ceil(total / bar))
    for b in range(nbars):
        t0 = b * bar
        root = prog[b % len(prog)]
        chord = _chord(root, quality)
        intensity = min(1.0, 0.55 + 0.45 * b / max(1, nbars - 1))
        # pad (all moods)
        pad_gain = {"cinematic": 0.16, "calm": 0.13, "dramatic": 0.11, "upbeat": 0.06, "quirky": 0.04}[mood]
        for n in chord:
            for side, det in ((L, -0.0018), (R, 0.0018)):
                tone = _tone(_midi(n + 12), bar + 0.6, 5 if mood != "calm" else 3, det, 0.5)
                _add(side, tone * _env(len(tone), a=bar * 0.35, d=0.2, s=0.9, r=0.8), t0, pad_gain)
        bass = _tone(_midi(root - 12), bar, 3, 0, 0.3)
        if mood in ("cinematic", "calm"):
            e = _env(len(bass), a=0.4, d=0.3, s=0.8, r=0.6)
            _add(L, bass * e, t0, 0.22)
            _add(R, bass * e, t0, 0.22)
        if mood == "cinematic":
            if b % 2 == 0:
                bm = _boom(2.0, seed + b)
                _add(L, bm, t0, 0.5 * intensity)
                _add(R, bm, t0, 0.5 * intensity)
            for k, n in enumerate([chord[0] + 24, chord[2] + 24, chord[1] + 24, chord[2] + 24]):
                p = _pluck(_midi(n), 1.6, 2.5, 3)
                _add(L if k % 2 else R, p, t0 + k * beat, 0.05)
        elif mood == "calm":
            for k in range(4):
                n = chord[[0, 1, 2, 1][k]] + 12
                p = _pluck(_midi(n), 2.0, 2.2, 5)
                _add(L, p, t0 + k * beat, 0.11)
                _add(R, p, t0 + k * beat + 0.012, 0.09)
        elif mood == "upbeat":
            for k in range(4):
                _add(L, _kick(), t0 + k * beat, 0.55)
                _add(R, _kick(), t0 + k * beat, 0.55)
                if k in (1, 3):
                    s = _snare(seed=b * 4 + k)
                    _add(L, s, t0 + k * beat, 0.3)
                    _add(R, s, t0 + k * beat, 0.3)
            for k in range(8):
                h = _hat(seed=b * 8 + k)
                _add(L if k % 2 else R, h, t0 + k * beat / 2, 0.25)
                bn = _pluck(_midi(root - 12), beat / 2, 6, 3)
                _add(L, bn, t0 + k * beat / 2, 0.28)
                _add(R, bn, t0 + k * beat / 2, 0.28)
            for k in range(16):
                n = chord[k % 3] + 24 + (12 if k % 8 == 7 else 0)
                p = _pluck(_midi(n), 0.3, 9, 3)
                _add(L if k % 2 else R, p, t0 + k * beat / 4, 0.07 * intensity)
        elif mood == "dramatic":
            for k in range(8):
                n = root - 12 + (0 if k % 2 == 0 else 12)
                s = _tone(_midi(n), beat / 2, 6, 0, 0.9) * _env(int(beat / 2 * SR), 0.01, 0.05, 0.6, 0.08)
                _add(L, s, t0 + k * beat / 2, 0.2 * intensity)
                _add(R, s, t0 + k * beat / 2 + 0.008, 0.2 * intensity)
            if b % 2 == 1:
                bm = _boom(1.6, seed + b)
                _add(L, bm, t0, 0.55)
                _add(R, bm, t0, 0.55)
            for k in range(4):
                _add(L, _kick(0.3), t0 + k * beat, 0.25 * intensity)
                _add(R, _kick(0.3), t0 + k * beat, 0.25 * intensity)
        elif mood == "quirky":
            for k in range(4):
                bn = _pluck(_midi((root if k % 2 == 0 else root + 7) - 12), beat * 0.8, 5, 2)
                _add(L, bn, t0 + k * beat, 0.32)
                _add(R, bn, t0 + k * beat, 0.32)
                h = _hat(0.04, b * 4 + k)
                _add(L, h, t0 + k * beat + beat / 2, 0.35)
                _add(R, h, t0 + k * beat + beat / 2, 0.35)
            melody = [chord[0], chord[1], chord[2], chord[1] + 1, chord[2], chord[1], chord[0] + 12, chord[2]]
            for k, n in enumerate(melody):
                if rng.random() < 0.85:
                    p = _pluck(_midi(n + 12), 0.25, 14, 3)
                    _add(L if k % 2 else R, p, t0 + k * beat / 2, 0.16)
    mix = np.stack([L, R], 1)[: int(seconds * SR)]
    mix /= max(1e-6, np.abs(mix).max()) / 0.85
    mix = np.tanh(mix * 1.15) / np.tanh(1.15)
    fade = np.minimum(1, np.arange(len(mix)) / (SR * 0.6))[:, None] * np.minimum(1, (len(mix) - np.arange(len(mix))) / (SR * 2.0))[:, None]
    write_wav(path, mix * fade)
    return path


# ---------------------------------------------------------------- sound effects
def sfx(kind: str, seed=0) -> np.ndarray:
    """Returns a stereo (n, 2) array."""
    if kind == "whoosh":
        sec = 0.55
        t = _t(sec)
        x = _filter(_noise(sec, seed), 300, 3500) * np.sin(np.pi * t / sec) ** 2
        pan = t / sec
        return np.stack([x * (1 - pan * 0.7), x * (0.3 + pan * 0.7)], 1) * 0.9
    if kind == "swoosh_up":
        sec = 0.4
        t = _t(sec)
        f = 300 + 1800 * (t / sec) ** 2
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25 + _filter(_noise(sec, seed), 1500, 8000) * 0.5
        x *= np.sin(np.pi * t / sec)
        return np.stack([x, x], 1)
    if kind == "punch":
        sec = 0.28
        t = _t(sec)
        f = 60 + 140 * np.exp(-t * 30)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14) + _filter(_noise(sec, seed), 150, 3000) * np.exp(-t * 40) * 0.9
        x = np.tanh(x * 2.2) * 0.9
        return np.stack([x, x], 1)
    if kind == "thud":
        sec = 0.4
        t = _t(sec)
        x = np.sin(2 * np.pi * np.cumsum(50 + 60 * np.exp(-t * 20)) / SR) * np.exp(-t * 10) + _filter(_noise(sec, seed), 0, 600) * np.exp(-t * 25) * 0.6
        return np.stack([x, x], 1) * 0.9
    if kind in ("boom", "explosion"):
        sec = 1.4 if kind == "boom" else 2.2
        x = _boom(sec, seed)
        if kind == "explosion":
            t = _t(sec)
            x = x + _filter(_noise(sec, seed + 5), 0, 2500) * np.exp(-t * 3) * 0.7
        x = np.tanh(x * 1.3) * 0.95
        return np.stack([x, np.roll(x, 300)], 1)
    if kind == "pop":
        sec = 0.12
        t = _t(sec)
        x = np.sin(2 * np.pi * np.cumsum(500 + 900 * t / sec) / SR) * np.exp(-t * 35) * 0.7
        return np.stack([x, x], 1)
    if kind == "ding":
        sec = 1.2
        t = _t(sec)
        x = (np.sin(2 * np.pi * 1318 * t) + 0.4 * np.sin(2 * np.pi * 2636 * t) + 0.2 * np.sin(2 * np.pi * 3951 * t)) * np.exp(-t * 4) * 0.35
        return np.stack([x, x], 1)
    if kind == "riser":
        sec = 1.6
        t = _t(sec)
        f = 150 + 900 * (t / sec) ** 2
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25 + _filter(_noise(sec, seed), 800, 9000) * 0.4 * (t / sec)
        x *= (t / sec) ** 1.5
        return np.stack([x, x], 1)
    if kind == "glitch":
        sec = 0.3
        x = np.sign(np.sin(2 * np.pi * 180 * _t(sec))) * (np.random.default_rng(seed).random(int(sec * SR)) > 0.5) * 0.25
        return np.stack([x, np.roll(x, 50)], 1)
    return np.zeros((1, 2))


def sfx_track(events, seconds, path):
    """events: [(time, kind, gain)] -> one stereo wav."""
    buf = np.zeros((int((seconds + 2.5) * SR), 2))
    for k, (at, kind, gain) in enumerate(events):
        x = sfx(kind, seed=k)
        i = int(max(0, at) * SR)
        n = min(len(x), len(buf) - i)
        if n > 0:
            buf[i:i + n] += x[:n] * gain
    buf = buf[: int(seconds * SR)]
    peak = np.abs(buf).max()
    if peak > 0.98:
        buf *= 0.98 / peak
    write_wav(path, buf)
    return path


def write_wav(path, stereo):
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
