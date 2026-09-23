from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".mkv", ".webm")

DIRS = {
    "input": "input",
    "media": "01-media",
    "transcript": "02-transcript",
    "analysis": "03-analysis",
    "review": "04-review",
    "poster": "05-poster",
    "shorts": "06-shorts",
    "memo": "07-memo",
}


@dataclass
class Context:
    title: str | None = None
    speaker: str = "Speaker"
    date: str | None = None
    language: str = "vi"
    shorts: int = 5
    series: str = "Show & Tell"
    whisper_model: str = "mlx-community/whisper-large-v3-mlx"
    vad: bool = True
    correction_model: str = "sonnet"
    analysis_model: str = "opus"
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_hashable(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "speaker": self.speaker,
            "date": self.date,
            "language": self.language,
            "shorts": self.shorts,
            "series": self.series,
            "notes": self.notes,
        }


def parse_context(text: str) -> Context:
    meta: dict[str, Any] = {}
    body = text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        body = match.group(2)
    if not isinstance(meta, dict):
        raise ValueError("context.md frontmatter must be a mapping")
    known = {f for f in Context.__dataclass_fields__} - {"notes", "extra"}
    ctx = Context(**{k: v for k, v in meta.items() if k in known})
    ctx.date = str(ctx.date) if ctx.date is not None else None
    ctx.shorts = int(ctx.shorts)
    ctx.notes = body.strip()
    ctx.extra = {k: v for k, v in meta.items() if k not in known}
    return ctx


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9\s_-]", "", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


class Session:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not (self.root / DIRS["input"]).is_dir():
            raise FileNotFoundError(f"{self.root} is not a session folder (no input/)")

    def dir(self, key: str) -> Path:
        path = self.root / DIRS[key]
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def slug(self) -> str:
        return slugify(self.root.name) or "session"

    @property
    def video(self) -> Path:
        for ext in VIDEO_EXTENSIONS:
            candidate = self.root / DIRS["input"] / f"video{ext}"
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"no input/video.* in {self.root}")

    @property
    def context_path(self) -> Path:
        return self.root / DIRS["input"] / "context.md"

    @property
    def context(self) -> Context:
        if not self.context_path.exists():
            return Context()
        return parse_context(self.context_path.read_text(encoding="utf-8"))

    def glossary(self) -> list[str]:
        terms: list[str] = []
        sources = sorted((REPO_ROOT / "glossary").glob("*.txt")) + [
            self.root / DIRS["input"] / "glossary.txt"
        ]
        for path in sources:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    terms.append(line)
        return list(dict.fromkeys(terms))

    def read_json(self, key: str, name: str) -> Any:
        return json.loads((self.dir(key) / name).read_text(encoding="utf-8"))

    def write_json(self, key: str, name: str, data: Any) -> Path:
        path = self.dir(key) / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def log(self, message: str) -> None:
        with (self.root / "run.log").open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip() + "\n")


def create_session(video: Path, context: Path | None, root: Path, name: str) -> Session:
    if video.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(f"unsupported video type {video.suffix}")
    target = root / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    (target / DIRS["input"]).mkdir(parents=True)
    shutil.copy2(video, target / DIRS["input"] / f"video{video.suffix.lower()}")
    if context:
        shutil.copy2(context, target / DIRS["input"] / "context.md")
    else:
        (target / DIRS["input"] / "context.md").write_text(
            "---\nspeaker: Speaker\nlanguage: vi\nshorts: 5\n---\n\n"
            "Describe the session here: topic, people, product names, anything the transcript might mishear.\n",
            encoding="utf-8",
        )
    return Session(target)
