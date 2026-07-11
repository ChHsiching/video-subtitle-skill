#!/usr/bin/env python3
"""Subtitle post-processing: build bilingual SRT/ASS, split into pure-language
files, and keep every cue short enough for Bilibili cloud subtitles.

Commands:
    python subtitles.py biliteral  <en.srt> <zh.srt> <out_bilingual.srt>
        Merge two same-timeline SRTs (zh on top, en below) into one bilingual SRT.

    python subtitles.py ass         <bilingual.srt> <out.ass>
        Convert a bilingual SRT (zh line + en line) into a styled ASS for
        hard-burning. Chinese larger on top, English smaller below.

    python subtitles.py split       <bilingual.srt> <out_zh.srt> <out_en.srt>
        Split a bilingual SRT back into two pure-language SRTs.

    python subtitles.py shorten     <input.srt> <output.srt> [--max-zh N] [--max-en N]
        Split any cue longer than the limit on sentence punctuation, then
        hard-wrap, redistributing timestamps proportionally. Defaults:
        zh=42 chars, en=90 chars (Bilibili-safe).

Length control is the whole point of `shorten` and the reason this file
exists as one module: long cues get rejected by platforms (Bilibili's limit
is ~45 Chinese chars / ~90 ASCII per cue), and whisperX occasionally emits
one cue spanning several sentences. `shorten` fixes both: split on 。！？；／.!?;,
then hard-wrap at commas when a fragment still exceeds the limit.
"""
import sys
import re
import argparse

MAX_ZH_DEFAULT = 42
MAX_EN_DEFAULT = 90


# ---------- SRT parsing ----------

def parse_ts(tc: str) -> float:
    m = re.match(r"(\d+):(\d+):(\d+),(\d+)", tc.strip())
    h, mn, s, ms = map(int, m.groups())
    return h * 3600 + mn * 60 + s + ms / 1000


