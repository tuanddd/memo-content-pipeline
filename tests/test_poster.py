from pathlib import Path

import pytest

from session_kit import poster
from session_kit.media import run


@pytest.fixture
def ready(session):
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x17181c:s=1280x720", "-frames:v", "1", str(session.dir("poster") / "frame.jpg")])
    return session


def approve(session, title, subtitle="Một câu mô tả ngắn."):
    session.write_json("review", "approved.json", {
        "title": title, "subtitle": subtitle, "speaker": "tieubao", "date": "2026-09-18",
        "chapters": [{"start": 0, "title": "a"}], "highlights": [], "poster_frame": 1,
    })


def render(session):
    page = session.dir("poster") / "poster.html"
    page.write_text(poster.build_html(session, session.dir("poster") / "frame.jpg"), encoding="utf-8")
    return poster.render(page, session.dir("poster") / "poster.png")


def test_vietnamese_title_with_stacked_diacritics_fits(ready):
    approve(ready, "Làm memo thân thiện với AI agent: từ 50 lên 93")
    assert render(ready) == []
    assert (ready.dir("poster") / "poster.png").stat().st_size > 10_000


def test_a_title_longer_than_three_lines_is_reported(ready):
    approve(ready, "Một tiêu đề rất rất dài " * 8)
    assert "title" in render(ready)
