---
name: video-subtitle
description: Turn a foreign-language raw video into a bilingual (or single-language) subtitled cooked video. Use when the user wants to add subtitles to a video, mentions 生肉/熟肉/双语字幕/字幕翻译, or asks to transcribe and translate a video for posting to Bilibili/Douyin/YouTube.
---

Turn a **raw** video (foreign audio, no subtitles) into a **cooked** video with bilingual or single-language subtitles. The agent does the translation itself — no external translation API.

The skill ships three scripts in its own `scripts/` folder: `transcribe.py` (whisperX → SRT), `subtitles.py` (merge / ASS / split / shorten), and `merge_short.py` (fix shorten fragmentation). They live **inside this skill folder** — not in the user's project. Before calling them, resolve their absolute path. If this skill is installed at `.agents/skills/video-subtitle/`, the scripts are at `.agents/skills/video-subtitle/scripts/`. Use the absolute path when invoking, since the user's video may be anywhere on disk.

**All SRT output must have no BOM and no empty cues.** BOM causes Bilibili to reject the file ("格式不正确"), and empty cues (timestamp with no text) also cause rejection. The scripts handle this automatically.

## What you produce

By default, for a bilingual run, all of these:

1. `<name>.en.srt` — English source transcript
2. `<name>.zh.srt` — Chinese translation (one cue per English cue)
3. `<name>.bilingual.srt` — bilingual SRT (zh line on top, en below)
4. `<name>.bilingual.ass` — styled ASS for hard-burning
5. `<name>.cooked.mp4` — video with subtitles burned into the frame
6. `<name>.upload.md` — title, description, and chapter timestamps for uploading (Step 6)
7. `README.md` — the index for this video's directory: what each subfolder holds, where to find each artifact, the processing log (Step 7)

For single-language (`zh` or `en`), produce that language's SRT + the cooked MP4 + the upload.md.

Produce everything by default. More outputs = more choices for the user at upload time. Only skip a step if the user explicitly says they don't want a specific output.

## Where the outputs land — one folder per stage

Every video's outputs go into a **per-video subdirectory**, and inside it the files are split into folders named after the pipeline stage that produces them. The folder names are self-describing — no numbers, no needing to remember an order.

Ask where the user wants the per-video directory before Step 1 — default is `<cwd>/<author>/<video-name>/` (e.g. `tony/linux-mint-2026/`), one level under a folder named after the source author. All output paths below are relative to that per-video directory.

