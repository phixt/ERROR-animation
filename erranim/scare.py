"""跳杀：红色大字 + 描边 + 向左上移动留下的一串残影。

这一版按"正常字体 + 叠加残影"重做：

* **字重中等、正体**：用 Arial Bold 而不是 Arial Black。太重就没有地方放描边了。
* **描边区分**：字身填一个红，最外一圈用更亮的红描边 —— 两个红色，
  重叠的残影之间就分得开，主字也始终认得出来。
* **残影不是拖尾，是复制粘贴**：主字往左上"走"，原地留下约 7 个原字形的副本，
  沿右下方向排开。间隔刻意不均匀，中间留几处大的空档；最后一个允许跑出屏幕一部分。
* **没有污渍**：污渍交给视频后期（见 film.py 的 --glitch，做的是解码失败那种块状损坏）。
"""

from __future__ import annotations

import math
import random
import zlib

from . import bigtext as BT
from . import render as R
from .render import Grid

STYLES = ("echo", "solid", "outline")

ON_LEVEL = 108          # 到这个灰度算实体（描边轮廓按它算）
ON_FILL = 62            # 更低的阈值 = 略胖一圈的形状，用它做填充才填得满
FRINGE_LOW = 22         # 低于这个灰度算背景
LINE_CHARS = "─│╱╲·"

ECHO_COUNT = 7          # 主字 + 残影一共几个
# 残影的横向间隔，单位是**主字宽度**（不是屏宽）。
# 这是整段跳杀最容易做错的地方：间隔比字宽小的时候，七个副本会叠成一坨红，
# 谁的字形都认不出来 —— 看着像"画面糊了"，而不是"这行字被复制了七次"。
# 所以间隔必须和字宽同量级，代价是后面几个副本跑到屏幕外面去（这是允许的）。
ECHO_STEPS = (0.0, 0.62, 1.15, 1.90, 2.60, 3.35, 4.10)
ECHO_DY = 0.34          # 每个副本往下带多少（单位是**字高**，不是字宽）
ECHO_APPEAR = 0.10      # 主字开始出现的时刻
# 主字的走位**不是动画，是瞬移**：一个位置停 1 个逻辑帧，然后整格跳过去。
# 不要缓动、不要插值 —— 早先那版是 1.05 秒的缓出滑行，看起来像"飘"，不像
# 一台机器在抽搐。数字设备的位置变化本来就是量子化的：要么在这儿，要么在那儿。
ECHO_HOLD = 1.0 / 12.0  # 正好等于跳杀的逻辑帧步长（HZ = 12），所以一格一帧
ECHO_DIM = 0.62         # 最近那个副本的亮度（往后的按 1/(1+0.9i) 递减）
ECHO_RGB = (0x6E, 0x0C, 0x11)   # 残影用暗红 —— 和主字的亮红拉开距离

# 向下拖影（瀑布）：主字落位之后，把字形的下端一列一列往下拉到屏幕外。
#
# 只做一件事：**每一列从它自己最低的那个实心像素开始，连续往下画到屏幕底**。
# 起点天然不齐（字母本身高低不齐），横向沿路缓慢随机漂移，所以每一列各有各的
# 歪法 —— 是"往下淌"，不是"整体斜切"。没有断点、没有跳变、没有长短之分。
DRIP_DELAY = 0.20       # 落位之后多久开始淌
DRIP_RAMP = 0.75        # 淌满需要多久
DRIP_W = 2              # 条的宽度（像素）
DRIP_SEG = 8            # 每隔多少像素更新一次横向位置
DRIP_LEAN = 0.045       # 每像素的横向倾向（随机，每列不同）
DRIP_JITTER = 0.5       # 每次更新时额外抖多少

# 终端字符格的宽高比（高 / 宽）。字号的默认值来自 film.Atlas：10×22 像素。
# 终端那条路要靠它把"格"换算成"像素当量"，否则字会被纵向拉长。
CELL_ASPECT = 2.2

# 终端里主字的最小高度（格）。低于这个数，两行字每行只有三格 ——
# 字符画的大字在这个尺寸下必然认不出来，所以终端那条件宁愿把字放大。
MIN_ROWS = 10


def _rng(seed: int, salt: str) -> random.Random:
    return random.Random(zlib.crc32(("%s|%d" % (salt, seed)).encode()))


def find_phrase(text):
    """把用户给的文字匹配到已有短语（str 用 | 或换行分行，也接受已经是分行的序列）。"""
    if not text:
        return None
    if isinstance(text, (tuple, list)):
        lines = tuple(str(p).strip() for p in text if str(p).strip())
    else:
        raw = str(text).replace("\n", "|")
        lines = tuple(p.strip() for p in raw.split("|") if p.strip())
    if not lines:
        return None
    if lines in BT.ART:
        return lines
    flat = " ".join(lines).upper()
    for key in BT.ART:
        if " ".join(key).upper() == flat:
            return key
    return None


def _line_char(m, y: int, x: int, rows: int, cols: int) -> str:
    """按字形梯度的垂直方向挑线字符 —— 轮廓是"画"出来的。"""
    def at(yy, xx):
        if 0 <= yy < rows and 0 <= xx < cols:
            return m[yy][xx]
        return 0

    gx = at(y, x + 1) - at(y, x - 1)
    gy = at(y + 1, x) - at(y - 1, x)
    ax, ay = abs(gx), abs(gy)
    if ax < 8 and ay < 8:
        return "·"
    if ax > 2 * ay:
        return "│"
    if ay > 2 * ax:
        return "─"
    # 轮廓方向垂直于梯度：梯度朝右下 → 切线是 ╱
    return "╱" if gx * gy > 0 else "╲"


