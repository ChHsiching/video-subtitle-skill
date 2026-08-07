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
