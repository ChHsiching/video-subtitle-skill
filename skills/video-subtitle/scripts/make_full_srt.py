"""Merge <name>.en.srt fragment cues at sentence-ending punctuation into
full-sentence cues, producing <name>.en.full.srt for downstream dubbing.

whisperX cuts on speech pauses, fragmenting one sentence across 2-3 cues.
That's fine for subtitles but bad for TTS dubbing, which synthesizes per cue
— a fragment like "and the" synthesizes badly. This script accumulates text
until it ends with sentence punctuation (. ! ?) and emits one cue per
complete sentence. The cue count drops (e.g. 151 fragments -> 141 sentences).

Run from the per-video root:

    python <skill>/scripts/make_full_srt.py [<output-root>] [<name>]

Produces transcript/<name>.en.full.srt. Skip if dubbing won't run.
"""
import re, sys
from pathlib import Path

SENT_END = re.compile(r'[.!?]["\']?\s*$')


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if len(sys.argv) > 2:
        name = sys.argv[2]
    else:
        srts = list((root / "transcript").glob("*.en.srt"))
        if not srts:
            sys.exit("no <name>.en.srt found under transcript/")
        name = srts[0].name[:-len(".en.srt")]

    en_srt = root / "transcript" / f"{name}.en.srt"
    out_srt = root / "transcript" / f"{name}.en.full.srt"
    if not en_srt.exists():
        sys.exit(f"missing input: {en_srt}")

    cues = []
    for block in en_srt.read_text(encoding="utf-8").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 3 or not re.match(r"\d+$", lines[0]):
            continue
        m = re.match(r"(\d\d:\d\d:\d\d,\d+) --> (\d\d:\d\d:\d\d,\d+)", lines[1])
        if not m:
            continue
        cues.append((m.group(1), m.group(2), " ".join(lines[2:])))

    merged = []
    buf_text = ""
    buf_start = None
    buf_end = None
    for start, end, text in cues:
        buf_start = buf_start or start
        buf_end = end
        buf_text = f"{buf_text} {text}".strip() if buf_text else text
        if SENT_END.search(buf_text):
            merged.append((buf_start, buf_end, buf_text))
            buf_text = ""
            buf_start = None
    if buf_text:  # trailing fragment with no terminal punctuation
        merged.append((buf_start, buf_end, buf_text))

    out = [f"{i}\n{start} --> {end}\n{text}"
           for i, (start, end, text) in enumerate(merged, 1)]
    out_srt.write_text("\n\n".join(out) + "\n", encoding="utf-8")
    print(f"merged {len(cues)} fragment cues -> {len(merged)} full-sentence cues -> {out_srt}")


if __name__ == "__main__":
    main()