class JumpScare:
    """时间轴（场景内相对秒）：

        0.00 – 0.10  全屏反白
        0.10 – 2.55  大字出现；0.40 起不规则错位，逐渐加剧
        2.55 – 2.70  再次全屏反白（硬切）
        2.70 – 结束  全黑
    """

    FLASH_END = 0.10
    HIDE_AT = 2.55
    CUT_END = 2.70
    SLICE_AT = 0.40
    HZ = 12.0

    def __init__(self, phrase=None, seed: int = 0, style: str = "echo"):
        self.seed = seed
        self.style = style if style in STYLES else "echo"
        pick = _rng(seed, "phrase")
        key = find_phrase(phrase) if phrase else None
        self.phrase = key or pick.choice(BT.phrases())
        self.text = BT.one_line(self.phrase)

        w, h, rows = BT.get(self.phrase)
        self.src_w, self.src_h, self.src = w, h, rows

        # 蒙版：低分辨率随机位图放大成块，初始化生成一次，整段复用
        mrng = _rng(seed, "mask")
        self.bs_x, self.bs_y = 6, 4
        self.mw = (self.src_w // self.bs_x) + 1
        self.mh = (self.src_h // self.bs_y) + 1
        self.mask = [[mrng.random() < 0.10 for _ in range(self.mw)] for _ in range(self.mh)]

        self._cache_key = None
        self._cache_m = None
        self._cache_ring = None
        self._cache_ring_fill = None
        self._plate_key = None
        self._plate = None
        self._bands = None          # 背景暗带的行号（固定顺序，一次生成）
        self._unit = 64             # 主字宽度（格/像素），stamped() 用它换算副本偏移
        self._vunit = 32            # 主字高度（行/像素）
        self._extent = 0            # 画面宽度（格/像素），决定走位从第几个位置起步
        self._slots_from = 0        # 走位起点（由 walk_from() 算出）

    # -- 名字 ----------------------------------------------------------
    def name(self) -> str:
        return self.text

    # -- 缩放 + 分环 ---------------------------------------------------
    @staticmethod
    def _rings(solid, rows: int, cols: int):
        """一格格往里腐蚀，得到每个格子的"深度"。0 = 最外圈，-1 = 背景。"""
        cur = [[bool(solid[y][x]) for x in range(cols)] for y in range(rows)]
        ring = [[-1] * cols for _ in range(rows)]
        k = 0
        while k < 32:
            nxt = [[False] * cols for _ in range(rows)]
            any_cur = False
            for y in range(rows):
                for x in range(cols):
                    if not cur[y][x]:
                        continue
                    any_cur = True
                    keep = True
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            yy, xx = y + dy, x + dx
                            if 0 <= yy < rows and 0 <= xx < cols:
                                if not cur[yy][xx]:
                                    keep = False
                            else:
                                keep = False
                    nxt[y][x] = keep
            if not any_cur:
                break
            for y in range(rows):
                for x in range(cols):
                    if cur[y][x] and not nxt[y][x]:
                        ring[y][x] = k
            cur = nxt
            k += 1
        return ring

    def scaled(self, cols: int, rows: int):
        """返回 (灰度图, 描边环, 填充环)。两份环分别按不同阈值算：
        描边要贴着字形外缘，填充要稍微胖一圈才有实心可填。"""
        if self._cache_key == (cols, rows):
            return self._cache_m, self._cache_ring, self._cache_ring_fill
        sw, sh, src = self.src_w, self.src_h, self.src
        m = []
        for cy in range(rows):
            y0 = cy * sh // rows
            y1 = max(y0 + 1, (cy + 1) * sh // rows)
            line = bytearray(cols)
            for cx in range(cols):
                x0 = cx * sw // cols
                x1 = max(x0 + 1, (cx + 1) * sw // cols)
                s = n = 0
                for yy in range(y0, y1):
                    r = src[yy]
                    s += sum(r[x0:x1])
                    n += x1 - x0
                line[cx] = s // max(1, n)
            m.append(line)

        edge = [[m[y][x] >= ON_LEVEL for x in range(cols)] for y in range(rows)]
        fill = [[m[y][x] >= ON_FILL for x in range(cols)] for y in range(rows)]
        self._cache_key = (cols, rows)
        self._cache_m = m
        self._cache_ring = self._rings(edge, rows, cols)
        self._cache_ring_fill = self._rings(fill, rows, cols)
        return m, self._cache_ring, self._cache_ring_fill

    # -- 蒙版 ----------------------------------------------------------
    def masked(self, cx: int, cy: int) -> bool:
        return self.mask[min(self.mh - 1, cy // self.bs_y)][min(self.mw - 1, cx // self.bs_x)]

    def active(self, t: float) -> bool:
        return self.FLASH_END <= t < self.HIDE_AT

    # -- 残影位置 ------------------------------------------------------
    def echo_slots(self, unit: int, vunit: int) -> list[tuple[int, int]]:
        """7 个位置的偏移（单位 = 主字宽 / 主字高）。间隔不均匀，中间刻意留空档。"""
        r = _rng(self.seed, "echo")
        out = []
        for i, mul in enumerate(ECHO_STEPS[:ECHO_COUNT]):
            jitter = 0.0 if i == 0 else r.uniform(-0.06, 0.06)
            dx = int(round((mul + jitter) * unit))
            out.append((max(0, dx), int(round(i * vunit * ECHO_DY))))
        return out

    def walk_from(self, extent: int) -> int:
        """走位的**起点**是第几个位置。

        取"最后一个还能整个装进画面的位置"：不能固定从最远的那个起步，
        那样主字有 0.25 秒待在屏幕外面，刚闪完白的那一下观众什么都看不到。
        比起点更远的那些位置在开局就盖好了 —— 它们本来就在屏幕外，看不见。
        """
        unit = self._unit
        offs = self.echo_slots(unit, self._vunit)
        start = 0
        for i, (dx, _dy) in enumerate(offs):
            if dx + unit <= extent:
                start = i
        return start

    def step_index(self, t: float) -> int:
        """主字现在停在第几个位置（起点 -> 0）。**离散**，没有中间态。

        一个位置停 ECHO_HOLD 秒（正好一个逻辑帧），然后整格跳到下一个。
        不要缓动：数字设备的位置变化是量子化的，"飘过去"是模拟设备的语汇。
        """
        if self.style != "echo":
            return 0
        k = math.floor(max(0.0, (t - ECHO_APPEAR) / ECHO_HOLD) + 1e-6)
        return int(max(0, self._slots_from - k))

    def step_times(self) -> list[float]:
        """所有会发生瞬移的时刻。给 next_change 用 —— 正好在这些时刻出帧，
        瞬移才会落在帧边界上，而不是被 12Hz 的细网格拖过半帧。"""
        if self.style != "echo" or self._extent <= 0:
            return []
        n = self.walk_from(self._extent)
        return [ECHO_APPEAR + (i + 1) * ECHO_HOLD for i in range(max(0, n))]

    def stamped(self, t: float, extent: int) -> tuple[list[tuple[int, int, int]], tuple[float, float]]:
        """返回 (已经盖下的副本 [(序号, dx, dy)], 主字当前位置的偏移)。

        位置是**整数序号**，不做插值 —— 主字是跳过去的，不是滑过去的。
        """
        if self.style != "echo":
            return [], (0.0, 0.0)
        offs = self.echo_slots(self._unit, self._vunit)
        p = self.step_index(t)
        here = (float(offs[p][0]), float(offs[p][1]))
        # 已经盖下的：位置在当前位置右下方的那几个（含当前位置本身）
        done = [(i, offs[i][0], offs[i][1]) for i in range(p, len(offs))]
        return done, here
        i0 = int(math.floor(p))
        i1 = min(len(offs) - 1, i0 + 1)
        f = p - i0
        here = (offs[i0][0] * (1 - f) + offs[i1][0] * f,
                offs[i0][1] * (1 - f) + offs[i1][1] * f)
        # 已经盖下的：位置在当前位置右下方的那几个
        done = [(i, offs[i][0], offs[i][1])
                for i in range(len(offs)) if i >= math.ceil(p) - 1e-9]
        return done, here

    # -- 错位：不规则分段（只用在残影上，主字保持可辨认）-----------------
    def _k(self, t: float) -> float:
        return min(1.0, max(0.0, (t - self.SLICE_AT) / 0.85))

    def row_offsets(self, t: float, rows: int) -> list[int]:
        k = self._k(t)
        if k <= 0:
            return [0] * rows
        r = _rng(self.seed, "seg@%d" % int(t * 9))
        amp = int(1 + 4 * k)
        density = 0.35 + 0.5 * k
        out = [0] * rows
        y = 0
        while y < rows:
            ln = r.randint(1, 6)
            o = r.randint(-amp, amp) if r.random() < density else 0
            for j in range(y, min(rows, y + ln)):
                out[j] = o
            y += ln
        return out

    def global_offset(self, t: float) -> int:
        k = self._k(t)
        if k <= 0:
            return 0
        r = _rng(self.seed, "glob@%d" % int(t * 6))
        if r.random() > 0.35 + 0.3 * k:
            return 0
        return r.randint(-2, 2)

    # -- 渲染 ----------------------------------------------------------
    def _drip_grid(self, g: Grid, solid, px: int, py: int, cols: int, rows: int,
                   t: float, k: float, u: float) -> None:
        """终端侧的向下拖影：每列从自己最低的实心格开始，连续往下淌到屏幕底。

        字符格做不出渐变，所以用**深浅三档**代替：贴着字身用字身色，往下换暗红，
        最远用更暗的一档。横向每三格挪一次，每列有自己的倾向 —— 错位是走出来的。
        """
        r = _rng(self.seed, "drip@%d" % int(t * 15))
        reach = int(round((g.h - py) * k))
        for cx in range(cols):
            b = -1
            for cy in range(rows - 1, -1, -1):
                if solid[cy][cx]:
                    b = cy
                    break
            if b < 0:
                continue
            # 就从这一列字形自己的底边往下掉
            y0 = py + b + 1
            y_end = min(g.h, y0 + reach)
            dx = 0
            lean = r.choice((-1, 0, 0, 0, 0, 1))
            for y in range(y0, y_end):
                if (y - y0) % 3 == 0:
                    dx = max(-3, min(3, dx + lean + r.choice((-1, 0, 0, 0, 0, 1))))
                gx = px + cx + dx
                if 0 <= gx < g.w:
                    frac = (y - py) / max(1.0, float(g.h - py))
                    st = (R.S_SCARE_BODY if frac < 0.34 else
                          R.S_SCARE_DIM if frac < 0.68 else R.S_SCARE_DRIP)
                    g.put(gx, y, "█", st)

    def collapse_rows(self, g: Grid, u: float) -> None:
        """终端侧的显像管塌缩：把字符网格压进一条横带。

        视频那边是把像素重采样进横带；字符网格没法重采样，所以只做"带外
        清空 + 带边缘回响"。看上去仍然是对的：亮带在收窄，最后剩一条白线。
        """
        if u <= 0.0:
            return
        h = g.h
        cy = h // 2
        half = int(max(1, (h * 0.5) / (1.0 + 13.0 * u) ** 1.3))
        y0, y1 = max(0, cy - half), min(h, cy + half)
        for y in range(h):
            if y0 <= y < y1:
                continue
            if u > 0.45 and (y0 - 2 <= y < y0 or y1 <= y < y1 + 2):
                g.fill(0, y, g.w, "█", R.S_BRIGHT)          # 亮回响
            else:
                g.fill(0, y, g.w, " ", R.S_BASE)
        if u > 0.82:
            for y in range(max(0, cy - 1), min(h, cy + 2)):
                g.fill(0, y, g.w, "█", R.S_FLASH)           # 最后一条亮线

    def render(self, g: Grid, t: float) -> None:
        if t < self.FLASH_END:
            # 闪屏要填亮色实心块：此刻网格刚被清空，反白一个空屏仍然是黑的；
            # 而整行空格落盘时会被裁掉（底色丢失），视频里就看不见了。
            for y in range(g.h):
                g.fill(0, y, g.w, "█", R.S_FLASH)
            return
        if self.HIDE_AT <= t < self.CUT_END:
            # 硬切那一闪不是一块白板：按不规则门闪，像显像管回扫
            st = R.S_FLASH if self.strobe(t) in self.STROBE_ON else R.S_BASE
            ch = "█" if st == R.S_FLASH else " "
            for y in range(g.h):
                g.fill(0, y, g.w, ch, st)
            return
        if t >= self.CUT_END:
            return

        u = self.sev(t)

        # 0) 终端层背景潜意识转储（只用非 █ 字符 + S_SCARE_DRIP/DIM 样式，
        #    既营造模拟恐怖的底层崩溃压迫感，又不干扰主字与瀑布的实心块检测）
        bg_rng = _rng(self.seed, "bg_grid@%d" % int(t * 15))
        bg_msgs = (
            "STOP: 0x00000133 (0x00000001, 0x00001E00, 0xFFFFF80003A1C000) // DPC_WATCHDOG_VIOLATION",
            "COMMIT_PEAK: 77.4 GB (+150.4 MB/s) // PAGEFILE_EXHAUSTED // MEMORY.DMP_ACTIVE",
            "WIN32K #700: INPUT_SUPPRESS_REQUEST=1 // KEYBOARD_AND_POINTER_LOCKED",
            "WIN32K #263: MONITOR_0_TOPOLOGY_UNKNOWN // EXTERNAL_OBSERVER_DETECTED",
            "NT_AUTHORITY\\SYSTEM: CREDENTIAL_VERIFICATION_FAILED // WHO_IS_WATCHING?",
        )
        n_bg = int(2 + u * (g.h * 0.45))
        for bi in range(n_bg):
            by = bg_rng.randrange(0, g.h)
            bx = bg_rng.randrange(0, max(1, g.w // 3))
            msg = bg_msgs[(bi + int(t * 9)) % len(bg_msgs)]
            st_bg = R.S_SCARE_DIM if (bi % 3 == 0 and u > 0.35) else R.S_SCARE_DRIP
            g.put(bx, by, R.truncate(msg, g.w - bx - 1), st_bg)
        for _ in range(int(12 + 45 * u)):
            by = bg_rng.randrange(0, g.h)
            bx = bg_rng.randrange(0, g.w)
            g.put(bx, by, bg_rng.choice("░▒┼═─│·:"), R.S_SCARE_DRIP)

        # 尺寸：和视频那边**按像素**对齐，不是按格对齐。
        # 终端的一个字符格是 10×22 像素（高是宽的 2.2 倍），如果拿同一个
        # scale 去乘源图的宽和高，字会被纵向拉长 2.2 倍 —— 这就是为什么
        # 早先终端版的大字又扁又胖，而且副本会一路排到屏幕外面去。
        # 所以高度先换算成"宽度当量"（×CELL_ASPECT）再参与比较。
        avail_c = max(24.0, g.w * 0.30)
        avail_r = max(6.0, g.h * 0.46) * CELL_ASPECT
        src_ar = self.src_w / max(1.0, self.src_h)
        cols = int(min(avail_c, avail_r * src_ar))
        rows = int(round(cols / src_ar / CELL_ASPECT))
        # 但按像素等比缩出来的字，在终端里只有三点几行高 —— 等于认不出写的是什么。
        # 字符的分辨率比像素低一个数量级，所以这里必须让步：**字高优先**，
        # 宁可少留几个副本（终端那条路大概只看得到 2~3 个），也不能糊成一团。
        rows = max(rows, MIN_ROWS)
        cols = max(20, int(round(rows * src_ar * CELL_ASPECT)))
        if cols > g.w * 0.52:
            cols = int(g.w * 0.52)
            rows = max(MIN_ROWS, int(round(cols / src_ar / CELL_ASPECT)))

        m, ring, ring_fill = self.scaled(cols, rows)
        self._unit, self._vunit = cols, rows
        self._extent = g.w
        self._slots_from = self.walk_from(g.w)
        done, here = self.stamped(t, g.w)
        x0 = max(3, int(g.w * 0.05))
        y0 = max(2, int(g.h * 0.09))

        # 1) 残影：暗红实心、逐个变淡。它们是背景 —— 主字才需要认得出来。
        solid = [[m[cy][cx] >= ON_FILL and not self.masked(cx, cy)
                  for cx in range(cols)] for cy in range(rows)]

        def near(cy, cx, d=1):
            for dy in range(-d, d + 1):
                for dx in range(-d, d + 1):
                    yy, xx = cy + dy, cx + dx
                    if 0 <= yy < rows and 0 <= xx < cols and solid[yy][xx]:
                        return True
            return False

        for i, dx, dy in done:
            ro = self.row_offsets(t, rows)
            go = self.global_offset(t)
            rr = _rng(self.seed, "eat%d@%d" % (i, int(t * 15)))
            p_eat = min(0.75, (u ** 1.3) * 0.9)
            px0 = x0 + dx
            py0 = y0 + dy
            for cy in range(rows):
                py = py0 + cy
                if py < 0 or py >= g.h:
                    continue
                sh = ro[cy] + go
                for cx in range(cols):
                    if not solid[cy][cx]:
                        continue
                    if p_eat > 0.02 and rr.random() < p_eat:
                        continue        # 缺墨：这一格丢了
                    px = px0 + cx + sh
                    if 0 <= px < g.w:
                        g.put(px, py, "█", R.S_SCARE_DIM)

        # 2) 主字：实心亮红 + 一圈黑缝 + 浅红描边环。始终画满。
        pxm, pym = int(round(x0 + here[0])), int(round(y0 + here[1]))
        if self.style != "solid":
            for cy in range(rows):
                py = pym + cy
                if py < 0 or py >= g.h:
                    continue
                for cx in range(cols):
                    if solid[cy][cx] or not near(cy, cx, 1):
                        continue
                    px = pxm + cx
                    if 0 <= px < g.w:
                        g.put(px, py, "█", R.S_SCARE_GAP)

        # 2b) 向下拖影：只给**落位之后**的主字做，画在主字**之前** ——
        #     起点高的列会穿过下面的字，压在字后面才像"墨从字缝里淌出来"。
        dk = self.drip_k(t)
        if dk > 0.01 and here[0] == 0.0 and here[1] == 0.0:
            self._drip_grid(g, solid, pxm, pym, cols, rows, t, dk, u)

        # 3) 主字：实心亮红 + 一圈黑缝 + 交给上面的描边环
        drop = _rng(self.seed, "maintext@%d" % int(t * 15)) if u > 0.90 else None
        for cy in range(rows):
            py = pym + cy
            if py < 0 or py >= g.h:
                continue
            for cx in range(cols):
                if not solid[cy][cx]:
                    continue
                if drop is not None and drop.random() < 0.04:
                    continue
                px = pxm + cx
                if 0 <= px < g.w:
                    g.put(px, py, "█", R.S_SCARE_RED)

        # 4) 收尾：显像管塌缩
        self.collapse_rows(g, self.collapse_u(t))

    # -- 视频端：真正的矢量绘制（实心填充 + 浅红紧密描边）------------------
    # 终端只能画字符，所以终端那条路仍然是字符近似；
    # 出片这条路直接画到像素上 —— 实心矢量字 + 一圈紧贴的浅红描边。
    FILL_RGB = (0xE8, 0x1B, 0x1F)      # 实心红
    STROKE_RGB = (0xFF, 0xB4, 0xAC)    # 浅红描边
    GLOW_RGB = (0x8A, 0x0C, 0x10)      # 荧光余辉（加性）
    FLASH_RGB = (0xE6, 0xEE, 0xFA)
    BG_RGB = (0x06, 0x07, 0x0A)        # 跳杀期间的黑底（不是纯黑，留一点余辉）

    # 严重度：全部效果共用**一个**标量。
    # 早先每个效果各走各的线性时钟，结果是一堆东西同时缓慢变化，没有"逼上来"
    # 的感觉。指数 2.6 的意思是：前一半时间只走到 16%，最后 20% 走完一半以上。
    # 这是 credits_ex_cli 全片唯一的时间语法（b**1.4 / b**1.2 / 24/b**1.3），
    # 也是这个结尾之前最缺的东西。
    SEV_P = 2.6
    # 显像管塌缩：最后 0.28 秒，画面被压成一条横带
    COLLAPSE_AT = HIDE_AT - 0.28
    # 不规则频闪：下标是时间的幂，所以频闪自己会越来越快，而且永远不成周期。
    # 注意频闪只作用在**残影和背景**上 —— 主字始终实心画满，否则就又变成
    # "认不出写的什么"了。
    STROBE_HZ = 12.0
    STROBE_N = 7
    STROBE_P = 1.30
    STROBE_ON = (0, 1, 4)

    # 低墨量替换集：早期用"缺墨"（点、空格）而不是"碎片" —— 信号丢失
    # 和画面被砸是两件事，先丢信号，后砸画面。
    LOW_INK = (".", ".", " ", " ", "`", "=", "/", "?", "-")

    def sev(self, t: float) -> float:
        k = (t - self.FLASH_END) / max(1e-6, self.HIDE_AT - self.FLASH_END)
        return min(max(k, 0.0), 1.0) ** self.SEV_P

    def strobe(self, t: float) -> int:
        return int((max(0.0, t) * self.STROBE_HZ) ** self.STROBE_P) % self.STROBE_N

    def collapse_u(self, t: float) -> float:
        """塌缩进度 0..1（只在最后 0.28 秒非零）。"""
        if t <= self.COLLAPSE_AT:
            return 0.0
        return min(1.0, (t - self.COLLAPSE_AT) / max(1e-6, self.HIDE_AT - self.COLLAPSE_AT))

    # -- 向下拖影（瀑布）------------------------------------------------
    def drip_k(self, t: float) -> float:
        """拖影进度 0..1。落位之后才开始淌 —— 走位那一路不留瀑布。"""
        land = ECHO_APPEAR + ECHO_HOLD * max(1, self._slots_from)
        return min(1.0, max(0.0, (t - land - DRIP_DELAY) / DRIP_RAMP))

    def _drip_bottoms(self, solid, cols: int, rows: int) -> list:
        """每一列最低的那个实心格 / 像素。字母本身高低不齐，起点天然就是错的。"""
        out = []
        for cx in range(cols):
            b = -1
            for cy in range(rows - 1, -1, -1):
                if solid[cy][cx]:
                    b = cy
                    break
            out.append(b)
        return out

    def _drip_pixels(self, frame, fill, px: int, py: int, cols: int, rows: int,
                     t: float, k: float, u: float) -> None:
        """把主字的下端一列一列连续往下拉出屏幕。

        每列一条：从它自己最低的实心像素开始，一直画到屏幕底。横向沿路缓慢
        随机漂移，所以列与列之间会慢慢岔开 —— 错位是走出来的，不是一开始切好的。
        """
        import numpy as np
        h, w = frame.shape[0], frame.shape[1]
        bottoms = self._drip_bottoms(fill.tolist(), cols, rows)
        r = _rng(self.seed, "drip@%d" % int(t * 15))
        fill_c = np.array(self.FILL_RGB, dtype=np.float32)
        reach = int(round((h - py) * k))      # 一开始只淌一小段，慢慢淌到底
        for cx in range(cols):
            b = bottoms[cx]
            if b < 0:
                continue
            # **就从这一列字形自己的底边往下掉**。不做统一底线 ——
            # 字母本身高低不齐，所以每一列的起点天然是错的。
            y0 = py + b + 1
            y_end = min(h, y0 + reach)
            x = float(px + cx)
            lean = r.uniform(-DRIP_LEAN, DRIP_LEAN)     # 这一列自己的倾向
            for y in range(y0, y_end, DRIP_SEG):
                dy = min(DRIP_SEG, y_end - y)
                x += lean * dy + r.uniform(-DRIP_JITTER, DRIP_JITTER)
                xx = int(round(x))
                if 0 <= xx < w:
                    frac = (y - py) / max(1.0, float(h - py))
                    a = max(0.10, k * (0.92 - 0.72 * frac) * (1.0 - 0.2 * u))
                    xx1 = min(w, xx + DRIP_W)
                    sub = frame[y:y + dy, xx:xx1].astype(np.float32)
                    frame[y:y + dy, xx:xx1] = (sub * (1.0 - a) + fill_c * a).astype(np.uint8)

    def pixel_plate(self, bw: int, bh: int):
        """把短语缩成 bw×bh 的 (填充, 描边, 辉光, 扫描线)，都是 0..1 的 float32。

        电子感来自三件事，缺一不可：
          * **硬边**：填充直接二值化，不做抗锯齿软过渡 —— 软过渡就是"纸质"的根源；
          * **扫描线**：填充内部按行打条纹，像荧光屏的行扫描；
          * **辉光**：整体模糊一份，加性叠在下面，当作荧光余辉。
        """
        if self._plate_key == (bw, bh):
            return self._plate
        import numpy as np
        from PIL import Image, ImageFilter

        src = np.array([list(r) for r in self.src], dtype=np.uint8)
        img = Image.fromarray(src, "L").resize((bw, bh), Image.BILINEAR)
        a = np.asarray(img, dtype=np.float32) / 255.0
        fill = (a > 0.5).astype(np.float32)                 # 硬边
        fi = Image.fromarray((fill * 255).astype(np.uint8), "L")
        dil = np.asarray(fi.filter(ImageFilter.MaxFilter(5)), dtype=np.float32) / 255.0
        stroke = np.clip(dil - fill, 0.0, 1.0)
        glow = np.asarray(fi.filter(ImageFilter.GaussianBlur(max(1.5, bw * 0.008))),
                          dtype=np.float32) / 255.0
        glow = np.clip(glow * 1.35 - 0.12, 0.0, 1.0)
        # 行扫描：每两行压暗一次
        scan = np.where((np.arange(bh) % 2 == 0)[:, None], 1.0, 0.52).astype(np.float32)
        scan = np.repeat(scan, bw, axis=1)
        self._plate_key = (bw, bh)
        self._plate = (fill, stroke, glow, scan)
        return self._plate

    def _blit(self, frame, mask, rgb, px: int, py: int, mode: str = "over",
              alpha: float = 1.0) -> None:
        import numpy as np
        h, w = frame.shape[0], frame.shape[1]
        mh, mw = mask.shape
        x0, y0 = max(0, px), max(0, py)
        x1, y1 = min(w, px + mw), min(h, py + mh)
        if x0 >= x1 or y0 >= y1:
            return
        sub = mask[y0 - py:y1 - py, x0 - px:x1 - px]
        if sub.max() <= 0.002:
            return
        al = sub[:, :, None] * float(alpha)
        dst = frame[y0:y1, x0:x1].astype(np.float32)
        col = np.array(rgb, dtype=np.float32)
        if mode == "add":
            frame[y0:y1, x0:x1] = np.clip(dst + col * al * 0.55, 0, 255).astype(np.uint8)
        else:
            frame[y0:y1, x0:x1] = (dst * (1.0 - al) + col * al).astype(np.uint8)

    # -- 背景层：爬过画面的损坏 ----------------------------------------
    def _background(self, frame, t: float, u: float) -> None:
        """残影之外的那一层：横向撕裂 + 丢像素。

        两个要点：

        * 撕裂带的位置按**固定顺序**推进（不是每帧重掷），所以画面上是
          "损坏在爬过整个画面"，而不是"损坏在原地闪"。这是 credits_ex_cli 的
          materialise 门（`randint(0, max(1, 32 - int(b**1.2))) < 4`）翻过来用：
          随机只用来定顺序，推进交给严重度。
        * 颜色必须比底色**亮**。背景是近黑的，往黑里再压黑等于什么都没画 ——
          这里填的是暗红/暗灰，才看得见"裂纹"。
        """
        import numpy as np
        h, w = frame.shape[0], frame.shape[1]
        if self._bands is None:
            r = _rng(self.seed, "bands")
            self._bands = sorted(r.sample(range(0, max(2, h - 4)), 14))
        n = int(len(self._bands) * min(1.0, u ** 1.5))
        tint = np.array([int(20 + 70 * u), int(6 + 16 * u), int(8 + 20 * u)],
                        dtype=np.uint8)
        for i in range(n):
            y = self._bands[i]
            bh = 1 + (i % 3)
            y1 = min(h, y + bh)
            if y1 <= y:
                continue
            dx = int((_rng(self.seed, "shift@%d" % i).random() - 0.5) * w * 0.22 * (0.4 + u))
            frame[y:y1] = np.roll(frame[y:y1], dx, axis=1)
            frame[y:y1] = np.maximum(frame[y:y1], tint)
        # 丢像素：亮点。压黑是看不见的，所以要提亮。
        cnt = int(w * h * 0.00045 * (u ** 1.3))
        if cnt > 0:
            r = _rng(self.seed, "spk@%d" % int(t * 15))
            ys = [r.randrange(h) for _ in range(cnt)]
            xs = [r.randrange(w) for _ in range(cnt)]
            hi = int(135 + 110 * u)
            frame[ys, xs] = np.array([hi, hi // 3, hi // 4], dtype=np.uint8)
        # 模拟恐怖高频负片/血红扫描闪烁条（随严重度逼近而密集）
        if u > 0.18:
            sr = _rng(self.seed, "slash@%d" % int(t * 15))
            bars = 1 + int(u * 6)
            for _ in range(bars):
                sy = sr.randrange(0, max(1, h - 18))
                sh = sr.randrange(2, max(4, int(16 * u) + 3))
                if sr.random() < 0.55:
                    # 血红反相扫描带
                    sub = frame[sy:sy + sh].astype(np.int32)
                    frame[sy:sy + sh, :, 0] = np.clip(180 + (255 - sub[:, :, 0]) // 3, 0, 255).astype(np.uint8)
                    frame[sy:sy + sh, :, 1] = (sub[:, :, 1] // 3).astype(np.uint8)
                    frame[sy:sy + sh, :, 2] = (sub[:, :, 2] // 3).astype(np.uint8)
                else:
                    # 强水平同步错位
                    frame[sy:sy + sh] = np.roll(frame[sy:sy + sh], sr.randint(-w // 3, w // 3), axis=1)

    def crt_collapse(self, frame, u: float) -> None:
        """显像管断电：整幅画面被压进一条横带，带外是黑，带边缘有亮/暗回响。

        这一招来自 credits_ex_cli 的 `make_poweroff_bars`：高度按 `24 / b**1.3`
        收缩，中心固定。它的四个 generator 用 b+1 / b / b-1 / b-2 分别画
        亮白 / 常白 / 暗白 / 黑，于是收缩的亮条前后各拖着一条回响。
        """
        import numpy as np
        h = frame.shape[0]
        if u <= 0.0:
            return
        bg = np.array(self.BG_RGB, dtype=np.uint8)
        cy = h // 2
        half = int(max(2, (h * 0.5) / (1.0 + 13.0 * u) ** 1.3))
        y0, y1 = max(0, cy - half), min(h, cy + half)
        src = frame.copy()
        bh = max(1, y1 - y0)
        rows = np.linspace(0, h - 1, bh).astype(np.int32)   # 整幅压进这条带
        frame[:] = bg
        frame[y0:y1] = src[rows]
        if u > 0.45:                                        # 亮回响
            frame[max(0, y0 - 3):y0] = (src[rows[:min(3, bh)]] * 0.45).astype(np.uint8)
            frame[y1:min(h, y1 + 3)] = (src[rows[-min(3, bh):]] * 0.30).astype(np.uint8)
        if u > 0.82:                                        # 最后一条亮线
            frame[max(0, cy - 1):cy + 2] = np.array([0xE6, 0xEE, 0xFA], dtype=np.uint8)

    def render_pixels(self, frame, t: float) -> None:
        """把跳杀直接画进 RGB 帧（原地）。frame 是 uint8 的 (H,W,3)。"""
        import numpy as np
        h, w = frame.shape[0], frame.shape[1]
        if t < self.FLASH_END:
            frame[:] = np.array(self.FLASH_RGB, dtype=np.uint8)
            return
        if self.HIDE_AT <= t < self.CUT_END:
            # 硬切那一闪不做成一块白板：按不规则门闪三下，像显像管回扫
            if self.strobe(t) in self.STROBE_ON:
                frame[:] = np.array(self.FLASH_RGB, dtype=np.uint8)
            else:
                frame[:] = np.array(self.BG_RGB, dtype=np.uint8)
            return
        if t >= self.CUT_END:
            return

        u = self.sev(t)
        # 底色不是清空，是**压暗到 55%**：出片那条路在这之前已经把解码失败的
        # 宏块画进 frame 了，清空就等于把它全抹掉。压暗既给了大字一个暗底，
        # 又让世界碎掉的那层留在后面。
        frame[:] = (frame.astype(np.float32) * 0.55).astype(np.uint8)
        self._background(frame, t, u)

        cols, rows = self.plate_size(w, h)
        self._unit, self._vunit = cols, rows
        self._extent = w
        self._slots_from = self.walk_from(w)
        fill, stroke, glow, scan = self.pixel_plate(cols, rows)
        done, here = self.stamped(t, w)
        x0 = max(3, int(w * 0.05))
        y0 = max(2, int(h * 0.09))

        # 1) 残影：暗红、逐个变淡、没有亮描边。它们是背景，不是主角。
        for i, dx, dy in done:
            a = max(0.06, ECHO_DIM * (0.78 ** i)) * (1.0 - 0.35 * u)
            m = fill
            if u > 0.05:
                # 缺墨：随严重度被啃掉一些格子。用固定顺序＋严重度推进，
                # 所以是"损坏在爬过字形"，不是"每帧重新随机"。
                m = fill.copy()
                rr = _rng(self.seed, "eat%d@%d" % (i, int(t * 15)))
                k = int(rows * cols * min(0.75, u ** 1.3) * 0.03)
                if k:
                    ys = [rr.randrange(rows) for _ in range(k)]
                    xs = [rr.randrange(cols) for _ in range(k)]
                    m[ys, xs] = 0.0
            if i <= 1:
                self._blit(frame, glow, self.GLOW_RGB, x0 + dx, y0 + dy,
                           mode="add", alpha=0.6)
            self._blit(frame, m * scan, ECHO_RGB, x0 + dx, y0 + dy, alpha=a)

        # 2) 主字：**始终**实心画满 + 一圈浅红紧贴描边。
        #    "认得出写的是什么"是底线 —— 前面几版跳杀全毁在这一条上：
        #    副本和主字一样亮、还有描边，七个叠在一起就什么都没了。
        px, py = int(round(x0 + here[0])), int(round(y0 + here[1]))
        pm = fill
        if u > 0.90:
            pm = fill.copy()
            rr = _rng(self.seed, "main@%d" % int(t * 15))
            k = int(rows * cols * 0.010)
            ys = [rr.randrange(rows) for _ in range(k)]
            xs = [rr.randrange(cols) for _ in range(k)]
            pm[ys, xs] = 0.0
        # 2b) 向下拖影：只给**落位之后**的主字做，走位那一路不留瀑布。
        #     画在主字**之前** —— 有些列的起点比另一些列高（字母高低不齐），
        #     那些会穿过下面的字。压在字后面才像"墨从字缝里淌出来"。
        dk = self.drip_k(t)
        if dk > 0.01 and here[0] == 0.0 and here[1] == 0.0:
            self._drip_pixels(frame, pm, px, py, cols, rows, t, dk, u)

        # 3) 主字：实心填充 + 浅红紧贴描边 + 加性辉光
        self._blit(frame, glow, self.GLOW_RGB, px, py, mode="add")
        self._blit(frame, stroke, self.STROKE_RGB, px - 2, py - 2)
        self._blit(frame, pm * scan, self.FILL_RGB, px, py)

        # 3) 色边：只在主字上做，红右移、蓝左移。范围一小就只是"没对齐"，
        #    铺满全屏就变成"看不清"。
        sh = 1 + int(u * 2)
        ax0, ay0 = max(0, px - 3), max(0, py - 3)
        ax1, ay1 = min(w, px + cols + 3), min(h, py + rows + 3)
        if ax1 > ax0 and ay1 > ay0:
            sub = frame[ay0:ay1, ax0:ax1]
            sub[:, :, 0] = np.roll(sub[:, :, 0], sh, axis=1)
            sub[:, :, 2] = np.roll(sub[:, :, 2], -sh, axis=1)

        # 4) 收尾：显像管塌缩
        self.crt_collapse(frame, self.collapse_u(t))

    def plate_size(self, w: int, h: int) -> tuple[int, int]:
        """主字画多大。占屏宽三成 —— 再大就没有地方给后面那串副本了。"""
        max_cols = max(24, int(w * 0.30))
        max_rows = max(6, int(h * 0.46))
        scale = min(max_cols / self.src_w, max_rows / self.src_h)
        return max(20, int(self.src_w * scale)), max(4, int(self.src_h * scale))

    # -- 逻辑帧 --------------------------------------------------------
    def next_change(self, t: float) -> float:
        """下一个画面会变的时刻：标记点 / 瞬移时刻 / 12Hz 细步长，取最早的。

        瞬移时刻必须显式列出来。只靠 12Hz 细网格的话，瞬移会被网格拖过半帧
        （0.10 的起点加上 1/12 的步长，与 1/12 网格差半格），看起来就不是
        "啪"地跳过去，而是隔一帧才跳 —— 量子化的意义就没了。
        """
        q = 1.0 / self.HZ
        # +1e-6：t 正好落在细网格上时，浮点误差会让算出来的"下一格"等于自己，
        # 结果被调用方的 eps 过滤掉，只能退到整秒刻度 —— 动画就成了每秒一跳。
        nxt = (math.floor(t / q + 1e-6) + 1) * q
        for mark in (self.FLASH_END, self.HIDE_AT, self.CUT_END):
            if mark > t + 1e-6:
                nxt = min(nxt, mark)
        for mark in self.step_times():
            if mark > t + 1e-6:
                nxt = min(nxt, mark)
        return nxt
