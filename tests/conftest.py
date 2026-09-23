import json
from pathlib import Path

import pytest

from session_kit.session import Session


def word(text, start, end, probability=0.9):
    return {"word": text, "start": start, "end": end, "probability": probability}


@pytest.fixture
def session(tmp_path: Path) -> Session:
    root = tmp_path / "2026-09-23-demo"
    (root / "input").mkdir(parents=True)
    (root / "input" / "video.mp4").write_bytes(b"not really a video")
    (root / "input" / "context.md").write_text(
        "---\ntitle: Demo\nspeaker: tieubao\nlanguage: vi\nshorts: 2\n---\nNotes about the demo.\n",
        encoding="utf-8",
    )
    s = Session(root)
    (s.dir("media") / "probe.json").write_text(json.dumps({"duration": 120.0}))
    return s
