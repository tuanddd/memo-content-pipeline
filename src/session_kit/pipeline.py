from __future__ import annotations

from . import analyze, correct, media, memo, poster, review, shorts, transcribe
from .runner import Stage
from .session import REPO_ROOT, Session


def recipe(*paths: str) -> list:
    return [REPO_ROOT / p for p in paths]


def stages(auto_review: bool) -> list[Stage]:
    return [
        Stage(
            "media", "media",
            inputs=lambda s: [s.video],
            outputs=lambda s: [media.audio_path(s), media.web_path(s), media.probe_path(s)],
            run=media.run_stage,
        ),
        Stage(
            "transcribe", "transcript",
            inputs=lambda s: [media.audio_path(s), s.context.language, s.context.whisper_model, s.glossary()],
            outputs=lambda s: [transcribe.raw_path(s)],
            run=transcribe.run_stage,
        ),
        Stage(
            "correct", "transcript",
            inputs=lambda s: [
                transcribe.raw_path(s), s.context.as_hashable(), s.glossary(), s.context.correction_model,
                recipe("prompts/correct-transcript.md", "schemas/correction.schema.json", "scripts/correct-transcript.sh"),
            ],
            outputs=lambda s: [s.dir("transcript") / n for n in ("corrected.json", "changes.json", "transcript.srt", "transcript.vtt")],
            run=correct.run_stage,
        ),
        Stage(
            "analyze", "analysis",
            inputs=lambda s: [
                s.dir("transcript") / "corrected.json", s.context.as_hashable(), s.context.analysis_model,
                recipe("prompts/analyze.md", "schemas/analysis.schema.json"),
            ],
            outputs=lambda s: [s.dir("analysis") / "analysis.json"],
            run=analyze.run_stage,
        ),
        Stage(
            "review", "review",
            inputs=lambda s: [s.dir("analysis") / "analysis.json", review.approved_path(s)],
            outputs=lambda s: [review.approved_path(s)],
            run=lambda s: review.run_stage(s, auto_review),
        ),
        Stage(
            "poster", "poster",
            inputs=lambda s: [
                review.approved_path(s), s.context.as_hashable(), s.video, media.probe_path(s),
                recipe("templates/poster/poster.html", "assets/brand/logo.svg"),
            ],
            outputs=lambda s: [poster.poster_path(s)],
            run=poster.run_stage,
        ),
        Stage(
            "shorts", "shorts",
            inputs=lambda s: [review.approved_path(s), s.dir("transcript") / "corrected.json", s.video],
            outputs=lambda s: [shorts.index_path(s)],
            run=shorts.run_stage,
        ),
        Stage(
            "memo", "memo",
            inputs=lambda s: [
                review.approved_path(s), s.dir("transcript") / "corrected.json", media.web_path(s),
                poster.poster_path(s), s.context.as_hashable(), s.slug,
            ],
            outputs=lambda s: list(memo.output_names(s).values()),
            run=memo.run_stage,
        ),
    ]


def stage_names() -> list[str]:
    return [s.name for s in stages(False)]


def status(session: Session) -> list[tuple[str, str]]:
    from .runner import is_fresh, state_path

    rows = []
    for stage in stages(False):
        if not state_path(session, stage).exists():
            rows.append((stage.name, "not run"))
        elif is_fresh(session, stage):
            rows.append((stage.name, "up to date"))
        else:
            rows.append((stage.name, "stale"))
    return rows
