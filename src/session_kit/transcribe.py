from __future__ import annotations

from pathlib import Path

from .media import audio_path
from .session import Session


def raw_path(session: Session) -> Path:
    return session.dir("transcript") / "raw.json"


MAX_WORDS_PER_SECOND = 8.0

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


def run_stage(session: Session) -> None:
    import mlx_whisper

    ctx = session.context
    result = mlx_whisper.transcribe(
        str(audio_path(session)),
        path_or_hf_repo=ctx.whisper_model,
        language=ctx.language,
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt(session.glossary()),
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
        "segments": segments,
        "dropped": dropped,
    })
    if dropped:
        session.log(f"transcribe: dropped {len(dropped)} likely hallucinated segment(s): " + "; ".join(d["text"] for d in dropped))
