"""生成跳杀用的大字（开发期工具，运行期不需要 PIL）。

和上一版的区别 —— 上一版在生成期就把字**阈值化**成 ▀▄█ 硬边，
所以放大后是一格一格的像素块，既不"矢量"也没法做立体感。现在改成：

  * 用 Arial Black / Impact 这类**重体**字体，在 200px 宽度上栅格化；
  * 保留**灰度**（只量化到 8 级），不做二值化；
  * 运行时再按终端尺寸做盒式缩放，灰度映射到 ` ░▒▓█` 渐变 —— 边缘因此是平滑的，
    看起来才像矢量绘制而不是马赛克；
  * 灰度还能直接拿来做立体：左上受光边缘提亮、右下边缘压暗、再往右下投一层影。

导出成 zlib + base85 的紧凑数据，运行期只是一串 ASCII，不需要字体文件。

用法：
    python tools/make_bigtext.py              # 写回 erranim/bigtext.py
    python tools/make_bigtext.py --preview    # 顺便在终端里预览一张
"""

from __future__ import annotations

import base64
import os
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

# 字重用中等偏粗就好：Arial Black 太厚，做描边区分时笔画里没地方落线。
FONTS = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\ariblk.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# 主谓结构的两三个词。**每一行都要短**（<=7 字）：
# 一行的字越少，同样的画布宽度下字就越大、笔画越粗，
# 红-黑-红 三带才有地方落（笔画约 3 格宽时最漂亮）。
PHRASES: list[tuple[str, ...]] = [
    ("SYSTEM", "HALTED"),
    ("FATAL", "ERROR"),
    ("SYSTEM", "FAILURE"),
    ("FATAL", "OCCURRED"),
    ("FATAL", "FAULT"),
    ("KERNEL", "PANIC"),
]

RES_W = 200        # 源位图宽度（像素）
LINE_GAP = 0.14    # 行距，占行高比例
QUANT = 8          # 灰度量级（1 = 二值，8 = 保留渐变）
SHEAR = float(os.environ.get("ERRANIM_SHEAR", "0.0"))  # 斜体比例；0 = 正体（默认）


def _font_path() -> str:
    for p in FONTS:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到重体字体，试过：%s" % FONTS)


def _quantize(v: int) -> int:
    step = 255 / (QUANT - 1)
    return int(round(round(v / step) * step))


def render_gray(lines: tuple[str, ...], res_w: int = RES_W) -> tuple[int, int, bytearray]:
    """把一个多行短语栅格化成灰度位图，返回 (宽, 高, 像素)。

    关键是按**墨迹**（ink bbox）裁切，而不是按字体度量 —— Arial Black 的大写
    没有下伸部，按度量裁会白白留出一条空白，缩放到屏幕上就浪费掉三分之一的格子。
    """
    path = _font_path()
    probe = ImageFont.truetype(path, 200)

    def ink_size(size: int) -> tuple[list[tuple[int, int]], ImageFont.FreeTypeFont]:
        f = ImageFont.truetype(path, size)
        boxes = []
        for s in lines:
            w = int(f.getlength(s)) + 40
            h = int(sum(f.getmetrics())) * 2
            tmp = Image.new("L", (max(4, w), max(4, h)), 0)
            ImageDraw.Draw(tmp).text((20, int(f.getmetrics()[0])), s, font=f, fill=255, anchor="ls")
            bb = tmp.getbbox()
            boxes.append(bb or (0, 0, 1, 1))
        return [(b[2] - b[0], b[3] - b[1]) for b in boxes], f  # type: ignore[return-value]

    # 让最宽的行正好占满 res_w
    size = 200
    for _ in range(4):
        sizes, _f = ink_size(size)
        widest = max(w for w, _h in sizes)
        if widest <= 0:
            break
        nxt = max(10, int(size * res_w / widest))
        if abs(nxt - size) <= 1:
            break
        size = nxt

    f = ImageFont.truetype(path, size)
    ascent = f.getmetrics()[0]
    crops: list[Image.Image] = []
    for s in lines:
        w = int(f.getlength(s)) + 40
        h = int(sum(f.getmetrics())) * 2
        tmp = Image.new("L", (max(4, w), max(4, h)), 0)
        ImageDraw.Draw(tmp).text((20, ascent), s, font=f, fill=255, anchor="ls")
        crops.append(tmp.crop(tmp.getbbox() or (0, 0, 1, 1)))

    gap = max(2, int(res_w * 0.032))
    total_h = sum(c.height for c in crops) + gap * (len(crops) - 1)
    canvas = Image.new("L", (res_w, max(2, total_h)), 0)
    y = 0
    for c in crops:
        x = (res_w - c.width) // 2
        canvas.paste(c, (max(0, x), y))
        y += c.height + gap

    # 斜体：顶部相对底部右移。x' = x - k*y，再整体右移 k*H 免得被裁掉。
    if SHEAR > 0:
        k = SHEAR
        shift = int(k * canvas.height) + 2
        canvas = canvas.transform(
            (canvas.width + shift, canvas.height),
            Image.AFFINE, (1, k, 0, 0, 1, 0), resample=Image.BICUBIC,
        )
        res_w = canvas.width
    else:
        res_w = canvas.width

    px = canvas.load()
    buf = bytearray(res_w * canvas.height)
    i = 0
    for yy in range(canvas.height):
        for xx in range(res_w):
            buf[i] = _quantize(px[xx, yy])
            i += 1
    return res_w, canvas.height, buf


