# textnorm

**转一次再转回来，内容必须一模一样——这是它唯一的验收标准。**

`textnorm` 给文本转换流程做体检：编码判定、换行规范、转义与反转义，
并用**往返一致性校验**证明转换没有偷偷改掉内容。

- 零依赖，Python 3.10+ 标准库即可运行
- 单文件，`textnorm.py` 拷走就能用
- **不一致必须报错**，不静默通过；差异定位到字节与字符序号

<!-- ipos:install -->
## 安装

零依赖，Python 3.10+ 即可：

```bash
pip install 19flavorbr-textnorm
```

装完直接用命令名调用：

```bash
textnorm --help
```

也可以不用安装，直接把 `textnorm.py` 拷走用——它只依赖标准库。

## 为什么需要它

文本处理里最吓人的不是报错，是**内容悄悄变了**。

转义多了一层、少了一层、换行从 LF 变成 CRLF、
编码判定把 UTF-8 当成了 GBK——程序都不报错，
等你发现的时候数据已经进库了。

更麻烦的是「转完再转回来对不上」这件事很难查：
你看着内容几乎一样，只有一处引号变成了中文引号，
但你不知道它是在哪一步变的。

`textnorm` 的做法是把每一步都变成**可验证的**：

1. 转换前先告诉你原文的编码与换行风格
2. 转换后再告诉你变成了什么
3. 最后做一次往返校验，不一致就报出**具体位置**

## 四个子命令

```bash
# 1. 探测编码与换行风格
python textnorm.py detect --input sample.txt

# 2. 统计并统一换行风格
python textnorm.py newlines --input sample.txt --to crlf --output out.txt

# 3. 转义与反转义
python textnorm.py escape --input sample.txt
python textnorm.py escape --input escaped.txt --unescape

# 4. 往返一致性校验
python textnorm.py roundtrip --input sample.txt --from utf-8 --to utf-8
```

输出示例：

```
文件：./sample.txt
编码：utf-8（可信度 0.95）
其他候选：utf-8-sig, gb18030, big5, shift_jis, euc-kr, cp1252, latin-1
换行风格：lf（共 3 处）
结尾有换行：是
```

往返校验不通过时：

```
文件：./sample.txt
往返：utf-8 → ascii → utf-8
结果：不一致
差异位置：字符 0，字节 0
原文：'中'
回转：''
说明：有些转换天然不可逆（例如 utf-8 → ascii 遇到非 ASCII 字符），
工具会明确报出差异而不是静默通过。
```

## 三个容易出错的地方

### 编码判定

`textnorm` 按固定顺序试严格解码，能解出来的候选列出来，
并给一个可信度。utf-8 排最前——它几乎不误判，
而 gb18030 和 latin-1 这类「什么都能解」的编码会被排到后面。

**但这不是万能的。** 没有 BOM、没有元信息时，
GBK 文本完全可能被判成 utf-8。
工具会列出其他候选，让你自己确认。

### 换行风格

按内容判定，不按操作系统默认猜：

- `lf`：Unix 风格 `\n`
- `crlf`：Windows 风格 `\r\n`
- `cr`：老 Mac 风格 `\r`
- `mixed`：同文件里混用了多种——这通常就是「同一个文件在两个系统上 diff 全是换行差异」的根源

### 转义与反转义

转义按 JSON 字符串规则处理（覆盖引号、反斜杠、控制字符），
换行统一成 `\\n` 这样的**两字符序列**。
反转义支持 `\n`、`\t`、`\r`、`\\`、`\"`、`\b`、`\f`、`\/` 和 `\uXXXX`。

CSV 里带换行的字段最容易被这里吃掉，所以工具**不会改写你的分隔符结构**——
只处理内容本身。

## 往返一致性校验

这是 `textnorm` 的核心。它做的是：

```
原文 --编码--> 字节 --解码--> 回转
```

然后逐字符比较原文与回转结果，给出：

- 是否完全一致
- 差异的**字符序号**与 **UTF-8 字节序号**
- 差异处两边的字符是什么

不可逆的转换（`utf-8 → ascii` 遇到中文）会**明确报出差异**，
而不是用替换字符糊过去。

## 已知局限

- **编码探测不可靠**。没有 BOM 或元信息时，同一批字节可能有多个合理解释。
  工具给候选和可信度，但不做最终断言。
- **不判断文本语义**。它只处理字节层面的转换，不检查 JSON 是否仍合法。
- **换行统一不处理 CSV 内嵌字段**。它把整个文件当作文本处理，
  不理解 CSV 的字段边界——这是有意的：它不猜你的结构。
- **转义按 JSON 规则**，不覆盖 Python 字面量的全部形式（如 `\x41`、原始字符串前缀）。
- **反转义遇到非法序列**会保留原字符，不抛错。
- **不处理 BOM 的写入**。`detect` 会报出 BOM，`newlines` 转换时保留原字节前缀。
- **不做 Unicode 规范化**（NFC/NFD）。看起来相同的字符在规范化后可能不同，
  工具不替你决定用哪一种。
- **大文件全量读入内存**，不做流式处理。
- **往返校验只做一层**（A → B → A），不检查多次转换的复合影响。

## 跑测试

```bash
python test_textnorm.py
```

测试覆盖：编码探测（含 BOM、latin-1 兜底、二进制）、换行统计与统一、
转义往返、差异定位到字节、以及不可逆转换必须报错。

## 为什么还要做这个

文本转换是自动化里最容易「静默出错」的一环。
`textnorm` 不追求替你猜对，只追求**把不确定的地方显式说出来**，
并给出可以核对的位置。

## 来源与参考

- Unicode Standard（编码与规范化）：<https://www.unicode.org/standard/standard.html>
- RFC 8259 JSON（字符串转义规则）：<https://www.rfc-editor.org/rfc/rfc8259>
- Python `codecs` 模块文档：<https://docs.python.org/3/library/codecs.html>

---

## 关于作者

19flavorbr 做文本转换体检。让文本转换这件事可以被验证，而不是被相信。

- 个人主页：<https://19flavorbr.github.io>
- 仓库：<https://github.com/19flavorbr/textnorm>

## 许可

MIT，见 [LICENSE](LICENSE)。
