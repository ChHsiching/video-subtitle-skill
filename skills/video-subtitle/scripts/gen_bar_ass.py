"""Generate a bar-mode ASS where ZH and EN are ONE dialogue block joined by \\N.
This avoids libass collision detection bumping EN above ZH when EN wraps.
The whole block sits in the bottom bar, ZH line on top, EN line(s) below."""
import re, sys

def parse(path):
    cues = []
    for b in re.split(r'\n\s*\n', open(path, encoding='utf-8').read().strip()):
        nl = [l for l in b.split('\n') if l.strip()]
        if len(nl) < 3: continue
        m = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', nl[1])
        g = list(map(int, m.groups()))
        s = g[0]*3600+g[1]*60+g[2]+g[3]/1000
        e = g[4]*3600+g[5]*60+g[6]+g[7]/1000
        zh = nl[2] if len(nl) > 2 else ""
        en = nl[3] if len(nl) > 3 else ""
        cues.append((s, e, zh, en))
    return cues

def ass_ts(ts):
    h = int(ts//3600); m = int((ts%3600)//60); s = ts%60
    return f"{h:d}:{m:02d}:{int(s):02d}.{int(round((s-int(s))*100)):02d}"

header = """[Script Info]
Title: Bilingual ZH-EN (bar)
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1260

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bilingual,Microsoft YaHei,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

cues = parse(sys.argv[1])
out = [header]
for s, e, zh, en in cues:
    # One block: ZH on top, EN below, joined by \N. EN in smaller size via override.
    # {\fs44} shrinks the EN line within the block; ZH uses style default (58).
    block = f"{zh}" + (f"\\N{{\\fs36}}{en}" if en else "")
    out.append(f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Bilingual,,0,0,0,,{block}")

open(sys.argv[2], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(f"wrote {len(cues)} bilingual blocks -> {sys.argv[2]}")
