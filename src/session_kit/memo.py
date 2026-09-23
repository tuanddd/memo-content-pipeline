from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from .review import load_approval
from .session import Session
from .text import all_words, sentences

TURN_PAUSE = 2.0
TURN_MAX_SENTENCES = 6


def build_turns(sents: list[dict[str, Any]], chapter_starts: list[float], speaker: str) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    boundaries = sorted(chapter_starts)

    def crosses_chapter(prev_end: float, next_start: float) -> bool:
        return any(prev_end <= b <= next_start + 0.01 for b in boundaries if b > 0)

    for s in sents:
        if current:
            prev = current[-1]
            if (
                s["start"] - prev["end"] > TURN_PAUSE
                or len(current) >= TURN_MAX_SENTENCES
                or crosses_chapter(prev["end"], s["start"])
            ):
                turns.append({"speaker": speaker, "sentences": current})
                current = []
        current.append({"start": s["start"], "end": s["end"], "text": s["text"]})
    if current:
        turns.append({"speaker": speaker, "sentences": current})
    return turns


def sidecar(session: Session, slug: str) -> dict[str, Any]:
    approval = load_approval(session)
    corrected = session.read_json("transcript", "corrected.json")
    probe = json.loads((session.dir("media") / "probe.json").read_text())
    duration = round(float(probe["duration"]), 2)
    sents = [s for s in sentences(all_words(corrected)) if s["start"] < duration]
    last_start = -1.0
    for s in sents:
        s["start"] = max(s["start"], last_start)
        s["end"] = min(max(s["end"], s["start"] + 0.1), duration)
        last_start = s["start"]
    chapters = [c for c in approval["chapters"] if 0 <= c["start"] < duration]
    speaker = approval.get("speaker") or session.context.speaker
    return {
        "version": 1,
        "src": f"{slug}.mp4",
        "type": "video/mp4",
        "poster": f"{slug}-poster.jpg",
        "duration": duration,
        "language": session.context.language,
        "chapters": [{"start": c["start"], "title": c["title"]} for c in chapters],
        "transcript": build_turns(sents, [c["start"] for c in chapters], speaker),
    }


def note_draft(session: Session, slug: str) -> str:
    approval = load_approval(session)
    ctx = session.context
    lines = [
        "---",
        f"title: {json.dumps(approval['title'], ensure_ascii=False)}",
        f"description: {json.dumps(approval['subtitle'], ensure_ascii=False)}",
        f"date: {approval.get('date') or ctx.date or ''}",
        "authors:",
        f"  - {approval.get('speaker') or ctx.speaker}",
        "tags:",
        "  - show-and-tell",
        f"recording: assets/{slug}-recording.json",
        "---",
        "",
        approval["subtitle"],
        "",
    ]
    return "\n".join(lines)


def link_or_copy(source: Path, target: Path) -> None:
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def output_names(session: Session) -> dict[str, Path]:
    folder = session.dir("memo")
    slug = session.slug
    return {
        "recording": folder / f"{slug}-recording.json",
        "video": folder / f"{slug}.mp4",
        "poster": folder / f"{slug}-poster.jpg",
        "note": folder / f"{slug}.md",
    }


def run_stage(session: Session) -> None:
    names = output_names(session)
    slug = session.slug
    names["recording"].write_text(json.dumps(sidecar(session, slug), ensure_ascii=False, indent=1), encoding="utf-8")
    link_or_copy(session.dir("media") / "web.mp4", names["video"])
    Image.open(session.dir("poster") / "poster.png").convert("RGB").save(names["poster"], quality=90)
    names["note"].write_text(note_draft(session, slug), encoding="utf-8")
