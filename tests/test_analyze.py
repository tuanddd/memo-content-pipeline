from session_kit.analyze import snap_chapters, snap_highlights


def sents(n=30, length=5.0, gap=0.5):
    out, t = [], 0.0
    for i in range(n):
        out.append({"start": round(t, 2), "end": round(t + length, 2), "text": f"s{i}."})
        t += length + gap
    return out


def test_highlights_snap_to_sentences_and_last_15_to_25_seconds():
    s = sents()
    out = snap_highlights([{"start": 12.0, "end": 40.0, "hook": "A", "why": "", "score": 9}], s)
    assert len(out) == 1
    h = out[0]
    assert h["start"] in {x["start"] for x in s}
    assert h["end"] in {x["end"] for x in s}
    assert 15 <= h["end"] - h["start"] <= 25


def test_overlapping_highlights_keep_the_higher_score():
    s = sents()
    out = snap_highlights([
        {"start": 11.0, "end": 30, "hook": "low", "why": "", "score": 3},
        {"start": 12.0, "end": 30, "hook": "high", "why": "", "score": 9},
        {"start": 90.0, "end": 110, "hook": "other", "why": "", "score": 5},
    ], s)
    assert [h["hook"] for h in out] == ["high", "other"]
    assert [h["id"] for h in out] == [1, 2]


def test_chapters_start_at_zero_snap_and_drop_tiny_ones():
    s = sents()
    out = snap_chapters([
        {"start": 3, "title": "Intro"},
        {"start": 34, "title": "Main"},
        {"start": 40, "title": "Too close"},
        {"start": 500, "title": "Past the end"},
    ], s, total=165)
    assert out[0] == {"start": 0.0, "title": "Intro"}
    assert [c["title"] for c in out] == ["Intro", "Main"]
    assert out[1]["start"] in {x["start"] for x in s}
