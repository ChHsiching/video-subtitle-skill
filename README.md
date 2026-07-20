# video-subtitle

A skill that turns a foreign-language **raw** video (生肉) into a bilingual or single-language **cooked** video (熟肉) with subtitles. Designed to run inside an AI coding agent — the agent does the transcription via whisperX and does the translation itself, so there's no translation API key to manage.

Built and tested on a CPU-only Windows machine, on a real 75-minute video.

## What it produces — the shipment

For a bilingual run, each video gets its own directory split into stage folders (`raw/`, `transcript/`, `subtitle/`, `cloud-srt/`, `cooked/`). The **shipment** is the complete release set:

| File | What it is |
|---|---|
| `transcript/<name>.en.srt` | Source-language transcript |
| `transcript/<name>.zh.srt` | Chinese translation |
| `transcript/asr-fixes.md` | ASR errors fixed during translation |
| `subtitle/<name>.bilingual.srt` | Bilingual SRT (Chinese on top, source below) |
| `subtitle/<name>.bilingual.{,bar.}ass` | Styled ASS for hard-burning (overlay or bottom-bar) |
| `cloud-srt/{zh,en}.srt` | Single-language SRTs for platforms that accept soft subs |
| `cooked/<name>.cooked.{,bar.}mp4` | Video with subtitles burned into the frame |
| `cooked/<name>.upload.md` | Per-platform titles, descriptions, chapter timestamps |
| `cooked/cover.jpg` | Publish cover |
| `README.md` | Index for this video's directory — what each folder holds, the processing log |

The run is not done until `cook verify-shipment` exits 0 (every file above present, durations match). For single-language output (`zh` or `en`), only that language's SRT + the cooked MP4 + the upload.md.

## How it works

```
<name>/raw/<name>.raw.mp4
  │
  ├─ cook extract ──► 16kHz mono WAV                              (transcript/)
  │
  ├─ cook transcribe ──► <name>.en.srt                            (whisperX, auto CUDA detect, auto-detach)
  │
  ├─ the agent ──► <name>.zh.srt + asr-fixes.md                   (translation + ASR corrections, by the agent)
  │  cook verify-align ──► exit 0                                  (DP alignment gate)
  │
  ├─ cook subtitles ──► bilingual.srt + .ass + cloud-srt/         (shorten+merge+biliteral+ass in one shot)
  │
  ├─ cook burn ──► <name>.cooked.{,bar.}mp4                       (ffmpeg, auto-detach)
  │
  ├─ the agent ──► <name>.upload.md                               (per-platform titles/descriptions/chapters)
  │  cook cover ──► cooked/cover.jpg
  │
  ├─ the agent ──► README.md                                      (index)
  │
  └─ cook verify-shipment ──► exit 0                              (final gate)
```

Two design choices that matter:

1. **The translation is done by the agent, not a translation API.** The agent running the skill translates the transcript directly. It has the full context, catches ASR errors, and keeps technical terms in English where the audience expects them.
2. **Deterministic execution is handled by [`cook`](https://github.com/ChHsiching/video-cook).** cook assembles every `ffmpeg` / `yt-dlp` / `whisperX` command correctly every time — no shell escaping traps, no forgotten flags, no hand-assembly drift. The skill docs shrink to a pipeline skeleton; each step's completion criterion becomes "cook exit 0". See [`SKILL.md`](skills/video-subtitle/SKILL.md) and [`REFERENCE.md`](skills/video-subtitle/REFERENCE.md) for details.

## Requirements

- **Python 3.10+** with `cook` + `whisperx` (the heavy one — pulls in torch, ~2GB) + `yt-dlp` (for cover fetching)
- **ffmpeg** and **Node.js** on PATH
- A CPU works (built and tested on CPU). A GPU makes transcription faster but isn't required — `cook transcribe --compute auto` detects it.

Models download on first run and cache under `~/.cache/` for reuse.

## Install

```bash
npx skills add ChHsiching/video-subtitle-skill
pip install video-cook[all]   # cook CLI + yt-dlp + whisperx
```

## Usage

Inside your agent, ask in plain language:

> 给这个视频做中英双语字幕:input.mp4

The skill fires, runs `cook doctor` to confirm the environment, then runs the pipeline. The agent tells you when the slow steps (transcription, re-encoding) are happening and verifies the shipment at the end.

To run the full download → subtitle chain in one command, use the [`video-cooking`](https://github.com/ChHsiching/video-cooking-skill) router: `/video-cooking <URL>`.

## Scripts (standalone, without cook)

The `scripts/` directory is usable without cook — `cook` wraps these for safety, but they work directly:

```bash
SK=skills/video-subtitle/scripts
python $SK/transcribe.py input.wav input.en.srt                              # English, CPU
python $SK/transcribe.py input.wav input.ja.srt large-v3 float32 ja cuda     # Japanese, GPU
python $SK/subtitles.py shorten input.srt out.srt --lang zh                  # split long cues
python $SK/subtitles.py merge-short input.short.srt out.srt --min-dur 1.2    # absorb fragments
python $SK/subtitles.py biliteral en.srt zh.srt bilingual.srt                # merge to bilingual
python $SK/subtitles.py ass bilingual.srt out.ass                            # -> styled ASS
```

Note: `subtitles.py split` has a known issue when run on `biliteral`'s union-mode output (English cues can leak into zh.srt). `cook subtitles` avoids this by copying the per-language merged SRTs directly. See [`REFERENCE.md`](skills/video-subtitle/REFERENCE.md#why-cook-subtitles-copies-merged-srts-instead-of-running-subtitlespy-split) for the full explanation.

## License

MIT
