"""控件：三级进度条、日志行、前缀、Y/n 提示、状态栏。"""

from __future__ import annotations

import random

from . import render as R
from .render import Grid

BLOCKS_FULL = "█"
BLOCKS_MID = "▓"
BLOCKS_LOW = "▒"
BLOCKS_FAINT = "░"

CORRUPT_CHARS = "▓▒░█▚▞▙▟⣿⣷⣯◇◆※¤§¶†‡"
CORRUPT_PCT = ["9999999%", "-0%", "NaN%", "112%", "--%", "4O%", "∞%", "  %", "1e9%"]


def meter_color(frac: float) -> int:
    """htop 那套配色语义：越满越危险。"""
    if frac < 0.50:
        return R.S_GREEN
    if frac < 0.80:
        return R.S_YELLOW
    if frac < 0.95:
        return R.S_AMBER
    return R.S_RED


def draw_meter(g: Grid, y: int, x: int, label: str, frac: float, inner: int = 16,
               pct: str | None = None) -> int:
    """htop 风格的一条：`CPU [|||||||||||·····  62%]`

    实心用 `|`，空槽用极暗的 `·`（纯空格在深色底上等于看不见，
    那样就分不出条有多长了）。
    """
    frac = max(0.0, min(1.0, frac))
    c = meter_color(frac)
    x = g.put(x, y, label, R.S_DIM)
    x = g.put(x, y, "[", R.S_FAINT)
    filled = int(round(frac * inner))
    x = g.put(x, y, "|" * filled, c)
    x = g.put(x, y, "·" * (inner - filled), R.S_FAINT)
    txt = pct if pct is not None else "%3d%%" % int(round(frac * 100))
    x = g.put(x, y, " " + txt, c)
    x = g.put(x, y, "]", R.S_FAINT)
    return x


def draw_prefix(g: Grid, y: int, x: int, ev: int | None, tag: str = "") -> int:
    if ev is None:
        return x
    return g.put(x, y, "[%d] " % ev, R.S_DIM)


def pct_text(frac: float, level: int, rng: random.Random | None = None) -> str:
    if level == 1:
        return "%3d%%" % int(max(0.0, min(1.0, frac)) * 100)
    if level == 2:
        return "%5.1f%%" % (max(0.0, min(1.0, frac)) * 100.0)
    r = rng or random
    if r.random() < 0.28:
        return r.choice(CORRUPT_PCT)
    v = frac * 100.0
    s = "%6.1f%%" % v
    if r.random() < 0.35:  # 随机把数字换成同形字符
        s = s.replace("0", "O" if r.random() < 0.5 else "0")
        s = s.replace("1", "l") if r.random() < 0.4 else s
    return s


def ms_text(ms: int | None, level: int, rng: random.Random | None = None) -> str:
    """「30000 毫秒」这类数字的崩坏版本。"""
    if ms is None:
        return ""
    if level <= 2:
        return "%d 毫秒" % ms
    r = rng or random
    if r.random() < 0.3:
        return r.choice(["-0 毫秒", "NaN 毫秒", "999999 毫秒", " 毫秒", "0.00 毫秒"])
    return "%d 毫秒" % ms


def bar_inner(width: int, level: int) -> int:
    """进度条内部的格子数（画和算下一帧变化点必须一致）。"""
    if level == 1:
        return max(8, min(width - 12, 26))
    if level == 2:
        return max(16, width - 14)
    return max(20, width - 16)


