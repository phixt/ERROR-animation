"""渲染核心：宽字符网格 + 调色板 + ANSI 差分输出。

设计要点
- Grid 每帧整体重建（便宜：实测 <1ms），保证是时间的纯函数，不会有残留。
- Emitter 只输出与上一帧不同的格子，同色连续段合并，减少字节数。
- 调色板是唯一真源：终端用真彩色，film.py 出片用同一批 RGB。
"""

from __future__ import annotations

import unicodedata

# --------------------------------------------------------------------------
# 字符宽度
# --------------------------------------------------------------------------

_WIDTH_CACHE: dict[str, int] = {}


def char_width(ch: str) -> int:
    w = _WIDTH_CACHE.get(ch)
    if w is None:
        if unicodedata.combining(ch):
            w = 0
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            w = 2
        elif ch == "\t":
            w = 1
        else:
            w = 1
        _WIDTH_CACHE[ch] = w
    return w


def text_width(s: str) -> int:
    return sum(char_width(c) for c in s)


def truncate(s: str, cols: int) -> str:
    """按显示宽度截断（不会把一个宽字符劈成两半）。"""
    out: list[str] = []
    used = 0
    for ch in s:
        w = char_width(ch)
        if used + w > cols:
            break
        out.append(ch)
        used += w
    return "".join(out)


def pad(s: str, cols: int, align: str = "left") -> str:
    """按显示宽度补齐到 cols。"""
    s = truncate(s, cols)
    gap = cols - text_width(s)
    if gap <= 0:
        return s
    if align == "right":
        return " " * gap + s
    if align == "center":
        left = gap // 2
        return " " * left + s + " " * (gap - left)
    return s + " " * gap


# --------------------------------------------------------------------------
# 调色板
# --------------------------------------------------------------------------


class Style:
    __slots__ = ("fg", "bg", "bold", "reverse", "ansi", "key", "film")

    def __init__(self, fg=None, bg=None, bold=False, reverse=False):
        self.fg = fg
        self.bg = bg
        self.bold = bold
        self.reverse = reverse
        eb = bg if bg is not None else BG
        parts = ["\x1b[0m"]
        if bold:
            parts.append("\x1b[1m")
        if reverse:
            parts.append("\x1b[7m")
        if fg:
            parts.append("\x1b[38;2;%d;%d;%dm" % fg)
        # 背景必须逐样式带上：reset 会把背景清掉，用户若用浅色主题就全毁了
        parts.append("\x1b[48;2;%d;%d;%dm" % eb)
        self.ansi = "".join(parts)
        self.key = (fg, bg, bold, reverse)
        # 出片时用的 (文字色, 底色)，与终端表现严格一致
        tfg = fg or (0xC8, 0xD2, 0xE0)
        self.film = (eb, tfg) if reverse else (tfg, eb)


# 模拟恐怖配色：VGA 系的青灰 + 琥珀 + 血红，底色近黑
BG = (0x08, 0x0A, 0x0D)

S_BASE = 0  # 普通日志
S_DIM = 1  # 次要/淡化（扫描线也用）
S_FAINT = 2  # 极暗、残影
S_BRIGHT = 3  # 强调白
S_AMBER = 4  # 修正动作 / 进度条
S_RED = 5  # 错误
S_GREEN = 6  # 成功
S_CYAN = 7  # 帧头 / 水印
S_YELLOW = 8  # 警告
S_TEAL = 9  # 故障色 1
S_MAGENTA = 10  # 故障色 2
S_INVERT = 11  # 反白（整行）
S_BLOCK = 12  # 进度条实心填充（琥珀实心块）
S_BLOCK_EMPTY = 13  # 进度条空槽
S_HEAD = 14  # 进度条头部高亮
S_SCARE_BODY = 15   # 跳杀：字身填充（暗一点的红）
S_SCARE_RED = 16    # 跳杀：描边 / 残影（亮红）
S_SCARE_DIM = 17    # 跳杀：备用暗红
S_SCARE_GAP = 18    # 跳杀：主字周围的黑缝（把主字从残影堆里分出来）
S_FLASH = 19        # 闪屏：整屏亮色实心块
S_SCARE_DRIP = 20   # 跳杀：向下拖影的远端（最暗的一档）
S_HEADER_BAR = 21   # 固件监控台顶栏（冷灰蓝底黑字）
S_ALERT_BAR = 22    # 严重告警顶栏（血红底亮白字）
S_WARN_BAR = 23     # 警告顶栏（琥珀底黑字）
S_MODAL_BG = 24     # 模态弹窗底色（暗褐红底米白字）
S_MODAL_BORDER = 25 # 模态弹窗边框（暗褐红底亮红框）
S_MODAL_TITLE = 26  # 模态弹窗标题栏（深红底亮白字）
S_SHADOW = 27       # 弹窗阴影（近黑压暗）
S_BORDER = 28       # 工业监控台分区双线边框（青灰钢色）
S_BORDER_HOT = 29   # 过载/崩坏中的分区边框（暗血红）
S_COMMIT_OVER = 30  # 已提交超过 31.2GB 物理红线时的分子反白高亮（血红底纯白粗体）