```
<video-name>/
├── README.md        ← the index for this video (see below) — always present
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

### The README.md — required, not optional

The per-video directory **must** contain a `README.md` at its root. It is the index: someone (including you, months later) opens the folder and immediately knows what each subdirectory holds and where to find each artifact. Without it, the stage-folder names are guesswork.

The folder names alone don't carry enough meaning — `transcript/` could be the English transcript or the Chinese one or both; `subtitle/` could be the soft-srt or the burned ASS; `cooked/` doesn't say whether the upload.md is in there. The README resolves all of that in one place.

Write it as the final step of the run, after every artifact exists. It must contain:

- **Header**: source author, original URL, duration, resolution, processing date.
- **An index table** — one row per subdirectory, columns `去哪找 | 目录 | 里面是什么`. This is the lookup the folder names can't provide on their own. Use the user's language (Chinese if the run is Chinese-facing).
- **An artifacts-by-purpose list** — group the actual files by what the user will do with them: "直接发 B 站" (cooked mp4 + upload.md), "传 B 站云字幕" (the cloud-srt files, with the don't-double-up warning), "存档/二次加工" (raw + per-language srts + ass). This is more useful than a flat file list because it answers "I want to do X, which file?"
- **Processing log**: transcription engine + model, who translated (you), ASR errors you fixed while translating, burn settings, and the verification checks you ran (duration match, subtitle-render spot-check). This is the provenance record — if something looks off later, it tells you how it was made.

The README's own completion criterion: a reader who has never seen this run can, in under 30 seconds, point to the file they need for any given purpose.

The overall layout criterion: at the end of a run, `find <video-name>/ -type f` shows `README.md` plus every other file inside a named stage folder, nothing loose in the per-video root.

## Environment reuse — never reinstall blindly

Before touching the pipeline, check what's already on disk. The goal is to skip work that's already done.

1. **Python**: find an existing venv with `whisperx` installed. Check, in order:
   - A `.venv/` in the current project directory
   - Common project directories under the user's workspace
   Run `python -c "import whisperx"` against each candidate. Use the first one that imports cleanly. Only if none found, create one and install `whisperx` (this is heavy — torch alone is ~2GB — so reuse aggressively).
2. **Models**: whisperX downloads models to `~/.cache/huggingface/hub/` (the `medium` model is ~1.5GB) and the wav2vec2 alignment model to `~/.cache/torch/hub/`. These persist across runs. If a model is already cached, the transcribe step skips the download — don't pre-download anything yourself.
3. **ffmpeg**: required for audio extraction and subtitle burning. Run `ffmpeg -version`; if missing, tell the user to install it (don't try to install it yourself on Windows).
4. **yt-dlp**: required for downloading videos and thumbnails from YouTube. Check `python -c "import yt_dlp"`. If missing, install with `pip install yt-dlp`. YouTube requires cookies for authentication — use `--cookies-from-browser firefox` (or chrome). YouTube also requires a JS runtime for challenge solving — use `--js-runtimes node --remote-components ejs:github`.

The completion criterion for this step: you can name the exact `python` path you'll use for transcription, and ffmpeg is on PATH. Don't proceed to transcription until both are confirmed.

### GPU detection — determines compute_type

Run `python -c "import torch; print(torch.cuda.is_available())"`. This decides the transcription compute_type:

- **CUDA available (NVIDIA GPU)**: use `compute_type=float16` — much faster, same accuracy.
- **No CUDA (CPU only, including AMD GPUs)**: use `compute_type=float32` — most accurate on CPU. **Do NOT use float16 on CPU** — it will crash with `ValueError: Requested float16 compute type, but the target device or backend do not support efficient float16 computation`. Do NOT use `int8` — it quantizes and loses accuracy (e.g. "How we doing" → "How are we doing").

AMD GPUs (e.g. RX 6750 XT) are NOT usable by PyTorch/CUDA on Windows. If the machine has only an AMD GPU or integrated graphics, treat it as CPU-only.

## Execution strategy — running long tasks without timeout

Background Bash tasks in some environments have a ~10 minute timeout. whisperX transcription and ffmpeg encoding can both exceed this for long videos. **Do not use chunking or segmentation to work around the timeout** — that destroys transcription quality (sentences cut at chunk boundaries) and creates ASS timestamp alignment bugs in burned video.

Instead, **launch the process detached** so it survives the timeout:

**Windows** (use `start /b`):
```bat
@echo off
cd /d "<project-dir>"
"<python>" "<skill>/scripts/transcribe.py" "<input.wav>" "<output.srt>" large-v3 float32 >> "<log>" 2>&1
echo DONE >> "<log>"
```
Launch with: `cmd.exe /c "start /b /min <wrapper.bat>"`

The Bash call that launches it returns immediately. The detached process keeps running. Monitor by checking the log file or `tasklist /FI "IMAGENAME eq python.exe"`.

**Linux/macOS** (use `nohup`):
```bash
nohup python <skill>/scripts/transcribe.py <input.wav> <output.srt> large-v3 float32 > <log> 2>&1 &
```

Verify the process survives past the timeout before relying on it: write a heartbeat test (a script that appends to a file every 30s for 15 min), launch it detached, and check it's still alive after 10 minutes.

## The pipeline

### Step 1 — Extract audio

whisperX needs 16kHz mono WAV:

```bash
ffmpeg -y -i "input.mp4" -vn -ac 1 -ar 16000 -c:a pcm_s16le "input.wav"
```

Done when `input.wav` exists and is non-empty.

### Step 2 — Transcribe (whisperX, the slow step)

```bash
python <skill>/scripts/transcribe.py input.wav input.en.srt [model_size] [compute_type]
```

`<skill>` is this skill's folder (wherever it's installed — `.agents/skills/video-subtitle` or `.claude/skills/video-subtitle`). Use the absolute path.

**Model**: default `large-v3` (most accurate, ~3GB). Use `medium` only if the user asks for speed over accuracy. On CPU with `float32`, large-v3 runs at roughly 0.5–0.7x realtime — a 17-minute video takes ~25-35 min, a 107-minute video takes ~50-60 min. Models download on first run only.

**compute_type**: default `float32` (CPU, no quantization). If CUDA is available (see GPU detection above), pass `float16` for a major speedup. **Never use `int8`** — it quantizes and loses accuracy. **Never use `float16` on CPU** — it crashes.

**Never chunk the audio.** Process the entire audio file in one call. whisperX internally uses 30-second sliding windows — chunking at boundaries breaks sentences and makes subtitles not match speech. If the task times out, use the detached execution strategy above, not chunking.

Done when `input.en.srt` exists with one segment per cue. Tell the user this step is slow and they should expect to wait.

### Step 3 — Translate (the agent does this, not a script)

This is the step that makes the quality. You — the agent running this skill — translate the English SRT into Chinese yourself. You have the full transcript, you understand context, and you'll catch ASR errors that the transcription model made.

The English SRT is your **source of meaning and timing**, not a rigid grid to fill cell-by-cell. whisperX cuts on speech pauses, which often splits one sentence across 2-3 cues or merges two sentences into one. Your Chinese cues must follow **Chinese sentence boundaries**, not the English cue boundaries. A viewer reads the Chinese — if it's chopped into word-fragments to match English pauses, it's unreadable.

**The core principle: translate as a human would.** Read the English transcript, understand what's being said, and write Chinese that reads naturally. Then lay those Chinese sentences onto the timeline so each appears while its English is spoken. Specifically:

- **One Chinese cue = one complete thought / clause.** If English split one sentence across cues 12-13-14, the Chinese for that sentence goes on whichever cue best fits (usually the longest, or split across them at a natural Chinese pause — not at the English word boundary). Never produce a Chinese cue that's a fragment like "惯例" or "的" or "pfetch" alone.
- **Never fragment Chinese to mirror English fragmentation.** If matching the English cue grid would leave you with a ≤2-character Chinese line, that line is wrong — merge it into the neighbour. The English stays long on screen; the Chinese condenses the same meaning into a clean short line.
- **Commands, keyboard shortcuts, file paths, and proper nouns are atomic — never split them across cues.** whisperX often cuts mid-utterance: "open our ZSH" / "rc and there you go" or "hit control" / "S to save". You MUST reassemble these in translation: `.zshrc` stays whole on one cue, `Ctrl+S` stays whole, `source .zshrc` stays whole. The cue boundary is not an excuse to break a command in half. When you spot a cue ending in `ZSH`, `control`, `Esc`, `cd`, etc. with the rest of the term in the next cue, merge them — move the whole term to whichever cue has room, adjust the other cue's wording to stay coherent. This is the single most embarrassing failure mode: a viewer sees "ZSH" then "rc" on two lines and knows the translator wasn't paying attention.
- **Fix ASR errors while you translate.** Proper nouns, technical terms, and commands are routinely mis-transcribed (e.g. "matpocock" → "mattpocock", "SimLink" → "symlink", "Claw Code" → "Claude Code", "matzilla" → ".mozilla", "scrub menu" → "GRUB menu"). The agent has context the transcription model didn't — use it. If a word sounds like a known command/term but is spelled weird in the transcript, it's a transcription error; write the correct form.
- **Keep technical terms in English where Chinese devs would.** Don't translate "skills", "agent", "token", "context window", "CLI" etc. into Chinese — that's how the audience reads them.
- **Translate technical concepts naturally, not literally.** "observability platform" → "监控平台" (not "可观测性平台" which sounds unnatural in Chinese). "to-do app" → "待办应用". When a concept has a common Chinese name, use it. When it doesn't, keep the English term.
- **Chinese cue length ≤ 42 characters.** Hard limit (Bilibili). But the floor matters just as much: no cue should be a bare word or punctuation. If you can't fill a cue with at least a short complete phrase, the cue shouldn't exist as a standalone — fold it in.
- **Tone: faithful, not marketing.** Translate what's said. Don't add emoji, don't punch up "神级/必看", don't editorialize.

**Self-review — two passes, mandatory, not optional.** This is where the quality lives. Translating cell-by-cell always produces fragmentation you can't see while writing it. You must read the finished zh.srt cold, as a viewer would, twice:

- **Pass 1 — read every cue as a sentence.** Does it read like something a person would say? Fix any cue that is ≤ 2 characters, ends mid-word/mid-clause, or is a sentence broken across cues at a point no speaker would pause. Read each cue together with the one before and after — a cue that looks fine alone may be a fragment in context.
- **Pass 2 — scan cue boundaries for split atoms.** Look at every place where one cue ends and the next begins. If the boundary falls inside a command (`.zshrc`, `source`), a shortcut (`Ctrl+S`, `Alt+F4`, `Super+D`), a file path, or a proper noun (Gruvbox, VSCodium, pfetch), that's a bug — reassemble the whole term onto one cue. This pass exists specifically because these splits are invisible when you read each cue in isolation but jump out immediately when you scan boundaries.

A run is not done until both passes are complete. If you find one split command, assume there are more — keep scanning until the boundary list is clean. The test: could a viewer screenshot any single cue and have it make sense on its own? If not, fix it.

Done when `<name>.zh.srt` exists, has the same cue count and timestamps as `<name>.en.srt`, every Chinese cue is ≤ 42 characters, and both review passes above passed.

### Step 4 — Shorten, then merge into bilingual SRT + ASS

**Shorten first, always — for the burned video too, not just cloud subtitles.** whisperX regularly emits cues spanning several sentences (one cue, 100+ characters), and the translator may split long cues further. If you merge those raw, the burned video gets multi-line walls of text. So before merging, run `shorten` on each language to split long cues at sentence punctuation and redistribute timestamps:

```bash
python <skill>/scripts/subtitles.py shorten input.en.srt input.en.short.srt --lang en
python <skill>/scripts/subtitles.py shorten input.zh.srt input.zh.short.srt --lang zh
```

Defaults are zh ≤ 42 chars, en ≤ 90. These are the same limits the cloud-srt path uses; apply them here so the burned video and the soft subtitles are consistent.

**Then merge short cues back together (the step shorten misses).** Char-based shorten splits words mid-character and leaves fragments: orphan punctuation (`。`, `s.`), single-letter tails (`t.`, `d.`), and sub-second cues (0.05s — a flash no one can read). These make the burned video flicker and the cloud upload look broken. After shortening, merge any cue shorter than a minimum duration into its neighbour, and absorb punctuation-only cues. A reference `merge_short.py` for this lives in the per-video `scripts/` folder — write one if it's not there. Run it on **both** en and zh (they share timestamps, so the same merges apply and they stay 1:1):

```bash
python <skill>/scripts/merge_short.py input.en.short.srt input.en.merged.srt 1.2
python <skill>/scripts/merge_short.py input.zh.short.srt input.zh.merged.srt 1.2
```

`1.2` is the minimum cue duration in seconds — the broadcast-subtitle floor (viewers need ~1s to read a line). After merging, verify: no cue under 1.0s, no punctuation-only cue, no cue whose text is a single character. The merged files become your en.srt / zh.srt for the rest of the pipeline. If merging produces a cue over the char limit (zh > 42), trim that cue's wording — don't split it back into a flash.

**Then merge the two shortened files.** If they have the same cue count and aligned timestamps (translator kept 1:1), use `biliteral`:

```bash
python <skill>/scripts/subtitles.py biliteral input.en.short.srt input.zh.short.srt input.bilingual.srt
```

If the cue counts differ (the translator split some cues), `biliteral` will warn about a mismatch and pair by min-count — that drops cues. Instead merge by timestamp overlap, which handles differing granularity without joining sentences. A small merge helper for this lives in the per-video `scripts/` folder; write one if it's not there (union of all cue boundaries, emit per-interval, coalesce identical consecutive text, never concatenate cue texts into one line).

Then generate the ASS from the merged bilingual SRT:

```bash
python <skill>/scripts/subtitles.py ass input.bilingual.srt input.bilingual.ass
```

If the user only wants single-language output, skip the merge — but still shorten the single language before burning.

**Subtitle placement — ask the user which they want.** Two modes, producing different ASS files:

- **Overlay** (default): subtitles render on top of the picture. The command above.
- **Bottom-bar**: subtitles sit in a black strip padded below the frame, so nothing in the image is covered. Add `--bottom-bar PX`:

  ```bash
  python <skill>/scripts/subtitles.py ass input.bilingual.srt input.bilingual.bar.ass --bottom-bar 180
  ```

  The ASS play resolution grows by `PX` (1080 → 1260) and subtitles land in the strip. A 180px bar fits the two-line bilingual layout on 1080p; ~120px for single-language. Step 5 must `pad` the frame to match, or subtitles render off-screen. Name the bar variant `<name>.bilingual.bar.ass` to keep it apart from the overlay one.

Don't generate both unless the user asks — pick one and use it.

Done when the chosen ASS exists **and** every cue in the merged bilingual SRT is within length limits (verify: max zh line ≤ 42, max en line ≤ 90). If any cue is over, the shorten didn't propagate — go back and shorten the source before merging.

### Step 5 — Burn subtitles into video

Hard-burn with libass. Use the command that matches the placement chosen in Step 4.

**Overlay** (default):

```bash
ffmpeg -y -i "input.mp4" -vf "ass=input.bilingual.ass" -c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart "input.cooked.mp4"
```

**Bottom-bar** (only with `--bottom-bar PX` in Step 4 — pad a black strip below the frame first, then burn the ASS whose play resolution already accounts for the bar):

```bash
ffmpeg -y -i "input.mp4" -vf "pad=iw:ih+PX:color=black,ass=input.bilingual.bar.ass" -c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart "input.cooked.bar.mp4"
```

`PX` is the same value passed to `--bottom-bar`. Filters run left-to-right: `pad` grows the frame, `ass` renders into the grown area. Output height becomes `source_height + PX`.

Two gotchas we hit and you will too:

- **Windows paths with `C:` break the ass filter** — the filter parses `:` as an option separator. Run ffmpeg from the directory containing the ASS and pass a **relative** filename (`ass=input.bilingual.ass`), never an absolute `C:\...` path.
- **ASS timestamps need zero-padded minutes** (`0:00:06.07`, not `0:0:6.7`). The `ass` subcommand handles this; if you hand-write ASS, mind the format.

Re-encoding a 17-minute 1080p video takes ~3-5 minutes with `preset faster`. A 100+ minute video takes ~15-20 minutes. For long videos, use the detached execution strategy to avoid timeout. **Never use segmented/chunked encoding** — it creates ASS timestamp misalignment and concat issues. Burn the full video in one pass.

Done when `input.cooked.mp4` exists, plays, and a spot-check frame at a speaking timestamp shows subtitles rendered (the cue for that timestamp is visible). To verify without eyeballing: extract a frame and check the bottom strip has bright (white) pixels above ~2% density — that's the subtitle text. In bottom-bar mode also confirm the image region itself is untouched.

### Step 6 — Write the upload metadata

The user is going to post this somewhere. Give them a ready-to-paste title, description, and chapter list — derived from the transcript you just translated, so it actually matches the video. Write it to `<name>.upload.md`.

This is authoring work, like Step 3. You — the agent — write it from the transcript. No script.

**No Markdown formatting in the actual description text.** Platforms like Bilibili don't render Markdown — `**bold**` shows as literal asterisks. Use plain text with line breaks. The upload.md file itself can use Markdown headings to organize sections, but the copy-paste content must be plain text.

**Titles — provide multiple, per platform.** Different platforms need different styles. Provide at least:

- **B站**: professional, shows what the video is about. Can be up to ~30 chars. Include the author's identity (e.g. repo name) if it's recognizable.
- **小红书**: ≤20 characters. Same professional tone as B站, just shorter. Don't use marketing/clickbait language ("大佬带你", "效率翻倍").
- **YouTube**: can include "(双语字幕)" or English title variant.

The title should tell the viewer **what happens in the video** (e.g. "从零搭建一个全新项目"), not use jargon they'd need the description to understand (e.g. don't put "Agent可观测性平台" in the title — that's for the description).

**Description — provide two versions:**

1. **Full version (B站/YouTube)**: 3-4 paragraphs — who the author is (link their repo/handle), what the project is, how they approached it, and a subtitle note. Include "看点" and "关键内容" sections with bullet points. Include source links.
2. **Short version (小红书置顶评论, ≤300 chars)**: just the first 3 paragraphs + subtitle note, compressed. No "看点", no "关键内容", no source links — they waste the 300-char budget.

**Chapters — per platform, format HH:MM:SS.**

All chapter timestamps must use `HH:MM:SS` format (e.g. `01:03:00`), not `MM:SS` — videos over 60 minutes need the hours digit.

Different platforms have different limits:
- **B站**: max 10 chapters
- **小红书**: max 15 chapters
- **YouTube**: no hard limit, but keep reasonable

Generate a full chapter list (for pinned comments) AND a platform-specific trimmed list for each platform's chapter feature. Chapter names must be **≤11 characters**.

To pull the cover image, use yt-dlp:
```bash
python -m yt_dlp --cookies-from-browser firefox --js-runtimes node --remote-components ejs:github --write-thumbnail --skip-download -o "cooked/cover.%(ext)s" "<youtube-url>"
```
Then convert to JPG: `ffmpeg -y -i cover.webp cover.jpg`

Same tone rule as Step 3: translator, not promoter.

Done when `<name>.upload.md` exists with per-platform titles, two description versions, per-platform chapter lists (all in HH:MM:SS, names ≤11 chars), and a cover image.

### Step 7 — Write the per-video README

The very last step: write `README.md` at the root of the per-video directory, per the spec in the "The README.md — required, not optional" subsection above. Do this after every other artifact exists, so the index reflects what's actually on disk.

Done when `README.md` exists at the per-video root, with the header, the index table, the artifacts-by-purpose list, and the processing log. Verify by reading it cold: can you find any given artifact from it alone? If not, the index isn't doing its job — fix it.

## Platform notes (only if the user asks about uploading)

- **Bilibili cloud subtitles**: only accepts SRT, one language per upload. Run `python <skill>/scripts/subtitles.py split input.bilingual.srt out.zh.srt out.en.srt` to get pure-language files. Upload each separately. **SRT must have no BOM and no empty cues** — the scripts handle this automatically, but if you edited a file manually, verify. Name the files simply `zh.srt` / `en.srt` (not `name.zh-cloud.srt`) — filenames with multiple dots can cause issues.
- **Bilibili length limit**: ~45 Chinese chars / ~90 ASCII per cue. The `shorten` subcommand fixes cues that exceed this: `python <skill>/scripts/subtitles.py shorten input.zh.srt output.zh.srt --lang zh`. Run it if a cue got rejected on upload.
- **Bilibili chapters**: max 10 chapters, timestamps in `HH:MM:SS` format, names ≤11 characters.
- **小红书 chapters**: max 15 chapters, same format requirements.
- **Hard-burned MP4**: works everywhere, no toggle. Hand the user both the cooked MP4 and the SRTs — they decide at upload time which to use (cooked MP4 for platforms that don't support soft subs, raw video + SRT for platforms that do).
