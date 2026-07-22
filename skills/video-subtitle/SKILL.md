---
name: video-subtitle
description: Turn a foreign-language raw video into a bilingual (or single-language) subtitled cooked video. Use when the user wants to add subtitles to a video, mentions 生肉/熟肉/双语字幕/字幕翻译, or asks to transcribe and translate a video for posting to Bilibili/Douyin/YouTube.
---

Turn a **raw** video (foreign audio, no subtitles) into a **cooked** video with bilingual or single-language subtitles. The agent does the translation itself — no external translation API.

Deterministic execution (audio extraction, transcription, subtitle processing, burning) is handled by the [`cook`](https://github.com/ChHsiching/video-cook) CLI. The agent focuses on the creative work the CLI can't do: translation, copywriting, quality judgment. If `cook` is not installed, the scripts in `scripts/` still work directly — see REFERENCE.md.

## What you produce

By default, for a bilingual run, the **shipment** — the full release set:

1. `transcript/<name>.en.srt` — English source transcript
2. `transcript/<name>.zh.srt` — Chinese translation
3. `transcript/asr-fixes.md` — ASR errors you fixed while translating (Step 3)
4. `subtitle/<name>.bilingual.srt` — bilingual SRT (zh line on top, en below)
5. `subtitle/<name>.bilingual.ass` — styled ASS for hard-burning (overlay), or `<name>.bilingual.bar.ass` (bottom-bar)
6. `cloud-srt/zh.srt`, `cloud-srt/en.srt` — single-language SRTs for platforms that accept soft subs
7. `cooked/<name>.cooked.mp4` (or `.cooked.bar.mp4`) — video with subtitles burned in
8. `cooked/<name>.upload.md` — title, description, chapters for uploading (Step 6)
9. `cooked/cover.jpg` — publish cover
10. `README.md` — the index for this video's directory (Step 7)

Produce everything by default. The shipment is the unit of "done" — see Step 8.

## Directory layout

Every video's outputs go into a per-video subdirectory, split into folders named after the pipeline stage. `<name>` is the same stem across all files. `<output-root>` defaults to `<cwd>/<author>/<video-name>/`.

```
<output-root>/
├── README.md                       ← the index — always present (Step 7)
├── raw/                            source video + metadata + cover (from video-download)
│   ├── <name>.raw.mp4
│   ├── <name>.source.json
│   └── <name>.jpg
├── transcript/                     Step 1–3: audio + English transcript + translation
│   ├── <name>.audio.wav
│   ├── <name>.en.srt
│   ├── <name>.zh.srt
│   ├── translations.txt            your working file (one Chinese line per English cue)
│   └── asr-fixes.md                ASR errors you fixed (Step 3)
├── subtitle/                       Step 4: bilingual merge + ASS
│   ├── <name>.bilingual.srt
│   └── <name>.bilingual.{,bar.}ass
├── cloud-srt/                      Step 4: single-language SRTs for soft-sub platforms
│   ├── zh.srt
│   └── en.srt
├── cooked/                         Step 5–6: burned video + upload metadata + cover
│   ├── <name>.cooked.{,bar.}mp4
│   ├── <name>.upload.md
│   └── cover.jpg
└── scripts/                        any helper scripts you write for this run
```

Rules:
- **`<name>` is the same stem across all files in the run.**
- **Each stage folder holds only that stage's outputs** — don't put cooked MP4 next to raw. Copy across rather than reach across.
- **`cloud-srt/` is a default product**, not lazy. It's cheap to produce (Step 4 copies from the per-language merged files) and users will ask for it at upload time. Files are named simply `zh.srt` / `en.srt` — no multi-dot names.

## The pipeline

### Step 0 — Ensure the shared environment

cook CLI and whisperx must live in **one persistent shared Python environment** — install once, every video project reuses it. torch alone is ~2GB; reinstalling per-project is the failure mode this step exists to prevent.

This is the agent's job, not the user's. The user never has to think about which Python whisperx is in.

**0a. Find or create the shared environment.** Check these locations in order; use the first that has cook installed:

1. A `VIDEO_TOOLS_VENV` environment variable (explicit user override).
2. `~/.venvs/video-tools/` (the conventional shared location).
3. The system Python (if cook is already pip-installed there and not in a project-local venv).

If none exists, create one and install cook into it:

```bash
python -m venv ~/.venvs/video-tools
~/.venvs/video-tools/Scripts/pip install video-cook[all]   # Windows
# or: ~/.venvs/video-tools/bin/pip install video-cook[all]  # macOS/Linux
```

`[all]` pulls yt-dlp + whisperx + torch in one shot. This is the only time the 2GB download happens.

**0b. Always invoke cook via the shared environment's interpreter**, never the project-local Python. Resolve the cook binary as `<venv>/Scripts/cook.exe` (Windows) or `<venv>/bin/cook` (macOS/Linux). The user's shell PATH does not matter — agent computes the absolute path itself.

**0c. Run doctor from the shared environment:**

```
<shared-venv>/Scripts/cook doctor    # Windows
<shared-venv>/bin/cook doctor        # macOS/Linux
```

Read the JSON. `cook doctor` checks the Python it's running in — so by invoking the shared-venv cook, you're checking the shared environment's whisperx/torch/yt_dlp. If any are missing despite 0a (shouldn't happen, but a partial install can), re-run `pip install video-cook[all]` in the shared venv. `ffmpeg` and `node` are system-level — if missing, tell the user to install them (cook can't pip-install those).

Done when the shared environment exists, cook is invoked from it, and doctor reports `whisperx`, `yt_dlp`, `torch`, `ffmpeg`, `node` all installed.

**`cook` in every step below means the shared-environment cook binary resolved here**, not whatever `cook` happens to be on PATH. The agent computes the absolute path once in 0b and uses it throughout.

**Why this matters**: `cook transcribe` runs its detached subprocess via `sys.executable` — the Python cook itself is running in. whisperx must be importable from that exact Python. By pinning all cook invocations to the shared environment, every video project transparently reuses the one whisperx install. Models cache under `~/.cache/huggingface/hub/` and `~/.cache/torch/hub/`, also shared across projects for free.

### Step 1 — Extract audio

```
cook extract <output-root> <name>
```

Produces `transcript/<name>.audio.wav` (16kHz mono WAV, the format whisperX needs).

Done when `cook extract` exits 0. (The old manual `ffmpeg -y -i ... -vn -ac 1 -ar 16000 -c:a pcm_s16le ...` is what cook runs internally — see REFERENCE.md if you need to run it without cook.)

### Step 2 — Transcribe (the slow step)

```
cook transcribe <output-root> <name> [--model large-v3] [--compute auto] [--language en]
```

Auto-detects CUDA: `--compute auto` picks `float16`+`cuda` if a GPU is available, else `float32`+`cpu`. Never use `int8` — it quantizes and loses accuracy. The command **detaches automatically** — cook launches the transcription in a detached process and returns immediately with a JSON object containing `pid`, `log`, `err_log`, and `done_marker`. Poll the `log` file until it contains the `done_marker` string (`[transcribe] done.`) — that signals the subprocess finished.

**Never chunk the audio.** Process the entire file in one call. whisperX uses 30-second sliding windows internally; chunking at boundaries breaks sentences and desyncs subtitles. The detached launch exists specifically to avoid timeouts without chunking.

Tell the user this is slow: CPU + `large-v3` runs at roughly 0.5–0.7× realtime (a 75-minute video takes ~50–90 minutes). While it runs, you can pre-read the partial transcript and start drafting the upload metadata.

Done when `transcript/<name>.en.srt` exists and the log file contains the `done_marker` string.

### Step 2b — Audit ASR output (fix proper nouns before translating)

whisperX routinely mis-transcribes proper nouns, product names, and technical terms. If you translate from the raw ASR output, these errors propagate into the Chinese and the burned video — and they are embarrassing when viewers catch them. **Fix the English transcript first, then translate from the clean version.**

Read the full `transcript/<name>.en.srt` end to end. Scan for:

- **Words that look like mis-spelled product/project names.** "Clawed Code" → Claude Code, "Soundcastle" → Sandcastle, "Groom" → GrillMe, "OpenClaw" → OpenCode. If a proper noun is spelled in a way no real product is, it's an ASR error.
- **Words you don't recognize.** If the transcript mentions a tool, project, or person you haven't heard of, **search the web to confirm what it actually is** before deciding it's an error. Do not assume an unfamiliar name is wrong and replace it with something you find more plausible — that is how "Pi" (a real coding agent by Mario Zechner) got replaced with "Crush" (a different product). When in doubt, search; when still in doubt, leave the original spelling.
- **Inconsistent spelling of the same term.** If the same tool appears as "Py" in one cue and "PI" in another, it's the same word — figure out the correct form and unify.
- **Names from the source context.** Run `cook show-source <output-root> <name>` and extract every proper noun from the source description/tags. These are your ground-truth spellings. Cross-reference the transcript against them.

For each fix, edit `transcript/<name>.en.srt` in place and log it to `transcript/asr-fixes.md`:

```
<ASR output> → <correct form> — <one line of context or how you confirmed it>
```

If you searched the web to confirm, note the search query you used.

Done when: every proper noun in `en.srt` has been verified (either confirmed correct or fixed), `asr-fixes.md` lists every change you made, and no unrecognized proper nouns remain. This is a **gate** — do not start Step 3 until this passes.

### Step 3 — Translate (the agent does this, not a script)

This is the step that makes the quality. You — the agent running this skill — translate the English SRT into Chinese yourself. By this point, Step 2b has already cleaned the transcript's proper nouns — you're translating from a verified English source, not guessing at ASR errors.

**Read the source context first.** Before translating, pull the source platform's own metadata — it's authoritative context the transcript can't give you:

```
cook show-source <output-root> <name>
```

This surfaces the original title, uploader, channel, links, duration, and crucially the **source description** — which often contains the video's topic outline, chapter titles, mentioned tools/people/projects, and terminology. Use it to:

- **Resolve ambiguous proper nouns.** The source description/tags usually name the tools, people, and projects mentioned. Cross-reference with Step 2b's audit — if you missed something there, fix it now and log to `asr-fixes.md`.
- **Understand the video's structure before you start.** The description's chapter outline (if present) tells you the arc of the video, so you translate section transitions with the right framing.
- **Match the author's own terminology.** If the description calls something a "crash course", your translation should reflect that, not invent a different term.

Write translations to `transcript/translations.txt` — **one Chinese line per English cue, line N = cue N** (1-based). Keep the line count exactly equal to the cue count. A helper script (`scripts/make_zh.py` or similar) reads translations.txt + en.srt's timestamps and emits `<name>.zh.srt`. This avoids hand-writing timestamps.

The English SRT is your **source of meaning and timing**, not a rigid grid to fill cell-by-cell. whisperX cuts on speech pauses, which often splits one sentence across 2-3 cues or merges two sentences into one. Your Chinese cues must follow **Chinese sentence boundaries**, not the English cue boundaries. A viewer reads the Chinese — if it's chopped into word-fragments to match English pauses, it's unreadable.

**The core principle: translate as a human would.** Read the English transcript, understand what's being said, and write Chinese that reads naturally. Then lay those Chinese sentences onto the timeline so each appears while its English is spoken. Specifically:

- **One Chinese cue = one complete thought / clause.** If English split one sentence across cues 12-13-14, the Chinese for that sentence goes on whichever cue best fits (usually the longest, or split across them at a natural Chinese pause — not at the English word boundary). Never produce a Chinese cue that's a fragment like "惯例" or "的" or "pfetch" alone.
- **Never fragment Chinese to mirror English fragmentation.** If matching the English cue grid would leave you with a ≤2-character Chinese line, that line is wrong — merge it into the neighbour. The English stays long on screen; the Chinese condenses the same meaning into a clean short line.
- **Commands, keyboard shortcuts, file paths, and proper nouns are atomic — never split them across cues.** whisperX often cuts mid-utterance: "open our ZSH" / "rc and there you go" or "hit control" / "S to save". You MUST reassemble these in translation: `.zshrc` stays whole on one cue, `Ctrl+S` stays whole, `source .zshrc` stays whole. The cue boundary is not an excuse to break a command in half. When you spot a cue ending in `ZSH`, `control`, `Esc`, `cd`, etc. with the rest of the term in the next cue, merge them — move the whole term to whichever cue has room, adjust the other cue's wording to stay coherent. This is the single most embarrassing failure mode: a viewer sees "ZSH" then "rc" on two lines and knows the translator wasn't paying attention.
- **Keep technical terms in English where Chinese devs would.** Don't translate "skills", "agent", "token", "context window", "CLI" etc. into Chinese — that's how the audience reads them.
- **Translate technical concepts naturally, not literally.** "observability platform" → "监控平台" (not "可观测性平台" which sounds unnatural). "to-do app" → "待办应用". When a concept has a common Chinese name, use it. When it doesn't, keep the English term.
- **Chinese cue length ≤ 42 characters.** Hard limit (Bilibili). But the floor matters just as much: no cue should be a bare word or punctuation. If you can't fill a cue with at least a short complete phrase, the cue shouldn't exist as a standalone — fold it in.
- **Tone: faithful, not marketing.** Translate what's said. Don't add emoji, don't punch up "神级/必看", don't editorialize.

**Self-review — two passes, mandatory, not optional.** This is where the quality lives. Translating cell-by-cell always produces fragmentation you can't see while writing it. You must read the finished zh.srt cold, as a viewer would, twice:

- **Pass 1 — read every cue as a sentence.** Does it read like something a person would say? Fix any cue that is ≤ 2 characters, ends mid-word/mid-clause, or is a sentence broken across cues at a point no speaker would pause. Read each cue together with the one before and after — a cue that looks fine alone may be a fragment in context.
- **Pass 2 — scan cue boundaries for split atoms.** Look at every place where one cue ends and the next begins. If the boundary falls inside a command (`.zshrc`, `source`), a shortcut (`Ctrl+S`, `Alt+F4`, `Super+D`), a file path, or a proper noun (Gruvbox, VSCodium, pfetch), that's a bug — reassemble the whole term onto one cue. This pass exists specifically because these splits are invisible when you read each cue in isolation but jump out immediately when you scan boundaries.

A run is not done until both passes are complete. If you find one split command, assume there are more — keep scanning until the boundary list is clean. The test: could a viewer screenshot any single cue and have it make sense on its own? If not, fix it.

**Then run mechanical alignment verification** — this catches drift that pass-by-pass reading can't (a translation that's off-by-one for the whole second half; one Chinese line accidentally covering two English cues):

