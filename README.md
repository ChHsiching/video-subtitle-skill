# video-subtitle

A skill that turns a foreign-language **raw** video (生肉) into a bilingual or single-language **cooked** video (熟肉) with subtitles. Designed to run inside an AI coding agent — the agent does the transcription via whisperX and does the translation itself, so there's no translation API key to manage.

Built and tested on a CPU-only Windows machine, on a real 75-minute video.

## Why

A subtitled release is the primary product of the video pipeline. The hard parts are ASR quality (whisperX mis-transcribes proper nouns), translation quality (technical terms, fragmentation), and never shipping a half-finished release set (missing cover, missing cloud-srt, translation drift). This skill owns all three: it audits the ASR before translating, translates with source context, and gates the whole run on `cook verify-shipment` exiting 0.

The translation is done by the agent itself, not a translation API — the agent has the full context, catches ASR errors, and keeps technical terms in English where the audience expects them. Deterministic execution (audio extraction, transcription, subtitle processing, burning) is handled by [`cook`](https://github.com/ChHsiching/video-cook), which assembles every ffmpeg / whisperX command correctly every time.

## Install

```bash
npx skills add ChHsiching/video-subtitle-skill
pip install video-cook[all]   # cook CLI + yt-dlp + whisperx
```

ffmpeg and Node.js must be on PATH separately (cook can't pip-install those).

## Use

Inside your agent, ask in plain language:

> 给这个视频做中英双语字幕:input.mp4

Or run the full download → subtitle chain in one command via the [`video-cooking`](https://github.com/ChHsiching/video-cooking-skill) router: `/video-cooking <URL>`.

## How it works

The pipeline, the translation step, the ASR quality gates, and all command details live in **[SKILL.md](skills/video-subtitle/SKILL.md)** — that is the authoritative source the agent runs from. This README is intentionally a landing page only; execution details are not duplicated here so they cannot drift out of sync. See also [REFERENCE.md](skills/video-subtitle/REFERENCE.md) for environment-reuse details, GPU detection, and the raw ffmpeg/whisperX commands cook runs internally.

## License

MIT
