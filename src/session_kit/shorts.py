from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .media import run
from .review import load_approval
from .session import REPO_ROOT, Session, slugify
from .text import Word, all_words, caption_chunks, to_srt

W, H = 1080, 1920
FONTS = REPO_ROOT / "assets" / "fonts"
BRAND = (225, 63, 94, 255)
INK = (35, 37, 44, 235)
CAPTION_SIZE = 70
CAPTION_CENTER_Y = 1330
CAPTION_MAX_WIDTH = 900
HOOK_SIZE = 50
HOOK_TOP = 250
HOOK_MAX_WIDTH = 860


def ascii_slug(text: str, limit: int = 40) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return (slugify(text) or "short")[:limit].strip("-")


def font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"IBMPlexSans-{weight}.ttf"), size)


def layout_lines(draw: ImageDraw.ImageDraw, words: list[str], face: ImageFont.FreeTypeFont, max_width: int) -> list[list[int]]:
    space = draw.textlength(" ", font=face)
    lines: list[list[int]] = [[]]
    width = 0.0
    for i, w in enumerate(words):
        wl = draw.textlength(w, font=face)
        extra = wl if not lines[-1] else width + space + wl
        if lines[-1] and extra > max_width:
            lines.append([i])
            width = wl
        else:
            lines[-1].append(i)
            width = extra
    return lines


def hook_layer(hook: str) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not hook:
        return img
    draw = ImageDraw.Draw(img)
    face = font(HOOK_SIZE, 600)
    words = unicodedata.normalize("NFC", hook).split()
    lines = layout_lines(draw, words, face, HOOK_MAX_WIDTH)[:3]
    line_h = int(HOOK_SIZE * 1.3)
    pad_x, pad_y = 30, 22
    texts = [" ".join(words[i] for i in line) for line in lines]
    box_w = int(max(draw.textlength(t, font=face) for t in texts)) + pad_x * 2
    box_h = line_h * len(texts) + pad_y * 2
    x0 = (W - box_w) // 2
    draw.rounded_rectangle((x0, HOOK_TOP, x0 + box_w, HOOK_TOP + box_h), radius=10, fill=INK)
    draw.rectangle((x0, HOOK_TOP, x0 + 8, HOOK_TOP + box_h), fill=BRAND)
    for n, t in enumerate(texts):
        tw = draw.textlength(t, font=face)
        draw.text(((W - tw) / 2 + 4, HOOK_TOP + pad_y + n * line_h), t, font=face, fill=(255, 255, 255, 255))
    return img


def caption_frame(base: Image.Image, words: list[str], active: int) -> Image.Image:
    img = base.copy()
    draw = ImageDraw.Draw(img)
    face = font(CAPTION_SIZE, 700)
    lines = layout_lines(draw, words, face, CAPTION_MAX_WIDTH)
    space = draw.textlength(" ", font=face)
    line_h = int(CAPTION_SIZE * 1.28)
    top = CAPTION_CENTER_Y - line_h * len(lines) // 2
    ascent, descent = face.getmetrics()
    for n, line in enumerate(lines):
        widths = [draw.textlength(words[i], font=face) for i in line]
        x = (W - (sum(widths) + space * (len(line) - 1))) / 2
        y = top + n * line_h
        for i, wl in zip(line, widths):
            if i == active:
                draw.rounded_rectangle((x - 12, y - 4, x + wl + 12, y + ascent + descent - 2), radius=10, fill=BRAND)
                draw.text((x, y), words[i], font=face, fill=(255, 255, 255, 255))
            else:
                draw.text((x, y), words[i], font=face, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 200))
            x += wl + space
    return img


def clip_words(words: list[Word], start: float, end: float) -> list[Word]:
    out = []
    for w in words:
        if w["start"] >= start - 0.05 and w["end"] <= end + 0.3 and w["start"] < end:
            out.append({"word": unicodedata.normalize("NFC", w["word"]), "start": max(0.0, w["start"] - start), "end": min(end - start, w["end"] - start)})
    return out


def caption_timeline(words: list[Word], length: float) -> list[tuple[list[str], int, float, float]]:
    states: list[tuple[list[str], int, float, float]] = []
    chunks = caption_chunks(words)
    for c, chunk in enumerate(chunks):
        texts = [w["word"] for w in chunk]
        chunk_end = chunk[-1]["end"] + 0.25
        if c + 1 < len(chunks):
            chunk_end = min(max(chunk_end, chunk[-1]["end"]), chunks[c + 1][0]["start"])
        chunk_end = min(chunk_end, length)
        for k, w in enumerate(chunk):
            s = w["start"]
            e = chunk[k + 1]["start"] if k + 1 < len(chunk) else chunk_end
            if e - s > 0.02:
                states.append((texts, k, s, e))
    return states


def render_short(session: Session, video: Path, h: dict[str, Any], words: list[Word], target: Path) -> dict[str, Any]:
    start, end = float(h["start"]), float(h["end"])
    length = end - start
    local = clip_words(words, start, end)
    work = target.parent / f".{target.stem}"
    work.mkdir(exist_ok=True)
    for stale in work.glob("*.png"):
        stale.unlink()
    base = hook_layer(h.get("hook", ""))
    blank = work / "blank.png"
    base.save(blank)

    entries: list[tuple[Path, float]] = []
    cursor = 0.0
    for n, (texts, active, s, e) in enumerate(caption_timeline(local, length)):
        if s > cursor + 0.02:
            entries.append((blank, s - cursor))
        frame = work / f"c{n:04d}.png"
        caption_frame(base, texts, active).save(frame)
        entries.append((frame, e - s))
        cursor = e
    if cursor < length:
        entries.append((blank, length - cursor))
    listing = work / "captions.txt"
    lines = []
    for path, dur in entries:
        lines.append(f"file '{path.as_posix()}'\nduration {dur:.3f}")
    lines.append(f"file '{entries[-1][0].as_posix()}'")
    listing.write_text("\n".join(lines) + "\n")

    run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(video),
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-filter_complex",
        "[0:v]crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1,fps=30[v];"
        "[1:v]format=rgba[c];[v][c]overlay=0:0:eof_action=repeat[out]",
        "-map", "[out]", "-map", "0:a?",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{length:.3f}",
        str(target),
    ])

    cues = [
        {"start": chunk[0]["start"], "end": chunk[-1]["end"], "lines": [" ".join(w["word"] for w in chunk)]}
        for chunk in caption_chunks(local)
    ]
    target.with_suffix(".srt").write_text(to_srt(cues), encoding="utf-8")
    for stale in work.glob("*"):
        stale.unlink()
    work.rmdir()
    return {"file": target.name, "hook": h.get("hook", ""), "start": start, "end": end, "seconds": round(length, 2)}


def index_path(session: Session) -> Path:
    return session.dir("shorts") / "index.json"


def run_stage(session: Session) -> None:
    approval = load_approval(session)
    words = all_words(session.read_json("transcript", "corrected.json"))
    folder = session.dir("shorts")
    for stale in list(folder.glob("*.mp4")) + list(folder.glob("*.srt")):
        stale.unlink()
    picked = [h for h in approval["highlights"] if h.get("approved")]
    made = []
    for n, h in enumerate(picked, 1):
        target = folder / f"{n:02d}-{ascii_slug(h.get('hook', ''))}.mp4"
        made.append(render_short(session, session.video, h, words, target))
    index_path(session).write_text(json.dumps(made, ensure_ascii=False, indent=1), encoding="utf-8")