```
cook verify-align <output-root> <name>
```

Exit 0 = perfectly aligned. Non-zero = `missing_translations` and/or `extra_translations` are listed in the JSON output — fix translations.txt and re-run until exit 0.

Done when `<name>.zh.srt` exists, `cook verify-align` exits 0, `transcript/asr-fixes.md` lists every ASR error you fixed, and both review passes above passed. (Note: cue count matching is enforced by verify-align, not by hand-counting — the translator may legitimately merge short cues, and the downstream `biliteral` merge handles mismatched counts via timestamp-union.)

### Step 4 — Subtitles (shorten + merge-short + biliteral + ASS + cloud-srt)

```
cook subtitles <output-root> <name> [--mode overlay|bottom-bar] [--bar-px 180]
```

Runs the full subtitle-processing pipeline in one shot:
- `shorten` both languages (split long cues at sentence punctuation)
- `merge-short` both (fold <1.2s fragments and punctuation-only cues into neighbours)
- `biliteral` merge into bilingual SRT (handles mismatched cue counts via timestamp-union)
- `ass` generate styled ASS (overlay or bottom-bar)
- copies `*.merged.srt` to `cloud-srt/{zh,en}.srt` (does NOT split from bilingual.srt — see REFERENCE.md for why)

**Subtitle placement** — two modes, producing different ASS files:
- **Overlay** (default): subtitles render on top of the picture. Use when the video has low information density in the lower frame (talking head, slides with margin).
- **Bottom-bar** (`--mode bottom-bar --bar-px 180`): subtitles sit in a black strip padded below the frame. Use when the video has high information density throughout (IDE demos, terminal sessions, UI walkthroughs) — nothing in the image is covered. A 180px bar fits the two-line bilingual layout on 1080p.

