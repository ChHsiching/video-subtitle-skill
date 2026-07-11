---
name: video-subtitle
description: Turn a foreign-language raw video into a bilingual (or single-language) subtitled cooked video. Use when the user wants to add subtitles to a video, mentions 生肉/熟肉/双语字幕/字幕翻译, or asks to transcribe and translate a video for posting to Bilibili/Douyin/YouTube.
---

Turn a **raw** video (foreign audio, no subtitles) into a **cooked** video with bilingual or single-language subtitles. The agent does the translation itself — no external translation API.

## What you produce

By default, for a bilingual run, all of these:

1. `<name>.en.srt` — English source transcript
2. `<name>.zh.srt` — Chinese translation (one cue per English cue)
3. `<name>.bilingual.srt` — bilingual SRT (zh line on top, en below)
4. `<name>.bilingual.ass` — styled ASS for hard-burning
5. `<name>.cooked.mp4` — video with subtitles burned into the frame

For single-language (`zh` or `en`), produce only that language's SRT + the cooked MP4.

Always ask the user which of these they want before running if it isn't obvious — the cooked MP4 is the slow step (re-encodes the whole video), and they may only need the SRT files.

## Environment reuse — never reinstall blindly

Before touching the pipeline, check what's already on disk. The goal is to skip work that's already done.

1. **Python**: find an existing venv with `whisperx` installed. Check, in order:
   - A `.venv/` in the current project directory
   - Common project directories under the user's workspace
   Run `python -c "import whisperx"` against each candidate. Use the first one that imports cleanly. Only if none found, create one and install `whisperx` (this is heavy — torch alone is ~2GB — so reuse aggressively).
2. **Models**: whisperX downloads models to `~/.cache/huggingface/hub/` (the `medium` model is ~1.5GB) and the wav2vec2 alignment model to `~/.cache/torch/hub/`. These persist across runs. If a model is already cached, the transcribe step skips the download — don't pre-download anything yourself.
3. **ffmpeg**: required for audio extraction and subtitle burning. Run `ffmpeg -version`; if missing, tell the user to install it (don't try to install it yourself on Windows).

The completion criterion for this step: you can name the exact `python` path you'll use for transcription, and ffmpeg is on PATH. Don't proceed to transcription until both are confirmed.

## The pipeline

### Step 1 — Extract audio

whisperX needs 16kHz mono WAV:

```bash
ffmpeg -y -i "input.mp4" -vn -ac 1 -ar 16000 -c:a pcm_s16le "input.wav"
```

Done when `input.wav` exists and is non-empty.

### Step 2 — Transcribe (whisperX, the slow step)

```bash
python scripts/transcribe.py input.wav input.en.srt medium
```

Use `medium` unless the user asks for a different size. On CPU this runs at roughly 2x realtime — a 17-minute video takes ~6-8 minutes. Models download on first run only.

Done when `input.en.srt` exists with one segment per cue. Tell the user this step is slow and they should expect to wait.

### Step 3 — Translate (the agent does this, not a script)

This is the step that makes the quality. You — the agent running this skill — translate the English SRT into Chinese yourself. You have the full transcript, you understand context, and you'll catch ASR errors that the transcription model made.

**Read the English SRT, then write the Chinese SRT cue-for-cue**, keeping the exact same index and timestamps, changing only the text. Rules:

- **Fix ASR errors while you translate.** Proper nouns, technical terms, and commands are routinely mis-transcribed (e.g. "matpocock" → "mattpocock", "SimLink" → "symlink", "Claw Code" → "Claude Code"). The agent has context the transcription model didn't — use it.
- **Keep technical terms in English where Chinese devs would.** Don't translate "skills", "agent", "token", "context window", "CLI" etc. into Chinese — that's how the audience reads them.
- **One cue, one sentence.** Never let a Chinese cue run multiple sentences joined only by commas. If the English cue is long, break the Chinese into a clean short sentence. This is the failure mode you must avoid: a single 100+ character cue that Bilibili rejects.
- **Chinese cue length ≤ 42 characters.** Hard limit. Bilibili cloud subtitles reject cues past ~45 Chinese characters. If a translation would exceed it, you've mis-segmented — translate into a shorter sentence, or flag the English cue for splitting first.
- **Tone: faithful, not marketing.** Translate what's said. Don't add emoji, don't punch up "神级/必看", don't editorialize. The cooked video should sound like the original speaker, in Chinese.

Done when `<name>.zh.srt` exists, has the same cue count and timestamps as `<name>.en.srt`, and every Chinese cue is ≤ 42 characters.

### Step 4 — Merge into bilingual SRT + ASS

```bash
python scripts/subtitles.py biliteral input.en.srt input.zh.srt input.bilingual.srt
python scripts/subtitles.py ass input.bilingual.srt input.bilingual.ass
```

If the user only wants single-language output, skip this step.

Done when `input.bilingual.srt` and `input.bilingual.ass` both exist. Verify the biliteral step reported no cue-count mismatch — if it did, the zh and en SRTs drifted out of sync; fix the translation before continuing.

### Step 5 — Burn subtitles into video (optional, slow)

Only if the user wants a cooked MP4. Hard-burn with libass:

```bash
ffmpeg -y -i "input.mp4" -vf "ass=input.bilingual.ass" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart "input.cooked.mp4"
```

Two gotchas we hit and you will too:

- **Windows paths with `C:` break the ass filter** — the filter parses `:` as an option separator. Run ffmpeg from the directory containing the ASS and pass a **relative** filename (`ass=input.bilingual.ass`), never an absolute `C:\...` path.
- **ASS timestamps need zero-padded minutes** (`0:00:06.07`, not `0:0:6.7`). The `ass` subcommand handles this; if you hand-write ASS, mind the format.

Re-encoding a 17-minute 1080p60 video takes ~5-10 minutes on this machine. Tell the user to expect the wait.

Done when `input.cooked.mp4` exists, plays, and a spot-check frame at a speaking timestamp shows subtitles rendered (the cue for that timestamp is visible). To verify without eyeballing: extract a frame and check the bottom strip has bright (white) pixels above ~2% density — that's the subtitle text.

## Platform notes (only if the user asks about uploading)

- **Bilibili cloud subtitles**: only accepts SRT, one language per upload. Run `python scripts/subtitles.py split input.bilingual.srt out.zh.srt out.en.srt` to get pure-language files. Upload each separately. Soft subtitles — viewer can toggle.
- **Bilibili length limit**: ~45 Chinese chars / ~90 ASCII per cue. The `shorten` subcommand fixes cues that exceed this: `python scripts/subtitles.py shorten input.zh.srt output.zh.srt --lang zh`. Run it if a cue got rejected on upload.
- **Hard-burned MP4**: works everywhere, no toggle, but can't be turned off. If the user uploaded a cooked MP4, they usually don't also need cloud subtitles (they'd double up on screen).
