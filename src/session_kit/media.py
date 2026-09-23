from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .session import Session


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"{cmd[0]} failed ({result.returncode}):\n{tail}")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    return {
        "duration": float(data["format"]["duration"]),
        "width": int(video["width"]) if video else None,
        "height": int(video["height"]) if video else None,
        "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"]),
    }


def audio_path(session: Session) -> Path:
    return session.dir("media") / "audio-16k.wav"


def web_path(session: Session) -> Path:
    return session.dir("media") / "web.mp4"


def probe_path(session: Session) -> Path:
    return session.dir("media") / "probe.json"


def run_stage(session: Session) -> None:
    info = probe(session.video)
    if not info["has_audio"]:
        raise RuntimeError("the input video has no audio track")
    probe_path(session).write_text(json.dumps(info, indent=1))
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(session.video), "-vn",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", "16000",
        str(audio_path(session)),
    ])
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(session.video),
        "-vf", "scale=-2:'min(1080,ih)'", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(web_path(session)),
    ])


