"""Merge cues shorter than MIN_DUR into an adjacent cue, and drop cue whose text
is only punctuation (absorb into neighbour). Reindexes sequentially.

Fixes the fragmentation left by char-based shorten: word-split fragments like
"t." / "ade." produce sub-second cues and orphan punctuation. After this pass,
every cue lasts >= MIN_DUR (default 1.2s) unless it's the last cue or can't
merge (e.g. a standalone very-short utterance at the very start).

Run on BOTH en.srt and zh.srt so they stay 1:1 aligned. They share the same
timestamps, so the same merges apply.

Usage: python merge_short.py <in.srt> <out.srt> [min_dur_seconds]
"""
import re, sys

MIN_DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 1.2

def parse(path):
    cues = []
    for b in re.split(r'\n\s*\n', open(path, encoding='utf-8').read().strip()):
        nl = [l for l in b.split('\n') if l.strip()]
        if len(nl) < 3:
            continue
        m = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', nl[1])
        g = list(map(int, m.groups()))
        s = g[0]*3600 + g[1]*60 + g[2] + g[3]/1000
        e = g[4]*3600 + g[5]*60 + g[6] + g[7]/1000
        cues.append([s, e, nl[2]])
    return cues

def is_punct_only(t):
    return not re.search(r'[A-Za-z0-9\u4e00-\u9fff]', t)

def merge(cues):
    out = []
    for c in cues:
        s, e, t = c
        dur = e - s
        # Decide: merge this cue into the previous one?
        if out and (dur < MIN_DUR or is_punct_only(t)):
            # absorb: extend previous cue's end, append text
            out[-1][1] = e
            sep = '' if is_punct_only(t) or is_punct_only(out[-1][2]) else ' '
            # don't double-append identical text
            if t.strip() and t.strip() not in out[-1][2]:
                out[-1][2] = out[-1][2] + sep + t.strip()
        else:
            out.append([s, e, t])
    # second pass: any remaining short cue at the start or between long ones —
    # if still < MIN_DUR and has a neighbour, merge forward into next
    return out

def fmt(ts):
    h = int(ts//3600); m = int((ts%3600)//60); s = ts%60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s-int(s))*1000)):03d}"

cues = parse(sys.argv[1])
merged = merge(cues)
# repeat until stable (a merge can leave a still-short previous cue)
for _ in range(3):
    new = merge(merged)
    if len(new) == len(merged):
        break
    merged = new

lines = []
for i, (s, e, t) in enumerate(merged, 1):
    lines.append(f"{i}\n{fmt(s)} --> {fmt(e)}\n{t.strip()}")
open(sys.argv[2], 'w', encoding='utf-8').write('\n\n'.join(lines) + '\n')

durs = [e - s for s, e, _ in merged]
print(f"{sys.argv[1]}: {len(cues)} -> {len(merged)} cues, "
      f"min {min(durs):.2f}s, <{MIN_DUR}s 的 {sum(1 for d in durs if d<MIN_DUR)} 条")