def fmt_ts(ts: float) -> str:
    h = int(ts // 3600)
    m = int((ts % 3600) // 60)
    s = ts % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def read_srt(path: str):
    """Yield (index, start, end, [text_lines])."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            continue
        tc = lines[1]
        m = re.match(r"(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)", tc)
        if not m:
            continue
        yield parse_ts(m.group(1)), parse_ts(m.group(2)), lines[2:]


def write_srt(path: str, cues):
    """cues: list of (start, end, text). Writes sequential index."""
    out = []
    for i, (start, end, text) in enumerate(cues, 1):
        out.append(f"{i}\n{fmt_ts(start)} --> {fmt_ts(end)}\n{text}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(out) + "\n")


# ---------- biliteral: merge two same-timeline SRTs ----------

def cmd_biliteral(args):
    # We pair by index — both SRTs must have the same segmentation (they do,
    # because the zh SRT was produced by translating the en SRT cue-for-cue).
    en_cues = list(read_srt(args.en))
    zh_cues = list(read_srt(args.zh))
    if len(en_cues) != len(zh_cues):
        print(
            f"[biliteral] WARNING: cue count mismatch "
            f"(en={len(en_cues)}, zh={len(zh_cues)}). Pairing by min count.",
            file=sys.stderr,
        )
    out = []
    for (start, end, _en_lines), (_zs, _ze, zh_lines) in zip(en_cues, zh_cues):
        zh_text = " ".join(zh_lines).strip()
        en_text = " ".join(_en_lines).strip()
        out.append((start, end, f"{zh_text}\n{en_text}"))
    write_srt(args.output, out)
    print(f"[biliteral] {len(out)} cues -> {args.output}")


# ---------- ass: bilingual SRT -> styled ASS ----------

ASS_HEADER = """[Script Info]
Title: Bilingual ZH-EN
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZH,Microsoft YaHei,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,70,1
Style: EN,Arial,44,&H00E0E0E0,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,60,60,130,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_ts(ts: float) -> str:
    """float seconds -> ASS timestamp H:MM:SS.CS."""
    h = int(ts // 3600)
    m = int((ts % 3600) // 60)
    s = ts % 60
    return f"{h:d}:{m:02d}:{int(s):02d}.{int(round((s - int(s)) * 100)):02d}"


def cmd_ass(args):
    events = []
    for start, end, text_lines in read_srt(args.input):
        s, e = ass_ts(start), ass_ts(end)
        zh = text_lines[0] if len(text_lines) > 0 else ""
        en = text_lines[1] if len(text_lines) > 1 else ""
        events.append(f"Dialogue: 0,{s},{e},ZH,,0,0,0,,{zh}")
        events.append(f"Dialogue: 0,{s},{e},EN,,0,0,0,,{en}")
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER)
        f.write("\n".join(events))
    print(f"[ass] {len(events)//2} cues (x2 layers) -> {args.output}")


# ---------- split: bilingual SRT -> two pure-language ----------

def cmd_split(args):
    zh_out, en_out = [], []
    for start, end, text_lines in read_srt(args.input):
        zh_text = text_lines[0] if len(text_lines) > 0 else ""
        en_text = text_lines[1] if len(text_lines) > 1 else ""
        zh_out.append((start, end, zh_text.strip()))
        en_out.append((start, end, en_text.strip()))
    write_srt(args.out_zh, zh_out)
    write_srt(args.out_en, en_out)
    print(f"[split] zh {len(zh_out)} cues -> {args.out_zh}")
    print(f"[split] en {len(en_out)} cues -> {args.out_en}")


# ---------- shorten: split long cues, hard-wrap, redistribute time ----------

def split_zh(text, limit=MAX_ZH_DEFAULT):
    parts = re.split(r"(?<=[。！？；])", text)
    parts = [p.strip() for p in parts if p.strip()]
    refined = []
    for p in parts:
        if len(p) <= limit:
            refined.append(p)
            continue
        subs = re.split(r"(?<=[，、])", p)
        refined.extend(s.strip() for s in subs if s.strip())
    return refined


def split_en(text):
    parts = re.split(r"(?<=[.!?;])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def pack(parts, limit):
    """Greedily pack fragments into chunks under `limit` chars."""
    chunks, buf = [], ""
    for p in parts:
        cand = buf + p
        if len(cand) <= limit:
            buf = cand
        else:
            if buf:
                chunks.append(buf)
            while len(p) > limit:
                chunks.append(p[:limit])
                p = p[limit:]
            buf = p
    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


def cmd_shorten(args):
    out, idx = [], 0
    cues = list(read_srt(args.input))
    for start, end, text_lines in cues:
        text = " ".join(text_lines).strip()
        dur = end - start
        if len(text) <= args.limit:
            idx += 1
            out.append((start, end, text))
            continue
        splitter = (lambda t: split_zh(t, args.limit)) if args.lang == "zh" else split_en
        parts = pack(splitter(text), args.limit) or [text]
        total = sum(len(p) for p in parts) or 1
        cur = start
        for p in parts:
            seg_end = min(cur + dur * (len(p) / total), end)
            idx += 1
            out.append((cur, seg_end, p))
            cur = seg_end
    write_srt(args.output, out)
    print(f"[shorten] {idx} cues (was {len(cues)}) -> {args.output}")


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("biliteral")
    p.add_argument("en")
    p.add_argument("zh")
    p.add_argument("output")
    p.set_defaults(func=cmd_biliteral)

    p = sub.add_parser("ass")
    p.add_argument("input")
    p.add_argument("output")
    p.set_defaults(func=cmd_ass)

    p = sub.add_parser("split")
    p.add_argument("input")
    p.add_argument("out_zh")
    p.add_argument("out_en")
    p.set_defaults(func=cmd_split)

    p = sub.add_parser("shorten")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--lang", choices=["zh", "en"], default="zh")
    p.add_argument("--max-zh", type=int, default=MAX_ZH_DEFAULT)
    p.add_argument("--max-en", type=int, default=MAX_EN_DEFAULT)
    p.set_defaults(func=cmd_shorten)

    args = parser.parse_args()
    if args.cmd == "shorten":
        args.limit = args.max_zh if args.lang == "zh" else args.max_en
    args.func(args)


if __name__ == "__main__":
    main()
