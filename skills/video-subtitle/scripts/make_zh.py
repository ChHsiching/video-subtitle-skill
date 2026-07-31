"""Build <name>.zh.srt from <name>.en.srt timestamps + translations.txt.

translations.txt holds one Chinese line per English cue (line N = cue N, 1-based).
This script lifts the timestamps from en.srt and overlays the Chinese text,
producing zh.srt without hand-writing timestamps. Run from the per-video root:

    python <skill>/scripts/make_zh.py [<output-root>] [<name>]

Defaults: output-root = cwd, name = the single en.srt found under transcript/.
Verifies line count == cue count before writing.
"""
import re, sys
from pathlib import Path


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
    trans = root / "transcript" / "translations.txt"
    zh_srt = root / "transcript" / f"{name}.zh.srt"
    for p in (en_srt, trans):
        if not p.exists():
            sys.exit(f"missing input: {p}")

    # parse en.srt cues: keep index + timecode, drop the English text
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
        cues.append((int(lines[0]), m.group(1), m.group(2)))

    zh_lines = [ln.rstrip("\n") for ln in trans.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    if len(cues) != len(zh_lines):
        sys.exit(f"count mismatch: en.srt has {len(cues)} cues, "
                 f"translations.txt has {len(zh_lines)} lines")

    out = [f"{i}\n{start} --> {end}\n{zh}"
           for (i, start, end), zh in zip(cues, zh_lines)]
    zh_srt.write_text("\n\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {zh_srt}: {len(out)} cues")


if __name__ == "__main__":
    main()
