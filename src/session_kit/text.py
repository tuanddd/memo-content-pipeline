from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

Word = dict[str, Any]

SENTENCE_END = re.compile(r"[.!?…。]+[\"'”’)\]]*$")
CLAUSE_END = re.compile(r"[,;:–—]+[\"'”’)\]]*$")


def normalize_token(token: str) -> str:
    token = unicodedata.normalize("NFC", token).lower()
    return re.sub(r"[^\w]+", "", token)


def all_words(transcript: dict[str, Any]) -> list[Word]:
    words: list[Word] = []
    for segment in transcript["segments"]:
        for w in segment.get("words", []):
            text = w["word"].strip()
            if text:
                words.append({"word": text, "start": float(w["start"]), "end": float(w["end"]), "segment": segment["id"]})
    return words


def sentences(words: list[Word], pause: float = 1.2, max_words: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current: list[Word] = []

    def flush() -> None:
        if current:
            start = current[0]["start"]
            end = max(current[-1]["end"], start + 0.1)
            out.append({"start": round(start, 2), "end": round(end, 2), "text": " ".join(w["word"] for w in current), "words": list(current)})
            current.clear()

    for i, w in enumerate(words):
        if current and w["start"] - current[-1]["end"] > pause:
            flush()
        current.append(w)
        if SENTENCE_END.search(w["word"]) or len(current) >= max_words:
            flush()
    flush()
    return out


def wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for token in text.split():
        candidate = f"{line} {token}".strip()
        if line and len(candidate) > width:
            lines.append(line)
            line = token
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def cues(words: list[Word], max_chars: int = 84, max_seconds: float = 6.0, line_width: int = 42) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current: list[Word] = []

    def flush() -> None:
        if current:
            text = " ".join(w["word"] for w in current)
            out.append({"start": current[0]["start"], "end": max(current[-1]["end"], current[0]["start"] + 0.3), "lines": wrap(text, line_width)})
            current.clear()

    for w in words:
        if current:
            text = " ".join(x["word"] for x in current + [w])
            too_long = len(text) > max_chars
            too_slow = w["end"] - current[0]["start"] > max_seconds
            gap = w["start"] - current[-1]["end"] > 1.0
            if too_long or too_slow or gap:
                flush()
        current.append(w)
        if SENTENCE_END.search(w["word"]):
            flush()
    flush()
    return out


def caption_chunks(words: list[Word], max_chars: int = 20, max_words: int = 4) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    current: list[Word] = []
    for w in words:
        if current:
            text = " ".join(x["word"] for x in current + [w])
            gap = w["start"] - current[-1]["end"] > 0.7
            if len(current) >= max_words or len(text) > max_chars or gap:
                chunks.append(current)
                current = []
        current.append(w)
        if SENTENCE_END.search(w["word"]) or CLAUSE_END.search(w["word"]):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def timestamp(seconds: float, sep: str = ",") -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(items: list[dict[str, Any]]) -> str:
    blocks = []
    for i, c in enumerate(items, 1):
        blocks.append(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n" + "\n".join(c["lines"]))
    return "\n\n".join(blocks) + "\n"


def to_vtt(items: list[dict[str, Any]]) -> str:
    blocks = ["WEBVTT"]
    for c in items:
        blocks.append(f"{timestamp(c['start'], '.')} --> {timestamp(c['end'], '.')}\n" + "\n".join(c["lines"]))
    return "\n\n".join(blocks) + "\n"


def realign(raw: list[Word], corrected_text: str) -> list[Word]:
    tokens = corrected_text.split()
    if not raw:
        return []
    if not tokens:
        return []
    a = [normalize_token(w["word"]) for w in raw]
    b = [normalize_token(t) for t in tokens]
    out: list[Word] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                w = raw[i1 + k]
                out.append({**w, "word": tokens[j1 + k]})
        elif op == "delete":
            continue
        elif op == "replace":
            start = raw[i1]["start"]
            end = raw[i2 - 1]["end"]
            new = tokens[j1:j2]
            weights = [max(1, len(t)) for t in new]
            total = sum(weights)
            cursor = start
            for t, weight in zip(new, weights):
                span = (end - start) * weight / total
                out.append({"word": t, "start": round(cursor, 3), "end": round(cursor + span, 3)})
                cursor += span
        elif op == "insert":
            prev_end = raw[i1 - 1]["end"] if i1 > 0 else raw[0]["start"]
            next_start = raw[i1]["start"] if i1 < len(raw) else raw[-1]["end"]
            if next_start < prev_end:
                next_start = prev_end
            new = tokens[j1:j2]
            step = (next_start - prev_end) / len(new) if next_start > prev_end else 0.0
            for n, t in enumerate(new):
                s = prev_end + step * n
                out.append({"word": t, "start": round(s, 3), "end": round(s + step, 3)})
    last = 0.0
    for w in out:
        w["start"] = max(w["start"], last)
        w["end"] = max(w["end"], w["start"])
        last = w["start"]
    return out
