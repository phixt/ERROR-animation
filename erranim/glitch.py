"""故障效果库：全部是确定性函数（同一 t 必然得到同一画面），
所以终端播放与离线出片永远一致。"""

from __future__ import annotations

import math
import random
import zlib

from . import render as R
from . import widgets as W
from .render import Grid

# 同形异码：把 ASCII 换成西里尔/希腊的"看起来一样"的字母。
# 视觉上察觉不到，但文本已经坏了 —— 这是最贴合"身份无法确认"的故障。
HOMOGLYPH = {
    "A": "Α", "B": "Β", "C": "С", "E": "Ε", "H": "Η", "I": "Ι", "K": "Κ",
    "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ", "S": "Ѕ", "T": "Τ", "X": "Χ",
    "Y": "Υ", "Z": "Ζ", "a": "а", "c": "с", "e": "е", "i": "і", "j": "ј",
    "o": "о", "p": "р", "s": "ѕ", "x": "х", "y": "у", "l": "ӏ", "n": "п",
    "u": "ц", "r": "г",
}

GLITCH_CHARS = "▓▒░█▄▀■□▪▫◢◣◤◥╳╱╲†‡¤§¶¥¢£¦¬±÷×※"

ESCAPE_LITERALS = [
    "ESC[2J", "\\x1b[31m", "ESC[?1049h", "^[[0m", "\\033[38;2;255;0;0m",
    "ESC[1;1H", "\\x1b[?25l", "ESC[K",
]

DEAD_PIXEL_CHARS = "▪▫·*+×"


def _rng(seed: int, name: str, t0: float) -> random.Random:
    return random.Random(zlib.crc32(("%s|%d|%.4f" % (name, seed, t0)).encode()))


class Glitch:
    __slots__ = ("t", "dur", "name", "p", "seed")

    def __init__(self, t: float, name: str, dur: float = 0.25, seed: int = 0, **p):
        self.t = t
        self.dur = dur
        self.name = name
        self.p = p
        self.seed = seed

    def rng(self, now: float) -> random.Random:
        """每次调用都新建 RNG，且种子只依赖 (效果, 起始时刻, 量化后的当前时刻)。

        绝不能缓存 RNG 实例 —— 那样随机数状态会在帧之间被消耗，
        同一时刻重渲染就会得到不同画面，跳段和重放都会不一致。
        量化到 15Hz，让故障有自己稳定的"帧率"。
        """
        q = int(now * 15.0)
        return _rng(self.seed, "%s@%d" % (self.name, q), self.t)

    def active(self, t: float) -> bool:
        return self.t <= t < self.t + self.dur

    def k(self, t: float) -> float:
        """进度 0..1。"""
        return 0.0 if self.dur <= 0 else min(1.0, max(0.0, (t - self.t) / self.dur))


# --------------------------------------------------------------------------
# 行操作辅助
# --------------------------------------------------------------------------


def _raw_copy_row(g: Grid, src: int, dst: int) -> None:
    if not (0 <= src < g.h and 0 <= dst < g.h):
        return
    w = g.w
    a, b = src * w, dst * w
    g.ch[b:b + w] = g.ch[a:a + w]
    g.st[b:b + w] = g.st[a:a + w]
    g.cont[b:b + w] = g.cont[a:a + w]


def _visible(g: Grid, y: int) -> list[tuple[int, str, int]]:
    """一行里可见的字（跳过宽字符续格）。"""
    w = g.w
    base = y * w
    out: list[tuple[int, str, int]] = []
    for x in range(w):
        i = base + x
        if g.cont[i]:
            continue
        ch = g.ch[i]
        if ch and ch != " ":
            out.append((x, ch, g.st[i]))
    return out


def _remap_row(g: Grid, y: int, fn) -> None:
    w = g.w
    base = y * w
    for x in range(w):
        i = base + x
        g.st[i] = fn(g.st[i], x)


# --------------------------------------------------------------------------
# 具体效果
# --------------------------------------------------------------------------


