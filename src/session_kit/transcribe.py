from __future__ import annotations

import wave
from pathlib import Path

from .media import audio_path
from .session import Session


def raw_path(session: Session) -> Path:
    return session.dir("transcript") / "raw.json"


MAX_WORDS_PER_SECOND = 8.0
VAD_MIN_SILENCE_MS = 500
VAD_PAD_MS = 200
MERGE_GAP = 1.0

KNOWN_HALLUCINATIONS = (
    "cảm ơn các bạn đã theo dõi",
    "hẹn gặp lại các bạn",
    "hãy subscribe",
    "đăng ký kênh",
    "thanks for watching",
    "please subscribe",
)


def is_hallucination(segment: dict, words: list[dict]) -> bool:
    text = segment.get("text", "").lower()
    avg_probability = sum(w["probability"] for w in words) / len(words)
    silent = segment.get("no_speech_prob", 0.0) > 0.5 and segment.get("avg_logprob", 0.0) < -0.8
    stock_phrase = any(p in text for p in KNOWN_HALLUCINATIONS) and avg_probability < 0.75
    span = words[-1]["end"] - words[0]["start"]
    too_fast = len(words) >= 3 and len(words) / max(span, 0.01) > MAX_WORDS_PER_SECOND
    return silent or stock_phrase or too_fast


def initial_prompt(terms: list[str], limit: int = 600) -> str | None:
    if not terms:
        return None
    text = ", ".join(terms)
    return text[:limit]


def merge_ranges(ranges: list[dict], gap: float = MERGE_GAP) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for r in ranges:
        start, end = float(r["start"]), float(r["end"])
        if merged and start - merged[-1][1] < gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def speech_ranges(path: Path) -> list[tuple[float, float]]:
    import numpy as np
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    audio = torch.from_numpy(pcm.astype(np.float32) / 32768.0)
    found = get_speech_timestamps(
        audio,
        load_silero_vad(),
        sampling_rate=rate,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_PAD_MS,
        return_seconds=True,
    )
    return merge_ranges(found)


def run_stage(session: Session) -> None:
    import mlx_whisper

    ctx = session.context
    ranges = speech_ranges(audio_path(session)) if ctx.vad else []
    if ctx.vad and not ranges:
        raise RuntimeError("voice activity detection found no speech in the audio")
    clips = [t for r in ranges for t in r] if ranges else "0"
    result = mlx_whisper.transcribe(
        str(audio_path(session)),
        path_or_hf_repo=ctx.whisper_model,
        language=ctx.language,
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt(session.glossary()),
        clip_timestamps=clips,
        verbose=None,
    )
    segments = []
    dropped = []
    for i, seg in enumerate(result.get("segments", [])):
        words = [
            {
                "word": w["word"].strip(),
                "start": round(float(w["start"]), 3),
                "end": round(float(w["end"]), 3),
                "probability": round(float(w.get("probability", 1.0)), 3),
            }
            for w in seg.get("words", [])
            if w["word"].strip()
        ]
        if not words:
            continue
        if is_hallucination(seg, words):
            dropped.append({"start": words[0]["start"], "text": " ".join(w["word"] for w in words),
                            "no_speech_prob": round(float(seg.get("no_speech_prob", 0)), 3),
                            "avg_logprob": round(float(seg.get("avg_logprob", 0)), 3)})
            continue
        segments.append({
            "id": len(segments),
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": " ".join(w["word"] for w in words),
            "words": words,
        })
    session.write_json("transcript", "raw.json", {
        "language": result.get("language", ctx.language),
        "model": ctx.whisper_model,
        "speech": [[round(a, 3), round(b, 3)] for a, b in ranges],
        "segments": segments,
        "dropped": dropped,
    })
    if dropped:
        session.log(f"transcribe: dropped {len(dropped)} likely hallucinated segment(s): " + "; ".join(d["text"] for d in dropped))
