# Decisions

Settled with the operator on 2026-09-23.

| Topic | Decision | Consequence |
|---|---|---|
| Where it runs | Entirely on one Apple Silicon Mac. Outputs stay local. | No cloud services. The only network calls are the two `claude` passes and the first Whisper model download. |
| Speaker names | No speaker detection. Every transcript turn gets one placeholder speaker, taken from `speaker:` in `context.md` (default `Speaker`). | Turns in the memo sidecar are split by pauses and chapter edges, not by who speaks. |
| Shorts framing | Plain centre crop from 16:9 to 9:16. | Content at the sides of a screen share is cut. Pick highlights that make sense as audio plus captions. |
| Language | Sessions are Vietnamese about 95% of the time. Transcripts and short captions stay Vietnamese. | Whisper runs with `language: vi`. No translation pass. Set `language: en` in `context.md` for an English session. |
| Poster | 1200×630 (1.91:1), text only: logo, series, title, subtitle, speaker, date, chapter count and length, in the d.foundation look: white ground, IBM Plex Sans, ink `#23252c`, crimson `#e13f5e`, grey uppercase eyebrow. No video frame. | The poster is shared as a link preview, and 1200×630 is the Open Graph size Facebook, LinkedIn, X and Slack show uncropped. The video frame was dropped because only `poster.png` is published, so an extracted frame had no other use. |
| Transcript correction | A second LLM pass through the `claude` CLI in JSON mode, driven by a bash script, written back to the transcript. | Segment ids are fixed, so timing survives. A length guard and a review list catch bad edits. |
| Burned-in captions | Drawn as transparent PNGs with Pillow and overlaid by ffmpeg. | The Homebrew ffmpeg on this machine has no libass or drawtext, and this avoids reinstalling it. |

## Defaults still open to change

- **Filler words** stay in the transcript. The correction prompt keeps them because they carry timing.
- **Glossary:** the shared file is `glossary/dwarves.txt`, plus an optional `input/glossary.txt` per session.
- **Models:** `sonnet` corrects, `opus` analyses. Override per session with `correction_model:` and `analysis_model:` in `context.md`.
- **Review** is required before posters and shorts render. `--no-review` accepts the model's picks.
- **Number of shorts** defaults to 5, set by `shorts:` in `context.md`. The review page can switch any candidate on or off.