def encode(buf: bytes) -> str:
    return base64.b85encode(zlib.compress(bytes(buf), 9)).decode("ascii")


def wrap_b85(s: str, width: int = 100, indent: str = "        ") -> list[str]:
    return ['%s"%s"' % (indent, s[i:i + width]) for i in range(0, len(s), width)]


def render_module(phrases: list[tuple[str, ...]]) -> str:
    out = [
        '"""跳杀用的大字 —— 由 tools/make_bigtext.py 生成，请勿手改。',
        "",
        "存的是**灰度**位图（zlib + base85），不是二值块：",
        "  * 运行期按终端尺寸做盒式缩放，灰度映射到 ` ░▒▓█` 渐变，边缘平滑，像矢量绘制；",
        "  * 同一份灰度还用来做立体：左上受光边缘提亮、右下边缘压暗、往右下投一层影。",
        "",
        "重新生成：python tools/make_bigtext.py",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import base64",
        "import zlib",
        "",
        "# 键是分行后的短语，例如 (\"FATAL ERROR\", \"OCCURRED\")",
        "ART: dict[tuple[str, ...], dict] = {",
    ]
    for ph in phrases:
        w, h, buf = render_gray(ph)
        enc = encode(buf)
        out.append("    %r: {" % (ph,))
        out.append('        "w": %d,' % w)
        out.append('        "h": %d,' % h)
        out.append('        "z": (')
        out.extend(wrap_b85(enc))
        out.append("        ),")
        out.append("    },")
    out += [
        "}",
        "",
        "_CACHE: dict[tuple[str, ...], list[bytearray]] = {}",
        "",
        "",
        "def get(phrase: tuple[str, ...] | str | None):",
        '    """取短语的灰度位图：(宽, 高, [每行的 bytearray])。"""',
        "    if phrase is None:",
        "        return None",
        "    if isinstance(phrase, str):",
        "        key = tuple(phrase.split(chr(10)))",
        "    else:",
        "        key = tuple(phrase)",
        "    e = ART.get(key)",
        "    if e is None:",
        "        return None",
        "    rows = _CACHE.get(key)",
        "    if rows is None:",
        '        raw = zlib.decompress(base64.b85decode(e["z"]))',
        '        w = e["w"]',
        "        rows = [bytearray(raw[i * w:(i + 1) * w]) for i in range(e[\"h\"])]",
        "        _CACHE[key] = rows",
        "    return e[\"w\"], e[\"h\"], rows",
        "",
        "",
        "def phrases() -> list[tuple[str, ...]]:",
        "    return list(ART)",
        "",
        "",
        "def one_line(phrase) -> str:",
        '    """给日志/调试用：把分行短语拼回一行。"""',
        "    if isinstance(phrase, str):",
        "        return phrase",
        "    return \" \".join(phrase)",
        "",
    ]
    return "\n".join(out)


def preview(ph: tuple[str, ...], cols: int = 92) -> None:
    w, h, rows = 0, 0, []
    data = render_gray(ph)
    w, h, buf = data
    rows = [buf[i * w:(i + 1) * w] for i in range(h)]
    out_cols = min(cols, w)
    out_rows = max(1, int(round(h * out_cols / w / 2)))
    ramp = " ░▒▓█"
    print("=== %s (%d×%d → %d×%d) ===" % (" / ".join(ph), w, h, out_cols, out_rows))
    for cy in range(out_rows):
        y0 = int(cy * h / out_rows)
        y1 = max(y0 + 1, int((cy + 1) * h / out_rows))
        line = []
        for cx in range(out_cols):
            x0 = int(cx * w / out_cols)
            x1 = max(x0 + 1, int((cx + 1) * w / out_cols))
            s = n = 0
            for yy in range(y0, y1):
                r = rows[yy]
                for xx in range(x0, x1):
                    s += r[xx]
                    n += 1
            v = s / max(1, n)
            line.append(ramp[min(4, int(v / 51.2))])
        print("".join(line))
    print()


def main(argv: list[str]) -> int:
    if "--preview" in argv:
        for ph in PHRASES:
            preview(ph)
        return 0
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = os.path.join(root, "erranim", "bigtext.py")
    src = render_module(PHRASES)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("→ %s（%.1f KB，%d 条短语）" % (dst, len(src.encode()) / 1024, len(PHRASES)))
    for ph in PHRASES:
        w, h, _ = render_gray(ph)
        print("   %-26s %d×%d" % (" / ".join(ph), w, h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
