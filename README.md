# memo-content-pipeline

`session-kit` turns a session recording plus a short context note into everything a memo post needs. It runs on one Apple Silicon Mac and keeps every output local.

From `video.mp4` and `context.md` it produces:

- a 1080×1350 poster in the d.foundation look, with this session's title and a frame from the video
- an SRT and VTT transcript from MLX Whisper large-v3, corrected by a second LLM pass
- vertical 1080×1920 shorts of about 20 seconds each, with Vietnamese captions burned in
- a memo bundle: the `recording.json` sidecar memo's recording player reads, the web video, the poster and a draft note

## Setup

Once per machine, about 5 minutes plus a 3 GB model download on the first run:

```
brew install ffmpeg jq uv
cd memo-content-pipeline
uv sync
```

Also needed: Google Chrome for the poster render, and the `claude` CLI logged in. If `claude` is only a shell alias, the scripts fall back to `~/.claude/local/claude`, or set `CLAUDE_BIN`.

## Run a session

```
uv run session-kit new ~/Downloads/recording.mp4 --context context.md
uv run session-kit run 2026-09-23-recording
uv run session-kit review 2026-09-23-recording
uv run session-kit run 2026-09-23-recording
```

1. `new` creates `~/Sessions/<date>-<name>/` and copies the inputs. Set `SESSION_KIT_ROOT` to use another folder.
2. The first `run` transcribes, corrects, analyses, then pauses for review.
3. `review` opens a local page. Play each suggested short, keep or drop it, edit the title, subtitle and chapters, pick the poster frame, and revert any transcript correction you disagree with. Press Save.
4. The second `run` renders the poster, the shorts and the memo bundle.

Other commands:

```
uv run session-kit status <session>              which stages are done, stale or not run
uv run session-kit run <session> --from shorts   redo one stage and everything after it
uv run session-kit run <session> --no-review     accept the model's picks and render straight away
uv run session-kit clean <session>               delete regenerable intermediates
```

A stage reruns only when its inputs change, so editing one chapter title re-renders the poster and the bundle but never re-transcribes.

## context.md

Copy `context.sample.md` and edit it:

```
cp context.sample.md ~/Downloads/context.md
```

```markdown
---
title: Làm memo thân thiện với AI agent
speaker: tieubao
date: 2026-09-18
language: vi
shorts: 5
---
What the session is about, who is in it, and any names or product terms
the transcript might mishear: is-agentic, Cloudflare Workers, DuckDB.
```

Every key is optional:

- `speaker` is the placeholder speaker on every transcript turn.
- `language` is the spoken language, `vi` by default.
- `shorts` is how many suggested shorts start switched on.
- `series` sets the poster eyebrow, `Show & Tell` by default.
- `correction_model` and `analysis_model` pick the Claude models.

The notes below the frontmatter go to both LLM passes. Add terms that recur across sessions to `glossary/dwarves.txt`, and one-off terms to `input/glossary.txt` in the session folder.

## What you get

```
~/Sessions/2026-09-18-agent-ready/
  02-transcript/transcript.srt         corrected transcript
  02-transcript/changes.json           every correction, with its reason
  05-poster/poster.png                 1080×1350
  06-shorts/01-<hook>.mp4 + .srt       1080×1920, 30 fps, -14 LUFS
  06-shorts/index.json                 hook, source range and file per short
  07-memo/<slug>-recording.json        the memo sidecar
  07-memo/<slug>.mp4                   web video (H.264, faststart)
  07-memo/<slug>-poster.jpg
  07-memo/<slug>.md                    draft note with the recording frontmatter
```

## Publish to memo

Manual, so the pipeline itself stays offline:

1. Copy `<slug>-recording.json` into the note's `assets/` folder in the vault, and add `recording: assets/<slug>-recording.json` to its frontmatter. `<slug>.md` is a starting point for a new note.
2. Upload the video and the poster to the `memo-vault-assets` R2 bucket, at the same path as the note's `assets/` folder:

   ```
   wrangler r2 object put memo-vault-assets/<vault-path>/assets/<slug>.mp4 --file 07-memo/<slug>.mp4 --content-type video/mp4 --remote
   wrangler r2 object put memo-vault-assets/<vault-path>/assets/<slug>-poster.jpg --file 07-memo/<slug>-poster.jpg --content-type image/jpeg --remote
   ```

The sidecar format is documented in `foundation-apps/docs/memo-recordings.md`.

## Docs

- `docs/design.md`: every stage and why it works the way it does.
- `docs/decisions.md`: what was decided with the operator, and the defaults still open to change.

## Tests

```
uv run pytest
```
