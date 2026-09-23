import json

from conftest import word

from session_kit.memo import build_turns, sidecar


def test_turns_break_on_pause_chapter_and_size():
    s = [{"start": i * 3.0, "end": i * 3.0 + 2.5, "text": f"s{i}."} for i in range(10)]
    s[4] = {"start": 20.0, "end": 22.0, "text": "after pause."}
    for i in range(5, 10):
        s[i] = {"start": 22.5 + (i - 5) * 3, "end": 22.5 + (i - 5) * 3 + 2.5, "text": f"s{i}."}
    turns = build_turns(s, [0, 25.5], "Speaker")
    assert all(t["speaker"] == "Speaker" for t in turns)
    assert [len(t["sentences"]) for t in turns] == [4, 2, 4]


def test_sidecar_matches_the_memo_contract(session):
    corrected = {"language": "vi", "segments": [
        {"id": 0, "start": 0.5, "end": 3.0, "text": "Xin chào mọi người.",
         "words": [word("Xin", .5, .8), word("chào", .8, 1.1), word("mọi", 1.1, 1.5), word("người.", 1.5, 3.0)]},
        {"id": 1, "start": 40.0, "end": 44.0, "text": "Phần hai.",
         "words": [word("Phần", 40, 41), word("hai.", 41, 44)]},
    ]}
    session.write_json("transcript", "corrected.json", corrected)
    session.write_json("review", "approved.json", {
        "title": "T", "subtitle": "S", "speaker": "tieubao", "date": "2026-09-18",
        "chapters": [{"start": 0, "title": "Mở đầu"}, {"start": 40, "title": "Phần hai"}],
        "highlights": [], "poster_frame": 10,
    })
    data = sidecar(session, "demo")
    assert data["version"] == 1 and data["src"] == "demo.mp4" and data["type"] == "video/mp4"
    assert data["duration"] == 120.0 and data["language"] == "vi"
    assert [c["title"] for c in data["chapters"]] == ["Mở đầu", "Phần hai"]
    flat = [s for t in data["transcript"] for s in t["sentences"]]
    assert [s["text"] for s in flat] == ["Xin chào mọi người.", "Phần hai."]
    assert all(s["end"] > s["start"] for s in flat)
    assert [s["start"] for s in flat] == sorted(s["start"] for s in flat)
    assert len(data["transcript"]) == 2
    json.dumps(data, ensure_ascii=False)
