from conftest import word

from session_kit.text import caption_chunks, cues, realign, sentences, to_srt


def test_realign_keeps_timing_for_unchanged_words_and_spreads_replacements():
    raw = [word("hôm", 0.0, 0.3), word("nay", 0.3, 0.6), word("cờ", 1.0, 1.2), word("lao", 1.2, 1.4),
           word("phờ", 1.4, 1.6), word("le", 1.6, 2.0), word("nhé", 2.1, 2.4)]
    out = realign(raw, "Hôm nay Cloudflare nhé.")
    assert [w["word"] for w in out] == ["Hôm", "nay", "Cloudflare", "nhé."]
    assert out[0]["start"] == 0.0 and out[1]["end"] == 0.6
    assert out[2]["start"] == 1.0 and out[2]["end"] == 2.0
    assert out[3]["start"] == 2.1


def test_realign_places_inserted_words_between_neighbours():
    raw = [word("npx", 0.0, 0.4), word("agentic", 0.8, 1.2)]
    out = realign(raw, "npx is-agentic")
    assert [w["word"] for w in out] == ["npx", "is-agentic"]
    out = realign(raw, "npx really agentic")
    assert [w["word"] for w in out] == ["npx", "really", "agentic"]
    assert 0.4 <= out[1]["start"] <= 0.8
    assert all(w["end"] >= w["start"] for w in out)


def test_realign_drops_deleted_words_and_stays_monotonic():
    raw = [word("a", 0, 1), word("b", 1, 2), word("c", 2, 3)]
    out = realign(raw, "a c")
    assert [w["word"] for w in out] == ["a", "c"]
    assert [w["start"] for w in out] == [0, 2]


def test_sentences_split_on_punctuation_and_long_pauses():
    words = [word("Xin", 0, 0.3), word("chào.", 0.3, 0.6), word("Hôm", 0.8, 1.0), word("nay", 1.0, 1.3),
             word("mình", 3.0, 3.3), word("nói.", 3.3, 3.6)]
    out = sentences(words)
    assert [s["text"] for s in out] == ["Xin chào.", "Hôm nay", "mình nói."]
    assert out[0]["start"] == 0 and out[0]["end"] == 0.6


def test_cues_respect_length_and_render_srt():
    words = [word(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(40)]
    out = cues(words, max_chars=30, max_seconds=6)
    assert all(len(" ".join(c["lines"])) <= 30 for c in out)
    srt = to_srt(out[:1])
    assert srt.startswith("1\n00:00:00,000 --> ")


def test_caption_chunks_stay_short_and_break_on_clauses():
    words = [word("Cái", 0, .2), word("này", .2, .4), word("rất", .4, .6), word("quan", .6, .8),
             word("trọng,", .8, 1.0), word("thật", 1.0, 1.2), word("đấy.", 1.2, 1.4)]
    chunks = caption_chunks(words, max_chars=20, max_words=4)
    assert [len(c) for c in chunks] == [4, 1, 2]
    assert all(len(" ".join(w["word"] for w in c)) <= 20 for c in chunks)


def test_stock_outro_with_low_confidence_is_treated_as_hallucination():
    from session_kit.transcribe import is_hallucination
    words = [word("Cảm", 0, .2, .3), word("ơn", .2, .4, .4)]
    assert is_hallucination({"text": "Cảm ơn các bạn đã theo dõi và hẹn gặp lại."}, words)
    confident = [word("Cảm", 0, .2, .95), word("ơn", .2, .4, .95)]
    assert not is_hallucination({"text": "Cảm ơn các bạn đã theo dõi."}, confident)
    assert is_hallucination({"text": "anything", "no_speech_prob": 0.9, "avg_logprob": -1.2}, confident)
    assert not is_hallucination({"text": "nội dung thật", "no_speech_prob": 0.1, "avg_logprob": -0.2}, confident)


def test_words_crammed_into_a_fraction_of_a_second_are_dropped():
    from session_kit.transcribe import is_hallucination
    crammed = [word(w, 122.12 + i * 0.016, 122.13 + i * 0.016, 0.9) for i, w in enumerate("Cảm ơn các bạn đã theo dõi và hẹn gặp lại.".split())]
    assert is_hallucination({"text": "Cảm ơn các bạn đã theo dõi và hẹn gặp lại."}, crammed)
    normal = [word(w, i * 0.3, i * 0.3 + 0.25, 0.9) for i, w in enumerate("Phần hỏi đáp mình để ở cuối bài viết.".split())]
    assert not is_hallucination({"text": "Phần hỏi đáp mình để ở cuối bài viết."}, normal)


def test_speech_ranges_closer_than_the_gap_are_merged():
    from session_kit.transcribe import merge_ranges
    found = [{"start": 0.5, "end": 4.0}, {"start": 4.6, "end": 9.0}, {"start": 15.0, "end": 20.0}]
    assert merge_ranges(found) == [(0.5, 9.0), (15.0, 20.0)]
    assert merge_ranges([]) == []