Don't generate both unless the user asks — pick one.

Done when `cook subtitles` exits 0 and the JSON output reports no `length_issues`. If there are length issues, the source cues were over the limit before shorten — investigate and re-run Step 3 fixes.

### Step 5 — Burn subtitles into video

```
cook burn <output-root> <name> [--mode overlay|bottom-bar] [--bar-px 180]
```

Hard-burns subtitles into the video via ffmpeg + libass. Auto-detaches (returns a JSON object with `pid`, `log`, `err_log`, `done_marker`; poll the `log` file until it contains the `done_marker` string `kb/s` — ffmpeg prints bitrate stats as the final step). Audio is transcoded to AAC (source Opus in mp4 breaks iMovie/QuickTime/小红书). Cook runs ffmpeg from the subtitle/ directory with a bare ASS filename — this avoids the Windows `C:` path trap that breaks the `ass` filter.

**Never use segmented/chunked encoding** — it creates ASS timestamp misalignment. Burn the full video in one pass.

Re-encoding a 17-minute 1080p video takes ~3-5 minutes. A 75-minute video takes ~10-15 minutes. While it runs, draft Step 6 and Step 7.

Done when `cooked/<name>.cooked.{,bar.}mp4` exists, `ffprobe` reports a duration matching the raw (cook checks this), and a spot-check frame at a speaking timestamp shows subtitles rendered.

