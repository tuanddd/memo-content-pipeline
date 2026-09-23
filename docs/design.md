# Design

Everything runs locally. The session folder is the job state: each stage reads earlier folders and writes its own. A stage stores a hash of its inputs next to its output, and `run` skips any stage whose hash is unchanged. Editing one chapter title in review reruns only what depends on it.

```
sessions/2026-09-23-agent-ready/
  input/           video.mp4, context.md, glossary.txt (optional)
  01-media/        audio-16k.wav, web.mp4
  02-transcript/   raw.json, corrected.json, changes.json, transcript.srt, transcript.vtt
  03-analysis/     analysis.json
  04-review/       approved.json
  05-poster/       poster.png
  06-shorts/       01-<slug>.mp4, 01-<slug>.srt, ...
  07-memo/         recording.json, web.mp4, poster.jpg
  run.log
```

## Stages

### 1. Media

ffmpeg writes 16 kHz mono WAV for Whisper, loudness-normalised, and a web MP4 for memo: H.264, AAC, `+faststart`.

### 2a. Transcribe

`mlx-whisper` with `large-v3`, `language` from `context.md`, `word_timestamps=True` and the glossary as the initial prompt. Written to `raw.json`. Each segment keeps its words with `start`, `end` and `probability`. Nothing downstream re-runs Whisper.

Segments that look invented are dropped and listed under `dropped` in `raw.json`:

- more than 8 words per second, which is faster than anyone speaks
- a stock outro such as "Cảm ơn các bạn đã theo dõi" with low confidence
- a high no-speech probability combined with a low log-probability

The first test recording ended in two seconds of silence, and Whisper filled them with "Cảm ơn các bạn đã theo dõi và hẹn gặp lại": 11 words in 0.18 seconds.

### 2b. Correct

An LLM pass that fixes mis-heard words, names, product terms, casing and punctuation, then writes the result back as `corrected.json`. Every later stage reads `corrected.json`, never `raw.json`.

A bash script, `scripts/correct-transcript.sh <session>`, drives it:

1. `session-kit _correct-prepare` cuts `raw.json` into chunks of about 120 segments. Each chunk file is named by a hash of its content, the prompt, the schema and the model, so a finished chunk is reused after a crash but never after the prompt changes. Each chunk carries the 5 segments before it as read-only context, so a sentence split across a chunk edge still makes sense.
2. Each chunk goes to the `claude` CLI in print mode with a JSON schema:

   ```
   claude -p --output-format json --model sonnet --tools "" \
     --no-session-persistence --setting-sources "" \
     --system-prompt-file prompts/correct-transcript.md \
     --json-schema "$(cat schemas/correction.schema.json)" \
     < chunk.json | jq '.structured_output'
   ```

   `scripts/claude-json.sh` wraps this for both LLM passes. It finds `claude` even when it is only a shell alias, and fails when the CLI reports an error.

   The prompt includes `context.md` and `glossary.txt`. Words Whisper scored below 0.5 probability are marked as suspects so the model looks there first.
3. The model returns `{ segments: [{ id, text }], changes: [{ id, from, to, reason }] }`. It may not merge, split, drop or reorder segments. It fixes words and does not paraphrase.
4. The script retries a failed call once. If every chunk fails, the stage fails. `_correct-apply` then checks each chunk: if the same set of ids doesn't come back, the chunk is kept raw. A segment whose text length falls below 60% or rises above 160% of the original keeps its raw text, and the rejection is logged in `changes.json`. Length is measured in characters, not words, because a Vietnamese rendering like "cờ lao phờ le" is four words for one English term.
5. A small Python helper puts word timings back. It diffs the raw words against the corrected words:
   - Words that didn't change keep their times.
   - A replaced run of words gets the replaced run's time span, split evenly across the new words.
   - An inserted word borrows the boundary of its neighbour.
6. SRT and VTT are regenerated from `corrected.json`.

`changes.json` is the audit trail. The review page lists every change so a wrong fix can be reverted by hand.

