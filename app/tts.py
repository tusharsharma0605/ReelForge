"""Text-to-speech.
- Neural voices (Microsoft Edge read-aloud, free, needs internet) with exact word timings for animated captions.
- Offline fallback: voices built into Windows (System.Speech / SAPI), word timings estimated.
"""
import asyncio
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from .media import NO_WINDOW, run_ffmpeg, wav_duration

NEURAL_VOICES = [
    "en-US-AndrewNeural", "en-US-AvaNeural", "en-US-BrianNeural", "en-US-EmmaNeural", "en-US-GuyNeural",
    "en-US-JennyNeural", "en-US-ChristopherNeural", "en-US-AriaNeural", "en-GB-RyanNeural", "en-GB-SoniaNeural",
    "en-IN-PrabhatNeural", "en-IN-NeerjaNeural", "en-AU-WilliamNeural", "hi-IN-MadhurNeural", "hi-IN-SwaraNeural",
]
DEFAULT_VOICE = "en-US-AndrewNeural"
FEMALE = ("Ava", "Emma", "Jenny", "Aria", "Sonia", "Neerja", "Swara", "Zira", "Hazel", "Susan", "Heera")

PS_SYNTH = r"""
param([string]$jobFile)
Add-Type -AssemblyName System.Speech
$items = Get-Content -Raw $jobFile | ConvertFrom-Json
foreach ($it in $items) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  if ($it.voice) { try { $s.SelectVoice($it.voice) } catch {} }
  $s.Rate = [int]$it.rate
  $s.SetOutputToWaveFile($it.path)
  $s.Speak([string]$it.text)
  $s.Dispose()
}
"""


def _ps(args):
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
                          capture_output=True, text=True, creationflags=NO_WINDOW)


@lru_cache(maxsize=1)
def windows_voices() -> tuple[str, ...]:
    p = _ps(["-Command", "Add-Type -AssemblyName System.Speech; "
             "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | % { $_.VoiceInfo.Name }"])
    return tuple(v.strip() for v in p.stdout.splitlines() if v.strip())


def list_voices() -> tuple[str, ...]:
    return tuple(NEURAL_VOICES) + windows_voices()


def is_neural(voice):
    return (voice or DEFAULT_VOICE).endswith("Neural")


def _speech_bounds(path):
    """(first, last) second with audible speech in a wav."""
    import wave

    with wave.open(str(path)) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    x = np.abs(x.reshape(-1, ch).mean(1)) if ch > 1 else np.abs(x)
    hop = max(1, sr // 100)
    env = np.array([x[i:i + hop].mean() for i in range(0, len(x), hop)]) if len(x) else np.zeros(1)
    on = np.where(env > env.max() * 0.06)[0]
    return (on[0] / 100, (on[-1] + 1) / 100) if len(on) else (0, len(x) / sr)


def estimate_words(text, path):
    """Spread words over the spoken part of the audio, weighting by length and punctuation pauses."""
    words = text.split()
    if not words:
        return []
    a, b = _speech_bounds(path)
    weights = np.array([len(re.sub(r"\W", "", w)) + 2 + (4 if re.search(r"[.!?]$", w) else 2 if re.search(r"[,;:]$", w) else 0)
                        for w in words], float)
    edges = a + (b - a) * np.concatenate([[0], np.cumsum(weights) / weights.sum()])
    return [{"word": w, "start": round(float(edges[i]), 3), "end": round(float(edges[i + 1]), 3)} for i, w in enumerate(words)]


async def _neural_one(it):
    import edge_tts

    rate = int(it.get("rate", 0)) * 8
    comm = edge_tts.Communicate(it["text"], it["voice"], rate=f"{rate:+d}%", boundary="WordBoundary")
    mp3 = Path(it["path"]).with_suffix(".mp3")
    words = []
    with open(mp3, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                s = ch["offset"] / 1e7
                words.append({"word": ch["text"], "start": round(s, 3), "end": round(s + ch["duration"] / 1e7, 3)})
    run_ffmpeg(["-i", mp3, "-ar", "44100", "-ac", "2", it["path"]])
    return words


async def _neural_all(items):
    sem = asyncio.Semaphore(4)

    async def one(it):
        async with sem:
            return await _neural_one(it)

    return await asyncio.gather(*(one(it) for it in items))


def _attach_punctuation(text, words):
    """Edge word boundaries drop punctuation; map back to the original tokens for nicer captions."""
    toks = text.split()
    out, j = [], 0
    for w in words:
        while j < len(toks) and re.sub(r"\W", "", toks[j]).lower() == "" :
            j += 1
        if j < len(toks) and re.sub(r"\W", "", w["word"]).lower() in re.sub(r"\W", "", toks[j]).lower():
            out.append({**w, "word": toks[j]})
            j += 1
        else:
            out.append(w)
    return out


def synthesize(items: list[dict], workdir: Path, log=print) -> list[tuple[float, list]]:
    """items: [{text, path(.wav), voice, rate}] -> [(duration, word_timings)] in the same order."""
    if not items:
        return []
    for it in items:
        it["voice"] = it.get("voice") or DEFAULT_VOICE
    neural = [it for it in items if is_neural(it["voice"])]
    sapi = [it for it in items if not is_neural(it["voice"])]
    timings = {}
    if neural:
        try:
            for it, words in zip(neural, asyncio.run(_neural_all(neural))):
                timings[it["path"]] = _attach_punctuation(it["text"], words)
        except Exception as e:
            log(f"Neural voice unavailable ({str(e)[:100]}) - using the offline Windows voice.")
            fallback = next((v for v in windows_voices() if any(f in v for f in FEMALE) == any(f in neural[0]["voice"] for f in FEMALE)), "")
            for it in neural:
                it["voice"] = fallback
            sapi += neural
    if sapi:
        script, job = workdir / "tts.ps1", workdir / "tts.json"
        script.write_text(PS_SYNTH, encoding="utf-8")
        job.write_text(json.dumps(sapi, ensure_ascii=True), encoding="ascii")
        p = _ps(["-File", str(script), str(job)])
        for it in sapi:
            if not Path(it["path"]).exists():
                raise RuntimeError("Voiceover failed: " + (p.stderr or "no audio produced")[-1500:])
            timings[it["path"]] = estimate_words(it["text"], it["path"])
    return [(wav_duration(it["path"]), timings.get(it["path"]) or estimate_words(it["text"], it["path"])) for it in items]
