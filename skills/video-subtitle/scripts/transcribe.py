#!/usr/bin/env python3
"""Transcribe an audio/video file with whisperX and emit an SRT.

Usage:
    python transcribe.py <input.wav|mp4> <output.srt> [model_size] [compute_type] [language] [device]

- model_size defaults to "large-v3" (most accurate Whisper model, ~3GB).
- compute_type defaults to "float32" (most accurate on CPU). On CPU, only
  int8 / int8_float32 / float32 are supported — float16 will crash with
  ValueError. If an NVIDIA GPU with CUDA is available, pass "float16".
- language defaults to "en" (English). Pass a Whisper language code (ja, fr,
  es, de, zh, ...) for non-English sources; the alignment model loads to match.
- device defaults to "cpu". Pass "cuda" when compute_type is float16 and a
  NVIDIA GPU is available — never combine float16 with device=cpu (crashes).
  Prefer `cook transcribe --compute auto` which detects this automatically.
- Performs word-level alignment for accurate segment boundaries.
- Downloads models on first run, reuses from cache afterwards.
- Outputs LF line endings (Bilibili accepts LF).

Output SRT has one segment per cue — designed to be split/translated
downstream without fighting whisperX's segmentation.
"""
import sys
import time
import os

import whisperx


def fmt(ts: float) -> str:
    h = int(ts // 3600)
    m = int((ts % 3600) // 60)
    s = ts % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: transcribe.py <input> <output.srt> [model_size] [compute_type] [language] [device]", file=sys.stderr)
        sys.exit(1)

    audio_path = sys.argv[1]
    out_path = sys.argv[2]
    model_size = sys.argv[3] if len(sys.argv) > 3 else "large-v3"
    compute_type = sys.argv[4] if len(sys.argv) > 4 else "float32"
    language = sys.argv[5] if len(sys.argv) > 5 else "en"
    device = sys.argv[6] if len(sys.argv) > 6 else "cpu"

    print(f"[transcribe] model={model_size} device={device} compute_type={compute_type} language={language}", flush=True)
    t0 = time.time()

    model = whisperx.load_model(model_size, device=device, compute_type=compute_type)
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=8, language=language)
    print(f"[transcribe] base transcribe done in {time.time()-t0:.1f}s", flush=True)

    # Word-level alignment — whisperX's key advantage: accurate boundaries.
    try:
        align_model, meta = whisperx.load_align_model(language_code=language, device=device)
        result = whisperx.align(result["segments"], align_model, meta, audio, device=device)
        print(f"[transcribe] alignment done in {time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"[transcribe] alignment skipped: {e}", flush=True)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    lines = []
    for i, seg in enumerate(result["segments"], 1):
        text = seg["text"].strip()
        if not text:
            continue  # skip empty segments — they break Bilibili upload
        lines.append(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{text}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines) + "\n")

    elapsed = time.time() - t0
    audio_dur = result["segments"][-1]["end"] if result["segments"] else 0
    n = len(lines)
    print(
        f"[transcribe] done. {n} segments, audio~{audio_dur:.1f}s, "
        f"elapsed={elapsed:.1f}s ({audio_dur/elapsed:.2f}x realtime) -> {out_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()

