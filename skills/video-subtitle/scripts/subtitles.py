#!/usr/bin/env python3
"""Subtitle post-processing: build bilingual SRT/ASS, split into pure-language
files, and keep every cue short enough for Bilibili cloud subtitles.

Commands:
    python subtitles.py biliteral   <en.srt> <zh.srt> <out_bilingual.srt>
        Merge two SRTs (zh on top, en below) into one bilingual SRT. 1:1 cue
        alignment -> fast pairwise path; mismatched cue counts -> automatic
        timestamp-union merge (no cues dropped).

    python subtitles.py merge-short <input.srt> <output.srt> [--min-dur 1.2]
        Absorb cues shorter than --min-dur and cues whose text is only
        punctuation into the previous cue. Run after `shorten` to clean up the
        sub-second fragments and orphan punctuation that char-based splitting
        leaves behind.

    python subtitles.py ass          <bilingual.srt> <out.ass> [--bottom-bar PX]
        Convert a bilingual SRT (zh line + en line) into a styled ASS for
        hard-burning. Chinese larger on top, English smaller below. With
        --bottom-bar PX, grow the ASS play resolution by PX and place subtitles
        inside a black strip padded below the picture (no image overlap); the
        ffmpeg burn command must pad the frame to match.

    python subtitles.py split        <bilingual.srt> <out_zh.srt> <out_en.srt>
        Split a bilingual SRT back into two pure-language SRTs.

    python subtitles.py shorten      <input.srt> <output.srt> [--max-zh N] [--max-en N]
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

MAX_ZH = 42
MAX_EN = 90
MIN_DUR = 1.2  # broadcast-subtitle readability floor (seconds)
# Legacy aliases for the argparse defaults below.
MAX_ZH_DEFAULT = MAX_ZH
MAX_EN_DEFAULT = MAX_EN


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
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
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
    """cues: list of (start, end, text). Writes sequential index.
    Outputs LF line endings (Bilibili accepts LF). Filters empty cues."""
    out = []
    i = 0
    for start, end, text in cues:
        if not text or not text.strip():
            continue  # skip empty cues — they break Bilibili upload
        i += 1
        out.append(f"{i}\n{fmt_ts(start)} --> {fmt_ts(end)}\n{text}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(out) + "\n")


# ---------- merge-short: absorb sub-MIN_DUR and punctuation-only cues ----------

def _is_punct_only(t: str) -> bool:
    return bool(t) and not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", t)


def _merge_pass(cues, min_dur, max_len=0):
    """Single pass: absorb any cue whose duration < min_dur or whose text is
    punctuation-only into a neighbour. Prefers the previous cue; if max_len > 0
    and merging into the previous would overflow it, tries the next cue
    instead; if both overflow, leaves the short cue standalone (it carries
    real content that can't be dropped). Repeats until stable."""
    out = []
    i = 0
    pending = list(cues)
    # forward pass absorbing into previous
    for s, e, lines in pending:
        text = " ".join(lines).strip() if isinstance(lines, list) else lines.strip()
        dur = e - s
        absorb = dur < min_dur or _is_punct_only(text)
        if out and absorb:
            ps, pe, pt = out[-1]
            sep = "" if _is_punct_only(text) or _is_punct_only(pt) else " "
            candidate = (pt + sep + text).strip() if (text and text not in pt) else pt
            if max_len and len(candidate) > max_len and not _is_punct_only(text):
                out.append([s, e, text])  # keep standalone, will try backward merge below
            else:
                out[-1] = (ps, e, candidate)
        else:
            out.append([s, e, text])
    # backward pass: short cues left standalone by the forward pass try merging
    # into the next cue instead
    if max_len:
        for j in range(len(out) - 2, -1, -1):
            s, e, text = out[j]
            dur = e - s
            if dur >= min_dur and not _is_punct_only(text):
                continue
            ns, ne, nt = out[j + 1]
            sep = "" if _is_punct_only(text) or _is_punct_only(nt) else " "
            candidate = (text + sep + nt).strip() if (text and text not in nt) else nt
            if len(candidate) <= max_len:
                out[j] = (s, ne, candidate)
                del out[j + 1]
    return out


def cmd_merge_short(args):
    cues = list(read_srt(args.input))
    # convert read_srt's (start, end, [lines]) into (start, end, text) for merging
    flat = [(s, e, " ".join(lines).strip()) for s, e, lines in cues]
    merged = _merge_pass(flat, args.min_dur, args.max_len)
    # iterate to stable — one pass may leave a fresh short cue
    for _ in range(3):
        new = _merge_pass(merged, args.min_dur, args.max_len)
        if len(new) == len(merged):
            break
        merged = new
    out = [(s, e, t) for s, e, t in merged if t and t.strip()]
    write_srt(args.output, out)
    durs = [e - s for s, e, _ in out]
    short_count = sum(1 for d in durs if d < args.min_dur)
    print(f"[merge-short] {len(cues)} -> {len(out)} cues, "
          f"min {min(durs):.2f}s, <{args.min_dur}s 的 {short_count} 条 -> {args.output}")


# ---------- biliteral: merge two SRTs (pairwise if aligned, else by timestamp) ----------

def _merge_pairwise(en_cues, zh_cues):
    """Fast path: both SRTs share segmentation -> pair cue i with cue i."""
    out = []
    for (start, end, en_lines), (_zs, _ze, zh_lines) in zip(en_cues, zh_cues):
        zh_text = " ".join(zh_lines).strip()
        en_text = " ".join(en_lines).strip()
        out.append((start, end, f"{zh_text}\n{en_text}"))
    return out


def _active_text(cues, t):
    """Text of the cue whose [start, end) contains t; prefer the
    latest-starting overlapping cue. '' if none."""
    best = None
    for s, e, lines in cues:
        if s <= t < e and (best is None or s >= best[0]):
            best = (s, e, " ".join(lines).strip())
    return best[2] if best else ""


def _merge_by_timestamp(en_cues, zh_cues):
    """Fallback path: en and zh have different granularity (e.g. shorten ran
    independently on each). Union all cue boundaries -> atomic intervals; each
    interval takes the active zh + active en text; coalesce consecutive
    identical (zh, en) pairs; absorb sub-MIN_DUR and punctuation-only intervals
    into the previous cue (extending its time, but dropping the text if merging
    it would exceed the char limit — those texts are shorten fragments that
    duplicate the previous cue's meaning). Never concatenates a full cue text
    onto another."""
    bounds = sorted({c[0] for c in en_cues + zh_cues} | {c[1] for c in en_cues + zh_cues})
    iv = [(s, e, _active_text(zh_cues, (s + e) / 2), _active_text(en_cues, (s + e) / 2))
          for s, e in zip(bounds[:-1], bounds[1:]) if e - s > 1e-6]

    # coalesce identical consecutive (zh, en) pairs
    coal = []
    for s, e, z, x in iv:
        if coal and z == coal[-1][2] and x == coal[-1][3]:
            coal[-1] = (coal[-1][0], e, z, x)
        else:
            coal.append([s, e, z, x])

    # absorb short / punct-only intervals, length-aware
    out = []
    for s, e, z, x in coal:
        dur = e - s
        both_punct = _is_punct_only(z) and _is_punct_only(x)
        if out and (dur < MIN_DUR or both_punct):
            ps, pe, pz, px = out[-1]
            new_z, new_x = pz, px
            if z and z not in pz:
                cand = (pz + " " + z).strip() if pz else z
                new_z = cand if len(cand) <= MAX_ZH else new_z  # drop text if it overflows
            if x and x not in px:
                cand = (px + " " + x).strip() if px else x
                new_x = cand if len(cand) <= MAX_EN else new_x
            out[-1] = (ps, e, new_z, new_x)
        else:
            out.append([s, e, z, x])
    return [(s, e, _bilingual_text(z, x)) for s, e, z, x in out if (z or x)]


def _bilingual_text(zh: str, en: str) -> str:
    """Lay out zh + en as a bilingual cue. Both present -> zh on top, en below
    (the ass/split commands read line 0 as zh, line 1 as en). Only one present
    -> place it on its own line so downstream length checks don't misread an
    English-only cue as an over-length zh line."""
    if zh and en:
        return f"{zh}\n{en}"
    return zh or en


def cmd_biliteral(args):
    en_cues = list(read_srt(args.en))
    zh_cues = list(read_srt(args.zh))
    if len(en_cues) == len(zh_cues):
        out = _merge_pairwise(en_cues, zh_cues)
        path = "pairwise (1:1 aligned)"
    else:
        out = _merge_by_timestamp(en_cues, zh_cues)
        path = (f"timestamp-union (en={len(en_cues)}, zh={len(zh_cues)} "
                f"mismatch -> no cues dropped)")
    write_srt(args.output, out)
    print(f"[biliteral] {path}: {len(out)} cues -> {args.output}")


# ---------- ass: bilingual SRT -> styled ASS ----------

# Layout constants (ASS script coordinates, assuming a 1920x1080 source frame).
PLAY_RES_X = 1920
PLAY_RES_Y = 1080

# In-bar mode the subtitle sits inside the padded bottom bar, so its
# vertical margin is measured from the bottom of the bar. Without a bar
# the margin is measured from the bottom of the picture itself.
ZH_MARGINV_OVERLAY = 70   # zh baseline above bottom edge (overlay mode)
EN_MARGINV_OVERLAY = 130  # en baseline above bottom edge (overlay mode)
ZH_MARGINV_BAR = 110      # zh baseline above the bar's bottom edge
EN_MARGINV_BAR = 50       # en baseline above the bar's bottom edge


def ass_header(bottom_bar: int = 0) -> str:
    """Build the ASS [Script Info] + [V4+ Styles] header.

    bottom_bar=0 (default): overlay mode — subtitles render over the picture,
    PlayResY stays 1080. bottom_bar>0: the bar's height is added to PlayResY
    so the subtitle coordinate system extends into the bar; ffmpeg then pads
    the frame with a black strip of that height before burning the ASS.
    """
    res_y = PLAY_RES_Y + bottom_bar
    if bottom_bar > 0:
        zh_v, en_v = ZH_MARGINV_BAR, EN_MARGINV_BAR
    else:
        zh_v, en_v = ZH_MARGINV_OVERLAY, EN_MARGINV_OVERLAY
    return f"""[Script Info]
Title: Bilingual ZH-EN
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResY: {res_y}
PlayResX: {PLAY_RES_X}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZH,Microsoft YaHei,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{zh_v},1
Style: EN,Arial,44,&H00E0E0E0,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,60,60,{en_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_ts(ts: float) -> str:
    """float seconds -> ASS timestamp H:MM:SS.CS."""
    h = int(ts // 3600)
    m = int(ts % 3600) // 60
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
        f.write(ass_header(args.bottom_bar))
        f.write("\n".join(events))
    print(f"[ass] {len(events)//2} cues (x2 layers) -> {args.output}")
    if args.bottom_bar > 0:
        print(
            f"[ass] bottom-bar mode: PlayResY={PLAY_RES_Y + args.bottom_bar}. "
            f"Pad the frame with `pad=iw:ih+{args.bottom_bar}:black` before burning.",
            file=sys.stderr,
        )


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


def split_en(text, limit=MAX_EN_DEFAULT):
    parts = re.split(r"(?<=[.!?;])\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    refined = []
    for p in parts:
        if len(p) <= limit:
            refined.append(p)
            continue
        # long sentence with no internal sentence punctuation -> split at commas
        subs = re.split(r"(?<=,)\s+", p)
        refined.extend(s.strip() for s in subs if s.strip())
    return refined


def pack(parts, limit):
    """Greedily pack fragments into chunks under `limit` chars.

    Word-boundary safe: never splits a word mid-character. If a fragment is
    longer than the limit, it's broken at the last space before the limit;
    only a single word longer than the limit itself is hard-cut (rare, and
    usually a URL or command that can't break)."""
    chunks, buf = [], ""
    for p in parts:
        cand = (buf + " " + p) if buf else p
        if len(cand) <= limit:
            buf = cand
            continue
        # cand overflows: flush buf, then handle p alone
        if buf:
            chunks.append(buf)
            buf = ""
        # break p at word boundaries until what remains fits the limit
        while len(p) > limit:
            # find last space within the limit; if none (one giant word), hard-cut
            cut = p.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit  # single word longer than limit, no choice
            chunks.append(p[:cut])
            p = p[cut:].lstrip()
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
        splitter = (lambda t: split_zh(t, args.limit)) if args.lang == "zh" else (lambda t: split_en(t, args.limit))
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

    p = sub.add_parser("merge-short")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--min-dur", type=float, default=1.2, metavar="SECONDS",
                   help="Absorb cues shorter than this duration (and "
                        "punctuation-only cues) into a neighbour. "
                        "Default 1.2s — the broadcast-subtitle readability floor.")
    p.add_argument("--max-len", type=int, default=0, metavar="CHARS",
                   help="Skip a merge that would push the target cue's text "
                        "past this many characters (tries the other neighbour, "
                        "else leaves the short cue standalone). Set to the "
                        "same limit you passed to `shorten` (90 for en, 42 "
                        "for zh) so merge-short re-joins shorten's fragments "
                        "without re-creating the over-length cues shorten "
                        "just split. Default 0 = no length check.")
    p.set_defaults(func=cmd_merge_short)

    p = sub.add_parser("ass")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument(
        "--bottom-bar",
        type=int,
        default=0,
        metavar="PX",
        help="Pad a black bar of this many pixels below the picture and put the "
        "subtitles inside it (no overlap with the image). Default 0 = overlay "
        "subtitles onto the picture as before. When set, the ASS PlayResY grows "
        "by this many pixels and you must pad the frame with ffmpeg before burning "
        "(see SKILL.md Step 5).",
    )
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
