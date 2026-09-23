from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .session import REPO_ROOT, Session
from .text import all_words, sentences

MIN_SHORT = 15.0
TARGET_SHORT = 20.0
MAX_SHORT = 25.0
LONG_SENTENCE_CAP = 30.0
MIN_CHAPTER = 20.0


def transcript_sentences(session: Session) -> list[dict[str, Any]]:
    corrected = session.read_json("transcript", "corrected.json")
    return sentences(all_words(corrected))


def duration(session: Session) -> float:
    return float(json.loads((session.dir("media") / "probe.json").read_text())["duration"])


def nearest_sentence(sents: list[dict[str, Any]], t: float) -> int:
    for i, s in enumerate(sents):
        if s["start"] <= t < s["end"]:
            return i
    return min(range(len(sents)), key=lambda i: abs(sents[i]["start"] - t))


def snap_chapters(raw: list[dict[str, Any]], sents: list[dict[str, Any]], total: float) -> list[dict[str, Any]]:
    if not sents:
        return []
    starts: dict[float, str] = {}
    for c in sorted(raw, key=lambda c: c["start"]):
        title = " ".join(str(c.get("title", "")).split())
        if not title or not 0 <= c["start"] < total:
            continue
        t = sents[nearest_sentence(sents, c["start"])]["start"]
        starts.setdefault(t, title)
    ordered = sorted(starts.items())
    if not ordered:
        return []
    ordered[0] = (0.0, ordered[0][1])
    kept: list[tuple[float, str]] = []
    for t, title in ordered:
        if kept and t - kept[-1][0] < MIN_CHAPTER:
            continue
        kept.append((t, title))
    return [{"start": round(t, 2), "title": title} for t, title in kept]


def snap_highlight(h: dict[str, Any], sents: list[dict[str, Any]]) -> tuple[float, float] | None:
    i = nearest_sentence(sents, float(h["start"]))
    start = sents[i]["start"]
    best: tuple[float, float] | None = None
    for j in range(i, len(sents)):
        length = sents[j]["end"] - start
        if length > MAX_SHORT:
            if j == i and length <= LONG_SENTENCE_CAP:
                best = (start, sents[j]["end"])
            break
        if length >= MIN_SHORT and (best is None or abs(length - TARGET_SHORT) < abs(best[1] - best[0] - TARGET_SHORT)):
            best = (start, sents[j]["end"])
    return best


def snap_highlights(raw: list[dict[str, Any]], sents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in sorted(raw, key=lambda h: -float(h.get("score", 0))):
        span = snap_highlight(h, sents) if sents else None
        if not span:
            continue
        if any(span[0] < o["end"] and o["start"] < span[1] for o in out):
            continue
        out.append({
            "start": round(span[0], 2),
            "end": round(span[1], 2),
            "hook": " ".join(str(h.get("hook", "")).split()),
            "why": h.get("why", ""),
            "score": float(h.get("score", 0)),
        })
    for n, h in enumerate(out, 1):
        h["id"] = n
    return out


def build_input(session: Session, sents: list[dict[str, Any]]) -> dict[str, Any]:
    ctx = session.context
    return {
        "language": ctx.language,
        "context": {"title": ctx.title, "speaker": ctx.speaker, "series": ctx.series, "notes": ctx.notes},
        "duration": round(duration(session), 2),
        "sentences": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in sents],
    }


def call_claude(payload: dict[str, Any], model: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        path = Path(fh.name)
    try:
        with path.open("rb") as stdin:
            result = subprocess.run(
                [str(REPO_ROOT / "scripts" / "claude-json.sh"), str(REPO_ROOT / "schemas" / "analysis.schema.json"),
                 str(REPO_ROOT / "prompts" / "analyze.md"), model],
                stdin=stdin, capture_output=True, text=True,
            )
    finally:
        path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"analysis call failed: {result.stderr.strip()[-600:]}")
    return json.loads(result.stdout)


def run_stage(session: Session) -> None:
    sents = transcript_sentences(session)
    if not sents:
        raise RuntimeError("the corrected transcript has no sentences")
    total = duration(session)
    raw = call_claude(build_input(session, sents), session.context.analysis_model)
    session.write_json("analysis", "raw-response.json", raw)
    analysis = {
        "title": " ".join(raw["title"].split()),
        "subtitle": " ".join(raw["subtitle"].split()),
        "chapters": snap_chapters(raw["chapters"], sents, total),
        "highlights": snap_highlights(raw["highlights"], sents),
    }
    session.write_json("analysis", "analysis.json", analysis)
