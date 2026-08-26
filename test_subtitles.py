"""Tests for subtitles.py — CLI-level tests at the highest seam.

Run: python -m pytest test_subtitles.py -x
"""
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).parent / "skills" / "video-subtitle" / "scripts" / "subtitles.py"


def run_subs(*args, input_path=None):
    """Run subtitles.py with args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True
    )
    return result.returncode, result.stdout, result.stderr


def write_srt(path: Path, cues: list[tuple[str, str, str]]):
    """Write a minimal SRT file. cues = [(start, end, text), ...]"""
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def read_srt(path: Path) -> list[str]:
    """Read SRT, return list of text bodies (one per cue)."""
    content = path.read_text(encoding="utf-8")
    bodies = []
    for block in content.strip().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            bodies.append("\n".join(lines[2:]))
    return bodies


class TestPackZhWordBoundary:
    """pack_zh must not split English words embedded in Chinese text."""

    def test_english_word_not_split(self, tmp_path):
        """A ZH cue containing 'Skills' should not become 'Skill' + 's'."""
        inp = tmp_path / "in.srt"
        out = tmp_path / "out.srt"
        # A long ZH cue with embedded English that exceeds width limit
        # wlen: CJK=2, ASCII=1. Limit for zh is 56.
        # "我们有模型调用的 Skills 和用户调用的 Skills。" has wlen > 56? Let's make it long enough.
        text = "我们有模型调用的 Skills 和用户调用的 Skills。用户调用型 Skill 的好处。"
        write_srt(inp, [("00:00:00,000", "00:00:05,000", text)])
        rc, so, se = run_subs("shorten", str(inp), str(out), "--lang", "zh")
        assert rc == 0, f"shorten failed: {se}"
        bodies = read_srt(out)
        # Check no body ends with a partial English word
        for b in bodies:
            # No body should end with "Skill" without the "s" (or vice versa)
            assert not b.rstrip().endswith("Skill"), f"Word split: cue ends with 'Skill' (missing 's'): {b}"
            assert not b.rstrip().endswith("skill"), f"Word split: {b}"
        # Also check no body STARTS with a stray "s" or "ls" fragment
        for b in bodies:
            first_word = b.strip().split()[0] if b.strip() else ""
            assert not (len(first_word) <= 3 and first_word.isascii() and first_word.islower()
                        and not first_word in ('the', 'and', 'for', 'but', 'so', 'is', 'in', 'on', 'to', 'of')
                       ), f"Possible orphan fragment at start: '{first_word}' in cue: {b}"

    def test_chinese_still_cuts_by_width(self, tmp_path):
        """Pure Chinese cues should still be split by display width."""
        inp = tmp_path / "in.srt"
        out = tmp_path / "out.srt"
        # 40 Chinese chars = wlen 80 > limit 56
        text = "这是一段非常非常长的纯中文文本需要被按照显示宽度切断成多个字幕行" * 2
        write_srt(inp, [("00:00:00,000", "00:00:10,000", text)])
        rc, so, se = run_subs("shorten", str(inp), str(out), "--lang", "zh")
        assert rc == 0, f"shorten failed: {se}"
        bodies = read_srt(out)
        assert len(bodies) > 1, "Long Chinese text should be split into multiple cues"

    def test_short_cue_unchanged(self, tmp_path):
        """A short cue should pass through unchanged."""
        inp = tmp_path / "in.srt"
        out = tmp_path / "out.srt"
        text = "短文本"
        write_srt(inp, [("00:00:00,000", "00:00:02,000", text)])
        rc, so, se = run_subs("shorten", str(inp), str(out), "--lang", "zh")
        assert rc == 0
        bodies = read_srt(out)
        assert len(bodies) == 1
        assert "短文本" in bodies[0]


class TestBiliteralDedup:
    """biliteral must not repeat the same ZH text on adjacent output cues."""

    def test_no_adjacent_zh_duplication(self, tmp_path):
        """When one ZH cue spans two EN cues, the ZH text should appear once."""
        en_srt = tmp_path / "en.srt"
        zh_srt = tmp_path / "zh.srt"
        out = tmp_path / "out.srt"

        # EN: two cues with different text, close timestamps
        write_srt(en_srt, [
            ("00:00:00,000", "00:00:03,000", "Before we had model invoked skills."),
            ("00:00:03,000", "00:00:06,000", "And user invoked skills were hidden."),
        ])
        # ZH: one cue spanning both EN cues (longer duration)
        write_srt(zh_srt, [
            ("00:00:00,000", "00:00:06,000", "我们有模型调用的 Skills 和用户调用的 Skills。"),
        ])
        rc, so, se = run_subs("biliteral", str(en_srt), str(zh_srt), str(out))
        assert rc == 0, f"biliteral failed: {se}"
        bodies = read_srt(out)
        # Extract ZH lines (line 0 of each cue)
        zh_lines = [b.split("\n")[0] for b in bodies if b.strip()]
        # No two adjacent ZH lines should be identical
        for i in range(len(zh_lines) - 1):
            assert zh_lines[i] != zh_lines[i + 1], \
                f"Adjacent ZH duplication at cues {i+1}-{i+2}: '{zh_lines[i]}'"
        # Also check suffix overlap: cue[i]'s ZH should not be a suffix of cue[i+1]'s
        for i in range(len(zh_lines) - 1):
            zh_cur = zh_lines[i].strip()
            zh_next = zh_lines[i + 1].strip()
            if len(zh_cur) > 10 and len(zh_next) > 10:
                # If zh_next contains the entirety of zh_cur, that's duplication
                assert zh_cur not in zh_next or zh_next not in zh_cur, \
                    f"Adjacent ZH suffix overlap at cues {i+1}-{i+2}"
        # Verify all English text is preserved (no content lost in dedup)
        en_text = " ".join(b.split("\n")[1] for b in bodies if len(b.split("\n")) > 1)
        assert "Before we had model invoked skills." in en_text, "EN text lost in dedup"
        assert "And user invoked skills were hidden." in en_text, "EN text lost in dedup"


class TestAssStyleParams:
    """ass --fontsize and --marginv override the ZH Style line."""

    def test_custom_fontsize_and_marginv(self, tmp_path):
        """--fontsize 48 --marginv 5 --bottom-bar 70 produces correct ASS."""
        inp = tmp_path / "in.srt"
        out = tmp_path / "out.ass"
        write_srt(inp, [("00:00:00,000", "00:00:02,000", "中文\nEnglish")])
        rc, so, se = run_subs("ass", str(inp), str(out),
                              "--fontsize", "48", "--marginv", "5", "--bottom-bar", "70")
        assert rc == 0, f"ass failed: {se}"
        content = out.read_text(encoding="utf-8")
        assert "PlayResY: 1150" in content  # 1080 + 70
        # ZH Style line should have Fontsize=48 and MarginV=5
        zh_style = [l for l in content.split("\n") if l.startswith("Style: ZH,")][0]
        assert ",48," in zh_style, f"Fontsize not 48 in: {zh_style}"
        # MarginV is field index 21 (0-based) in the Style line
        fields = zh_style.split(",")
        assert fields[21].strip() == "5", f"MarginV not 5: {fields[21]}"

    def test_defaults_match_current_behavior(self, tmp_path):
        """Without --fontsize/--marginv, output matches current defaults (64/140 bar)."""
        inp = tmp_path / "in.srt"
        out = tmp_path / "out.ass"
        write_srt(inp, [("00:00:00,000", "00:00:02,000", "中文\nEnglish")])
        rc, so, se = run_subs("ass", str(inp), str(out), "--bottom-bar", "180")
        assert rc == 0
        content = out.read_text(encoding="utf-8")
        zh_style = [l for l in content.split("\n") if l.startswith("Style: ZH,")][0]
        assert ",64," in zh_style  # default fontsize
        fields = zh_style.split(",")
        assert fields[21].strip() == "140"  # default ZH_MARGINV_BAR

    def test_en_style_unchanged(self, tmp_path):
        """EN Style line should be unaffected by --fontsize/--marginv."""
        inp = tmp_path / "in.srt"
        out = tmp_path / "out.ass"
        write_srt(inp, [("00:00:00,000", "00:00:02,000", "中文\nEnglish")])
        rc, so, se = run_subs("ass", str(inp), str(out),
                              "--fontsize", "48", "--marginv", "5", "--bottom-bar", "70")
        assert rc == 0
        content = out.read_text(encoding="utf-8")
        en_style = [l for l in content.split("\n") if l.startswith("Style: EN,")][0]
        assert ",44," in en_style  # EN fontsize always 44


class TestUnionBoundaryDefects:
    """Q5: the biliteral union used to (a) absorb short intervals up to
    MAX_ZH*2=84 width — over the 64 render ceiling — and (b) merge a
    boundary-sliver's text into the previous cue while the SAME text stayed
    active in the next cue, double-displaying the clause."""

    def _bilingual(self, tmp_path, en, zh):
        en_p, zh_p, out_p = tmp_path / "en.srt", tmp_path / "zh.srt", tmp_path / "out.srt"
        write_srt(en_p, en)
        write_srt(zh_p, zh)
        rc, so, se = run_subs("biliteral", str(en_p), str(zh_p), str(out_p))
        assert rc == 0, se
        return out_p.read_text(encoding="utf-8")

    def test_boundary_sliver_no_double_display(self, tmp_path):
        # zh cue B starts 0.3s BEFORE the en boundary -> a 0.3s sliver interval.
        # zh has more cues than en (the dub layout), forcing the union path.
        # Old behavior: B's text merged into cue A AND shown next -> twice.
        out = self._bilingual(tmp_path,
            [("00:00:00,000", "00:00:04,700", "English A span"),
             ("00:00:05,000", "00:00:09,000", "English B span")],
            [("00:00:00,000", "00:00:02,500", "中文甲句子前半"),
             ("00:00:02,500", "00:00:04,700", "中文甲句子后半"),
             ("00:00:04,700", "00:00:09,000", "中文乙句子")])
        texts = [b.strip().split("\n")[2] for b in out.split("\n\n") if b.strip()]
        joined = [t for t in texts if "中文乙" in t]
        assert len(joined) == 1, out          # shown once, not twice
        assert all("中文乙" not in t or t == "中文乙句子" for t in texts), out

    def test_absorbed_width_ceiling_64(self, tmp_path):
        # a short interval whose text does NOT continue next may still be
        # absorbed — but the merged cue must never exceed width 64
        a = "一二三四五六七八九十" * 3          # 60w
        b = "乙句"                              # would make 65w merged
        out = self._bilingual(tmp_path,
            [("00:00:00,000", "00:00:04,900", "English long span")],
            [("00:00:00,000", "00:00:04,000", a),
             ("00:00:04,000", "00:00:04,500", b),
             ("00:00:04,500", "00:00:04,900", "丙句尾巴显示内容")])
        for block in out.split("\n\n"):
            if not block.strip():
                continue
            zh = block.split("\n")[-1] if "\n" not in block.split("\n", 1)[-1] else None
        widths = [sum(2 if ord(c) > 0x2E7F else 1 for c in blk.split("\n", 1)[0])
                  for blk in out.split("\n\n") if blk.strip()]
        assert all(w <= 64 for w in widths), out

    def test_real_run_union_clean(self, tmp_path):
        # regression vs the shipped defect: a ZH cue starting 345ms before
        # its EN boundary used to merge into the previous cue AND repeat
        zh = [("00:00:44,000", "00:00:45,500", "前一句的内容展示前半"),
              ("00:00:45,500", "00:00:47,000", "前一句的内容后半"),
              ("00:00:47,000", "00:00:50,000", "这时候就可以把整场拷问转成一份问卷。")]
        en = [("00:00:44,000", "00:00:47,345", "first english sentence here"),
              ("00:00:47,345", "00:00:50,000", "second english sentence")]
        out = self._bilingual(tmp_path, en, zh)
        count = out.count("这时候就可以把整场拷问转成一份问卷")
        assert count == 1, out


class TestShortenOrphanPunctuation:
    """Q6: pack_zh's width hard-cut could land right before a comma, leaving
    the next chunk to start with '，' — an orphaned leading-punct cue."""

    def test_comma_stays_with_preceding_chunk(self, tmp_path):
        inp, out = tmp_path / "in.srt", tmp_path / "out.srt"
        write_srt(inp, [("00:06:34,667", "00:06:41,517",
            "Diagnosing Bugs 和 Resolving Merge Conflicts 这两个技能，"
            "本质上都是在补模型自己的短板。")])
        rc, so, se = run_subs("shorten", str(inp), str(out),
                              "--lang", "zh", "--max-zh", "56")
        assert rc == 0, se
        content = out.read_text(encoding="utf-8")
        assert not any(line.startswith("，") or line.startswith("、")
                       for line in content.split("\n"))
        # the comma belongs to the end of the first chunk
        assert "这两个技能，" in content

    def test_short_line_untouched(self, tmp_path):
        inp, out = tmp_path / "in.srt", tmp_path / "out.srt"
        write_srt(inp, [("00:00:00,000", "00:00:02,000", "短句无需切分。")])
        rc, _, _ = run_subs("shorten", str(inp), str(out), "--lang", "zh")
        assert rc == 0
        assert "短句无需切分。" in out.read_text(encoding="utf-8")
