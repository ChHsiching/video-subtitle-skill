# video-subtitle

A skill that turns a foreign-language **raw** video (生肉) into a bilingual or single-language **cooked** video (熟肉) with subtitles. Designed to run inside an AI coding agent — the agent does the transcription via whisperX and does the translation itself, so there's no translation API key to manage.

Built and tested on a CPU-only Windows machine, on a real 17-minute video.

## What it produces

For a bilingual run on `input.mp4`:

| File | What it is |
|---|---|
| `input.en.srt` | English source transcript |
| `input.zh.srt` | Chinese translation, cue-for-cue with the English |
| `input.bilingual.srt` | Bilingual SRT (Chinese on top, English below) |
| `input.bilingual.ass` | Styled ASS for hard-burning subtitles |
| `input.cooked.mp4` | Video with subtitles burned into the frame |

For single-language output (`zh` or `en`), only that language's SRT + the cooked MP4.

## How it works

```
input.mp4
  │
  ├─ ffmpeg ──► 16kHz mono WAV
  │
  ├─ whisperX ──► input.en.srt          (transcription + word-level alignment)
  │
  ├─ the agent ──► input.zh.srt         (translation, done by the agent itself)
  │
  ├─ subtitles.py biliteral ──► bilingual.srt + .ass
  │
  └─ ffmpeg (ass filter) ──► cooked.mp4 (hard-burned subtitles)
```

The translation step is the design choice that matters: instead of calling a translation API, the agent running the skill translates the transcript directly. It has the full context, catches ASR errors, and keeps technical terms in English where the audience expects them.

## Requirements

- **Python 3.10+** with `whisperx` (the only heavy dependency — pulls in torch, ~2GB)
- **ffmpeg** on PATH
- A CPU works (that's what it was built on). A GPU makes transcription faster but isn't required.

First run downloads the whisperX `medium` model (~1.5GB) and the wav2vec2 alignment model (~360MB). They cache under `~/.cache/` and reuse on every subsequent run.

## Install

Install into any agent project via the [skills.sh](https://skills.sh) installer:

```bash
npx skills add ChHsiching/video-subtitle-skill
```

This works because the repo follows the standard layout the installer walks: a `skills/video-subtitle/SKILL.md` with valid `name` + `description` frontmatter, plus a `.claude-plugin/plugin.json` manifest. The installer copies the skill (including its `scripts/` folder) into your agent's skills directory (`.agents/skills/`, `.claude/skills/`, etc.).

The skill needs a Python environment with `whisperx` — set it up once anywhere on your machine:

```bash
python -m venv .venv
.venv/Scripts/pip install whisperx   # Windows
# or: source .venv/bin/activate && pip install whisperx   # macOS/Linux
```

The skill detects and reuses an existing whisperX environment; it doesn't reinstall.

## Usage

Inside your agent, ask in plain language:

> 给这个视频做中英双语字幕:input.mp4

The skill fires, checks for an existing whisperX environment (reuses it, doesn't reinstall), and runs the pipeline. The agent tells you when the slow steps (transcription, re-encoding) are happening.

## Scripts

The `scripts/` directory is usable standalone, without the skill:

```bash
# Transcribe (whisperX, CPU, medium model)
python skills/video-subtitle/scripts/transcribe.py input.wav input.en.srt medium

# Subtitle utilities
SK=skills/video-subtitle/scripts
python $SK/subtitles.py biliteral en.srt zh.srt bilingual.srt   # merge two SRTs
python $SK/subtitles.py ass bilingual.srt out.ass               # bilingual SRT -> styled ASS
python $SK/subtitles.py split bilingual.srt zh.srt en.srt       # bilingual -> two pure-language
python $SK/subtitles.py shorten input.srt out.srt --lang zh     # split cues over the length limit
```

`shorten` exists because whisperX occasionally emits a cue spanning several sentences, which platforms like Bilibili reject (limit ~45 Chinese chars / ~90 ASCII per cue). It splits on sentence punctuation, hard-wraps at commas if a fragment is still too long, and redistributes timestamps proportionally.

## License

MIT