def _char_noise(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    n = int(gl.p.get("peak", 90) * (1.0 - 0.55 * k))
    for _ in range(n):
        y = r.randrange(top, bot)
        x = r.randrange(0, g.w)
        g.put(x, y, r.choice(GLITCH_CHARS), r.choice([R.S_MAGENTA, R.S_TEAL, R.S_RED, R.S_FAINT]))


def _homoglyph(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    ratio = gl.p.get("ratio", 0.3)
    for y in range(top, bot):
        for x, ch, st in _visible(g, y):
            if ch in HOMOGLYPH and r.random() < ratio:
                g.put(x, y, HOMOGLYPH[ch], st)


def _row_flip(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    for _ in range(gl.p.get("rows", 2)):
        y = r.randrange(top, bot)
        vis = _visible(g, y)
        if len(vis) < 4:
            continue
        chars = [(ch, st) for _, ch, st in vis]
        chars.reverse()
        for (x, _, _), (ch, st) in zip(vis, chars):
            g.put(x, y, ch, st)


def _row_dup(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    for _ in range(gl.p.get("rows", 2)):
        y = r.randrange(top, max(top + 1, bot - 1))
        _raw_copy_row(g, y, min(bot - 1, y + 1))


def _row_shift(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    dx = gl.p.get("dx", 3)
    for _ in range(gl.p.get("rows", 2)):
        y = r.randrange(top, bot)
        vis = _visible(g, y)
        if not vis:
            continue
        shift = r.choice([-dx, dx])
        g.fill(0, y, g.w, " ", R.S_BASE)
        for x, ch, st in vis:
            nx = x + shift
            if 0 <= nx < g.w:
                g.put(nx, y, ch, st)


def _row_invert(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    for _ in range(gl.p.get("rows", 1)):
        y = r.randrange(top, bot)
        _remap_row(g, y, lambda st, x: R.S_INVERT)


def _scanlines(g, t, gl, area, k):
    top, bot = area
    step = gl.p.get("step", 2)
    for y in range(top + (0 if gl.p.get("phase", 0) == 0 else 1), bot, step):
        _remap_row(g, y, lambda st, x: R.S_DIM if st not in (R.S_INVERT, R.S_BLOCK) else st)


def _escape_literal(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    s = r.choice(ESCAPE_LITERALS)
    for _ in range(gl.p.get("n", 1)):
        y = r.randrange(top, bot)
        x = r.randrange(2, max(3, g.w - len(s) - 2))
        g.put(x, y, s, r.choice([R.S_MAGENTA, R.S_TEAL, R.S_RED]))


def _dead_pixels(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    for _ in range(gl.p.get("n", 40)):
        y = r.randrange(top, bot)
        x = r.randrange(0, g.w)
        g.put(x, y, r.choice(DEAD_PIXEL_CHARS), r.choice([R.S_BRIGHT, R.S_RED, R.S_MAGENTA]))


def _blackout(g, t, gl, area, k):
    top, bot = area
    y0 = top + int((bot - top) * gl.p.get("a", 0.0))
    y1 = top + int((bot - top) * gl.p.get("b", 0.5))
    for y in range(y0, max(y0 + 1, y1)):
        g.fill(0, y, g.w, " ", R.S_BASE)


def _flash(g, t, gl, area, k):
    for i in range(len(g.st)):
        g.st[i] = R.S_INVERT


def _dim_all(g, t, gl, area, k):
    f = gl.p.get("factor", 0.5)
    for i in range(len(g.st)):
        if g.st[i] in (R.S_BASE, R.S_BRIGHT):
            g.st[i] = R.S_DIM if f > 0.4 else R.S_FAINT


def _bright_rows(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    for _ in range(gl.p.get("rows", 3)):
        y = r.randrange(top, bot)
        _remap_row(g, y, lambda st, x: R.S_BRIGHT)


# --------------------------------------------------------------------------
# 结构性 UI 崩坏效果（模拟恐怖：边框融化、仪表越界溢出、弹窗堆叠、行同步撕裂、内存倾泻）
# --------------------------------------------------------------------------

_BOX_SET = frozenset("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬")
_MELT_CHARS = "╬╫╨╥▓▒░│¦⋮╏╽╿"

_MODAL_POOL = [
    ("SCM.EXE - VIRTUAL MEMORY EXHAUSTED", [
        "物理内存使用率 99% (30.9 / 31.2 GB)。",
        "已提交内存 77.4 / 31.2 GB，页面文件分配失败 (0xC000012D)。",
    ], "0xC000012D"),
    ("DXGKRNL.SYS - LIVE KERNEL DUMP", [
        "dxgkrnl!ProcessDeadlockThread 检测到显示合成器无响应。",
        "已生成实时内核转储 LKD_0x141 / LKD_0x193。",
    ], "0x00000193"),
    ("WIN32KBASE.SYS - EXRESOURCE TIMEOUT", [
        "图形与电源资源锁超时 (LKD_0x1cc)。",
        "shutdown.exe /r /t 0 /f 未在超时时间内返回 (0x000005B4)。",
    ], "0x000001CC"),
    ("KERNEL-POWER #507 - MODERN STANDBY", [
        "系统正在退出新型待机状态 (Reason: SetThreadExecutionState)。",
        "监视器通电时间: 182 毫秒。本地用户会话: 0。",
    ], "0x000001FB"),
]


def _border_melt(g, t, gl, area, k):
    """UI 边框与分隔线融化下垂、断裂成乱码块。"""
    r = gl.rng(t)
    top, bot = area
    ratio = gl.p.get("ratio", 0.45) * (0.35 + 0.65 * k)
    for y in range(top, bot):
        for x, ch, st in _visible(g, y):
            if (ch in _BOX_SET or x in (0, 1, g.w - 2, g.w - 1)) and r.random() < ratio:
                mc = r.choice(_MELT_CHARS)
                mst = r.choice((R.S_BORDER_HOT, R.S_RED, R.S_AMBER, R.S_FAINT))
                g.put(x, y, mc, mst)
                # 向下滴落 1~3 格
                drip = r.randint(1, 3)
                for dy in range(1, drip + 1):
                    if y + dy < bot and r.random() < 0.7:
                        g.put(x, y + dy, r.choice("│¦░·"), R.S_BORDER_HOT if dy == 1 else R.S_FAINT)


def _meter_overflow(g, t, gl, area, k):
    """进度条与内存条冲破边界，向全屏横向溢出。"""
    r = gl.rng(t)
    top, bot = area
    rows = gl.p.get("rows", 2)
    for _ in range(rows):
        y = r.randrange(top, bot)
        x0 = r.randrange(2, max(4, g.w // 4))
        span = int((g.w - x0 - 2) * min(1.0, 0.45 + 0.65 * k))
        bar_str = "█" * int(span * 0.62) + "▓" * int(span * 0.20) + "▒░" * max(1, int(span * 0.09))
        tag = r.choice((
            " [COMMIT 60.4/31.2GB SWAP]",
            " [COMMIT 77.4/31.2GB LOCK]",
            " [PAGEFILE_DEAD // IO 100%]",
            " [9999999% NaN]",
        ))
        g.put(x0, y, bar_str[:max(4, span - len(tag))] + tag, r.choice((R.S_RED, R.S_COMMIT_OVER, R.S_AMBER, R.S_INVERT)))


def _popup_cascade(g, t, gl, area, k):
    """故障模态弹窗阶梯状无限堆叠。"""
    r = gl.rng(t)
    top, bot = area
    total = max(1, int(round(gl.p.get("count", 3) * (0.35 + 0.65 * k))))
    base_x = gl.p.get("x", max(6, g.w // 5))
    base_y = max(top + 1, min(bot - 8, gl.p.get("y", top + 2)))
    mw = min(g.w - 10, gl.p.get("w", 54))
    idx0 = gl.p.get("modal", 0)
    for i in range(total):
        title, lines, code = _MODAL_POOL[(idx0 + i) % len(_MODAL_POOL)]
        px = min(g.w - mw - 3, base_x + i * 4 + r.randint(-1, 1))
        py = min(bot - 7, base_y + i * 2)
        if py >= top and py + len(lines) + 4 <= bot:
            W.draw_modal(
                g, px, py, mw, title, lines, code=code,
                buttons="[ ACCESS DENIED (SUPPRESSED) ]" if (idx0 + i) % 2 else "[ Retry (Y) ]  [ Abort (N) ]",
                corrupt_k=k * 0.8, rng=r,
            )


def _hsync_wave(g, t, gl, area, k):
    """字符网格级的水平行同步失锁（H-Sync Tear / Wave），整块区域左右撕裂。"""
    r = gl.rng(t)
    top, bot = area
    amp = gl.p.get("amp", 6) * (0.4 + 0.6 * k)
    freq = gl.p.get("freq", 0.55)
    phase = t * 19.0
    for y in range(top, bot):
        wave = int(round(amp * math.sin(y * freq + phase)))
        if r.random() < 0.28:
            wave += r.choice((-4, -2, 2, 4))
        if wave == 0:
            continue
        vis = _visible(g, y)
        if not vis:
            continue
        g.fill(0, y, g.w, " ", R.S_BASE)
        for x, ch, st in vis:
            nx = x + wave
            if 0 <= nx < g.w:
                g.put(nx, y, ch, st)
        # 撕裂边缘留一道模拟同步噪波
        if wave > 0:
            g.put(0, y, "░▒"[:min(2, wave)], R.S_FAINT)
        else:
            g.put(max(0, g.w + wave), y, "▒░"[:min(2, -wave)], R.S_FAINT)


def _hex_flood(g, t, gl, area, k):
    """MEMORY.DMP 十六进制与内核栈转储倾泻。"""
    r = gl.rng(t)
    top, bot = area
    n_rows = max(2, int(round(gl.p.get("rows", 5) * (0.4 + 0.6 * k))))
    y0 = r.randrange(top, max(top + 1, bot - n_rows))
    tags = (
        "COMMIT_77.4_31.2GB", "PAGEFILE_0xC000012D", "S0IX_EXEC_STATE_507",
        "LKD_0x193_DWM_LOCK", "LKD_0x1CC_EXRES_TMO", "SHUTDOWN_0x000005B4",
    )
    for i in range(n_rows):
        y = y0 + i
        if y >= bot:
            break
        addr = 0xFFFFF80003A00000 + ((y * 0x1040 + int(t * 256)) & 0xFFFFFF)
        hex_bytes = " ".join("%02X" % r.randrange(256) for _ in range(12))
        ascii_tag = tags[(i + int(t * 7)) % len(tags)]
        line = "  0x%016X: %s  |%s|" % (addr, hex_bytes, ascii_tag)
        st = R.S_INVERT if (i == 0 and r.random() < 0.4) else (R.S_RED if i % 2 == 0 else R.S_FAINT)
        g.put(1, y, R.truncate(line, g.w - 2), st)


# --------------------------------------------------------------------------
# htop 信息层的故障
# --------------------------------------------------------------------------
# 早先信息层（资源面板 / 时间戳 / 段标题 / 状态行）是**免疫**的：故障只作用在
# 日志区。结果是画面上唯一一直"正常"的东西反而是最不可信的那块仪表 ——
# 一台正在死的机器，它的监控面板不可能还那么整齐。
#
# 这里的效果作用范围是面板行（资源行 + 表头 + 分隔线），做法和日志区一致：
# 确定性、可重放、按 k 推进。

_PANEL_JUNK = "▒░█▄■□▪◢◤╳†¤§¶¥¢¬±÷×※#%@&$"


def _panel_noise(g, t, gl, area, k):
    """面板上撒噪声字符。密度随 k 增长。"""
    r = gl.rng(t)
    top, bot = area
    n = int(gl.p.get("peak", 26) * (0.35 + 0.65 * k))
    for _ in range(n):
        y = r.randrange(top, bot)
        x = r.randrange(0, g.w)
        g.put(x, y, r.choice(_PANEL_JUNK),
              r.choice([R.S_MAGENTA, R.S_TEAL, R.S_RED, R.S_INVERT]))


def _panel_corrupt(g, t, gl, area, k):
    """把面板上已有的字换成低墨量的垃圾 —— 像信号丢了，而不是被砸了。"""
    r = gl.rng(t)
    top, bot = area
    ratio = gl.p.get("ratio", 0.35) * (0.4 + 0.6 * k)
    pool = gl.p.get("chars", ".·:;'/\\|-_=+")
    for y in range(top, bot):
        for x, ch, st in _visible(g, y):
            if r.random() < ratio:
                g.put(x, y, r.choice(pool), st)


def _panel_garbage(g, t, gl, area, k):
    """在资源行上糊一串"读数" —— 计数器开始吐垃圾。

    真实机器出问题的时候，那一行往往不是变空，而是变成一串没人认识的数字。
    """
    r = gl.rng(t)
    top, bot = area
    y = r.randrange(top, max(top + 1, bot))
    ln = r.randint(6, max(7, g.w // 4))
    x0 = r.randrange(0, max(1, g.w - ln))
    s = "".join(r.choice("0123456789ABCDEF") for _ in range(ln))
    g.put(x0, y, s, r.choice([R.S_RED, R.S_MAGENTA, R.S_INVERT]))


def _panel_invert(g, t, gl, area, k):
    r = gl.rng(t)
    top, bot = area
    for _ in range(gl.p.get("rows", 2)):
        y = r.randrange(top, bot)
        _remap_row(g, y, lambda st, x: R.S_INVERT)


def _panel_dim(g, t, gl, area, k):
    """面板整体变暗：仪表读数掉下去。"""
    top, bot = area
    for y in range(top, bot):
        _remap_row(g, y, lambda st, x: R.S_FAINT if st in (R.S_BASE, R.S_BRIGHT,
                                                           R.S_DIM) else st)


_EFFECTS = {
    "char_noise": _char_noise,
    "homoglyph": _homoglyph,
    "row_flip": _row_flip,
    "row_dup": _row_dup,
    "row_shift": _row_shift,
    "row_invert": _row_invert,
    "scanlines": _scanlines,
    "escape_literal": _escape_literal,
    "dead_pixels": _dead_pixels,
    "blackout": _blackout,
    "flash": _flash,
    "dim_all": _dim_all,
    "bright_rows": _bright_rows,
    # 结构性 UI 崩坏
    "border_melt": _border_melt,
    "meter_overflow": _meter_overflow,
    "popup_cascade": _popup_cascade,
    "hsync_wave": _hsync_wave,
    "hex_flood": _hex_flood,
    # 信息层
    "panel_noise": _panel_noise,
    "panel_corrupt": _panel_corrupt,
    "panel_garbage": _panel_garbage,
    "panel_invert": _panel_invert,
    "panel_dim": _panel_dim,
}

# 每个效果作用在哪一层：log = 日志区（默认），panel = 信息层。
# flash 填满整屏，所以哪一层都无所谓。
TARGETS = {
    "panel_noise": "panel",
    "panel_corrupt": "panel",
    "panel_garbage": "panel",
    "panel_invert": "panel",
    "panel_dim": "panel",
}

# 哪些效果属于"信息层故障"：资源读数要用它来决定抖动强度。
PANEL_EFFECTS = frozenset(k for k, v in TARGETS.items() if v == "panel")


def apply(g: Grid, glitches: list[Glitch], t: float, area: tuple[int, int],
          panel: tuple[int, int] | None = None) -> None:
    for gl in glitches:
        if not gl.active(t):
            continue
        fn = _EFFECTS.get(gl.name)
        if fn is None:
            continue
        if TARGETS.get(gl.name) == "panel":
            if panel is not None:
                fn(g, t, gl, panel, gl.k(t))
        else:
            fn(g, t, gl, area, gl.k(t))


def name_of(seed_text: str) -> str:
    """给定一句话，稳定地挑一个故障效果名（供场景随机化使用）。

    只从**日志区**的效果里挑 —— 信息层的效果作用范围不一样，随机撒在日志区
    会什么都不发生。
    """
    r = random.Random(zlib.crc32(seed_text.encode()))
    pool = [k for k in _EFFECTS if TARGETS.get(k) != "panel"]
    return r.choice(pool)
