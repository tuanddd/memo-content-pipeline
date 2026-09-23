from __future__ import annotations

import json
import mimetypes
import re
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .correct import write_subtitles
from .runner import ReviewPending, inputs_hash
from .session import Session

PAGE = Path(__file__).parent / "review" / "index.html"


def analysis_hash(session: Session) -> str:
    return inputs_hash([session.dir("analysis") / "analysis.json"])


def default_approval(session: Session, analysis: dict[str, Any]) -> dict[str, Any]:
    ctx = session.context
    return {
        "analysis_hash": analysis_hash(session),
        "title": analysis["title"],
        "subtitle": analysis["subtitle"],
        "speaker": ctx.speaker,
        "date": ctx.date,
        "chapters": analysis["chapters"],
        "highlights": [{**h, "approved": i < ctx.shorts} for i, h in enumerate(analysis["highlights"])],
        "auto": True,
    }


def approved_path(session: Session) -> Path:
    return session.dir("review") / "approved.json"


def load_approval(session: Session) -> dict[str, Any]:
    return json.loads(approved_path(session).read_text(encoding="utf-8"))


def current_approval(session: Session) -> dict[str, Any] | None:
    if not approved_path(session).exists():
        return None
    approval = load_approval(session)
    return approval if approval.get("analysis_hash") == analysis_hash(session) else None


def run_stage(session: Session, auto: bool) -> None:
    if current_approval(session):
        return
    if not auto:
        stale = approved_path(session).exists()
        raise ReviewPending("the analysis changed since the last approval" if stale else "waiting for review")
    analysis = session.read_json("analysis", "analysis.json")
    session.write_json("review", "approved.json", default_approval(session, analysis))


def validate(session: Session, data: dict[str, Any]) -> dict[str, Any]:
    probe = json.loads((session.dir("media") / "probe.json").read_text())
    total = float(probe["duration"])
    title = " ".join(str(data.get("title", "")).split())
    if not title:
        raise ValueError("title is empty")
    chapters = sorted(
        ({"start": round(float(c["start"]), 2), "title": " ".join(str(c["title"]).split())} for c in data.get("chapters", [])),
        key=lambda c: c["start"],
    )
    for c in chapters:
        if not c["title"] or not 0 <= c["start"] < total:
            raise ValueError(f"chapter at {c['start']}s is empty or outside the recording")
    highlights = []
    for h in data.get("highlights", []):
        start, end = float(h["start"]), float(h["end"])
        if not 0 <= start < end <= total + 0.5:
            raise ValueError(f"highlight {h.get('id')} has an invalid range")
        highlights.append({**h, "start": round(start, 2), "end": round(end, 2), "approved": bool(h.get("approved"))})
    return {
        "analysis_hash": analysis_hash(session),
        "title": title,
        "subtitle": " ".join(str(data.get("subtitle", "")).split()),
        "speaker": " ".join(str(data.get("speaker", "")).split()) or session.context.speaker,
        "date": data.get("date") or session.context.date,
        "chapters": chapters,
        "highlights": highlights,
        "auto": False,
    }


def revert_correction(session: Session, segment_id: int) -> None:
    raw = {s["id"]: s for s in session.read_json("transcript", "raw.json")["segments"]}
    corrected = session.read_json("transcript", "corrected.json")
    for seg in corrected["segments"]:
        if seg["id"] == segment_id:
            original = raw[segment_id]
            seg.update({"text": original["text"], "words": original["words"], "start": original["start"], "end": original["end"]})
    session.write_json("transcript", "corrected.json", corrected)
    changes = session.read_json("transcript", "changes.json")
    for entry in changes["accepted"]:
        if entry["id"] == segment_id:
            entry["reverted"] = True
    session.write_json("transcript", "changes.json", changes)
    write_subtitles(session, corrected)


def state(session: Session) -> dict[str, Any]:
    analysis = session.read_json("analysis", "analysis.json")
    approval = current_approval(session) or default_approval(session, analysis)
    probe = json.loads((session.dir("media") / "probe.json").read_text())
    return {
        "session": session.root.name,
        "duration": probe["duration"],
        "analysis": analysis,
        "approval": approval,
        "changes": session.read_json("transcript", "changes.json"),
        "has_poster": (session.dir("poster") / "poster.png").exists(),
    }


def serve(session: Session, port: int, open_browser: bool) -> None:
    files = {
        "/media/web.mp4": session.dir("media") / "web.mp4",
        "/poster.png": session.dir("poster") / "poster.png",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def send_json(self, body: Any, status: int = 200) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path) -> None:
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            match = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("range", ""))
            first, last = 0, size - 1
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    first = int(match.group(1))
                    last = int(match.group(2)) if match.group(2) else size - 1
                else:
                    first = max(0, size - int(match.group(2)))
                last = min(last, size - 1)
                if first > last:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("content-range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("content-range", f"bytes {first}-{last}/{size}")
            else:
                self.send_response(HTTPStatus.OK)
            self.send_header("content-type", ctype)
            self.send_header("accept-ranges", "bytes")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(last - first + 1))
            self.end_headers()
            with path.open("rb") as fh:
                fh.seek(first)
                remaining = last - first + 1
                while remaining > 0:
                    chunk = fh.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/":
                self.send_file(PAGE)
            elif path == "/api/state":
                self.send_json(state(session))
            elif path in files:
                self.send_file(files[path])
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/approve":
                    session.write_json("review", "approved.json", validate(session, body))
                    self.send_json({"ok": True})
                elif self.path == "/api/revert":
                    revert_correction(session, int(body["id"]))
                    self.send_json({"ok": True})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except (ValueError, KeyError, TypeError) as error:
                self.send_json({"ok": False, "error": str(error)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Review page: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