On the Vietnamese test recording the pass fixed 16 of 19 sentences, all correctly. For example, "Java Circuit, ai dớn chỉ thấy một thẻ diếp chống" became "JavaScript, AI agent chỉ thấy một thẻ div rỗng", and "e -troy" became "deploy". One early run kept a stray syllable, "chạy ra JavaScript", because the prompt forbade deleting words. The prompt now says a mis-heard term can span several words and the whole run is replaced.

### 3. Analyse

A second `claude` call, same mechanism, over the whole corrected transcript with segment timestamps plus `context.md`. It returns:

- `title`, `subtitle`, `speakers[]` and `date` for the poster
- `chapters[]` with `start` and `title`
- `highlights[]`: 8 to 12 candidates, each with `start`, `end`, `hook`, `why` and `score`

Code then enforces what the model drifts on:

- Highlight edges snap to sentence boundaries.
- Each highlight lasts 15 to 25 seconds.
- Highlights don't overlap.
- Chapters are sorted and inside the duration.

### 4. Review

`session-kit review` serves a local page. It plays each highlight in place, approves or drops it, edits chapter titles and poster text, lists the transcript corrections, and previews the poster. Saving writes `approved.json`. Later stages read approved values, falling back to `analysis.json` for anything untouched.

### 5. Poster

An HTML template in `templates/poster/` with named text slots, rendered at 1080×1350 by the installed Chrome through Playwright, with the Plex fonts bundled in `assets/fonts`. The render fails if the title or subtitle runs past three lines, or the layout pushes past the bottom edge. It does not shrink text silently. Overflow is counted in lines, not pixels, because Vietnamese stacked diacritics rise above the line box.

### 6. Shorts

For each approved highlight:

- ffmpeg cuts the range from the source video, not the web copy.
- The clip is centre-cropped to 9:16 and scaled to 1080×1920. Audio is normalised to -14 LUFS.
- Captions are drawn with Pillow in IBM Plex Sans Bold as transparent 1080×1920 PNGs, one per word state, and overlaid through ffmpeg's concat demuxer. The current word sits on a crimson pill. Chunks are 2 to 4 words and break at punctuation. This ffmpeg build has no libass or drawtext.
- The highlight's hook is drawn at the top as a dark headline box with a crimson edge, for the whole clip.
- Captions stay out of the platform UI zones: the top 250 px and the bottom 400 px.
- Output: `NN-<slug>.mp4`, H.264, AAC, 30 fps, plus a matching `.srt`.

### 7. Memo bundle

`07-memo/` is the whole contract with memo: `recording.json` in the version 1 sidecar shape (`foundation-apps/docs/memo-recordings.md`) plus the files it names.

- Chapters come from the approved analysis.
- Transcript turns are built from corrected sentences, re-segmented from word timings on sentence-ending punctuation. With no speaker detection, a new turn starts after a pause over 2 seconds, at a chapter edge, or after 6 sentences. Every turn carries the placeholder speaker from `context.md`.
- `<slug>.md` is a draft note with the title, description and `recording:` frontmatter already filled in.

Publishing stays manual: copy the sidecar into the note's `assets/` folder, add `recording:` to the frontmatter, and upload the media to R2 at the same vault path.

## Why these choices

| Choice | Reason |
|---|---|
| Local only | MLX needs Apple Silicon, and a recording rarely needs to leave the machine |
| `claude` CLI instead of the API | No key management. It uses the logged-in account, and `--json-schema` gives validated output. |
| Folder as state | No database to keep in sync. A session can be copied, zipped or deleted as one unit. |
| One chunk per call, ids fixed | Timing survives the correction pass because segments never move |
| Human review before rendering | Model picks for highlights are good but not reliable enough to publish unseen |

## Costs to plan for

- **Disk:** a one-hour 1080p session with intermediates takes roughly 3 to 6 GB. `clean` keeps `input/` and the final outputs.
- **Time:** Whisper is the slowest step, probably 5 to 15 minutes per hour of audio. Time the first real session.
- Stages run one after another, because Whisper and ffmpeg slow each other down.