PALETTE: list[Style] = [
    Style(fg=(0xC8, 0xD2, 0xE0)),                     # 0 base
    Style(fg=(0x5C, 0x66, 0x76)),                     # 1 dim
    Style(fg=(0x3A, 0x42, 0x4F)),                     # 2 faint
    Style(fg=(0xFF, 0xFF, 0xFF), bold=True),          # 3 bright
    Style(fg=(0xFF, 0xB0, 0x00)),                     # 4 amber
    Style(fg=(0xFF, 0x55, 0x55)),                     # 5 red
    Style(fg=(0x66, 0xFF, 0x99)),                     # 6 green
    Style(fg=(0x55, 0xDD, 0xFF)),                     # 7 cyan
    Style(fg=(0xFF, 0xF0, 0x66)),                     # 8 yellow
    Style(fg=(0x00, 0xFF, 0xC8)),                     # 9 teal
    Style(fg=(0xFF, 0x2B, 0x9C)),                     # 10 magenta
    Style(fg=(0xC8, 0xD2, 0xE0), reverse=True),       # 11 反白行
    Style(fg=(0xFF, 0xB0, 0x00), bold=True),          # 12 琥珀实心块
    Style(fg=(0x3A, 0x40, 0x4C)),                     # 13 空槽
    Style(fg=(0xFF, 0xFF, 0xFF), bold=True),          # 14 条头
    Style(fg=(0xC4, 0x18, 0x1C)),                     # 15 跳杀：字身（暗红）
    Style(fg=(0xFF, 0x3A, 0x2E), bold=True),          # 16 跳杀：描边/残影（亮红）
    Style(fg=(0x6E, 0x0C, 0x11)),                     # 17 跳杀：残影（和主字拉开距离）
    Style(fg=(0x08, 0x0A, 0x0D)),                     # 18 跳杀：黑缝（同底色）
    Style(fg=(0xE6, 0xEE, 0xFA), bold=True),          # 19 闪屏亮块
    Style(fg=(0x2A, 0x06, 0x09)),                     # 20 跳杀：拖影远端（最暗）
    Style(fg=(0x08, 0x0A, 0x0E), bg=(0x7E, 0x92, 0xA8), bold=True),  # 21 固件顶栏
    Style(fg=(0xFF, 0xF0, 0xF0), bg=(0x98, 0x10, 0x16), bold=True),  # 22 血红告警栏
    Style(fg=(0x0A, 0x08, 0x04), bg=(0xE0, 0x96, 0x00), bold=True),  # 23 琥珀警告栏
    Style(fg=(0xEC, 0xE2, 0xD0), bg=(0x1C, 0x0E, 0x12)),             # 24 弹窗正文
    Style(fg=(0xFF, 0x4D, 0x4D), bg=(0x1C, 0x0E, 0x12), bold=True),  # 25 弹窗红框
    Style(fg=(0xFF, 0xFF, 0xFF), bg=(0xA8, 0x12, 0x1A), bold=True),  # 26 弹窗标题
    Style(fg=(0x26, 0x2C, 0x36), bg=(0x03, 0x04, 0x06)),             # 27 阴影
    Style(fg=(0x4C, 0x5E, 0x78)),                                    # 28 工业分区框
    Style(fg=(0xC8, 0x28, 0x2E), bold=True),                         # 29 过载红框
    Style(fg=(0xFF, 0xFF, 0xFF), bg=(0xC8, 0x0E, 0x18), bold=True),  # 30 COMMIT 越界高亮
]


def bg_rgb() -> tuple[int, int, int]:
    return BG


# --------------------------------------------------------------------------
# 网格
# --------------------------------------------------------------------------


