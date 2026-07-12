---
name: video-subtitle
description: Turn a foreign-language raw video into a bilingual (or single-language) subtitled cooked video. Use when the user wants to add subtitles to a video, mentions 生肉/熟肉/双语字幕/字幕翻译, or asks to transcribe and translate a video for posting to Bilibili/Douyin/YouTube.
---

Turn a **raw** video (foreign audio, no subtitles) into a **cooked** video with bilingual or single-language subtitles. The agent does the translation itself — no external translation API.

The skill ships two scripts in its own `scripts/` folder: `transcribe.py` (whisperX → SRT) and `subtitles.py` (merge / ASS / split / shorten). They live **inside this skill folder** — not in the user's project. Before calling them, resolve their absolute path. If this skill is installed at `.agents/skills/video-subtitle/`, the scripts are at `.agents/skills/video-subtitle/scripts/`. Use the absolute path when invoking, since the user's video may be anywhere on disk.

## What you produce

By default, for a bilingual run, all of these:

1. `<name>.en.srt` — English source transcript
2. `<name>.zh.srt` — Chinese translation (one cue per English cue)
3. `<name>.bilingual.srt` — bilingual SRT (zh line on top, en below)
4. `<name>.bilingual.ass` — styled ASS for hard-burning
5. `<name>.cooked.mp4` — video with subtitles burned into the frame
6. `<name>.upload.md` — title, description, and chapter timestamps for uploading (Step 6)

For single-language (`zh` or `en`), produce that language's SRT + the cooked MP4 + the upload.md.

Produce everything by default. More outputs = more choices for the user at upload time. Only skip a step if the user explicitly says they don't want a specific output.

## Where the outputs land — one folder per stage

Every video's outputs go into a **per-video subdirectory**, and inside it the files are split into folders named after the pipeline stage that produces them. The folder names are self-describing — no numbers, no needing to remember an order.

Ask where the user wants the per-video directory before Step 1 — default is `<cwd>/<author>/<video-name>/` (e.g. `tony/linux-mint-2026/`), one level under a folder named after the source author. All output paths below are relative to that per-video directory.

```
<video-name>/
├── raw/            the source video (download or user-provided)
│   └── raw.mp4
├── transcript/     Step 1–2: audio + English transcript
│   ├── <name>.audio.wav
│   └── <name>.en.srt
├── subtitle/       Step 3–4: Chinese translation + bilingual merge
│   ├── <name>.zh.srt
│   ├── <name>.bilingual.srt
│   └── <name>.bilingual.ass
├── cooked/         Step 5–6: burned video + upload metadata
│   ├── <name>.cooked.mp4
│   └── <name>.upload.md
├── cloud-srt/      soft-subtitle files (split, length-safe) — produced on request or for platform upload
│   ├── <name>.zh-cloud.srt
│   └── <name>.en-cloud.srt
└── scripts/        any helper scripts you write for this run (e.g. a custom merge) — kept with the run that produced them
```

Rules:

- **`<name>` is the same stem across all files in the run** — e.g. `linux-mint` everywhere, not `linux-mint.en.srt` but `linuxmint.cooked.mp4`. The user names it; reuse it.
- **Each stage folder holds only that stage's outputs.** Don't put the cooked MP4 next to the raw. If you find yourself cross-referencing a file from another stage, copy it in rather than reach across — the folders are the unit of "is this step done."
- **`cloud-srt/` is produced lazily** — only when the user asks for soft subtitles (e.g. Bilibili cloud subtitle upload). It's not part of the default burn pipeline; it's the platform-notes path.
- If a video has extra assets (screenshots for an article, a write-up), give them their own descriptive folder (`screenshots/`, `writeup/`) — don't pollute the stage folders.

The completion criterion for layout: at the end of a run, `find <video-name>/ -type f` shows every file inside a named stage folder, nothing loose in the per-video root.

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
python <skill>/scripts/transcribe.py input.wav input.en.srt medium
```

`<skill>` is this skill's folder (wherever it's installed — `.agents/skills/video-subtitle` or `.claude/skills/video-subtitle`). Use the absolute path.

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
python <skill>/scripts/subtitles.py biliteral input.en.srt input.zh.srt input.bilingual.srt
python <skill>/scripts/subtitles.py ass input.bilingual.srt input.bilingual.ass
```

If the user only wants single-language output, skip this step.

**Subtitle placement — ask the user which they want.** Two modes, producing different ASS files:

- **Overlay** (default): subtitles render on top of the picture. The command above.
- **Bottom-bar**: subtitles sit in a black strip padded below the frame, so nothing in the image is covered. Add `--bottom-bar PX`:

  ```bash
  python <skill>/scripts/subtitles.py ass input.bilingual.srt input.bilingual.bar.ass --bottom-bar 180
  ```

  The ASS play resolution grows by `PX` (1080 → 1260) and subtitles land in the strip. A 180px bar fits the two-line bilingual layout on 1080p; ~120px for single-language. Step 5 must `pad` the frame to match, or subtitles render off-screen. Name the bar variant `<name>.bilingual.bar.ass` to keep it apart from the overlay one.

