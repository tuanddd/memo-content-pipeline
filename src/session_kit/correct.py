from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .session import REPO_ROOT, Session
from .text import all_words, cues, realign, to_srt, to_vtt

CHUNK_SIZE = int(os.environ.get("SESSION_KIT_CHUNK", "120"))
OVERLAP = 5
SUSPECT_BELOW = 0.5
MIN_RATIO = 0.6
MAX_RATIO = 1.6


def work_dir(session: Session) -> Path:
    path = session.dir("transcript") / "correction"
    path.mkdir(exist_ok=True)
    return path


def prepare(session: Session) -> list[Path]:
    raw = session.read_json("transcript", "raw.json")
    ctx = session.context
    segments = raw["segments"]
    folder = work_dir(session)
    recipe = "".join(
        (REPO_ROOT / rel).read_text(encoding="utf-8")
        for rel in ("prompts/correct-transcript.md", "schemas/correction.schema.json")
    ) + ctx.correction_model
    written = []
    for n, start in enumerate(range(0, len(segments), CHUNK_SIZE)):
        chunk = segments[start:start + CHUNK_SIZE]
        before = segments[max(0, start - OVERLAP):start]
        payload = {
            "language": raw.get("language", ctx.language),
            "context": {"title": ctx.title, "speaker": ctx.speaker, "notes": ctx.notes},
            "glossary": session.glossary(),
            "before": [{"id": s["id"], "text": s["text"]} for s in before],
            "segments": [
                {
                    "id": s["id"],
                    "text": s["text"],
                    "suspects": [w["word"] for w in s["words"] if w.get("probability", 1) < SUSPECT_BELOW],
                }
                for s in chunk
            ],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=1)
        digest = hashlib.sha256((body + recipe).encode("utf-8")).hexdigest()[:12]
        path = folder / f"in-{n:03d}-{digest}.json"
        path.write_text(body, encoding="utf-8")
        written.append(path)
    keep = {p.name for p in written} | {p.name.replace("in-", "out-", 1) for p in written}
    for stale in folder.glob("*.json"):
        if stale.name not in keep:
            stale.unlink()
    return written


def chunk_result(folder: Path, name: str) -> dict[str, Any] | None:
    path = folder / name.replace("in-", "out-", 1)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("segments"), list) else None


def apply(session: Session) -> dict[str, Any]:
    raw = session.read_json("transcript", "raw.json")
    folder = work_dir(session)
    by_id = {s["id"]: s for s in raw["segments"]}
    fixed: dict[int, str] = {}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    failed: list[str] = []

    for path in sorted(folder.glob("in-*.json")):
        expected = {s["id"] for s in json.loads(path.read_text(encoding="utf-8"))["segments"]}
        result = chunk_result(folder, path.name)
        returned = {s.get("id") for s in result["segments"]} if result else set()
        if not result or returned != expected:
            failed.append(path.name)
            continue
        reasons = {c.get("id"): c for c in result.get("changes", []) if isinstance(c, dict)}
        for seg in result["segments"]:
            sid = seg["id"]
            before = by_id[sid]["text"]
            after = " ".join(str(seg.get("text", "")).split())
            if not after or after == before:
                continue
            ratio = len(after) / max(1, len(before))
            entry = {"id": sid, "start": by_id[sid]["start"], "from": before, "to": after, "reason": reasons.get(sid, {}).get("reason", "")}
            if ratio < MIN_RATIO or ratio > MAX_RATIO:
                rejected.append({**entry, "why": f"length changed to {ratio:.0%} of the original"})
                continue
            fixed[sid] = after
            accepted.append(entry)

    segments = []
    for seg in raw["segments"]:
        text = fixed.get(seg["id"], seg["text"])
        words = realign(seg["words"], text) if seg["id"] in fixed else [dict(w) for w in seg["words"]]
        if not words:
            continue
        segments.append({"id": seg["id"], "start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})

    corrected = {"language": raw.get("language"), "segments": segments}
    session.write_json("transcript", "corrected.json", corrected)
    report = {"accepted": accepted, "rejected": rejected, "failed_chunks": failed}
    session.write_json("transcript", "changes.json", report)
    write_subtitles(session, corrected)
    return report


def write_subtitles(session: Session, transcript: dict[str, Any]) -> None:
    items = cues(all_words(transcript))
    folder = session.dir("transcript")
    (folder / "transcript.srt").write_text(to_srt(items), encoding="utf-8")
    (folder / "transcript.vtt").write_text(to_vtt(items), encoding="utf-8")


def run_stage(session: Session) -> None:
    script = REPO_ROOT / "scripts" / "correct-transcript.sh"
    env = {**os.environ, "SESSION_KIT_MODEL": session.context.correction_model}
    result = subprocess.run(["bash", str(script), str(session.root)], env=env)
    if result.returncode != 0:
        raise RuntimeError(f"correct-transcript.sh exited {result.returncode}; see {session.root / 'run.log'}")
    report = session.read_json("transcript", "changes.json")
    session.log(
        f"correction: {len(report['accepted'])} accepted, {len(report['rejected'])} rejected, "
        f"{len(report['failed_chunks'])} chunks kept raw"
    )
