from session_kit import poster


def approve(session, title, subtitle="Một câu mô tả ngắn."):
    session.write_json("review", "approved.json", {
        "title": title, "subtitle": subtitle, "speaker": "tieubao", "date": "2026-09-18",
        "chapters": [{"start": 0, "title": "a"}], "highlights": [],
    })


def render(session):
    page = session.dir("poster") / "poster.html"
    page.write_text(poster.build_html(session), encoding="utf-8")
    return poster.render(page, session.dir("poster") / "poster.png")


def test_vietnamese_title_with_stacked_diacritics_fits(session):
    approve(session, "Làm memo thân thiện với AI agent: từ 50 lên 93")
    assert render(session) == []
    assert (session.dir("poster") / "poster.png").stat().st_size > 10_000


def test_a_title_longer_than_three_lines_is_reported(session):
    approve(session, "Một tiêu đề rất rất dài " * 8)
    assert "title" in render(session)