class Grid:
    """宽字符感知的字符网格。ch 用 '' 表示被左侧宽字符占据的续格。"""

    __slots__ = ("w", "h", "ch", "st", "cont")

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.ch = [" "] * (w * h)
        self.st = [0] * (w * h)
        self.cont = bytearray(w * h)

    def clear(self) -> None:
        w, h = self.w, self.h
        self.ch = [" "] * (w * h)
        self.st = [0] * (w * h)
        self.cont = bytearray(w * h)

    # ---- 绘制 ----------------------------------------------------------
    def _clobber(self, i: int) -> None:
        """准备覆盖 i 时，把被牵连的宽字符/续格解绑，避免留下半截字形。"""
        if self.cont[i]:
            # i 是某个宽字符的右半格 —— 那个宽字符已经废了
            self.cont[i] = 0
            self.ch[i] = " "
            if i % self.w and self.cont[i - 1]:
                self.cont[i - 1] = 0
                self.ch[i - 1] = " "
        if i % self.w != self.w - 1 and self.cont[i + 1]:
            # i 上有个宽字符，它的右半格在 i+1
            self.cont[i + 1] = 0
            self.ch[i + 1] = " "

    def put(self, x: int, y: int, s: str, style: int = 0) -> int:
        """在 (x, y) 写字，返回结束列。超宽自动截断。"""
        if y < 0 or y >= self.h or x >= self.w:
            return x
        if x < 0:
            s = truncate(s, text_width(s) + x)
            x = 0
        w = self.w
        i = y * w + x
        col = x
        for ch in s:
            cw = char_width(ch)
            if cw == 0:
                continue
            if col >= w:
                break
            if cw == 2:
                if col + 1 >= w:
                    self._clobber(i)
                    self.ch[i] = " "
                    self.st[i] = style
                    col += 1
                    i += 1
                    break
                self._clobber(i)
                self.ch[i] = ch
                self.st[i] = style
                self.ch[i + 1] = ""
                self.st[i + 1] = style
                self.cont[i + 1] = 1
            else:
                self._clobber(i)
                self.ch[i] = ch
                self.st[i] = style
            col += cw
            i += cw
        return col

    def fill(self, x0: int, y: int, x1: int, ch: str = " ", style: int = 0) -> None:
        if y < 0 or y >= self.h:
            return
        for x in range(max(0, x0), min(self.w, x1)):
            i = y * self.w + x
            self._clobber(i)
            self.ch[i] = ch
            self.st[i] = style

    def hline(self, y: int, ch: str = "─", style: int = 1, x0: int = 0, x1: int | None = None) -> None:
        self.fill(x0, y, self.w if x1 is None else x1, ch, style)

    # ---- 取用 ----------------------------------------------------------
    def row_runs(self, y: int) -> list[list]:
        """把一行压成 [[style, text], ...] 游程，供落盘/出片使用。"""
        runs: list[list] = []
        w = self.w
        base = y * w
        for x in range(w):
            i = base + x
            if self.cont[i]:
                continue
            ch = self.ch[i]
            st = self.st[i]
            if runs and runs[-1][0] == st:
                runs[-1][1] += ch
            else:
                runs.append([st, ch])
        # 去掉尾部纯空格（出片时直接填背景色）
        while runs:
            st, txt = runs[-1]
            stripped = txt.rstrip(" ")
            if stripped:
                runs[-1][1] = stripped
                break
            runs.pop()
        return runs

    def text(self, y: int) -> str:
        w = self.w
        base = y * w
        out = []
        for x in range(w):
            i = base + x
            if self.cont[i]:
                continue  # 宽字符已经占了这一列，不能再补空格
            out.append(self.ch[i] or " ")
        return "".join(out).rstrip()

    def lines(self) -> list[str]:
        return [self.text(y) for y in range(self.h)]

    def snapshot(self) -> tuple[list[str], list[int]]:
        return (self.ch[:], self.st[:])

    def same_as(self, snap: tuple[list[str], list[int]]) -> bool:
        return self.ch == snap[0] and self.st == snap[1]


# --------------------------------------------------------------------------
# ANSI 差分输出
# --------------------------------------------------------------------------


class Emitter:
    """把网格差分成最小 ANSI 字节流。

    注意：必须保存网格的**快照**而不是引用 —— 网格是复用的同一个对象，
    持有引用会让第二帧起永远"没有变化"。
    """

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.pch: list[str] | None = None
        self.pst: list[int] | None = None
        self.pct: bytearray | None = None
        self.bytes_out = 0
        self.frames = 0

    def reset(self) -> None:
        self.pch = self.pst = self.pct = None

    def full_clear(self) -> str:
        self.reset()
        return "\x1b[2J\x1b[1;1H"

    def diff(self, grid: Grid) -> str:
        self.frames += 1
        w, h = self.w, self.h
        first = self.pch is None
        pch, pst, pct = self.pch, self.pst, self.pct
        out: list[str] = []
        gch, gst, gct = grid.ch, grid.st, grid.cont
        for y in range(h):
            base = y * w
            x = 0
            while x < w:
                i = base + x
                if gct[i]:
                    x += 1
                    continue
                if not first and gch[i] == pch[i] and gst[i] == pst[i] and gct[i] == pct[i]:
                    x += 1
                    continue
                out.append("\x1b[%d;%dH" % (y + 1, x + 1))
                last_style = -1
                while x < w:
                    i = base + x
                    if gct[i]:
                        x += 1
                        continue
                    if not first and gch[i] == pch[i] and gst[i] == pst[i] and gct[i] == pct[i]:
                        break
                    st = gst[i]
                    if st != last_style:
                        out.append(PALETTE[st].ansi)
                        last_style = st
                    out.append(gch[i])
                    x += 1
        self.pch = gch[:]
        self.pst = gst[:]
        self.pct = bytearray(gct)
        s = "".join(out)
        self.bytes_out += len(s.encode("utf-8", "replace"))
        return s

    def kb_per_frame(self) -> float:
        return (self.bytes_out / self.frames / 1024.0) if self.frames else 0.0
