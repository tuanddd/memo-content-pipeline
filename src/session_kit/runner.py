from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .session import Session

LARGE_FILE = 64 * 1024 * 1024


class ReviewPending(Exception):
    pass


@dataclass
class Stage:
    name: str
    folder: str
    inputs: Callable[[Session], list[Any]]
    outputs: Callable[[Session], list[Path]]
    run: Callable[[Session], None]


def fingerprint(value: Any) -> Any:
    if isinstance(value, Path):
        if not value.exists():
            return {"missing": str(value)}
        stat = value.stat()
        if stat.st_size > LARGE_FILE:
            return {"file": value.name, "size": stat.st_size, "mtime": int(stat.st_mtime)}
        return {"file": value.name, "sha256": hashlib.sha256(value.read_bytes()).hexdigest()}
    if isinstance(value, dict):
        return {k: fingerprint(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [fingerprint(v) for v in value]
    return value


def inputs_hash(values: list[Any]) -> str:
    blob = json.dumps(fingerprint(values), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def state_path(session: Session, stage: Stage) -> Path:
    return session.dir(stage.folder) / f".stage-{stage.name}.json"


def is_fresh(session: Session, stage: Stage) -> bool:
    path = state_path(session, stage)
    if not path.exists():
        return False
    if not all(p.exists() for p in stage.outputs(session)):
        return False
    recorded = json.loads(path.read_text()).get("inputs")
    return recorded == inputs_hash(stage.inputs(session))


def run_pipeline(
    session: Session,
    stages: list[Stage],
    start_from: str | None = None,
    only: str | None = None,
    echo: Callable[[str], None] = print,
) -> None:
    names = [s.name for s in stages]
    for requested in (start_from, only):
        if requested and requested not in names:
            raise ValueError(f"unknown stage {requested}; stages are {', '.join(names)}")
    forcing = False
    for stage in stages:
        if only and stage.name != only:
            continue
        if start_from and stage.name == start_from:
            forcing = True
        if not forcing and not only and is_fresh(session, stage):
            echo(f"  {stage.name:<10} up to date")
            continue
        echo(f"▶ {stage.name}")
        started = time.monotonic()
        stage.run(session)
        elapsed = time.monotonic() - started
        state_path(session, stage).write_text(
            json.dumps({"inputs": inputs_hash(stage.inputs(session)), "seconds": round(elapsed, 1)})
        )
        session.log(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {stage.name} done in {elapsed:.1f}s")
        echo(f"  {stage.name:<10} done in {elapsed:.1f}s")
