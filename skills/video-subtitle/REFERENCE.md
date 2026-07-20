# video-subtitle — Reference

Loaded on demand from [SKILL.md](SKILL.md) when the situation calls for it. The main skill file is the pipeline skeleton; this file holds the details you consult only when something needs explaining or cook isn't available.

## Why cook exists

The pipeline used to be a wall of `ffmpeg` / `yt-dlp` / `python subtitles.py ...` commands that the agent hand-assembled every run. Three classes of bugs recurred:

1. **Shell escaping traps** — Windows paths with `C:` break ffmpeg's `ass` filter (it parses `:` as an option separator); backslashes get eaten by PowerShell; `--dump-json > file.json` stdout redirects silently swallowed downloads.
2. **Hand-assembly drift** — the agent forgets a flag, picks the wrong template variable, renames the wrong file.
3. **No mechanical completion check** — "the agent feels done" shipped without `cover.jpg`, without `cloud-srt/`, with translation drift the agent couldn't see.

[`cook`](https://github.com/ChHsiching/video-cook) is the single place where commands are assembled. Each step's completion criterion becomes "cook exit 0", which is checkable.

If cook is not installed, the scripts in `scripts/` (`transcribe.py`, `subtitles.py`) still work directly — commands below show both forms. Install cook with `pip install video-cook[all]` to get the wrappers.

## Environment reuse — never reinstall blindly

Before touching the pipeline, check what's already on disk. `cook doctor` does this for you:

```
cook doctor
```

Reports `ffmpeg`, `node`, `yt_dlp`, `whisperx`, `torch` (+ CUDA availability) as JSON. Read the `issues` list and tell the user what to install only when something's missing.

Manual equivalents (if running without cook):
- **Python venv with whisperx**: check `.venv/` in the current project, then common project dirs. Run `python -c "import whisperx"` against each candidate. Reuse the first that imports cleanly. Only install fresh if none found — torch alone is ~2GB, so reuse aggressively.
- **ffmpeg**: `ffmpeg -version`. Required for extract + burn + cover conversion. If missing, tell the user to install it (don't try to install it yourself on Windows).
- **yt-dlp**: `python -c "import yt_dlp"`. If missing, `pip install yt-dlp`.
- **Models**: whisperX caches to `~/.cache/huggingface/hub/` (medium ~1.5GB, large-v3 ~3GB) and wav2vec2 alignment to `~/.cache/torch/hub/`. These persist across runs — don't pre-download.

## GPU detection — determines compute_type

`cook transcribe --compute auto` handles this automatically. The decision tree:

- **CUDA available (NVIDIA GPU)**: `device=cuda`, `compute_type=float16` — much faster, same accuracy.
- **No CUDA (CPU only, including AMD GPUs)**: `device=cpu`, `compute_type=float32` — most accurate on CPU.
  - **Never `float16` on CPU** — crashes with `ValueError: Requested float16 compute type, but the target device or backend do not support efficient float16 computation`.
  - **Never `int8`** — quantizes and loses accuracy (e.g. "How we doing" → "How are we doing").

AMD GPUs (e.g. RX 6750 XT) are NOT usable by PyTorch/CUDA on Windows. A machine with only an AMD GPU or integrated graphics is CPU-only.

Note: the old `scripts/transcribe.py` hardcoded `device="cpu"` in three places, so even passing `float16` would crash. `cook transcribe` fixes this — it parameterizes device based on the auto-detection above. If you must run `transcribe.py` directly, pass `compute_type=float32` to avoid the hardcoded-device bug.

## Detached execution — running long tasks without timeout

Background Bash tasks in some agent environments have a ~10 minute timeout. whisperX transcription and ffmpeg encoding both exceed this for long videos.

**Never chunk the audio or video to work around the timeout** — chunking destroys transcription quality (sentences cut at boundaries) and creates ASS timestamp misalignment in burned video. whisperX uses 30-second sliding windows internally; let it process the entire file in one call.

`cook transcribe` and `cook burn` detach automatically. Cook's `_detach()` helper:
- **Windows**: launches via PowerShell `Start-Process -WindowStyle Hidden -RedirectStandardOutput/RedirectStandardError`, returns immediately with PID.
- **Unix**: launches via `subprocess.Popen(start_new_session=True)` (equivalent to `setsid`), returns immediately with PID.

After either launch, the JSON output gives you `log` and `err_log` paths plus a `done_marker` string. Poll the log until it contains the done marker (e.g. `[transcribe] done.` or ffmpeg's final bitrate line).

The old `scripts/windows-detached.ps1` template is preserved for reference but is no longer the recommended path — cook's `_detach()` covers both transcribe and burn uniformly, and the template was transcribe-only.

## Raw commands cook runs internally

If cook is not installed or you need to debug what it's doing, here are the underlying commands.

### Step 1 — audio extraction (cook extract)
```
ffmpeg -y -i <raw.mp4> -vn -ac 1 -ar 16000 -c:a pcm_s16le <audio.wav>
```

### Step 2 — transcription (cook transcribe)
```
python <skill>/scripts/transcribe.py <audio.wav> <output.en.srt> [model_size] [compute_type] [language]
```
`<skill>` is this skill's folder. Use the absolute path — the user's video may be anywhere on disk.

Linux/macOS nohup wrapper (cook does this internally on Unix):
```
nohup python <skill>/scripts/transcribe.py <audio.wav> <output.srt> large-v3 float32 > <log> 2>&1 &
```

### Step 4 — subtitle processing (cook subtitles)
```
python <skill>/scripts/subtitles.py shorten <en.srt> <en.short.srt> --lang en
python <skill>/scripts/subtitles.py shorten <zh.srt> <zh.short.srt> --lang zh
python <skill>/scripts/subtitles.py merge-short <en.short.srt> <en.merged.srt> --min-dur 1.2 --max-len 90
python <skill>/scripts/subtitles.py merge-short <zh.short.srt> <zh.merged.srt> --min-dur 1.2 --max-len 42
python <skill>/scripts/subtitles.py biliteral <en.merged.srt> <zh.merged.srt> <bilingual.srt>
python <skill>/scripts/subtitles.py ass <bilingual.srt> <bilingual.ass>
# bottom-bar variant:
python <skill>/scripts/subtitles.py ass <bilingual.srt> <bilingual.bar.ass> --bottom-bar 180
```

### Step 5 — burn (cook burn)
```
# overlay
ffmpeg -y -i <raw.mp4> -vf "ass=<bilingual.ass>" -c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart <cooked.mp4>
# bottom-bar (pad frame first, then burn ASS whose PlayResY already accounts for the bar)
ffmpeg -y -i <raw.mp4> -vf "pad=iw:ih+180:color=black,ass=<bilingual.bar.ass>" -c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart <cooked.bar.mp4>
```

The audio stream is transcoded to AAC (`-c:a aac -b:a 192k`), not copied — source videos often carry Opus, and Opus inside mp4 breaks iMovie/QuickTime/小红书 ("unsupported audio format").

## The ass-filter path gotcha

Two ways Windows paths break ffmpeg's `ass` filter:

1. **Drive letter `C:`** — the filter parses `:` as an option separator. `ass=C:\path\to.ass` fails.
2. **Backslashes** — PowerShell and ffmpeg's command-line parsing can eat `\` in `ass=path\to.ass`, producing `assto.ass`.

Defence: **run ffmpeg from the directory containing the ASS and pass just the bare filename** (`ass=file.ass`). Never any path with a slash, backslash, or drive letter. `cook burn` does this automatically — it sets `cwd` to the subtitle/ directory and uses the bare ASS filename.

If you must run ffmpeg by hand and hit this, copy the ASS to the current directory first, or use the `subtitle/` directory as cwd.

## Why cook subtitles copies merged SRTs instead of running `subtitles.py split`

The old Platform notes said to produce single-language SRTs by running `subtitles.py split <bilingual.srt> <zh.srt> <en.srt>`. This has a subtle bug:

`biliteral` (Step 4's merge) takes a fast pairwise path when cue counts match, but falls back to a **timestamp-union** path when they don't (which is the normal case — translators legitimately merge short cues, so en and zh rarely have equal counts after merge-short). In union mode, when a timestamp has content in only one language, that single-language line gets inserted into the bilingual SRT as-is.

`subtitles.py split` then mechanically assigns "line 0 of each cue = zh, line 1 = en". When a cue has only an English line (because zh was empty at that timestamp), split puts that English line into `zh.srt`. Result: `zh.srt` contains English cues. Real-world observed: 21 cues in `zh.srt` were pure English, some up to 87 chars.

`cook subtitles` fixes this by **copying `transcript/<name>.{zh,en}.merged.srt` directly to `cloud-srt/{zh,en}.srt`**. These merged files are already clean single-language, already shortened, already merge-shorted, already within length limits. No split step, no cross-language leak.

If you need to run without cook: `cp transcript/<name>.zh.merged.srt cloud-srt/zh.srt` and `cp transcript/<name>.en.merged.srt cloud-srt/en.srt`. Don't run `subtitles.py split`.

## Platform upload notes

Consult when the user asks about uploading, or when authoring Step 6's upload.md.

### Bilibili cloud subtitles
- Only accepts SRT, one language per upload.
- Use `cloud-srt/zh.srt` and `cloud-srt/en.srt` (produced by Step 4). Upload each separately.
- Filenames must be simple (`zh.srt` / `en.srt`) — multi-dot names like `name.zh-cloud.srt` can cause issues.
- Files are no-BOM, no-empty-cue (subtitles.py's `write_srt` guarantees this).

### Length limits
- Bilibili: ~45 Chinese chars / ~90 ASCII per cue. The `shorten` + `merge-short` pipeline enforces this; if a cue gets rejected on upload, run `python <skill>/scripts/subtitles.py shorten <input.srt> <output.srt> --lang zh` as a remedial fix.
- 小红书 pinned-comment description: ≤300 characters. Count = every character including spaces and punctuation (how the platform counts). Compress if over.

### Chapter limits
- Bilibili chapter field: max 10 chapters, `HH:MM:SS` timestamps, names ≤11 characters.
- 小红书 chapter field: max 15 chapters, same format.
- YouTube: no hard chapter limit, keep reasonable.
- Pinned-comment chapter list (separate product): full detailed list, names have no length limit.

### Hard-burned MP4 vs soft subs
- Hard-burned (`cooked/<name>.cooked.{,bar.}mp4`): works everywhere, no toggle. Use on platforms that don't support soft subs, or when you want the subtitle style locked in.
- Soft subs (`cloud-srt/*.srt` + raw video): use on platforms that support soft subs (Bilibili cloud subtitles, YouTube). Lets viewers toggle subtitles and pick language. Smaller upload (raw video is unchanged), but the subtitle style is platform-controlled.

Hand the user both at upload time — they decide per platform.

## Length and counting rules (summary)

| Product | Limit | Counter |
|---|---|---|
| Chinese cue (`zh.srt`, `cloud-srt/zh.srt`) | ≤45 chars (Bilibili), ≤42 (internal target) | characters (Chinese counts as 1) |
| English cue (`en.srt`, `cloud-srt/en.srt`) | ≤90 ASCII | characters |
| 小红书 short description | ≤300 chars | every character incl. spaces+punctuation |
| Bilibili chapter field name | ≤11 chars | characters |
| 小红书 chapter field name | ≤11 chars | characters |
| Bilibili title | ~30 chars | characters |
| 小红书 title | ≤20 chars | characters |
