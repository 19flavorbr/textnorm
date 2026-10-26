"""textnorm 的自检测试。只用内存与临时目录里的样例数据。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from textnorm import (detect_encoding, detect_newlines,  # noqa: E402
                      escape_text, find_first_difference, normalize_newlines,
                      roundtrip, unescape_text)

ENTRY = os.path.join(BASE, "textnorm.py")


def _tmpdir() -> str:
    return tempfile.mkdtemp(prefix="textnorm_")


def test_detect_utf8() -> None:
    info = detect_encoding("你好，世界".encode("utf-8"))
    assert info["encoding"] == "utf-8", info
    assert info["confidence"] > 0.9, info


def test_detect_utf8_bom() -> None:
    info = detect_encoding(b"\xef\xbb\xbfhello")
    assert info["bom"] == "utf-8", info


def test_detect_empty() -> None:
    info = detect_encoding(b"")
    assert info["encoding"] == "utf-8", info


def test_detect_latin1_fallback() -> None:
    info = detect_encoding(b"caf\xe9 na\xefve")
    assert info["encoding"] is not None, info
    assert "utf-8" not in info["alternatives"][:1], info


def test_detect_binary_fails() -> None:
    info = detect_encoding(bytes(range(0, 32)))
    assert info["encoding"] is None or info["alternatives"], info


def test_detect_newlines_lf() -> None:
    out = detect_newlines("a\nb\nc\n")
    assert out["style"] == "lf", out
    assert out["counts"]["lf"] == 3, out
    assert out["mixed"] is False, out
    assert out["trailing_newline"] is True, out


def test_detect_newlines_crlf() -> None:
    out = detect_newlines("a\r\nb\r\n")
    assert out["style"] == "crlf", out
    assert out["counts"]["crlf"] == 2, out
    assert out["counts"]["lf"] == 0, out


def test_detect_newlines_mixed() -> None:
    out = detect_newlines("a\r\nb\nc\r")
    assert out["style"] == "mixed", out
    assert out["mixed"] is True, out


def test_detect_newlines_none() -> None:
    out = detect_newlines("abc")
    assert out["style"] == "none", out
    assert out["total"] == 0, out


def test_normalize_to_crlf() -> None:
    out = normalize_newlines("a\nb\nc", "crlf")
    assert out == "a\r\nb\r\nc", repr(out)


def test_normalize_to_lf_from_crlf() -> None:
    out = normalize_newlines("a\r\nb\r\nc\r", "lf")
    assert out == "a\nb\nc\n", repr(out)


def test_normalize_is_idempotent() -> None:
    once = normalize_newlines("a\r\nb\nc", "lf")
    twice = normalize_newlines(once, "lf")
    assert once == twice


def test_escape_roundtrip() -> None:
    text = "第一行\n第二行\t带引号\"和反斜杠\\\n"
    escaped = escape_text(text)
    assert "\n" not in escaped, repr(escaped)
    assert "\\n" in escaped, repr(escaped)
    assert unescape_text(escaped) == text, repr(unescaped_text(escaped))


def test_escape_keeps_unicode() -> None:
    out = escape_text("中文")
    assert "中文" in out, out


def test_unescape_handles_unicode_escape() -> None:
    assert unescape_text("中") == "中"


def test_unescape_plain_text() -> None:
    assert unescape_text("plain") == "plain"


def test_find_first_difference_same() -> None:
    diff = find_first_difference("abc", "abc")
    assert diff["identical"] is True, diff
    assert diff["char_index"] == 3, diff


def test_find_first_difference_locates() -> None:
    diff = find_first_difference("abcd", "abXd")
    assert diff["identical"] is False, diff
    assert diff["char_index"] == 2, diff
    assert diff["char_a"] == "c", diff
    assert diff["char_b"] == "X", diff


def test_find_first_difference_byte_index() -> None:
    diff = find_first_difference("中a", "中b")
    assert diff["byte_index"] == 3, diff


def test_roundtrip_identical() -> None:
    diff = roundtrip("hello 世界", "utf-8", "utf-8")
    assert diff["identical"] is True, diff


def test_roundtrip_lossy_detects_difference() -> None:
    # 目标编码无法表示源字符时，roundtrip 必须明确抛错而不是静默通过。
    try:
        roundtrip("中文", "utf-8", "ascii")
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("不可逆转换应当抛出 UnicodeEncodeError")


def test_cli_help_exits_zero() -> None:
    r = subprocess.run([sys.executable, ENTRY, "--help"], capture_output=True,
                       text=True, timeout=30, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert "textnorm" in r.stdout


def test_cli_detect() -> None:
    tmp = _tmpdir()
    try:
        p = Path(tmp) / "a.txt"
        p.write_bytes("你好\n世界\n".encode("utf-8"))
        r = subprocess.run([sys.executable, ENTRY, "detect", "--input", str(p)],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        assert "utf-8" in r.stdout, r.stdout
        assert "换行风格：lf" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_detect_json() -> None:
    tmp = _tmpdir()
    try:
        p = Path(tmp) / "a.txt"
        p.write_bytes(b"a\r\nb\r\n")
        r = subprocess.run([sys.executable, ENTRY, "detect", "--input", str(p),
                            "--json"], capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["newlines"]["style"] == "crlf", data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_newlines_converts() -> None:
    tmp = _tmpdir()
    try:
        src = Path(tmp) / "a.txt"
        src.write_bytes(b"a\nb\n")
        dst = Path(tmp) / "b.txt"
        r = subprocess.run([sys.executable, ENTRY, "newlines", "--input", str(src),
                            "--to", "crlf", "--output", str(dst)],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        assert dst.read_bytes() == b"a\r\nb\r\n", dst.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_escape_output() -> None:
    tmp = _tmpdir()
    try:
        src = Path(tmp) / "a.txt"
        src.write_bytes(b"line1\nline2\n")
        r = subprocess.run([sys.executable, ENTRY, "escape", "--input", str(src)],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        assert "line1\\nline2" in r.stdout, repr(r.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_roundtrip_reports_mismatch() -> None:
    tmp = _tmpdir()
    try:
        src = Path(tmp) / "a.txt"
        src.write_bytes("中文".encode("utf-8"))
        r = subprocess.run([sys.executable, ENTRY, "roundtrip", "--input", str(src),
                            "--from", "utf-8", "--to", "ascii"],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 1, (r.returncode, r.stdout)
        assert "不一致" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_roundtrip_success() -> None:
    tmp = _tmpdir()
    try:
        src = Path(tmp) / "a.txt"
        src.write_bytes("hello".encode("utf-8"))
        r = subprocess.run([sys.executable, ENTRY, "roundtrip", "--input", str(src),
                            "--from", "utf-8", "--to", "utf-8"],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, (r.returncode, r.stdout)
        assert "一致" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_missing_file_exits_two() -> None:
    r = subprocess.run([sys.executable, ENTRY, "detect", "--input", "no_such.txt"],
                       capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 2, (r.returncode, r.stderr)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK  ] {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n共 {len(tests)} 项，失败 {failed} 项")
    raise SystemExit(1 if failed else 0)