### Step 6 — Write the upload metadata

The user is going to post this somewhere. Give them a ready-to-paste title, description, and chapter list — derived from **two sources**: the transcript you just translated (what actually happens in the video) and the source context (who the author is, where to find them, the source's own framing). Write it to `cooked/<name>.upload.md`. This is authoring work, like Step 3 — no script.

If you haven't already, run `cook show-source <output-root> <name>` to pull the source context (original title, uploader, uploader_url, webpage_url, description). You'll need these for the author blurb and source links below.

**No Markdown formatting in the actual description text.** Platforms like Bilibili don't render Markdown — `**bold**` shows as literal asterisks. Use plain text with line breaks. The upload.md file itself can use Markdown headings to organize sections, but the copy-paste content must be plain text.

**Titles — provide multiple, per platform:**
- **B站**: professional, shows what the video is about. Up to ~30 chars. Include the author's identity (from source context `uploader`/`channel`) if recognizable.
- **小红书**: ≤20 characters. Same professional tone as B站, just shorter. Don't use marketing language ("大佬带你", "效率翻倍").
- **YouTube**: can include "(双语字幕)" or the English title variant (from source context `title`).

The title should tell the viewer **what happens in the video** (e.g. "从零搭建一个全新项目"), not use jargon they'd need the description to understand.

**Description — provide two versions:**
1. **Full version (B站/YouTube)**: 3-4 paragraphs — who the author is (link their repo/handle from source context `uploader_url`), what the project is, how they approached it, subtitle note. Include "看点" and "关键内容" sections with bullet points. Include source links (the `webpage_url` from source context, plus any links the author put in their description).
2. **Short version (小红书置顶评论, ≤300 characters)**: just the first 3 paragraphs + subtitle note, compressed. No "看点", no "关键内容", no source links — they waste the 300-char budget. **Character count = every character including spaces and punctuation** (this is how the platform counts). Verify with `len()` after writing; if over 300, compress.

The subtitle note is fixed wording — use it verbatim:
> 字幕：AI 辅助转录 + 翻译并经人工校对。如有不准确之处，欢迎指出。

**Chapters — two products, different rules:**
- **Platform chapter fields** (B站 ≤10, 小红书 ≤15, YouTube reasonable): timestamps in `HH:MM:SS`, **names ≤11 characters**. This is the hard platform limit.
- **Pinned-comment chapter list** (full, detailed): timestamps in `HH:MM:SS`, names have no length limit — this is for a pinned comment under the video, not the platform's chapter field. Longer descriptive names are fine and useful here.

All chapter timestamps must use `HH:MM:SS` (e.g. `01:03:00`), not `MM:SS` — videos over 60 minutes need the hours digit.

Same tone rule as Step 3: translator, not promoter.

**Place the cover:**
```
cook cover <output-root> <name>
```

Copies `raw/<name>.jpg` to `cooked/cover.jpg`. Done when `cooked/cover.jpg` exists.

Done when `cooked/<name>.upload.md` exists with per-platform titles, two description versions (short ≤300 chars), per-platform chapter lists (HH:MM:SS, platform-field names ≤11 chars), and `cooked/cover.jpg` exists.

### Step 7 — Write the per-video README

The per-video directory **must** contain a `README.md` at its root. It is the index: someone (including you, months later) opens the folder and immediately knows what each subdirectory holds and where to find each artifact. Write it as the final step, after every artifact exists.

It must contain:
- **Header**: source author, original URL, duration, resolution, processing date. Pull the author/URL/duration/upload_date from `cook show-source` (the source context); resolution comes from `ffprobe` on the raw mp4; processing date is today.
- **An index table** — one row per subdirectory, columns `去哪找 | 目录 | 里面是什么`. Use the user's language (Chinese if the run is Chinese-facing).
- **An artifacts-by-purpose list** — group files by what the user will do with them: "直接发 B 站" (cooked mp4 + upload.md + cover.jpg), "传 B 站云字幕" (cloud-srt/{zh,en}.srt, each uploaded separately), "存档/二次加工" (raw + per-language srts + ass). This answers "I want to do X, which file?"
- **Processing log**: transcription engine + model + device, who translated (you), ASR errors you fixed (reference `transcript/asr-fixes.md`), burn settings (overlay vs bottom-bar, CRF, preset), verification checks ran (duration match, subtitle-render spot-check, verify-align exit 0).

Done when `README.md` exists at the per-video root with header, index table, artifacts-by-purpose list, and processing log.

### Step 8 — Verify the shipment

```
cook verify-shipment <output-root> <name>
```

The final gate. Checks that every file in the shipment (listed in "What you produce" above) exists, plus cross-checks (e.g. cooked.mp4 duration matches raw.mp4). Exit 0 = the shipment is complete and ready to publish. Non-zero = the `missing` list tells you what to go back and produce.

Done when `cook verify-shipment` exits 0. The run is not done until this passes — "the agent feels done" is not a completion criterion.

## Reference

The following details are pushed out of this file because they're consulted on demand, not every run. Load them when the situation calls for it:

- **[REFERENCE.md](REFERENCE.md)** — environment-reuse details (venv hunting, model cache paths), GPU detection (CUDA/AMD/float16/float32 tradeoffs), detached-execution internals (what `cook _detach` does, the old `windows-detached.ps1` template), the raw ffmpeg/yt-dlp/whisperx commands cook runs internally (for running without cook), the Windows `ass`-filter path gotcha, why `cook subtitles` copies merged SRTs instead of running `subtitles.py split` (the union-mode cue-leak bug), platform upload notes (Bilibili/小红书/YouTube limits, soft-sub vs hard-burn strategy), and the length/counting rules in detail.