Don't generate both unless the user asks — pick one and use it.

Done when the chosen ASS exists. Verify the biliteral step reported no cue-count mismatch — if it did, the zh and en SRTs drifted out of sync; fix the translation before continuing.

### Step 5 — Burn subtitles into video

Hard-burn with libass. Use the command that matches the placement chosen in Step 4.

**Overlay** (default):

```bash
ffmpeg -y -i "input.mp4" -vf "ass=input.bilingual.ass" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart "input.cooked.mp4"
```

**Bottom-bar** (only with `--bottom-bar PX` in Step 4 — pad a black strip below the frame first, then burn the ASS whose play resolution already accounts for the bar):

```bash
ffmpeg -y -i "input.mp4" -vf "pad=iw:ih+PX:color=black,ass=input.bilingual.bar.ass" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart "input.cooked.bar.mp4"
```

`PX` is the same value passed to `--bottom-bar`. Filters run left-to-right: `pad` grows the frame, `ass` renders into the grown area. Output height becomes `source_height + PX`.

Two gotchas we hit and you will too:

- **Windows paths with `C:` break the ass filter** — the filter parses `:` as an option separator. Run ffmpeg from the directory containing the ASS and pass a **relative** filename (`ass=input.bilingual.ass`), never an absolute `C:\...` path.
- **ASS timestamps need zero-padded minutes** (`0:00:06.07`, not `0:0:6.7`). The `ass` subcommand handles this; if you hand-write ASS, mind the format.

Re-encoding a 17-minute 1080p60 video takes ~5-10 minutes on this machine. Tell the user to expect the wait.

Done when `input.cooked.mp4` exists, plays, and a spot-check frame at a speaking timestamp shows subtitles rendered (the cue for that timestamp is visible). To verify without eyeballing: extract a frame and check the bottom strip has bright (white) pixels above ~2% density — that's the subtitle text. In bottom-bar mode also confirm the image region itself is untouched.

### Step 6 — Write the upload metadata

The user is going to post this somewhere. Give them a ready-to-paste title, description, and chapter list — derived from the transcript you just translated, so it actually matches the video. Write it to `<name>.upload.md`.

This is authoring work, like Step 3. You — the agent — write it from the transcript. No script.

**Title.** One line, faithful to what the video is about. Pull the hook from the source if there is one (e.g. "16万Star的仓库,却没有教程" mirrors the original's "...and no tutorial"). Keep it under 30 Chinese characters; don't add clickbait ("神级/必看/震惊"). If the original author has their own framing, mirror it rather than invent your own.

**Description.** The translated summary of what the video covers, plus the provenance the user will need at upload time:

- What the video is, in 2-3 sentences, translated from the source's own framing (don't editorialize)
- Key points / commands / timestamps, as a short list — these are the terms people will search for
- Source attribution: author handle, original link, install command (`npx skills add ...`) if it's a skills repo
- One line: "中英双语字幕,AI 辅助转录 + 翻译并经人工校对,技术术语已对齐。如有不准确之处,欢迎指出。"

Same tone rule as Step 3: translator, not promoter.

**Chapters.** Read through the translated SRT and find the natural topic boundaries — where the speaker moves to a new command, a new section, a new demo. Emit each as `MM:SS 章节名`, in the **comment format for the target platform**, because Bilibili and YouTube parse chapters from pinned-comment timestamps that users can click to jump:

```
00:00 开场:为什么做这个
00:32 安装配置
03:44 ask-matt 演示
...
```

Use the timestamp of the first cue at each boundary (pull it from the SRT). Chapter names are short noun phrases, not sentences. Aim for 5-12 chapters for a 15-20 minute video — too few is useless, too many is noise.

Done when `<name>.upload.md` exists with a title, a description, and a chapter list whose timestamps all fall within the video's duration.

## Platform notes (only if the user asks about uploading)

- **Bilibili cloud subtitles**: only accepts SRT, one language per upload. Run `python <skill>/scripts/subtitles.py split input.bilingual.srt out.zh.srt out.en.srt` to get pure-language files. Upload each separately.
- **Bilibili length limit**: ~45 Chinese chars / ~90 ASCII per cue. The `shorten` subcommand fixes cues that exceed this: `python <skill>/scripts/subtitles.py shorten input.zh.srt output.zh.srt --lang zh`. Run it if a cue got rejected on upload.
- **Hard-burned MP4**: works everywhere, no toggle. Hand the user both the cooked MP4 and the SRTs — they decide at upload time which to use (cooked MP4 for platforms that don't support soft subs, raw video + SRT for platforms that do).
