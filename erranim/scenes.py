"""场景编排：把崩溃记录排成一条严重度递增的叙事线。

每个场景是"有效时间"的纯函数：render(g, t) 只依赖 t。
时间重映射（holds）让画面真的可以卡住 —— 冻结期间 teff 不动。
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from datetime import datetime, timedelta

from . import glitch as G
from . import records as REC
from . import render as R
from . import widgets as W
from .render import Grid, pad, truncate
from .scare import JumpScare

SEED = 20260924
TS_BASE = datetime(2026, 9, 24, 23, 8, 21)
BLINK = 0.5  # 帧头 REC 灯的闪烁周期
RES_HZ = 4.0  # 资源面板的刷新率：它只在这条时间轴上取值，逻辑帧照旧只认变化点


def L(t: float, text: str, style: int = R.S_BASE) -> tuple:
    return (t, text, style)


def style_for_event(ev) -> int:
    """按事件严重度给颜色，让"有逻辑的错误出现"一眼能读出层次。"""
    sev = getattr(ev, "severity", 1)
    if sev <= 0:
        return R.S_DIM
    if sev == 2:
        return R.S_RED
    if sev == 3:
        return R.S_YELLOW
    if sev == 4:
        return R.S_RED
    return R.S_MAGENTA


class GenContext:
    """随机机制的总开关与共享上下文。

    random_on 为真且有语料库时：噪声行读真实事件，各段还会额外插入
    按严重度递增采样出来的"有逻辑的错误链"。全部由 seed 决定，可复现。
    """

    def __init__(self, corpus=None, seed: int = 20260924, random_on: bool = False):
        self.corpus = corpus
        self.rng = random.Random(seed)
        self.random_on = bool(random_on and corpus is not None)

    def describe(self) -> str:
        if self.random_on and self.corpus is not None:
            st = self.corpus.stats()
            return "随机模式 开（语料库 %d 条去重事件，%d 条带原因）" % (st["distinct"], st["with_reason"])
        if self.corpus is not None:
            return "随机模式 关（语料库已加载，可加 --random on 启用）"
        return "随机模式 关（未找到语料库）"


# --------------------------------------------------------------------------
# 进度条相位
# --------------------------------------------------------------------------


class BarPhase:
    """一段"修正操作"的倒计时。frac 由关键帧插值得到，因此可解析求出下一帧变化点。"""

    def __init__(
        self,
        t0: float,
        t1: float,
        level: int = 1,
        ms: int | None = None,
        outcome: str = "ok",
        label: str = "",
        tail: str = "正在重新启动服务...",
        levels: list | None = None,
    ):
        self.t0 = t0
        self.t1 = t1
        self.level = level
        self.ms = ms
        self.outcome = outcome
        self.label = label or ("以下的修正操作将在 %s 毫秒内运行: 重新启动服务。" % (ms if ms is not None else 0))
        self.tail = tail
        self.levels = sorted(levels or [])
        self._segs: list[tuple[float, float]] | None = None

    # -- 关键帧 --------------------------------------------------------
    def segs(self) -> list[tuple[float, float]]:
        if self._segs is None:
            d = max(1e-6, self.t1 - self.t0)
            o = self.outcome
            if o == "ok":
                s = [(self.t0, 0.0), (self.t1, 1.0)]
            elif o == "fail":
                s = [(self.t0, 0.0), (self.t0 + 0.80 * d, 0.88), (self.t1, 0.88)]
            elif o == "reset":
                s = [
                    (self.t0, 0.0),
                    (self.t0 + 0.50 * d, 1.0),
                    (self.t0 + 0.56 * d, 0.02),
                    (self.t0 + 0.86 * d, 0.52),
                    (self.t1, 0.30),
                ]
            else:  # never —— 卡住不动
                s = [(self.t0, 0.0), (self.t0 + 0.55 * d, 0.61), (self.t0 + 0.78 * d, 0.62), (self.t1, 0.61)]
            self._segs = s
        return self._segs

    def level_at(self, t: float) -> int:
        lv = self.level
        for tt, l in self.levels:
            if t >= tt:
                lv = l
        return lv

    def frac_at(self, t: float) -> float:
        s = self.segs()
        if t <= s[0][0]:
            return s[0][1]
        if t >= s[-1][0]:
            return s[-1][1]
        for (ta, fa), (tb, fb) in zip(s, s[1:]):
            if ta <= t <= tb:
                if tb <= ta:
                    return fb
                return fa + (fb - fa) * (t - ta) / (tb - ta)
        return s[-1][1]

    def next_change(self, t: float, gw: int) -> float:
        s = self.segs()
        best = self.t1 + 1e-3
        # 下一个关键帧
        for ta, _fa in s:
            if ta > t + 1e-9:
                best = min(best, ta)
                break
        # 下一个格子边界（进度条真正"看起来变了"的时刻）
        for (ta, fa), (tb, fb) in zip(s, s[1:]):
            if ta <= t < tb:
                if fb == fa or tb <= ta:
                    best = min(best, tb)
                    break
                inner = W.bar_inner(gw, self.level_at(t))
                cur = fa + (fb - fa) * (t - ta) / (tb - ta)
                if fb > fa:
                    target = (int(cur * inner) + 1) / inner
                else:
                    target = (int(cur * inner) - 1) / inner
                tt = ta + (target - fa) / (fb - fa) * (tb - ta)
                best = min(best, tt if t < tt < tb else tb)
                break
        return best


class Prompt:
    """「是否重试? (Y/n)」—— 交互模式下玩家可以真的按键，但系统未必听。"""

    def __init__(self, t0: float, t1: float, text: str = "是否重试? (Y/n)", auto: str = "Y"):
        self.t0 = t0
        self.t1 = t1
        self.text = text
        self.auto = auto
        self.answer: str | None = None  # 'y' / 'n' / None

    def shown_answer(self, t: float) -> str:
        if self.answer:
            return self.answer.upper()
        if t >= self.t1:
            return self.auto
        return ""


# --------------------------------------------------------------------------
# 场景
# --------------------------------------------------------------------------


class Scene:
    def __init__(
        self,
        name: str,
        title: str,
        duration: float,
        logs=(),
        bars=(),
        prompts=(),
        glitches=(),
        status=(),
        count=(),
        clears=(),
        holds=(),
        ts_jumps=(),
        modals=(),
        bare: bool = False,
        log_align: str = "bottom",
        cursor: bool = False,
        noise_step: float = 0.22,
        noise_from: float = -6.0,
        ctx: "GenContext | None" = None,
        scare=None,
        extra_errors: int = 0,
    ):
        self.name = name
        self.title = title
        self.duration = float(duration)
        self.logs = sorted(logs, key=lambda c: c[0])
        self.bars = sorted(bars, key=lambda b: b.t0)
        self.prompts = sorted(prompts, key=lambda p: p.t0)
        self.glitches = sorted(glitches, key=lambda g: g.t)
        self.status = sorted(status, key=lambda c: c[0])
        self.count = sorted(count, key=lambda c: c[0])
        self.clears = sorted(clears)
        self.holds = sorted(holds)
        self.ts_jumps = sorted(ts_jumps)
        self.modals = sorted(modals, key=lambda m: m[0])
        self.bare = bare
        self.log_align = log_align
        self.cursor = cursor
        self.ctx = ctx
        self.scare = scare
        self.extra: list[tuple] = []
        self._merged: list[tuple] | None = None
        self._times: list[float] | None = None
        self.ts_origin = 0.0  # 全局起点，由 schedule() 填，保证时间戳跨段连续
        # 每段的资源曲线相位错开，免得每段开场都长一个样
        self.res_seed = (sum(ord(c) for c in name) % 360) * 0.01745
        self._build_map()
        if noise_step > 0:
            self._fill_noise(noise_step, noise_from)
        if extra_errors > 0 and ctx is not None and ctx.random_on:
            self._add_corpus_errors(extra_errors)

    # -- 语料库随机错误 ------------------------------------------------
    def _add_corpus_errors(self, n: int) -> None:
        """从语料库按严重度递增采一串"有逻辑"的事件，均匀铺在本段里。"""
        assert self.ctx is not None and self.ctx.corpus is not None
        evs = self.ctx.corpus.sequence(self.ctx.rng, n)
        end = max(0.6, self.duration_eff - 1.0)
        step = end / (n + 1)
        out = []
        for i, ev in enumerate(evs):
            t = step * (i + 1)
            out.append((t, ("[%d] " % ev.id) + ev.text(), style_for_event(ev)))
        if out:
            self.logs = sorted(self.logs + out, key=lambda c: c[0])

    # -- 日常噪声填充 --------------------------------------------------
    def _fill_noise(self, step: float, start: float) -> None:
        """让日志区总是满的：红/琥珀色的异常行才有"从噪声里浮出来"的对比。

        start 为负表示在时间轴起点之前就预置若干行 —— 这样每段一开场
        日志区就已经是满的，而不是先空一大片再慢慢填。
        """
        marks = [c[0] for c in self.logs]
        out = []
        t = start
        i = 600 + int(self.duration * 37) % 4000
        end = self.duration_eff - 0.12
        while t < end:
            # 预置行（t<=0）无条件加；正时间轴上避开已有日志的时刻
            if t <= 0 or not any(abs(t - m) < 0.06 for m in marks):
                out.append((t, self._noise_text(i), R.S_DIM))
            i += 1
            t += step
        if out:
            self.logs = sorted(self.logs + out, key=lambda c: c[0])

    def _noise_text(self, i: int) -> str:
        """背景噪声行：随机模式开且语料库可用时，读真实事件。

        每 5 行留一行给带数字的诊断模板，免得长文全是同一句 7040。
        """
        if self.ctx is not None and self.ctx.random_on and self.ctx.corpus is not None:
            if i % 5 != 4:
                ev = self.ctx.corpus.noise(self.ctx.rng)
                return "[%d] %s" % (ev.id, ev.main)
        return REC.noise_line(i)

    # -- 时间重映射 ----------------------------------------------------
    def _build_map(self) -> None:
        segs: list[tuple[float, float, float, float]] = []
        real = 0.0
        eff = 0.0
        for a, b in self.holds:
            if b <= a:
                continue
            if a > real:
                segs.append((real, a, eff, 1.0))
                eff += a - real
                real = a
            segs.append((real, b, eff, 0.0))  # 冻结
            real = b
        segs.append((real, float("inf"), eff, 1.0))
        self._segs = segs

    def teff(self, t: float) -> float:
        for r0, r1, e0, s in self._segs:
            if r0 <= t < r1:
                return e0 + (t - r0) * s
        return self.duration

    def real_of(self, te: float) -> float:
        for r0, r1, e0, s in self._segs:
            if s <= 0:
                continue
            e1 = e0 + (r1 - r0)
            if e0 <= te < e1:
                return r0 + (te - e0)
        return self.duration

    def frozen_at(self, t: float) -> float | None:
        """若 t 落在冻结区间内，返回冻结结束的实时时间。"""
        for a, b in self.holds:
            if a < t < b:
                return b
        return None

    @property
    def duration_eff(self) -> float:
        return self.teff(self.duration)

    # -- 日志缓冲 ------------------------------------------------------
    def _merged_logs(self) -> list[tuple]:
        if self._merged is None:
            m = list(self.logs) + list(self.extra)
            m.sort(key=lambda c: c[0])
            self._merged = m
            self._times = [c[0] for c in m]
        return self._merged

    def add_log(self, t_eff: float, text: str, style: int = R.S_BASE) -> None:
        self.extra.append((t_eff, text, style))
        self._merged = None

    def visible_logs(self, te: float, n: int) -> list[tuple]:
        merged = self._merged_logs()
        times = self._times or []
        hi = bisect_right(times, te)
        lo = 0
        cl = [c for c in self.clears if c <= te]
        if cl:
            lo = bisect_right(times, cl[-1])
        rows = merged[lo:hi]
        if n <= 0:
            return []
        return rows[:n] if self.log_align == "top" else rows[-n:]

    # -- 状态 ----------------------------------------------------------
    def count_at(self, te: float) -> int:
        n = 0
        for t, v in self.count:
            if te >= t:
                n = v
        return n

    def status_at(self, te: float) -> str:
        s = ""
        for t, v in self.status:
            if te >= t:
                s = v
        return s

    def ts_at(self, te: float) -> datetime:
        jump = 0.0
        for t, v in self.ts_jumps:
            if te >= t:
                jump += v
        return TS_BASE + timedelta(seconds=self.ts_origin + te + jump)

    def bar_at(self, te: float) -> BarPhase | None:
        cur = None
        for b in self.bars:
            if b.t0 <= te:
                cur = b
        return cur

    def prompt_at(self, te: float) -> tuple[int, Prompt] | None:
        for i, p in enumerate(self.prompts):
            if p.t0 <= te < p.t1 + 0.9:
                return i, p
        return None

    # -- 渲染 ----------------------------------------------------------
    def layout(self, h: int) -> dict:
        """复古工业/系统固件监控台多分区布局：
        顶部 5 行（Row 0 固件反白状态带 + Row 1..3 三联仪表盘 + Row 4 双线分界），
        中部带左右双线护栏的日志流与弹窗层，底部修正操作台与固件状态栏。"""
        if h >= 26:
            return dict(res=0, head=3, rule=4, log_top=5, log_bot=max(6, h - 5))
        return dict(res=-1, head=0, rule=1, log_top=2, log_bot=max(3, h - 5))

    def render(self, g: Grid, t: float, hud: str = "", skip_scare: bool = False) -> None:
        te = self.teff(t)
        g.clear()
        h = g.h
        w = g.w
        if self.bare:
            top, bot = 0, h
            self._render_logs(g, te, top + 1, bot - 1)
            if self.cursor:
                self._render_cursor(g, te, bot)
            panel = None
        else:
            lay = self.layout(h)
            if lay["res"] >= 0:
                self._render_dashboard(g, te, w, lay)
            else:
                self._render_header(g, te, w, lay["head"])
                g.hline(lay["rule"], "═", R.S_BORDER)
            top, bot = lay["log_top"], lay["log_bot"]
            self._render_frame_rails(g, te, w, h, top, bot)
            self._render_logs(g, te, top, bot)
            self._render_bar(g, te, w, h)
            self._render_modals(g, te, w, top, bot)
            self._render_status(g, te, w, h, hud)
            # 信息层（顶部 5 行监控仪表台）也要吃故障 —— 它不能免疫
            panel = (0, lay["rule"] + 1)
        G.apply(g, self.glitches, te, (top, bot), panel)
        if self.scare is not None and not skip_scare:
            self.scare.render(g, te)

    # -- 资源面板与 31.2GB 物理 / 77.4GB 提交真实死机遥测 ----------------
    PHYS_TOTAL_GB = 31.2
    COMMIT_MAX_GB = 77.4

    def panel_sev(self, te: float) -> float:
        """信息层故障的强度 0..1。资源读数按它抖动。"""
        s = 0.0
        for gl in self.glitches:
            if gl.name in G.PANEL_EFFECTS and gl.active(te):
                s = max(s, float(gl.p.get("amp", 1.0)))
        return min(1.0, s)

    def mem_telemetry(self, te: float) -> tuple[float, float, float, int, int]:
        """内存与磁盘换页演化曲线（物理可用 31.2 GB）：
        - boot (0..7s): 日常空闲基线 ~10.2 / 31.2 GB (32%)
        - noise (7..19s): 后台进程持续分配导致物理内存逼近 30 GB，触发页面文件换出
        - first_fix..identity (19..65s): 物理内存顶死 30.9 / 31.2 GB (99%)，已提交突破 31.2 GB 攀升过 60.4 GB
        - abandon..cascade (65..95s): 页面文件写入队列 100%，已提交达 77.4 GB 上限
        返回 (phys_gb, commit_gb, rate_mbs, disk_io_pct, suppress)。"""
        q = math.floor(te * RES_HZ) / RES_HZ
        gt = self.ts_origin + q
        s = self.res_seed
        if gt < 7.0:
            phys = 10.2 + gt * 0.09 + 0.06 * math.sin(q * 0.8 + s)
            commit = 11.6 + gt * 0.16
            rate = 12.4 + 2.4 * math.sin(q * 1.1)
            disk_io = 4 + int(3 * abs(math.sin(q * 0.7 + s)))
        elif gt < 19.0:
            el = gt - 7.0
            frac = el / 12.0
            phys = min(30.4, 10.8 + frac * 19.4 + 0.12 * math.sin(q * 1.3 + s))
            commit = 12.7 + el * 1.84 + 0.25 * math.sin(q * 0.9)
            rate = 150.4 + 6.2 * math.sin(q * 1.37 + s)
            disk_io = min(92, int(22 + frac * 68))
        elif gt < 65.0:
            el = gt - 19.0
            phys = min(30.9, 30.4 + el * 0.25)
            commit = min(74.2, 34.8 + el * 0.855 + 0.30 * math.sin(q * 0.7))
            rate = 152.1 + 5.8 * math.sin(q * 1.37 + s)
            disk_io = min(99, 92 + int(6 * abs(math.sin(q * 1.1 + s))))
        else:
            el = gt - 65.0
            phys = 30.9
            commit = min(self.COMMIT_MAX_GB, 74.1 + el * 0.56)
            rate = (154.2 + 4.4 * math.sin(q * 2.1 + s)) if commit < 77.35 else 0.0
            disk_io = 100
        suppress = 1 if (gt >= 65.0 or self.name in ("abandon", "cascade")) else 0
        return phys, commit, rate, disk_io, suppress

    def commit_telemetry(self, te: float) -> tuple[float, float, int]:
        """兼容接口：返回 (当前提交内存 GB, 增长速率 MB/s, INPUT_SUPPRESS 状态 0/1)。"""
        _phys, commit, rate, _disk_io, suppress = self.mem_telemetry(te)
        return commit, rate, suppress

    def res_values(self, te: float) -> tuple[float, float, float]:
        """CPU / GPU / RAM 三个占用率。按 4Hz 量化。"""
        q = math.floor(te * RES_HZ) / RES_HZ
        s = self.res_seed
        phys, _commit, _rate, _dio, _sup = self.mem_telemetry(te)
        cpu = 48.0 + 22.0 * (0.55 * math.sin(q * 0.37 + s) +
                             0.30 * math.sin(q * 1.13 + s * 1.7) +
                             0.15 * math.sin(q * 2.71 + s * 0.3))
        gpu = 93.5 + 5.0 * (0.60 * math.sin(q * 0.29 + s * 2.1) +
                            0.40 * math.sin(q * 0.83 + s * 0.7))
        ram = min(99.0, (phys / self.PHYS_TOTAL_GB) * 100.0)
        k = self.panel_sev(te)
        if k > 0.01:
            r = random.Random(int(self.res_seed) * 7919 + int(q * 1000) + 13)
            cpu += r.uniform(-60, 60) * k
            gpu += r.uniform(-95, 5) * k
            ram += (100.0 - ram) * k
        return (max(0.0, min(100.0, cpu)),
                max(0.0, min(100.0, gpu)),
                max(0.0, min(100.0, ram)))

    def res_display(self, te: float, gw: int) -> tuple:
        cpu, gpu, ram = self.res_values(te)
        phys, gb, rate, dio, sup = self.mem_telemetry(te)
        inner = max(8, min(16, (gw - 24) // 3 - 10))
        return (int(round(cpu / 100 * inner)), int(round(gpu / 100 * inner)),
                int(round(ram / 100 * inner)), int(cpu), int(gpu), int(ram),
                int(round(phys * 10)), int(round(gb * 10)), int(round(rate)), dio, sup)

    def _next_res_change(self, te: float, gw: int, limit: int = 48) -> float | None:
        """下一个资源或内存遥测会变化的时刻（4Hz 网格）。"""
        cur = self.res_display(te, gw)
        step = 1.0 / RES_HZ
        t = (math.floor(te * RES_HZ) + 1) * step
        for _ in range(limit):
            if self.res_display(t, gw) != cur:
                return t
            t += step
        return None

    def _render_dashboard(self, g: Grid, te: float, w: int, lay: dict) -> None:
        """渲染复古工业/系统固件三联监控台（Row 0..4，纯英文硬件/内核遥测，不常驻特定进程名）。"""
        cpu, gpu, ram = self.res_values(te)
        phys, gb, rate, dio, sup = self.mem_telemetry(te)
        k = self.panel_sev(te)
        q = math.floor(te * RES_HZ) / RES_HZ
        gt = self.ts_origin + q
        prng = random.Random(int(self.res_seed) * 31337 + int(q * 1000) + 7)
        over_phys = gb > self.PHYS_TOTAL_GB

        # Row 0: 纯英文固件反白状态横幅
        bar_st = R.S_ALERT_BAR if (gb >= 60.0 or k > 0.5 or sup) else (
            R.S_WARN_BAR if over_phys else R.S_HEADER_BAR
        )
        g.fill(0, 0, w, " ", bar_st)
        sid_txt = "NT AUTHORITY\\SYSTEM"
        if gb >= 70.0 or self.name in ("abandon", "cascade"):
            sid_txt = "UNAVAILABLE[0x8001012D]"
        elif gb >= 55.0 or self.name == "identity":
            sid_txt = "AUTH_ERR[NO_MEM]"
        ts_str = self.ts_at(te).strftime("%Y-%m-%d %H:%M:%S")
        right_banner = " │ %s │ %s " % (ts_str, self.title or "DIAGNOSTIC")
        rw_banner = R.text_width(right_banner)
        left_banner = " ▐ NT-SCM // PID[14020] │ SID:%s │ SUPPRESS:%d" % (sid_txt, sup)
        g.put(0, 0, truncate(left_banner, max(12, w - rw_banner - 1)), bar_st)
        g.put(max(2, w - rw_banner), 0, right_banner, bar_st)

        # 分区列坐标：左区 (Core & 31.2GB RAM) | 中区 (COMMIT / 31.2GB Swap) | 右区 (Display & Kernel)
        c1 = max(31, min(37, int(w * 0.30)))
        c2 = max(c1 + 42, min(w - 30, int(w * 0.72)))
        b_st = R.S_BORDER_HOT if (gb >= 60.0 or k > 0.4) else R.S_BORDER

        for yy in (1, 2, 3):
            g.put(0, yy, "║", b_st)
            g.put(c1, yy, "║", b_st)
            g.put(c2, yy, "║", b_st)
            g.put(w - 1, yy, "║", b_st)

        # 左区：CPU / GPU / 31.2GB 物理内存演进
        m_inner = max(8, c1 - 14)
        W.draw_meter(g, 1, 2, "CPU", cpu / 100.0, m_inner, "%3d%%" % int(round(cpu)))
        W.draw_meter(g, 2, 2, "GPU", gpu / 100.0, m_inner, "%3d%%" % int(round(gpu)))
        ram_inner = max(5, c1 - 24)
        ram_pct = 99 if phys >= 30.85 else int(round(ram))
        rx = W.draw_meter(g, 3, 2, "RAM", ram_pct / 100.0, ram_inner, "%3d%%" % ram_pct)
        ram_gb_str = " %4.1f/31.2G" % phys
        ram_gb_st = R.S_RED if phys >= 30.85 else (R.S_AMBER if phys >= 28.0 else R.S_DIM)
        g.put(rx, 3, truncate(ram_gb_str, max(0, c1 - rx)), ram_gb_st)

        # 中区：已提交内存 vs 31.2GB 物理红线（超 31.2GB 时分子单独红底反白高亮）
        mid_w = c2 - c1 - 3
        mx = c1 + 2
        if k > 0.65 and prng.random() < 0.5:
            mx = g.put(mx, 1, "COMMIT:", R.S_RED)
            mx = g.put(mx, 1, " 999.9 ", R.S_COMMIT_OVER)
            g.put(mx, 1, truncate("/ 31.2 GB [SWAP_OVERFLOW +NaN]", max(0, c2 - 1 - mx)), R.S_RED)
        elif over_phys:
            mx = g.put(mx, 1, "COMMIT:", R.S_DIM)
            mx = g.put(mx, 1, " %4.1f " % gb, R.S_COMMIT_OVER)
            if gb >= 77.35:
                tail = "/ 31.2 GB [PAGEFILE_LOCKED // DISK_IO 100%]" if mid_w >= 54 else "/ 31.2G [PAGEFILE_LOCKED // IO 100%]"
            else:
                tail = ("/ 31.2 GB [SWAP THRASHING +%.1f MB/s]" % rate) if mid_w >= 54 else ("/ 31.2G [SWAP THRASH +%.1fM/s]" % rate)
            g.put(mx, 1, truncate(tail, max(0, c2 - 1 - mx)), R.S_RED)
        else:
            commit_line = "COMMIT: %4.1f / 31.2 GB (+%.1f MB/s)" % (gb, rate)
            c_st = R.S_AMBER if gb >= 25.0 else R.S_CYAN
            g.put(mx, 1, truncate(commit_line, mid_w), c_st)

        g.put(c1 + 2, 2, "VM_MAP: ", R.S_DIM)
        bar_w = max(10, mid_w - 15)
        bx = W.draw_commit_bar(g, 2, c1 + 10, bar_w, gb, self.COMMIT_MAX_GB,
                               corrupt_k=k, rng=prng, phys_gb=self.PHYS_TOTAL_GB)
        pct_v = int(round(gb / self.PHYS_TOTAL_GB * 100))
        g.put(bx + 1, 2, "%3d%%" % pct_v, R.S_COMMIT_OVER if pct_v >= 190 else (R.S_RED if pct_v > 100 else R.S_AMBER))

        # 中区 Row 3：纯内核页面文件与磁盘换页队列（不常驻特定进程名）
        if gt < 7.0:
            pf_txt = "PGFILE: AUTO_MANAGED [OK]    │ DISK_IO: %02d%%" % dio
            pf_st = R.S_DIM
        elif gt < 19.0:
            pf_txt = "PGFILE: SWAP_OUT [ACTIVE]    │ DISK_IO: %02d%%" % dio
            pf_st = R.S_AMBER if phys >= 28.0 else R.S_CYAN
        elif gt < 65.0:
            pf_txt = "PGFILE: LOW_COMMIT [7000]    │ DISK_IO: %02d%%" % dio
            pf_st = R.S_RED if gb >= 55.0 else R.S_AMBER
        else:
            pf_txt = "PGFILE: EXHAUSTED [C000012D] │ DISK_IO:100%%"
            pf_st = R.S_RED
        g.put(c1 + 2, 3, truncate(pf_txt, mid_w), pf_st)

        # 右区：显示驱动 / 内存页表 / 会话与电源路径状态（纯内核遥测，无光标/观测者字样）
        rw = w - c2 - 3
        if gt >= 75.0 or self.name == "cascade":
            mon_txt = "DISP : DWM_DEADLOCK [0x193]"
            mon_st = R.S_RED
        elif gt >= 65.0 or self.name == "abandon":
            mon_txt = "DISP : MODE_ENUM [0x141 TDR]"
            mon_st = R.S_RED
        elif gt >= 49.0 or self.name == "identity":
            mon_txt = "DISP : S0ix_RESUME [182ms]"
            mon_st = R.S_AMBER
        elif gt >= 35.0 or self.name == "timeout":
            mon_txt = "DISP : NO_INFO [Win32k#263]"
            mon_st = R.S_AMBER
        else:
            mon_txt = "DISP : 3200x2000@60 [OK]"
            mon_st = R.S_DIM
        g.put(c2 + 2, 1, truncate(mon_txt, rw), mon_st)

        # 内存页十六进制矩阵
        pg_cells = 10
        filled_pg = int(round((gb / self.COMMIT_MAX_GB) * pg_cells))
        pg_bar = ""
        for pi in range(pg_cells):
            if pi < filled_pg:
                pg_bar += prng.choice("╬▓?") if (k > 0.4 and prng.random() < 0.35) else "█"
            else:
                pg_bar += "·"
        addr_hi = 0xFFFFF800 + int(q * 16) % 0xFF
        g.put(c2 + 2, 2, truncate("PG_TBL: 0x%08X [%s]" % (addr_hi, pg_bar), rw),
              R.S_RED if filled_pg >= 8 else R.S_TEAL)

        if gt >= 75.0 or self.name == "cascade":
            obs_txt = "PWR  : SHUTDOWN_HANG [0x1CC]"
            obs_st = R.S_RED
        elif sup:
            obs_txt = "INPUT: BLOCKED [SUPPRESS=1]"
            obs_st = R.S_RED
        elif gt >= 49.0 or self.name == "identity":
            obs_txt = "WAKE : SET_EXEC_STATE [507]"
            obs_st = R.S_AMBER
        else:
            obs_txt = "SESS : 0 [SERVICE_HOST]"
            obs_st = R.S_DIM
        g.put(c2 + 2, 3, truncate(obs_txt, rw), obs_st)

        # Row 4: 双线工业分界线
        rule_row = "╠" + "═" * (c1 - 1) + "╩" + "═" * (c2 - c1 - 1) + "╩" + "═" * (w - c2 - 2) + "╣"
        g.put(0, lay["rule"], rule_row, b_st)

    def _render_frame_rails(self, g: Grid, te: float, w: int, h: int, top: int, bot: int) -> None:
        """渲染中下部工业监控台双线外框与右侧内存压力滚动槽。"""
        gb, _rate, sup = self.commit_telemetry(te)
        b_st = R.S_BORDER_HOT if (gb >= 60.0 or sup) else R.S_BORDER
        span = max(1, bot - top)
        thumb_y = top + min(span - 1, int((gb / self.COMMIT_MAX_GB) * (span - 1)))
        for yy in range(top, h - 2):
            g.put(0, yy, "║", b_st)
            g.put(w - 1, yy, "║", b_st)
            if top <= yy < bot and w >= 80:
                g.put(w - 2, yy, "█" if yy == thumb_y else "░", R.S_RED if yy == thumb_y and gb >= 55 else R.S_FAINT)
        g.put(0, h - 2, "╠" + "═" * (w - 2) + "╣", b_st)

    def _render_modals(self, g: Grid, te: float, w: int, top: int, bot: int) -> None:
        """在日志区上方渲染场景编排的复古系统故障弹窗。"""
        if not self.modals:
            return
        jrng = random.Random((int(te * 8) * 1664525 ^ SEED) & 0xFFFFFFFF)
        for idx, m in enumerate(self.modals):
            t0, t1, title, lines, code = m[0], m[1], m[2], m[3], m[4]
            buttons = m[5] if len(m) > 5 else "[ Retry (Y) ]   [ Ignore (N) ]"
            if t0 <= te < t1:
                mw = min(w - 10, max(46, max(R.text_width(x) for x in lines) + 8))
                mx = max(4, (w - mw) // 2 + (idx % 3 - 1) * 5)
                my = max(top + 1, min(bot - len(lines) - 5, top + 2 + idx * 2))
                k = min(1.0, (te - t0) / max(0.1, t1 - t0))
                W.draw_modal(g, mx, my, mw, title, lines, code=code, buttons=buttons,
                             corrupt_k=0.35 * k if self.name in ("identity", "abandon", "cascade") else 0.0,
                             rng=jrng)

    def _render_header(self, g: Grid, te: float, w: int, y: int) -> None:
        """信息栏只留真实日志里会有的东西。

        原来有 `REC ●`、`UPTIME`、`×10` —— 那些是自己的装饰（REC 是摄像机语汇，
        ×N 是去重统计的产物），放在一台机器的诊断日志上会出戏。
        现在这里是时间戳 + 段标题，上面一行交给资源面板。
        """
        g.put(2, y, self.ts_at(te).strftime("%Y-%m-%d %H:%M:%S"), R.S_DIM)
        if self.title:
            g.put(max(24, w - R.text_width(self.title) - 2), y, self.title, R.S_BRIGHT)

    def _render_logs(self, g: Grid, te: float, top: int, bot: int) -> None:
        n = bot - top
        cues = self.visible_logs(te, n)
        # 一条事件可能展开成多行（主行 + 缩进的原因 + 缩进的提示）
        rows: list[tuple[str, int]] = []
        for _t, text, st in cues:
            parts = text.split("\n")
            rows.append((parts[0], st))
            for p in parts[1:]:
                rows.append((p if p.startswith(" ") else " " * REC.INDENT + p, R.S_DIM))
        rows = rows[-n:] if n > 0 else []
        base_y = top if self.log_align == "top" else bot - len(rows)
        max_w = g.w - 4 if self.bare else g.w - 5
        for i, (text, st) in enumerate(rows):
            g.put(2, base_y + i, truncate(text, max_w), st)

    def _render_bar(self, g: Grid, te: float, w: int, h: int) -> None:
        label_y = h - 4
        bar_y = h - 3
        bar = self.bar_at(te)
        # 故障抖动按 12Hz 量化，避免每个格子都换一遍导致糊成一团
        jrng = random.Random((int(te * 12) * 2654435761 ^ SEED) & 0xFFFFFFFF)
        pr = self.prompt_at(te)
        bw = w - 6
        if pr is not None:
            idx, p = pr
            x = g.put(2, label_y, "» ", R.S_YELLOW)
            x = g.put(x, label_y, p.text + "  ", R.S_YELLOW)
            ans = p.shown_answer(te)
            if ans:
                g.put(x, label_y, ans, R.S_BRIGHT)
            if bar is not None:
                lv = bar.level_at(te)
                W.draw_bar(g, bar_y, 2, bw, bar.frac_at(te), lv, rng=jrng,
                           ghost=bar.frac_at(max(bar.t0, te - 0.45)))
            return
        if bar is not None and te < bar.t1 + 1.4:
            if te < bar.t1:
                lv = bar.level_at(te)
                label = bar.label
                if lv >= 3 and bar.ms is not None and jrng.random() < 0.25:
                    label = label.replace(str(bar.ms), W.ms_text(bar.ms, 3, jrng))
                g.put(2, label_y, truncate(label, bw), R.S_AMBER if lv < 3 else R.S_RED)
                W.draw_bar(g, bar_y, 2, bw, bar.frac_at(te), lv, rng=jrng,
                           ghost=bar.frac_at(max(bar.t0, te - 0.45)))
            else:
                g.put(2, label_y, truncate(bar.tail, bw), R.S_AMBER)

    def _render_status(self, g: Grid, te: float, w: int, h: int, hud: str = "") -> None:
        st = self.status_at(te)
        if not st:
            st = "未检测到任何用户。"
        gb, _rate, sup = self.commit_telemetry(te)
        b_st = R.S_BORDER_HOT if (gb >= 70.0 or sup) else R.S_BORDER
        g.put(0, h - 1, "╚═[ ", b_st)
        st_color = R.S_RED if sup else (R.S_AMBER if gb >= 48.0 else R.S_DIM)
        end_x = g.put(4, h - 1, truncate(st, w - 42), st_color)
        g.put(end_x, h - 1, " ]" + "═" * max(1, w - end_x - 3), b_st)
        g.put(w - 1, h - 1, "╝", b_st)
        right_tag = ("[ " + hud + " ]") if hud else (
            "[ F1:DIAG  F3:INPUT_LOCKED  ESC:HALT ]" if sup else "[ F1:DIAG  F3:INTERVENE  ESC:HALT ]"
        )
        rx = max(end_x + 3, w - R.text_width(right_tag) - 2)
        if rx + R.text_width(right_tag) < w:
            g.put(rx, h - 1, right_tag, R.S_AMBER if hud else (R.S_RED if sup else R.S_DIM))

    def _render_cursor(self, g: Grid, te: float, bot: int) -> None:
        if W.blink(te, 1.0):
            rows = self.visible_logs(te, bot)
            y = min(bot - 1, 1 + len(rows))
            g.put(2, y, "█", R.S_DIM)

    # -- 逻辑帧：下一个画面会变的时间点（场景实时坐标） -----------------
    def next_change(self, t: float, gw: int) -> float:
        fz = self.frozen_at(t)
        if fz is not None:
            return fz
        te = self.teff(t)
        da = self.duration_eff
        cands: list[float] = [da]

        merged = self._merged_logs()
        times = self._times or []
        i = bisect_right(times, te)
        if i < len(times):
            cands.append(times[i])
        for c in self.clears:
            if c > te:
                cands.append(c)
        for c in self.status:
            if c[0] > te:
                cands.append(c[0])
        for c in self.count:
            if c[0] > te:
                cands.append(c[0])
        for c in self.ts_jumps:
            if c[0] > te:
                cands.append(c[0])
        for b in self.bars:
            if b.t0 > te:
                cands.append(b.t0)
            elif te < b.t1:
                cands.append(b.next_change(te, gw))
                cands.append(b.t1)
            for tt, _lv in b.levels:
                if tt > te:
                    cands.append(tt)
            if b.t1 <= te < b.t1 + 1.4:
                cands.append(b.t1 + 1.4)
        for p in self.prompts:
            if te < p.t0:
                cands.append(p.t0)
            elif te < p.t1:
                cands.append(min(p.t1, te + 0.05))
        for m in self.modals:
            if m[0] > te:
                cands.append(m[0])
            elif te < m[1]:
                cands.append(m[1])
        for gl in self.glitches:
            if gl.t > te:
                cands.append(gl.t)
            elif te < gl.t + gl.dur:
                cands.append(gl.t + gl.dur)
                if gl.name in ("hsync_wave", "border_melt", "popup_cascade", "meter_overflow", "hex_flood"):
                    cands.append(min(gl.t + gl.dur, (math.floor(te * 8.0) + 1) / 8.0))
        if self.scare is not None:
            cands.append(self.scare.next_change(te))
        if not self.bare:
            nxt = self._next_res_change(te, gw)
            if nxt is not None:
                cands.append(nxt)
        # 帧头闪烁 / 秒级 uptime
        cands.append((te // BLINK + 1) * BLINK)
        cands.append(float(int(te) + 1))
        if self.cursor:
            cands.append(float(int(te) + 1))
        eps = 1e-4
        nxt = min(c for c in cands if c > te + eps)
        return self.real_of(nxt)


# --------------------------------------------------------------------------
# 场景定义（纯机械/官僚系统报错风格，仅在终段保留极克制 Meta）
# --------------------------------------------------------------------------


def _s0_boot(ctx=None) -> Scene:
    logs = []
    for i, line in enumerate(REC.BOOT_LINES):
        logs.append(L(0.35 + i * 0.45, line, R.S_BRIGHT if i == 0 else R.S_BASE))
    logs.append(L(3.10, "[SCM] 诊断会话已初始化 (PID: 14020 / 可用物理内存: 31.2 GB / 已使用: 10.2 GB)。", R.S_CYAN))
    logs.append(L(3.55, "[263] " + REC.record_text(REC.find("Win32k", 263), hint=False), R.S_AMBER))
    for i in range(4):
        logs.append(L(4.0 + i * 0.50, REC.normal_line(i * 3 + 1), R.S_DIM))
    return Scene(
        "boot", "SCM · SESSION START", 7.0, logs=logs, ctx=ctx,
        status=[
            (0.0, "正在初始化服务控制管理器会话 (PID: 14020)。"),
            (3.5, "Win32k [263]: 指针设备没有有关其连接的监视器的信息。"),
            (5.6, "当前会话没有可用的用户上下文。"),
        ],
        glitches=[
            G.Glitch(5.35, "char_noise", 0.14, seed=SEED, peak=26),
            G.Glitch(6.15, "scanlines", 0.70, seed=SEED, step=3),
        ],
    )


def _s1_noise(ctx=None) -> Scene:
    logs = []
    i = 0
    t = 0.2
    while t < 3.40:
        logs.append(L(t, REC.normal_line(i), R.S_DIM))
        t += 0.24
        i += 1
    logs.append(L(3.60, "[PERF] 进程 godot.exe (PID: 8842) 帧提交率 4820 fps，工作集增长速率 +150.4 MB/s。", R.S_AMBER))
    logs.append(L(4.30, "[2004] " + REC.record_text(REC.find("Resource-Exhaustion-Detector", 2004), hint=False), R.S_AMBER))
    nls_fail = "[7000] " + REC.record_text(REC.find("Network List Service", 7000), hint=False)
    for k in range(10):
        logs.append(L(5.0 + k * 0.38, nls_fail, R.S_RED))
    count = [(5.0 + k * 0.38, k + 1) for k in range(10)]
    logs.append(L(8.95, "[7000] 由于下列错误，Windows 推送通知系统服务 服务启动失败:\n       页面文件太小，无法完成操作。", R.S_RED))
    logs.append(L(9.35, "[MEM] 可用物理内存低于阈值 (29.8 / 31.2 GB)。正在将工作集换出至页面文件。", R.S_AMBER))
    t = 9.7
    while t < 11.85:
        logs.append(L(t, REC.normal_line(i), R.S_DIM))
        t += 0.24
        i += 1
    return Scene(
        "noise", "COMMIT · +150MB/S", 12.0, logs=logs, count=count, noise_step=0,
        ctx=ctx, extra_errors=2,
        status=[
            (0.0, "服务控制管理器正在运行。物理内存: 10.8 / 31.2 GB。"),
            (3.6, "检测到虚拟内存提交速率异常 (+150.4 MB/s)。"),
            (8.6, "Network List Service 启动失败。页面文件太小，无法完成操作。"),
            (10.5, "已提交内存超过物理内存上限 (31.2 GB)。"),
        ],
        glitches=[
            G.Glitch(8.80, "char_noise", 0.22, seed=SEED, peak=55),
            G.Glitch(9.50, "meter_overflow", 0.35, seed=SEED, rows=1),
            G.Glitch(11.05, "hsync_wave", 0.25, seed=SEED, amp=4),
        ],
    )


def _s2_first_fix(ctx=None) -> Scene:
    r1 = REC.find("Network List Service", 7031)
    nls1 = ("[7031] Network List Service 服务意外地终止，这种情况已经出现了 1 次。"
            "以下的修正操作将在 1000 毫秒内运行: 重新启动服务。")
    nls2 = ("[7031] Network List Service 服务意外地终止，这种情况已经出现了 2 次。"
            "以下的修正操作将在 10000 毫秒内运行: 重新启动服务。")
    logs = [
        L(0.40, "[7031] Network List Service 服务意外地终止，这种情况已经出现了 1 次。", R.S_RED),
        L(1.10, nls1, R.S_AMBER),
        L(2.30, "[MEM] godot.exe (PID: 8842) 工作集 20.4–24.8 GB。物理内存使用率 99% (30.9 / 31.2 GB)。", R.S_AMBER),
        L(5.45, "等待用户输入超时。执行默认操作: Y。", R.S_FAINT),
        L(5.80, "正在重新启动服务...", R.S_AMBER),
        L(6.40, "[7036] Network List Service 服务处于 正在运行 状态。", R.S_GREEN),
        L(6.90, "目标服务已恢复。耗时 3.1 秒。", R.S_GREEN),
        L(8.20, nls2, R.S_RED),
        L(10.80, "[1000] " + REC.record_text(REC.find("atieclxx.exe", 1000), hint=False), R.S_RED),
        L(13.40, "修正操作未完成 (进度 88%，错误代码 0xC000012D)。", R.S_RED),
        L(13.70, r1["text"], R.S_AMBER),
        L(15.65, "正在重新启动服务...", R.S_AMBER),
    ]
    bars = [
        BarPhase(1.50, 4.20, level=1, ms=1000, outcome="ok", label="以下的修正操作将在 1000 毫秒内运行: 重新启动服务。"),
        BarPhase(8.60, 13.20, level=1, ms=10000, outcome="fail", label="以下的修正操作将在 10000 毫秒内运行: 重新启动服务。"),
        BarPhase(13.90, 15.50, level=1, ms=1000, outcome="fail", label="以下的修正操作将在 1000 毫秒内运行: 重新启动服务。"),
    ]
    modals = [
        (13.35, 15.65, "SCM.EXE - CORRECTIVE ACTION FAILED", [
            "Network List Service 重新启动操作超时 (88%)。",
            "物理内存 30.9 / 31.2 GB (99%)，已提交 46.0 GB，页面文件分配失败。",
        ], "0xC000012D", "[ Retry (Y) ]"),
    ]
    return Scene(
        "first_fix", "CORRECTIVE ACTION", 16.0, logs=logs, bars=bars, modals=modals, ctx=ctx, extra_errors=2,
        prompts=[Prompt(4.35, 5.40)],
        count=[(0.40, 1), (8.20, 2)],
        status=[
            (0.0, "正在执行修正操作。"),
            (6.90, "目标服务已恢复。页面文件写入队列持续增长。"),
            (13.40, "修正操作未完成 (88%)。已提交 46.0 / 31.2 GB。"),
            (15.50, "正在重新启动服务。"),
        ],
        glitches=[
            G.Glitch(10.75, "hsync_wave", 0.25, seed=SEED, amp=5),
            G.Glitch(13.30, "char_noise", 0.28, seed=SEED, peak=70),
            G.Glitch(14.80, "border_melt", 0.45, seed=SEED, ratio=0.35),
            G.Glitch(15.58, "row_invert", 0.12, seed=SEED, rows=2),
            G.Glitch(15.80, "flash", 0.05, seed=SEED),
        ],
    )


def _s3_timeout(ctx=None) -> Scene:
    wsl = "等待来自 WSLService 服务的事务处理响应超时(30000 毫秒)。"
    logs = [
        L(0.30, "[7011] " + wsl, R.S_RED),
        L(1.00, "[7011] " + wsl, R.S_RED),
        L(1.70, "[7011] " + wsl, R.S_RED),
        L(3.10, "[10010] " + REC.record_text(REC.find("DistributedCOM", 10010), hint=False), R.S_AMBER),
        L(8.00, "[7009] 等待 Windows Push Notifications User Service_4d9f4c31 服务的连接超时(30000 毫秒)。", R.S_AMBER),
        L(9.40, "[36884] " + REC.record_text(REC.find("Schannel", 36884), hint=False), R.S_RED),
        L(10.50, "连接仍在等待。系统时钟偏移 +90 秒。", R.S_FAINT),
        L(11.60, "[507] " + REC.record_text(REC.find("Kernel-Power", 507), hint=False), R.S_AMBER),
        L(12.80, "事务处理响应超时(30000 毫秒)。DPC 计时器未响应。", R.S_RED),
    ]
    bars = [BarPhase(2.20, 12.50, level=2, ms=30000, outcome="never",
                     label="等待服务的事务处理响应。上限 30000 毫秒。")]
    modals = [
        (5.45, 8.20, "DPC_WATCHDOG // RESPONSE TIMEOUT", [
            "等待来自 WSLService 服务的事务处理响应超时(30000 毫秒)。",
            "已提交内存超过 55.0 / 31.2 GB。正在写入转储信息。",
        ], "0x00000133", "[ Awaiting Response... ]"),
    ]
    return Scene(
        "timeout", "RESPONSE TIMEOUT", 14.0, logs=logs, bars=bars, modals=modals, ctx=ctx, extra_errors=2,
        holds=[(5.60, 7.60)],
        ts_jumps=[(2.60, 30.0), (5.00, 30.0), (9.00, 30.0)],
        count=[(0.30, 1), (1.00, 2), (1.70, 3)],
        status=[
            (0.0, "等待服务响应 (上限 30000 毫秒)。"),
            (5.50, "服务控制管理器线程无响应。"),
            (7.65, "系统时钟偏移 +90 秒。TLS 连接请求失败。"),
            (11.60, "Kernel-Power [507]: 退出新型待机状态 (SetThreadExecutionState)。"),
        ],
        glitches=[
            G.Glitch(3.40, "scanlines", 8.6, seed=SEED, step=2),
            G.Glitch(5.20, "hsync_wave", 0.35, seed=SEED, amp=7),
            G.Glitch(7.65, "hex_flood", 0.55, seed=SEED, rows=4),
            G.Glitch(11.00, "escape_literal", 0.35, seed=SEED, n=3),
            G.Glitch(12.85, "dim_all", 0.45, seed=SEED, factor=0.3),
        ],
    )


def _s4_identity(ctx=None) -> Scene:
    np_rec = REC.find("netprofm", 7038)
    np_full = "[7038] " + REC.record_text(np_rec)              # 第一次带 MMC 提示行
    np_short = "[7038] " + REC.record_text(np_rec, hint=False)  # 后续只保留原因
    logs = [L(0.30, np_full, R.S_RED)]
    for k in range(1, 5):
        logs.append(L(0.30 + k * 0.42, np_short, R.S_RED))
    logs += [
        L(2.40, "[507] 系统正在退出新型待机状态。原因: SetThreadExecutionState。监视器通电时间: 182 毫秒。本地会话: 0。", R.S_AMBER),
        L(3.15, "[10001] " + REC.record_text(REC.find("DistributedCOM", 10001), hint=False), R.S_RED),
        L(4.15, "[7038] " + REC.record_text(REC.find("DiagTrack", 7038), hint=False), R.S_RED),
        L(5.05, "[7038] " + REC.record_text(REC.find("CDPSvc", 7038), hint=False), R.S_RED),
        L(5.90, "[7038] " + REC.record_text(REC.find("WerSvc", 7038), hint=False), R.S_RED),
        L(6.60, "[1] " + REC.record_text(REC.find("Universal Print", 1), hint=False), R.S_AMBER),
        L(9.20, "[AUTH] 无法验证 NT AUTHORITY\\SYSTEM 登录凭据。错误代码: 0x8001012d。", R.S_MAGENTA),
        L(15.40, "凭据无效。安全标识符: 不可用/不可用。", R.S_RED),
        L(15.70, "当前会话没有可用的用户上下文。", R.S_AMBER),
    ]
    bars = [BarPhase(8.30, 15.20, level=2, ms=None, outcome="never",
                     label="正在验证 NT AUTHORITY\\SYSTEM 服务账户凭据…", levels=[(11.00, 3)])]
    modals = [
        (11.20, 14.90, "LSASS / SCM - AUTHENTICATION FAILED", [
            "无法使用当前配置的密码以 NT AUTHORITY\\SYSTEM 身份登录: 内存资源不足。",
            "无法作为 不可用/不可用 启动服务器 (0x8001012d)。",
            "退出新型待机原因: SetThreadExecutionState (本地会话: 0)。",
        ], "0x8001012D", "[ Retry (Y) ]   [ Cancel (N) ]"),
    ]
    return Scene(
        "identity", "AUTHENTICATION", 16.0, logs=logs, bars=bars, modals=modals, ctx=ctx,
        prompts=[Prompt(7.00, 8.00, text="无法验证服务账户凭据。是否重试? (Y/n)")],
        count=[(0.30 + k * 0.42, k + 1) for k in range(8)],
        status=[
            (0.0, "正在验证服务账户凭据 (COMMIT: 60.4 / 31.2 GB)。"),
            (2.40, "Kernel-Power [507]: 退出新型待机状态 (本地会话: 0)。"),
            (11.50, "身份验证失败。SID: 不可用/不可用。"),
            (15.30, "没有可用的用户上下文。"),
        ],
        glitches=[
            G.Glitch(9.60, "homoglyph", 1.40, seed=SEED, ratio=0.22),
            G.Glitch(10.80, "border_melt", 0.80, seed=SEED, ratio=0.45),
            G.Glitch(11.00, "dim_all", 2.50, seed=SEED, factor=0.3),
            G.Glitch(11.40, "homoglyph", 2.20, seed=SEED, ratio=0.38),
            G.Glitch(13.50, "meter_overflow", 0.55, seed=SEED, rows=2),
            G.Glitch(14.55, "hsync_wave", 0.35, seed=SEED, amp=8),
            G.Glitch(15.55, "flash", 0.06, seed=SEED),
        ],
    )


def _s5_abandon(ctx=None) -> Scene:
    logs = [
        L(0.25, "[2004] 进程 zcode.exe 请求分配虚拟内存失败 (0xC000012D)。页面文件写入队列 100%。", R.S_RED),
        L(0.90, "[4107] " + REC.record_text(REC.find("Display", 4107), hint=False), R.S_AMBER),
        L(1.55, "[1000] " + REC.record_text(REC.find("atieclxx.exe", 1000), hint=False), R.S_RED),
        L(2.25, "[141] " + REC.record_text(REC.find("WER-LiveKernel", 141), hint=False), R.S_RED),
        L(3.05, "[460] " + REC.record_text(REC.find("WER-LiveKernel", 460), hint=False), R.S_RED),
        L(3.75, "[700] " + REC.record_text(REC.find("Win32k", 700), hint=False), R.S_RED),
        L(4.40, "[7034] 服务 FileIndex_Daemon 意外停止。这发生了 1 次。", R.S_RED),
        L(5.00, "[7034] 服务 AudioFX_API_Service 意外停止。这发生了 1 次。", R.S_RED),
        L(5.60, "[8193] " + REC.record_text(REC.find("VSS", 8193), hint=False), R.S_RED),
        L(6.40, "(没有可用的修正操作。shutdown.exe /r /t 0 /f 返回超时 0x000005B4。)", R.S_AMBER),
        L(9.55, "服务未恢复。内核显示与电源路径无响应 (0x141 / 0x193 / 0x1cc)。", R.S_RED),
    ]
    bars = [BarPhase(5.80, 9.50, level=3, ms=60000, outcome="never",
                     label="LKD_0x1cc EXRESOURCE_TIMEOUT // 等待系统关机路径响应…")]
    modals = [
        (3.80, 9.10, "DXGKRNL.SYS - DEADLOCK [0x193 / 0x1CC]", [
            "dxgkrnl!ProcessDeadlockThread: 显示合成器无响应 (LKD_0x193)。",
            "win32kbase EXRESOURCE_TIMEOUT (LKD_0x1cc): 电源管理器已阻止所有输入。",
            "pnputil /restart-device 与 shutdown.exe /r /t 0 /f 操作超时 (0x000005B4)。",
        ], "0x000001CC", "[ INPUT LOCKED ]   [ TIMEOUT ]"),
    ]
    return Scene(
        "abandon", "NO CORRECTIVE ACTION", 10.0, logs=logs, bars=bars, modals=modals, ctx=ctx, extra_errors=2,
        status=[
            (0.0, "页面文件写入队列已满 (0xC000012D)。显示模式重枚举失败。"),
            (2.25, "已生成实时内核转储: LKD_0x141 / LKD_0x193。"),
            (3.80, "没有可用的修正操作。关机操作超时 (0x000005B4)。"),
        ],
        glitches=[
            G.Glitch(2.80, "border_melt", 0.90, seed=SEED, ratio=0.55),
            G.Glitch(6.20, "blackout", 1.40, seed=SEED, a=0.0, b=0.50),
            G.Glitch(7.80, "popup_cascade", 0.95, seed=SEED, count=3, modal=1),
            G.Glitch(8.80, "hsync_wave", 0.45, seed=SEED, amp=9),
            G.Glitch(9.62, "dim_all", 0.38, seed=SEED, factor=0.3),
        ],
    )


def _s6_cascade(ctx=None) -> Scene:
    picks = [
        ("Windows Error Reporting Service", 7031),
        ("Resource-Exhaustion-Detector", 2004),
        ("Display", 4107),
        ("atieclxx.exe", 1000),
        ("WER-LiveKernel", 141),
        ("WER-LiveKernel", 460),
        ("Windows 推送通知系统服务", 7000),
        ("Windows Push Notifications User Service_4d9f4c31", 7031),
        ("inpoutx64", 7000),
        ("Connected User Experiences and Telemetry", 7000),
        ("连接设备平台用户服务_4d9f4c31", 7000),
        ("连接设备平台服务", 7000),
        ("DistributedCOM", 10001),
        ("Kernel-Power", 507),
        ("主机网络服务", 7031),
        ("Overlay Tunnel Service", 7031),
        ("Routing and Remote Access", 7024),
        ("KPICService_Web", 7000),
        ("ScRegSetValueExW", 7006),
        ("Kernel-Power", 41),
    ]
    logs = []
    t = 0.40
    for svc, ev in picks:
        rec = REC.find(svc, ev)
        st = R.S_RED if ev in (7000, 7001, 7006, 7024, 10001, 1000, 141, 460, 41) else R.S_AMBER
        logs.append(L(t, "[%d] %s" % (ev, REC.record_text(rec, hint=False)), st))
        t += 0.58
    bars = [
        BarPhase(10.60, 13.80, level=2, ms=3000, outcome="reset", label="COMMIT 77.4 / 31.2 GB // 正在重新启动服务…"),
        BarPhase(14.00, 17.40, level=3, ms=1000, outcome="never", label="-0 毫秒后重新启动服务 // LKD_0x193 / LKD_0x1cc。"),
        BarPhase(17.60, 19.70, level=3, ms=3000, outcome="reset", label="shutdown.exe /r /t 0 /f 操作超时 // 正在写入 C:\\Windows\\MEMORY.DMP…"),
    ]
    count = [(0.40, min(8, 1 + k // 3)) for k in range(len(picks))]
    gs = [
        G.Glitch(1.80, "hsync_wave", 0.35, seed=SEED, amp=6),
        G.Glitch(3.20, "meter_overflow", 0.55, seed=SEED, rows=2),
        G.Glitch(4.30, "char_noise", 0.25, seed=SEED, peak=85),
        G.Glitch(5.50, "border_melt", 0.90, seed=SEED, ratio=0.55),
        G.Glitch(6.80, "popup_cascade", 1.10, seed=SEED, count=3, modal=0),
        G.Glitch(8.10, "hex_flood", 0.75, seed=SEED, rows=6),
        G.Glitch(8.80, "scanlines", 1.60, seed=SEED, step=2),
        G.Glitch(9.90, "row_flip", 0.22, seed=SEED, rows=4),
        G.Glitch(11.10, "meter_overflow", 0.70, seed=SEED, rows=3),
        G.Glitch(12.20, "popup_cascade", 1.30, seed=SEED, count=4, modal=1),
        G.Glitch(13.30, "blackout", 0.45, seed=SEED, a=0.15, b=0.75),
        G.Glitch(14.40, "homoglyph", 1.40, seed=SEED, ratio=0.42),
        G.Glitch(15.40, "border_melt", 1.20, seed=SEED, ratio=0.80),
        G.Glitch(16.10, "char_noise", 0.55, seed=SEED, peak=160),
        G.Glitch(16.70, "hsync_wave", 0.65, seed=SEED, amp=12),
        G.Glitch(17.30, "flash", 0.06, seed=SEED),
        G.Glitch(17.80, "hex_flood", 0.95, seed=SEED, rows=8),
        G.Glitch(18.60, "popup_cascade", 0.85, seed=SEED, count=4, modal=2),
        G.Glitch(19.10, "blackout", 0.30, seed=SEED, a=0.30, b=0.95),
        G.Glitch(19.60, "dim_all", 0.30, seed=SEED, factor=0.2),
    ]
    return Scene(
        "cascade", "CASCADE FAILURE", 20.0, logs=logs, bars=bars, count=count,
        glitches=gs, ctx=ctx, extra_errors=4,
        status=[
            (0.0, "服务恢复队列已满。COMMIT: 77.4 / 31.2 GB。"),
            (6.00, "页面文件已耗尽 (0xC000012D)。"),
            (10.60, "正在批量执行修正操作。"),
            (14.00, "显示合成器无响应 (LKD_0x193)。"),
            (17.60, "关机操作超时 (0x000005B4)。"),
            (19.60, "没有可用的修正操作。"),
        ],
    )


def _s7_silence(ctx=None) -> Scene:
    return Scene(
        "silence", "", 9.5, bare=True, log_align="top", cursor=True, noise_step=0, ctx=ctx,
        logs=[
            L(1.80, "系统已就绪。", R.S_DIM),
            L(4.20, "未检测到任何本地用户。(Reason: SetThreadExecutionState)", R.S_BASE),
            L(6.90, "关机操作未完成。当前显示输出仍处于活动状态。", R.S_AMBER),
        ],
        glitches=[
            G.Glitch(0.20, "blackout", 1.20, seed=SEED, a=0.0, b=1.0),
            G.Glitch(4.80, "scanlines", 0.60, seed=SEED, step=4),
            G.Glitch(6.95, "row_invert", 0.12, seed=SEED, rows=1),
            G.Glitch(8.40, "dim_all", 1.10, seed=SEED, factor=0.2),
        ],
    )


def _s8_jumpscare(ctx=None, seed: int = SEED, text: str | None = None,
                  style: str = "outline") -> Scene:
    """静默之后的跳杀：全屏反白 -> 蒙版遮住的红线大字 -> 整体错位 -> 黑场。"""
    return Scene(
        "jumpscare", "", 4.2, bare=True, log_align="top", noise_step=0, ctx=ctx,
        scare=JumpScare(text, seed, style),
    )


# 信息层（htop 面板）的故障表：(段内秒, 效果, 时长, 参数)。
#
# 为什么单独一张表而不是塞进每个场景里：这块故障的**节奏**本身就是要设计的东西
# —— 前段偶尔一次，越到后面越密、力度越大。集中写一处，一眼能看出它在递增，
# 改起来也只需要动一个数字。`amp` 是资源读数的抖动强度（0 = 只坏字符，
# 1 = 读数彻底不可信）。
PANEL_GLITCHES = {
    "boot": [
        (5.40, "panel_corrupt", 0.70, dict(ratio=0.22, amp=0.35)),
    ],
    "noise": [
        (4.20, "panel_invert", 0.18, dict(rows=1, amp=0.30)),
        (10.60, "panel_noise", 0.45, dict(peak=14, amp=0.45)),
    ],
    "first_fix": [
        (3.30, "panel_garbage", 0.35, dict(amp=0.55)),
        (9.80, "panel_corrupt", 0.60, dict(ratio=0.32, amp=0.60)),
        (14.60, "panel_noise", 0.40, dict(peak=18, amp=0.70)),
    ],
    "timeout": [
        (2.10, "panel_dim", 0.90, dict(amp=0.35)),
        (7.40, "panel_garbage", 0.40, dict(amp=0.75)),
        (12.60, "panel_noise", 0.55, dict(peak=24, amp=0.85)),
    ],
    "identity": [
        (1.80, "panel_noise", 0.45, dict(peak=20, amp=0.70)),
        (6.40, "panel_corrupt", 0.75, dict(ratio=0.40, amp=0.85)),
        (11.20, "panel_garbage", 0.45, dict(amp=0.90)),
        (14.20, "panel_invert", 0.22, dict(rows=2, amp=0.60)),
    ],
    "abandon": [
        (2.40, "panel_garbage", 0.45, dict(amp=0.90)),
        (5.60, "panel_dim", 1.00, dict(amp=0.70)),
        (8.40, "panel_noise", 0.60, dict(peak=30, amp=1.00)),
    ],
    "cascade": [
        (1.20, "panel_noise", 0.40, dict(peak=20, amp=0.80)),
        (3.60, "panel_garbage", 0.35, dict(amp=0.95)),
        (5.20, "panel_corrupt", 0.70, dict(ratio=0.45, amp=0.90)),
        (7.40, "panel_invert", 0.20, dict(rows=2, amp=0.80)),
        (8.80, "panel_noise", 0.50, dict(peak=34, amp=1.00)),
        (10.40, "panel_garbage", 0.40, dict(amp=1.00)),
        (11.80, "panel_dim", 0.70, dict(amp=0.90)),
        (12.90, "panel_noise", 0.60, dict(peak=40, amp=1.00)),
        (14.30, "panel_corrupt", 0.80, dict(ratio=0.55, amp=1.00)),
        (15.60, "panel_garbage", 0.45, dict(amp=1.00)),
        (16.80, "panel_invert", 0.24, dict(rows=3, amp=1.00)),
        (18.00, "panel_noise", 0.80, dict(peak=48, amp=1.00)),
        (19.20, "panel_dim", 0.70, dict(amp=1.00)),
    ],
    "silence": [],
}


def _add_panel_glitches(scene: "Scene") -> "Scene":
    """把信息层故障按表挂到场景上。"""
    for t, name, dur, p in PANEL_GLITCHES.get(scene.name, ()):
        scene.glitches.append(G.Glitch(t, name, dur, seed=SEED, **p))
    scene.glitches.sort(key=lambda gl: gl.t)
    return scene


def build_scenes(ctx: "GenContext | None" = None, jumpscare: bool = True,
                 scare_text: str | None = None, seed: int = SEED,
                 scare_style: str = "outline") -> list[Scene]:
    scenes = [
        _s0_boot(ctx),
        _s1_noise(ctx),
        _s2_first_fix(ctx),
        _s3_timeout(ctx),
        _s4_identity(ctx),
        _s5_abandon(ctx),
        _s6_cascade(ctx),
        _s7_silence(ctx),
    ]
    for sc in scenes:
        _add_panel_glitches(sc)
    if jumpscare:
        scenes.append(_s8_jumpscare(ctx, seed, scare_text, scare_style))
    return scenes


def schedule(scenes: list[Scene]) -> list[tuple[float, float, Scene]]:
    """把场景首尾相接，返回 [(全局起点, 全局终点, scene)]，并补齐时间戳原点。"""
    out = []
    t = 0.0
    for s in scenes:
        s.ts_origin = t
        out.append((t, t + s.duration, s))
        t += s.duration
    return out


def locate_idx(sched, t: float) -> int:
    for i, (a, b, s) in enumerate(sched):
        if a <= t < b:
            return i
    return len(sched) - 1


def locate(sched, t: float):
    """全局时间 -> (scene, 场景内时间)。超出范围返回最后一个场景的末尾。"""
    for a, b, s in sched:
        if a <= t < b:
            return s, t - a
    s = sched[-1][2]
    return s, s.duration


def total_duration(scenes: list[Scene]) -> float:
    return sum(s.duration for s in scenes)