def draw_bar(
    g: Grid,
    y: int,
    x0: int,
    width: int,
    frac: float,
    level: int = 1,
    rng: random.Random | None = None,
    ghost: float = 0.0,
) -> str:
    """三级进度条。返回右侧百分比文本。

    L1 常见简略：[######--------]  40%
    L2 宽字符：满宽实心块 + 残影 + 扫描头
    L3 崩坏：字符碎裂、位置抖动、有洞、可能分裂成两段
    """
    r = rng or random
    frac = max(0.0, min(1.0, frac))
    if level == 1:
        inner = max(8, min(width - 12, 26))
        x = x0
        x = g.put(x, y, "[", R.S_DIM)
        filled = int(round(frac * inner))
        x = g.put(x, y, "#" * filled, R.S_AMBER)
        x = g.put(x, y, "-" * (inner - filled), R.S_DIM)
        x = g.put(x, y, "]", R.S_DIM)
        x = g.put(x, y, "  ", R.S_BASE)
        pct = pct_text(frac, 1)
        g.put(x, y, pct, R.S_AMBER)
        return pct

    if level == 2:
        inner = max(16, width - 14)
        x = x0
        x = g.put(x, y, "▕", R.S_DIM)
        filled = int(round(frac * inner))
        ghost_cells = max(0, int(round(ghost * inner)) - filled)
        # 残影（上一次的位置）
        if ghost_cells:
            x = g.put(x, y, BLOCKS_FAINT * ghost_cells, R.S_FAINT)
        body = filled
        head = 1 if 0 < body < inner else 0
        x = g.put(x, y, BLOCKS_FULL * max(0, body - head), R.S_BLOCK)
        if head:
            x = g.put(x, y, BLOCKS_MID, R.S_HEAD)
        rest = inner - max(0, body)
        x = g.put(x, y, BLOCKS_FAINT * rest, R.S_FAINT)
        x = g.put(x, y, "▏", R.S_DIM)
        x = g.put(x, y, " ", R.S_BASE)
        pct = pct_text(frac, 2)
        g.put(x, y, pct, R.S_AMBER)
        return pct

    # L3：崩坏
    inner = max(20, width - 16)
    x = x0
    x = g.put(x, y, "▕", R.S_RED)
    cells: list[tuple[str, int]] = []
    jitter = r.uniform(-0.06, 0.06)
    f = max(0.0, min(1.0, frac + jitter))
    edge = int(f * inner)
    for i in range(inner):
        if i < edge:
            if r.random() < 0.14:  # 洞
                cells.append((" ", R.S_BASE))
            elif r.random() < 0.22:
                cells.append((r.choice(CORRUPT_CHARS), r.choice([R.S_MAGENTA, R.S_TEAL, R.S_RED])))
            else:
                cells.append((BLOCKS_FULL, R.S_BLOCK))
        else:
            if r.random() < 0.05:
                cells.append((r.choice(CORRUPT_CHARS), R.S_FAINT))
            else:
                cells.append((BLOCKS_FAINT, R.S_FAINT))
    # 随机断开成两段
    if r.random() < 0.25 and edge > 4:
        cut = r.randrange(1, max(2, edge - 1))
        cells[cut] = (" ", R.S_BASE)
    for ch, st in cells:
        x = g.put(x, y, ch, st)
    x = g.put(x, y, "▏", R.S_RED)
    x = g.put(x, y, " ", R.S_BASE)
    pct = pct_text(frac, 3, r)
    g.put(x, y, pct, R.S_RED)
    return pct


def log_prefix(ev: int | None, style: int) -> str:
    if ev is None:
        return ""
    return "[%d] " % ev


def spinner(t: float, style: int = R.S_AMBER) -> tuple[str, int]:
    return "|/-\\"[int(t * 12) % 4], style


def blink(t: float, period: float = 1.0, duty: float = 0.5) -> bool:
    return (t % period) < (period * duty)


def typewriter(s: str, t: float, t_start: float, cps: float = 28.0) -> str:
    n = int(max(0.0, t - t_start) * cps)
    return s[:n]


def draw_prompt(g: Grid, y: int, x: int, prompt: str, answer: str, style: int = R.S_YELLOW) -> None:
    x = g.put(x, y, prompt, style)
    if answer:
        g.put(x, y, answer, R.S_BRIGHT)


