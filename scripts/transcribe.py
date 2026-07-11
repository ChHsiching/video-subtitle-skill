#!/usr/bin/env python3
"""Transcribe an audio/video file with whisperX and emit an SRT.

Usage:
    python transcribe.py <input.wav|mp4> <output.srt> [model_size]

- model_size defaults to "medium" (good accuracy on CPU, ~1.5GB).
- Runs on CPU with int8 quantization (fastest on CPU).
- Performs word-level alignment for accurate segment boundaries.
- Downloads models on first run, reuses from cache afterwards.

Output SRT has one segment per line — designed to be split/translated
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
        print("usage: transcribe.py <input> <output.srt> [model_size]", file=sys.stderr)
        sys.exit(1)

    audio_path = sys.argv[1]
    out_path = sys.argv[2]
    model_size = sys.argv[3] if len(sys.argv) > 3 else "medium"

    print(f"[transcribe] model={model_size} device=cpu compute_type=int8", flush=True)
    t0 = time.time()

    model = whisperx.load_model(model_size, device="cpu", compute_type="int8")
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=8, language="en")
    print(f"[transcribe] base transcribe done in {time.time()-t0:.1f}s", flush=True)

    # Word-level alignment — whisperX's key advantage: accurate boundaries.
    try:
        align_model, meta = whisperx.load_align_model(language_code="en", device="cpu")
        result = whisperx.align(result["segments"], align_model, meta, audio, device="cpu")
        print(f"[transcribe] alignment done in {time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"[transcribe] alignment skipped: {e}", flush=True)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    lines = []
    for i, seg in enumerate(result["segments"], 1):
        lines.append(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{seg['text'].strip()}\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    elapsed = time.time() - t0
    audio_dur = result["segments"][-1]["end"] if result["segments"] else 0
    n = len(result["segments"])
    print(
        f"[transcribe] done. {n} segments, audio~{audio_dur:.1f}s, "
        f"elapsed={elapsed:.1f}s ({audio_dur/elapsed:.2f}x realtime) -> {out_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
