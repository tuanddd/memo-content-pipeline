from __future__ import annotations

import html
import json
from datetime import date as Date
from pathlib import Path

from .review import load_approval
from .session import REPO_ROOT, Session

WIDTH, HEIGHT = 1200, 630
TEMPLATE = REPO_ROOT / "templates" / "poster" / "poster.html"

LABELS = {
    "vi": {"watch": "Xem lại buổi chia sẻ", "chapters": "chương"},
    "en": {"watch": "Watch the session", "chapters": "chapters"},
}


class PosterOverflow(RuntimeError):
    pass


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return Date.fromisoformat(str(value)).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def poster_path(session: Session) -> Path:
    return session.dir("poster") / "poster.png"


def fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def build_html(session: Session) -> str:
    approval = load_approval(session)
    ctx = session.context
    labels = LABELS.get(ctx.language, LABELS["en"])
    probe = json.loads((session.dir("media") / "probe.json").read_text())
    meta = " · ".join(
        part for part in [format_date(approval.get("date")), f"{len(approval['chapters'])} {labels['chapters']}"] if part
    )
    return fill(TEMPLATE.read_text(encoding="utf-8"), {
        "fonts": (REPO_ROOT / "assets" / "fonts").as_uri(),
        "logo": (REPO_ROOT / "assets" / "brand" / "logo.svg").as_uri(),
        "series": html.escape(ctx.series),
        "title": html.escape(approval["title"]),
        "subtitle": html.escape(approval["subtitle"]),
        "speaker": html.escape(approval.get("speaker") or ctx.speaker),
        "meta": html.escape(meta),
        "watch_label": html.escape(labels["watch"]),
        "duration": format_duration(float(probe["duration"])),
    })


def render(page_html: Path, target: Path) -> list[str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            page.goto(page_html.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_load_state("networkidle")
            overflow = page.evaluate(
                """() => {
                  const over = [...document.querySelectorAll('[data-slot]')].filter(el => {
                    const lh = parseFloat(getComputedStyle(el).lineHeight);
                    const lines = Math.round(el.getBoundingClientRect().height / lh);
                    return lines > Number(el.dataset.maxLines || 99);
                  }).map(el => el.dataset.slot);
                  if (document.body.scrollHeight > innerHeight + 1) over.push('layout');
                  return over;
                }"""
            )
            page.screenshot(path=str(target), clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
        finally:
            browser.close()
    return overflow


def run_stage(session: Session) -> None:
    page = session.dir("poster") / "poster.html"
    page.write_text(build_html(session), encoding="utf-8")
    overflow = render(page, poster_path(session))
    if overflow:
        raise PosterOverflow(
            f"poster text does not fit: {', '.join(overflow)}. Shorten it in `session-kit review`, then run again. "
            f"The clipped render is at {poster_path(session)}"
        )