def draw_commit_bar(
    g: Grid,
    y: int,
    x: int,
    width: int,
    commit_gb: float,
    max_gb: float = 77.4,
    corrupt_k: float = 0.0,
    rng: random.Random | None = None,
    phys_gb: float = 31.2,
) -> int:
    """真实死机内存条：以 31.2GB 为物理红线，直观呈现已提交冲破物理上限并吞噬硬盘 Swap 至 77.4GB。"""
    r = rng or random
    frac = max(0.0, min(1.0, commit_gb / max(1e-6, max_gb)))
    inner = max(8, width - 2)
    wall = max(2, min(inner - 2, int(round((phys_gb / max(1e-6, max_gb)) * inner))))
    filled = int(round(frac * inner))
    over = commit_gb > phys_gb
    x = g.put(x, y, "▕", R.S_RED if over else R.S_DIM)
    for i in range(inner):
        if i == wall:
            # 31.2 GB 物理红线刻度：未越界时是青色刻度，冲破后变成血红反白裂口
            ch = "▓" if (over and i < filled) else "│"
            st = R.S_COMMIT_OVER if over else R.S_CYAN
        elif i < filled:
            if corrupt_k > 0.25 and r.random() < 0.22 * corrupt_k:
                ch = r.choice(CORRUPT_CHARS)
                st = r.choice((R.S_RED, R.S_MAGENTA, R.S_INVERT))
            elif i > wall:
                ch = BLOCKS_FULL if (commit_gb < 74.0 or i % 2 == 0) else BLOCKS_MID
                st = R.S_COMMIT_OVER if (commit_gb >= 68.0 and i >= inner - 3) else R.S_RED
            elif i >= int(wall * 0.80):
                ch = BLOCKS_FULL
                st = R.S_AMBER
            else:
                ch = BLOCKS_FULL
                st = R.S_GREEN if not over else R.S_AMBER
        else:
            ch = BLOCKS_FAINT
            st = R.S_FAINT
        x = g.put(x, y, ch, st)
    # 超过 60GB 后右括号被进度条顶破变红
    end_ch = "▓" if (commit_gb >= 74.0 and corrupt_k > 0.2) else "▏"
    x = g.put(x, y, end_ch, R.S_COMMIT_OVER if commit_gb >= 74.0 else (R.S_RED if over else R.S_DIM))
    return x


def draw_modal(
    g: Grid,
    x0: int,
    y0: int,
    w: int,
    title: str,
    lines: list[str],
    code: str = "0xC000012D",
    buttons: str = "[ Retry (Y) ]   [ Ignore (N) ]",
    corrupt_k: float = 0.0,
    rng: random.Random | None = None,
) -> None:
    """90s/00s Windows NT / BIOS 风格的故障模态弹窗（带右侧与底部阴影）。"""
    r = rng or random
    h = len(lines) + 4
    w = max(28, min(g.w - 4, w))
    x0 = max(1, min(g.w - w - 2, x0))
    y0 = max(1, min(g.h - h - 1, y0))

    # 1) 投射阴影（把底下内容的样式压入 S_SHADOW，保留隐约字形）
    for sy in range(y0 + 1, min(g.h, y0 + h + 1)):
        for sx in range(x0 + 2, min(g.w, x0 + w + 2)):
            idx = sy * g.w + sx
            if not g.cont[idx]:
                g.st[idx] = R.S_SHADOW

    # 2) 背景填充与双线边框
    for yy in range(y0, min(g.h, y0 + h)):
        g.fill(x0, yy, x0 + w, " ", R.S_MODAL_BG)

    tl, tr, bl, br, hz, vt = "╔", "╗", "╚", "╝", "═", "║"
    if corrupt_k > 0.35 and r.random() < corrupt_k:
        hz = r.choice(("═", "─", "▓", "▒"))
    g.put(x0, y0, tl + hz * (w - 2) + tr, R.S_MODAL_BORDER)
    for yy in range(y0 + 1, y0 + h - 1):
        g.put(x0, yy, vt, R.S_MODAL_BORDER)
        g.put(x0 + w - 1, yy, vt, R.S_MODAL_BORDER)
    g.put(x0, y0 + h - 1, bl + hz * (w - 2) + br, R.S_MODAL_BORDER)

    # 3) 标题栏
    t_str = " [!] %s (%s) " % (title, code)
    g.fill(x0 + 1, y0, x0 + w - 1, " ", R.S_MODAL_TITLE)
    g.put(x0 + 1, y0, R.truncate(t_str, w - 6), R.S_MODAL_TITLE)
    g.put(x0 + w - 4, y0, "[X]", R.S_MODAL_TITLE)

    # 4) 内容行
    for i, ln in enumerate(lines):
        yy = y0 + 1 + i
        if yy >= y0 + h - 2:
            break
        g.put(x0 + 2, yy, R.truncate(ln, w - 4), R.S_MODAL_BG)

    # 5) 按钮行
    by = y0 + h - 2
    bx = x0 + max(2, (w - R.text_width(buttons)) // 2)
    g.put(bx, by, R.truncate(buttons, w - 4), R.S_ALERT_BAR if corrupt_k > 0.2 else R.S_WARN_BAR)
