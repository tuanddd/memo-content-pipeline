import json

from session_kit.correct import apply
from session_kit.runner import Stage, run_pipeline
from session_kit.session import parse_context


def test_context_frontmatter_and_notes():
    ctx = parse_context("---\nspeaker: minh\nshorts: 3\ndate: 2026-09-18\ncustom: x\n---\nAbout Cloudflare.\n")
    assert ctx.speaker == "minh" and ctx.shorts == 3 and ctx.date == "2026-09-18"
    assert ctx.language == "vi" and ctx.notes == "About Cloudflare." and ctx.extra == {"custom": "x"}


def test_stages_skip_when_inputs_are_unchanged_and_rerun_when_forced(session):
    source = session.root / "input" / "source.txt"
    source.write_text("one")
    calls = []

    def build(s):
        calls.append(1)
        (s.dir("analysis") / "out.txt").write_text(source.read_text())

    stage = Stage("build", "analysis", inputs=lambda s: [source], outputs=lambda s: [s.dir("analysis") / "out.txt"], run=build)
    run_pipeline(session, [stage], echo=lambda _: None)
    run_pipeline(session, [stage], echo=lambda _: None)
    assert len(calls) == 1
    source.write_text("two")
    run_pipeline(session, [stage], echo=lambda _: None)
    assert len(calls) == 2
    run_pipeline(session, [stage], start_from="build", echo=lambda _: None)
    assert len(calls) == 3


def test_apply_accepts_fixes_rejects_big_rewrites_and_keeps_failed_chunks_raw(session):
    from conftest import word
    raw = {"language": "vi", "segments": [
        {"id": 0, "start": 0, "end": 2, "text": "cờ lao phờ le guốc cơ", "words": [
            word("cờ", 0, .3), word("lao", .3, .6), word("phờ", .6, .9), word("le", .9, 1.2), word("guốc", 1.2, 1.6), word("cơ", 1.6, 2)]},
        {"id": 1, "start": 2, "end": 4, "text": "một hai ba bốn năm sáu bảy tám", "words": [
            word(w, 2 + i * .25, 2.2 + i * .25) for i, w in enumerate("một hai ba bốn năm sáu bảy tám".split())]},
        {"id": 2, "start": 5, "end": 6, "text": "chưa sửa", "words": [word("chưa", 5, 5.5), word("sửa", 5.5, 6)]},
    ]}
    session.write_json("transcript", "raw.json", raw)
    folder = session.dir("transcript") / "correction"
    folder.mkdir()
    (folder / "in-000-aaa.json").write_text(json.dumps({"segments": [{"id": 0}, {"id": 1}]}))
    (folder / "out-000-aaa.json").write_text(json.dumps({
        "segments": [{"id": 0, "text": "Cloudflare Workers."}, {"id": 1, "text": "Một."}],
        "changes": [{"id": 0, "from": "", "to": "", "reason": "product name"}],
    }))
    (folder / "in-001-bbb.json").write_text(json.dumps({"segments": [{"id": 2}]}))
    report = apply(session)
    assert [c["id"] for c in report["accepted"]] == [0]
    assert report["accepted"][0]["reason"] == "product name"
    assert [c["id"] for c in report["rejected"]] == [1]
    assert report["failed_chunks"] == ["in-001-bbb.json"]
    corrected = {s["id"]: s for s in session.read_json("transcript", "corrected.json")["segments"]}
    assert corrected[0]["text"] == "Cloudflare Workers."
    assert [w["word"] for w in corrected[0]["words"]] == ["Cloudflare", "Workers."]
    assert corrected[1]["text"] == raw["segments"][1]["text"]
    assert corrected[2]["text"] == "chưa sửa"
    assert (session.dir("transcript") / "transcript.srt").read_text().startswith("1\n")
