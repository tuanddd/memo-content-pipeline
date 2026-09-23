from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import correct, pipeline, review
from .runner import ReviewPending, run_pipeline
from .session import DIRS, Session, create_session, slugify

DEFAULT_ROOT = Path(os.environ.get("SESSION_KIT_ROOT", Path.home() / "Sessions"))


def resolve(value: str) -> Session:
    path = Path(value).expanduser()
    if not path.exists():
        path = DEFAULT_ROOT / value
    return Session(path)


def cmd_new(args: argparse.Namespace) -> int:
    video = Path(args.video).expanduser().resolve()
    name = args.name or f"{date.today().isoformat()}-{slugify(video.stem) or 'session'}"
    session = create_session(video, Path(args.context).expanduser() if args.context else None, Path(args.root).expanduser(), name)
    print(f"Created {session.root}")
    if not args.context:
        print(f"Next: edit {session.context_path}, then run: session-kit run {session.root.name}")
    else:
        print(f"Next: session-kit run {session.root.name}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    session = resolve(args.session)
    try:
        run_pipeline(session, pipeline.stages(args.no_review), start_from=args.start_from, only=args.only)
    except ReviewPending as pending:
        print(f"\nPaused before rendering: {pending}.")
        print(f"Next: session-kit review {session.root.name}, save, then run again.")
        return 3
    except Exception as error:
        session.log(f"error: {error}")
        print(f"\nStopped: {error}", file=sys.stderr)
        return 1
    memo_dir = session.root / DIRS["memo"]
    print(f"\nDone. Memo bundle: {memo_dir}")
    print(f"Shorts: {session.root / DIRS['shorts']}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    session = resolve(args.session)
    if not (session.root / DIRS["analysis"] / "analysis.json").exists():
        print("Nothing to review yet. Run the pipeline first; it stops at the review step.", file=sys.stderr)
        return 1
    review.serve(session, args.port, not args.no_open)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    session = resolve(args.session)
    for name, state in pipeline.status(session):
        print(f"  {name:<10} {state}")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    session = resolve(args.session)
    removed = 0
    targets = [
        session.root / DIRS["media"] / "audio-16k.wav",
        session.root / DIRS["poster"] / "poster.html",
        session.root / DIRS["poster"] / "frame.jpg",
    ]
    targets += list((session.root / DIRS["transcript"] / "correction").glob("*.json"))
    for path in targets:
        if path.exists():
            removed += path.stat().st_size
            path.unlink()
    print(f"Freed {removed / 1_048_576:.1f} MB. Inputs, transcripts, shorts and the memo bundle are kept.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="session-kit", description="Turn a session recording into a poster, transcript, shorts and a memo bundle.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create a session folder from a video")
    p.add_argument("video")
    p.add_argument("--context", help="context.md with frontmatter and notes")
    p.add_argument("--name", help="session folder name; defaults to <date>-<video name>")
    p.add_argument("--root", default=str(DEFAULT_ROOT), help=f"where sessions live (default {DEFAULT_ROOT})")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("run", help="run every stage whose inputs changed")
    p.add_argument("session")
    p.add_argument("--from", dest="start_from", choices=pipeline.stage_names(), help="rerun this stage and everything after it")
    p.add_argument("--only", choices=pipeline.stage_names(), help="run just this stage")
    p.add_argument("--no-review", action="store_true", help="approve the model's picks without the review page")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("review", help="open the local review page")
    p.add_argument("session")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("status", help="show which stages are done")
    p.add_argument("session")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("clean", help="delete intermediates that can be regenerated")
    p.add_argument("session")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("_correct-prepare")
    p.add_argument("session")
    p.set_defaults(func=lambda a: (correct.prepare(resolve(a.session)), 0)[1])

    p = sub.add_parser("_correct-apply")
    p.add_argument("session")
    p.set_defaults(func=lambda a: (correct.apply(resolve(a.session)), 0)[1])

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
