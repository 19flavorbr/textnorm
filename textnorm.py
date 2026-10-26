"""textnorm —— 文本转换体检工具。

设计原则：
1. 往返一致性是硬标准：转一次再转回来，内容必须完全一致。
2. 差异定位到字节与字符序号，不只说「有区别」。
3. 换行风格按内容判定，不按操作系统默认猜。

仅依赖 Python 标准库。

    python textnorm.py --help
    python textnorm.py detect --input sample.txt
    python textnorm.py newlines --input sample.txt
    python textnorm.py escape --input sample.txt
    python textnorm.py roundtrip --input sample.txt --to utf-8
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
from pathlib import Path

VERSION = "0.1.0"

# 常见编码的探测顺序
CANDIDATE_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "gb18030",
    "big5",
    "shift_jis",
    "euc-kr",
    "cp1252",
    "latin-1",
)

NEWLINE_STYLES = {
    "lf": "\n",
    "crlf": "\r\n",
    "cr": "\r",
}


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def detect_encoding(data: bytes) -> dict:
    """探测一段字节的编码。

    先试严格解码：能解出来的候选按可信度排序。
    utf-8 始终排在前面，因为它几乎不误判。
    """
    if not data:
        return {"encoding": "utf-8", "confidence": 1.0, "alternatives": [],
                "bom": None, "note": "空输入，默认按 utf-8 处理"}

    bom = None
    body = data
    if body.startswith(codecs.BOM_UTF8):
        bom = "utf-8"
        body = body[len(codecs.BOM_UTF8):]
    elif body.startswith(codecs.BOM_UTF16_LE):
        bom = "utf-16-le"
        body = body[len(codecs.BOM_UTF16_LE):]
    elif body.startswith(codecs.BOM_UTF16_BE):
        bom = "utf-16-be"
        body = body[len(codecs.BOM_UTF16_BE):]

    alternatives = []
    for enc in CANDIDATE_ENCODINGS:
        try:
            body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        alternatives.append(enc)

    if not alternatives:
        return {"encoding": None, "confidence": 0.0, "alternatives": [],
                "bom": bom, "note": "无法用候选编码严格解码，文件可能是二进制或混合编码"}

    encoding = alternatives[0]
    confidence = 0.95 if encoding.startswith("utf-8") else 0.6
    if bom and encoding.replace("-sig", "") in bom:
        confidence = 1.0
    return {
        "encoding": encoding,
        "confidence": confidence,
        "alternatives": alternatives,
        "bom": bom,
        "note": "",
    }


def detect_newlines(text: str) -> dict:
    """统计一段文本里各种换行符的出现次数。"""
    counts = {"lf": text.count("\n") - text.count("\r\n"),
              "crlf": text.count("\r\n"),
              "cr": text.count("\r") - text.count("\r\n")}
    total = counts["lf"] + counts["cr"] + counts["crlf"]
    if total == 0:
        return {"style": "none", "counts": counts, "total": 0,
                "mixed": False, "trailing_newline": text.endswith(("\n", "\r"))}
    present = [k for k, v in counts.items() if v > 0]
    style = present[0] if len(present) == 1 else "mixed"
    return {
        "style": style,
        "counts": counts,
        "total": total,
        "mixed": len(present) > 1,
        "trailing_newline": text.endswith(("\n", "\r")),
    }


def normalize_newlines(text: str, style: str = "lf") -> str:
    """把换行统一成指定风格。"""
    if style not in NEWLINE_STYLES:
        raise ValueError(f"未知换行风格：{style}")
    target = NEWLINE_STYLES[style]
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    if target == "\n":
        return unified
    return unified.replace("\n", target)


def escape_text(text: str) -> str:
    """把文本转成可安全放进单行字符串的形式。

    先按 JSON 字符串规则转义（覆盖引号、反斜杠、控制字符），
    再把换行统一成 ``\\n`` 这样的两字符序列。
    """
    escaped = json.dumps(text, ensure_ascii=False)[1:-1]
    return escaped.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def unescape_text(text: str) -> str:
    """反转义：把 ``\\n`` 之类的序列还原成真实字符。"""
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        pass
    out = []
    index = 0
    length = len(text)
    simple = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"',
              "b": "\b", "f": "\f", "/": "/"}
    while index < length:
        ch = text[index]
        if ch != "\\":
            out.append(ch)
            index += 1
            continue
        if index + 1 >= length:
            out.append(ch)
            break
        nxt = text[index + 1]
        if nxt in simple:
            out.append(simple[nxt])
            index += 2
            continue
        if nxt == "u" and index + 5 < length:
            hexpart = text[index + 2:index + 6]
            try:
                out.append(chr(int(hexpart, 16)))
                index += 6
                continue
            except ValueError:
                pass
        out.append(ch)
        index += 1
    return "".join(out)


def find_first_difference(a: str, b: str) -> dict:
    """定位两个字符串的第一处差异。

    同时给出字符序号与 UTF-8 字节序号。
    """
    limit = min(len(a), len(b))
    index = 0
    while index < limit and a[index] == b[index]:
        index += 1
    byte_offset = len(a[:index].encode("utf-8"))
    return {
        "char_index": index,
        "byte_index": byte_offset,
        "length_a": len(a),
        "length_b": len(b),
        "char_a": a[index] if index < len(a) else "",
        "char_b": b[index] if index < len(b) else "",
        "identical": a == b,
    }


def decode_text(data: bytes, encoding: str) -> str:
    return data.decode(encoding)


def roundtrip(text: str, source_encoding: str, target_encoding: str) -> dict:
    """做一次编码往返，验证内容是否完全一致。"""
    data = text.encode(target_encoding, errors="strict")
    back = data.decode(source_encoding, errors="strict")
    diff = find_first_difference(text, back)
    diff["source_encoding"] = source_encoding
    diff["target_encoding"] = target_encoding
    diff["byte_count"] = len(data)
    return diff


def render_detect(info: dict, path: Path) -> str:
    lines = [f"文件：{path}"]
    if info["encoding"] is None:
        lines.append("编码：无法判定")
        lines.append(f"说明：{info['note']}")
        return "\n".join(lines)
    lines.append(f"编码：{info['encoding']}（可信度 {info['confidence']:.2f}）")
    if info.get("bom"):
        lines.append(f"BOM：{info['bom']}")
    if len(info["alternatives"]) > 1:
        lines.append("其他候选：" + ", ".join(info["alternatives"][1:]))
    if info.get("note"):
        lines.append(f"说明：{info['note']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="textnorm",
        description="文本转换体检：编码判定、换行规范、转义还原与往返一致性校验",
        epilog=(
            "示例:\n"
            "  python textnorm.py detect --input sample.txt\n"
            "  python textnorm.py newlines --input sample.txt --to crlf\n"
            "  python textnorm.py escape --input sample.txt\n"
            "  python textnorm.py roundtrip --input sample.txt --from utf-8 --to gbk\n"
            "\n"
            "往返一致性是不可逆转换的诚实说明：不可逆时工具会明确报出差异位置。\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"textnorm {VERSION}")
    sub = ap.add_subparsers(dest="command")

    det = sub.add_parser("detect", help="探测文件编码与换行风格")
    det.add_argument("--input", required=True, help="文件路径")
    det.add_argument("--json", action="store_true", help="输出 JSON")

    nl = sub.add_parser("newlines", help="统计并统一换行风格")
    nl.add_argument("--input", required=True, help="文件路径")
    nl.add_argument("--to", choices=sorted(NEWLINE_STYLES), default="lf",
                    help="目标换行风格（默认 lf）")
    nl.add_argument("--output", help="输出文件路径（默认打印统计）")
    nl.add_argument("--json", action="store_true", help="输出 JSON")

    esc = sub.add_parser("escape", help="转义 / 反转义")
    esc.add_argument("--input", required=True, help="文件路径")
    esc.add_argument("--unescape", action="store_true", help="执行反转义而非转义")
    esc.add_argument("--output", help="输出文件路径（默认打印到标准输出）")

    rt = sub.add_parser("roundtrip", help="校验编码往返一致性")
    rt.add_argument("--input", required=True, help="文件路径")
    rt.add_argument("--from", dest="source", default="utf-8", help="源编码")
    rt.add_argument("--to", dest="target", default="utf-8", help="目标编码")
    rt.add_argument("--json", action="store_true", help="输出 JSON")

    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 0

    if args.command == "detect":
        path = Path(args.input)
        if not path.is_file():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 2
        data = path.read_bytes()
        info = detect_encoding(data)
        text = ""
        if info["encoding"]:
            try:
                text = data.decode(info["encoding"])
            except (UnicodeDecodeError, LookupError):
                text = ""
        newline_info = detect_newlines(text)
        if args.json:
            print(json.dumps({"file": str(path), "encoding": info,
                              "newlines": newline_info},
                             ensure_ascii=False, indent=2))
            return 0
        print(render_detect(info, path))
        print(f"换行风格：{newline_info['style']}"
              f"（共 {newline_info['total']} 处"
              f"{'，混用' if newline_info['mixed'] else ''}）")
        print(f"结尾有换行：{'是' if newline_info['trailing_newline'] else '否'}")
        return 0

    if args.command == "newlines":
        path = Path(args.input)
        if not path.is_file():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 2
        data = path.read_bytes()
        info = detect_encoding(data)
        encoding = info["encoding"] or "utf-8"
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as e:
            print(f"解码失败（{encoding}）：{e}", file=sys.stderr)
            return 2
        before = detect_newlines(text)
        converted = normalize_newlines(text, args.to)
        after = detect_newlines(converted)
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(converted.encode(encoding))
            print(f"已写出：{out}（{before['style']} → {after['style']}）")
            return 0
        if args.json:
            print(json.dumps({"file": str(path), "encoding": encoding,
                              "before": before, "after": after},
                             ensure_ascii=False, indent=2))
            return 0
        print(f"文件：{path}")
        print(f"编码：{encoding}")
        print(f"换行（转换前）：{before['style']}"
              f"  lf={before['counts']['lf']} crlf={before['counts']['crlf']}"
              f" cr={before['counts']['cr']}")
        print(f"换行（转换后）：{after['style']}")
        print(f"内容长度：{len(text)} 字符")
        return 0

    if args.command == "escape":
        path = Path(args.input)
        if not path.is_file():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 2
        data = path.read_bytes()
        info = detect_encoding(data)
        encoding = info["encoding"] or "utf-8"
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as e:
            print(f"解码失败（{encoding}）：{e}", file=sys.stderr)
            return 2
        if args.unescape:
            result = unescape_text(text.rstrip("\r\n"))
        else:
            result = escape_text(text)
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(result.encode(encoding, errors="replace"))
            print(f"已写出：{out}")
            return 0
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    if args.command == "roundtrip":
        path = Path(args.input)
        if not path.is_file():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 2
        data = path.read_bytes()
        info = detect_encoding(data)
        source = args.source
        if info["encoding"] and info["encoding"].replace("-sig", "") != source:
            source = info["encoding"]
        try:
            text = data.decode(source)
        except (UnicodeDecodeError, LookupError) as e:
            print(f"解码失败（{source}）：{e}", file=sys.stderr)
            return 2
        try:
            diff = roundtrip(text, source, args.target)
        except UnicodeEncodeError as e:
            payload = {
                "file": str(path),
                "source_encoding": source,
                "target_encoding": args.target,
                "identical": False,
                "error": f"编码到 {args.target} 失败：{e.reason}",
                "char_index": None,
                "byte_index": None,
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"文件：{path}")
                print(f"结果：不一致")
                print(f"原因：{payload['error']}")
                print(f"字符位置：{e.start}")
            return 1
        if args.json:
            print(json.dumps({"file": str(path), **diff}, ensure_ascii=False,
                             indent=2))
        else:
            print(f"文件：{path}")
            print(f"往返：{source} → {args.target} → {source}")
            if diff["identical"]:
                print("结果：一致（字节级）")
            else:
                print("结果：不一致")
                print(f"差异位置：字符 {diff['char_index']}，字节 {diff['byte_index']}")
                print(f"原文：{diff['char_a']!r}")
                print(f"回转：{diff['char_b']!r}")
                print("说明：有些转换天然不可逆（例如 utf-8 → ascii 遇到非 ASCII 字符），"
                      "工具会明确报出差异而不是静默通过。")
        return 0 if diff["identical"] else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
