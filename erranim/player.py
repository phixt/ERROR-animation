"""播放器：逻辑帧驱动 + 倍速 + 跳段 + 交互式重试 + 帧录制。

核心：画面是时间的纯函数，且播放只"跳到下一个画面会变的时间点"。
所以不动就一帧都不渲染；而无论 0.4x 还是 10x，采样到的画面集合完全相同，
录下来的帧序列与速度无关。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import corpus as CORPUS
from . import glitch as G
from . import render as R
from . import scenes as S
from . import term
from .render import Emitter, Grid

SPEED_MIN, SPEED_MAX = 0.1, 20.0
SPEED_REF = (0.4, 10.0)
MIN_QUANTUM = 1.0 / 240.0  # 防止 next_change 退化时的死循环


# --------------------------------------------------------------------------
# 录制
# --------------------------------------------------------------------------


class Recorder:
    """按"画面变化"落盘，每行一帧：{"t": 逻辑秒, "rows": [[[style, text], ...], ...]}"""

    def __init__(self, path: str, w: int, h: int, meta: dict | None = None):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        self.f = open(path, "w", encoding="utf-8", newline="\n")
        self.f.write(json.dumps({"meta": dict(w=w, h=h, **(meta or {}))}, ensure_ascii=False) + "\n")
        self.n = 0

    def add(self, t: float, grid: Grid) -> None:
        rows = [grid.row_runs(y) for y in range(grid.h)]
        self.f.write(json.dumps({"t": round(t, 4), "rows": rows}, ensure_ascii=False) + "\n")
        self.n += 1

    def close(self) -> None:
        try:
            self.f.flush()
            self.f.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 参数
# --------------------------------------------------------------------------


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m erranim.player",
        description="ERROR-animation —— 模拟恐怖风格的终端艺术（SCM 崩溃日志）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--speed", type=float, default=1.0,
                   help="播放倍速，参考区间 0.4–10.0，最多一位小数（默认 1.0）")
    p.add_argument("--scene", type=int, default=0, help="从第几段开始（0 起，默认 0）")
    p.add_argument("--width", type=int, default=0, help="强制列数（默认用终端宽度）")
    p.add_argument("--height", type=int, default=0, help="强制行数（默认用终端高度）")
    p.add_argument("--seed", type=int, default=S.SEED, help="故障效果随机种子")
    p.add_argument("--audio", action="store_true",
                   help="打开音频：一条常驻噪声床 + 日志行的系统音效，故障是对床做的操作")
    p.add_argument("--no-warnings", action="store_true",
                   help="关掉红/黄的系统经典警告音（关掉后日志改在噪声上留一道打断）")
    p.add_argument("--audio-gain", type=float, default=0.9, help="音频总音量")
    p.add_argument("--bed-level", type=float, default=1.0, help="噪声床的电平倍数（嫌底噪大就调小）")
    p.add_argument("--corpus", default="", help="语料库 JSON 路径（默认 data/corpus.json）")
    p.add_argument("--random", choices=("on", "off"), default="off",
                   help="随机机制开关：on 时背景噪声与额外错误事件从语料库结构化采样")
    p.add_argument("--no-jumpscare", action="store_true", help="去掉结尾的跳杀")
    p.add_argument("--scare-text", default="", help="指定跳杀的大字内容（默认按种子随机挑）")
    p.add_argument("--scare-style", default="echo", choices=("echo", "solid", "outline"),
                   help="跳杀画法：echo 主字+残影叠加（默认）/ solid 只有主字 / outline 全描边")
    p.add_argument("--snap", default="", help="不开动画，打印指定全局时间点的纯文本帧，逗号分隔")
    p.add_argument("--record", default="", help="把变化过的帧写进 JSONL（给 film.py 出片）")
    p.add_argument("--headless", action="store_true", help="不碰终端，只计算/录制")
    p.add_argument("--bench", action="store_true", help="统计逻辑帧数量与开销，然后退出")
    p.add_argument("--interactive", action="store_true", help="允许真的按 Y/n 回答重试提示")
    p.add_argument("--list", action="store_true", help="列出段落与时长，然后退出")
    return p.parse_args(argv)


def make_ctx(args) -> "S.GenContext":
    """按参数装配语料库与随机机制。"""
    corp = CORPUS.Corpus.load(args.corpus or None)
    return S.GenContext(corp, seed=args.seed, random_on=(args.random == "on"))


def build(args):
    return S.build_scenes(make_ctx(args), jumpscare=not args.no_jumpscare,
                          scare_text=(args.scare_text or None), seed=args.seed,
                          scare_style=args.scare_style)


def clamp_speed(v: float) -> float:
    v = round(float(v), 1)
    if v <= 0:
        print("倍速必须为正，已改用 1.0", file=sys.stderr)
        return 1.0
    if v < SPEED_MIN or v > SPEED_MAX:
        c = min(max(v, SPEED_MIN), SPEED_MAX)
        print("倍速 %.1f 超出可用范围 [%.1f, %.1f]，已收敛到 %.1f" % (v, SPEED_MIN, SPEED_MAX, c), file=sys.stderr)
        return c
    if not (SPEED_REF[0] <= v <= SPEED_REF[1]):
        print("提示：%.1f 不在参考区间 %.1f–%.1f 内，仅供参考。"
              % (v, SPEED_REF[0], SPEED_REF[1]), file=sys.stderr)
    return v


# --------------------------------------------------------------------------
# 渲染一帧
# --------------------------------------------------------------------------


def render_at(sched, t: float, grid: Grid, hud: str = "", skip_scare: bool = False) -> None:
    scene, lt = S.locate(sched, t)
    scene.render(grid, lt, hud, skip_scare=skip_scare)


# --------------------------------------------------------------------------
# 播放器
# --------------------------------------------------------------------------


class Player:
    def __init__(self, args, w: int, h: int):
        self.args = args
        self.w, self.h = w, h
        self.ctx = make_ctx(args)
        self.scenes = S.build_scenes(self.ctx, jumpscare=not args.no_jumpscare,
                                     scare_text=(args.scare_text or None), seed=args.seed,
                                     scare_style=args.scare_style)
        self.sched = S.schedule(self.scenes)
        self.total = S.total_duration(self.scenes)
        self.speed = clamp_speed(args.speed)
        self.t = self.sched[min(max(args.scene, 0), len(self.sched) - 1)][0]
        # 把跳杀的时间窗与短语写进录制元数据：视频后期要用它画矢量版
        scare_win = None
        scare_phrase = None
        for a, b, sc in self.sched:
            if sc.name == "jumpscare" and sc.scare is not None:
                scare_win = [round(a, 3), round(b, 3)]
                scare_phrase = list(sc.scare.phrase)
        self.grid = Grid(w, h)
        self.emitter = Emitter(w, h)
        self.last_snap = None
        self.hud = ""
        self.hud_until = 0.0
        self.paused = False
        self.frames = 0
        self.bytes = 0
        self.rec = Recorder(args.record, w, h,
                            {"seed": args.seed, "duration": round(self.total, 3),
                             "scare": scare_win, "scare_style": args.scare_style,
                             "scare_phrase": scare_phrase}
                            ) if args.record else None
        self.interactive = args.interactive
        self._answered: set[int] = set()

        # 音频（可选）：一条常驻噪声床 + 事件导演。导演的代码在 director.py ——
        # 出片那条路也用它，保证终端听到的和视频里的是同一个东西。
        self.audio = None
        self.director = None
        if getattr(args, "audio", False):
            try:
                from . import audio as A
                from .director import Director
                self.audio = A.Mixer(gain=getattr(args, "audio_gain", 0.9),
                                     bed_level=getattr(args, "bed_level", 1.0),
                                     seed=args.seed,
                                     warnings=not getattr(args, "no_warnings", False))
                self.director = Director(self.sched, self.audio)
            except Exception as e:
                print("音频不可用：%s" % e, file=sys.stderr)

    # -- 音频 ----------------------------------------------------------
    def _pump_audio(self) -> None:
        if self.director is not None:
            self.director.step(self.t)

    # -- HUD -----------------------------------------------------------
    def set_hud(self, s: str, hold: float = 2.5) -> None:
        self.hud = s
        self.hud_until = time.perf_counter() + hold

    def hud_now(self) -> str:
        if self.hud and time.perf_counter() < self.hud_until:
            return self.hud
        if abs(self.speed - 1.0) > 1e-9:
            return "SPD %.1fx" % self.speed
        return ""

    # -- 帧 ------------------------------------------------------------
    def draw(self, force: bool = False) -> None:
        # 录制时**不**把跳杀画进字符网格：出片那条路会按像素重新画矢量版，
        # 两版叠在一起就废了。终端实时播放时照旧走字符版。
        render_at(self.sched, self.t, self.grid, self.hud_now(),
                  skip_scare=self.rec is not None)
        changed = self.last_snap is None or not self.grid.same_as(self.last_snap)
        # 但跳杀那段网格是静止的（全黑），必须按跳杀自己的时间轴强制出帧，
        # 否则录出来的那 4 秒只有一帧，矢量动画就没地方落。
        force_rec = False
        if self.rec is not None:
            scene, lt = S.locate(self.sched, self.t)
            if scene.scare is not None and scene.teff(lt) <= scene.scare.CUT_END + 1e-6:
                force_rec = True
        if not changed and not force and not force_rec:
            return
        if self.rec and (changed or force_rec):
            self.rec.add(self.t, self.grid)
        self.frames += 1
        self.last_snap = self.grid.snapshot()
        # headless 下也算一遍差分，好让统计数字是真的（只是不写出去）
        s = self.emitter.diff(self.grid)
        if self.args.headless:
            return
        if s:
            term.write(s)
            term.flush()
            self.bytes += len(s.encode("utf-8", "replace"))

    def next_t(self) -> float:
        i = S.locate_idx(self.sched, self.t)
        a, _b, scene = self.sched[i]
        nt = a + scene.next_change(self.t - a, self.w)
        if nt <= self.t + 1e-6:
            nt = self.t + MIN_QUANTUM
        return min(nt, self.total)

    # -- 按键 ----------------------------------------------------------
    def handle_key(self, k: str) -> bool:
        """返回 False 表示要退出。"""
        if k in ("q", "Q", "\x1b"):
            return False
        if k in ("p", "P", " "):
            self.paused = not self.paused
            self.set_hud("PAUSE" if self.paused else "RESUME")
            return True
        if k in ("+", "="):
            self.speed = clamp_speed(round(min(SPEED_MAX, self.speed + 0.1), 1))
            self.set_hud("SPD %.1fx" % self.speed)
            return True
        if k in ("-", "_"):
            self.speed = clamp_speed(round(max(SPEED_MIN, self.speed - 0.1), 1))
            self.set_hud("SPD %.1fx" % self.speed)
            return True
        if k == "0":
            self.speed = 1.0
            self.set_hud("SPD 1.0x")
            return True
        if k.isdigit() and k != "0":
            i = int(k) - 1
            if 0 <= i < len(self.sched):
                self.t = self.sched[i][0]
                self.emitter.reset()
                self.last_snap = None
                term.write(self.emitter.full_clear())
                self.set_hud("SCENE %d" % (i + 1))
            return True
        if self.interactive and k in ("y", "Y", "n", "N"):
            self._answer(k.lower())
            return True
        return True

    def _answer(self, v: str) -> None:
        scene, lt = S.locate(self.sched, self.t)
        te = scene.teff(lt)
        pr = scene.prompt_at(te)
        if pr is None:
            return
        idx, p = pr
        if idx in self._answered:
            return
        self._answered.add(idx)
        p.answer = v
        scene.add_log(te + 0.05, "用户输入: %s" % v, R.S_BRIGHT)
        if v == "n":
            scene.add_log(p.t1 + 0.05, "系统选择: Y —— 忽略用户输入。", R.S_AMBER)
        self.set_hud("INPUT " + v.upper())
        self.last_snap = None

    # -- 主循环 --------------------------------------------------------
    def run(self) -> int:
        term.drain_keys()
        if self.audio is not None:
            try:
                self.audio.start()
            except Exception as e:
                print("音效启动失败：%s" % e, file=sys.stderr)
                self.audio = None
        if not self.args.headless:
            term.alt_screen(True)
            term.write(self.emitter.full_clear())
            term.flush()
        self.draw(force=True)
        last_size_check = 0.0
        try:
            while self.t < self.total - 1e-9:
                nt = self.next_t()
                if self.args.headless:
                    # 录制/压测不跟实时节奏：逻辑帧本来就是时间的纯函数，
                    # 按实时睡只会白白等一整条时间线的长度（曾经白等 111 秒）。
                    deadline = time.perf_counter()
                elif self.paused:
                    deadline = time.perf_counter() + 0.05
                else:
                    deadline = time.perf_counter() + max(0.0, (nt - self.t) / self.speed)
                while True:
                    now = time.perf_counter()
                    if now >= deadline:
                        break
                    k = term.poll_key()
                    if k is not None and not self.handle_key(k):
                        return self._finish()
                    if self.paused:
                        deadline = max(deadline, now + 0.05)
                    if now - last_size_check > 0.5:
                        last_size_check = now
                        self._check_resize()
                    term.sleep_until(min(deadline, now + 0.02))
                if not self.paused:
                    self.t = nt
                self._pump_audio()
                self.draw()
                if self.hud and time.perf_counter() >= self.hud_until:
                    self.hud = ""
                    self.last_snap = None
        except KeyboardInterrupt:
            pass
        return self._finish()

    def _check_resize(self) -> None:
        w, h = term.size((self.w, self.h))
        if (w, h) != (self.w, self.h):
            self.w, self.h = w, h
            self.grid = Grid(w, h)
            self.emitter = Emitter(w, h)
            self.last_snap = None
            term.write(self.emitter.full_clear())

    def _finish(self) -> int:
        if self.audio is not None:
            try:
                self.audio.stop_all(0.05)
                self.audio.stop()
            except Exception:
                pass
        if self.rec:
            self.rec.close()
            print("→ 已录制 %d 帧到 %s" % (self.rec.n, self.rec.path))
        if not self.args.headless:
            term.alt_screen(False)
            term.write("\x1b[2J\x1b[1;1H")
            term.flush()
        else:
            print("逻辑帧 %d 帧 / 总时长 %.1fs（平均 %.2f 帧/秒，"
                  "输出 %.2f KB/帧）" % (
                      self.frames, self.total,
                      self.frames / max(1e-6, self.total),
                      self.emitter.kb_per_frame()))
        return 0


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------


def do_list(args=None) -> int:
    scenes = build(args) if args is not None else S.build_scenes()
    sched = S.schedule(scenes)
    if args is not None:
        print(make_ctx(args).describe())
        corp = CORPUS.Corpus.load(args.corpus or None)
        if corp is not None:
            st = corp.stats()
            print("语料库：%s" % st["path"])
            print("  原始 %d 条 → 去重 %d 条，其中 %d 条带具体错误原因"
                  % (st["raw"], st["distinct"], st["with_reason"]))
            print("  种类：" + "、".join("%s×%d" % (CORPUS.KIND_LABEL.get(k, k), v)
                                        for k, v in sorted(st["kinds"].items(), key=lambda x: -x[1])))
        print()
    print("段落列表（按严重度递增排列）：")
    print("%-3s %-18s %-24s %8s  %s" % ("#", "名称", "标题", "时长", "故障效果数"))
    for i, (a, b, s) in enumerate(sched):
        print("%-3d %-18s %-24s %7.1fs  %d" % (i + 1, s.name, s.title, s.duration, len(s.glitches)))
    print("合计 %.1f 秒（1.0x）。按 1-9 跳段，p 暂停，+/- 调速，q 退出。"
          % S.total_duration(scenes))
    return 0


def do_snap(args) -> int:
    w = args.width or 132
    h = args.height or 42
    scenes = build(args)
    sched = S.schedule(scenes)
    total = S.total_duration(scenes)
    grid = Grid(w, h)
    for part in args.snap.split(","):
        part = part.strip()
        if not part:
            continue
        t = float(part)
        if t > total:
            t = total - 1e-6
        scene, lt = S.locate(sched, t)
        render_at(sched, t, grid, "")
        print("=" * w)
        print("t=%7.2fs  scene=%-10s local=%6.2fs  eff=%6.2fs  %dx%d"
              % (t, scene.name, lt, scene.teff(lt), w, h))
        print("=" * w)
        for line in grid.lines():
            print(line)
        print()
    return 0


def do_bench(args) -> int:
    w = args.width or 132
    h = args.height or 42
    scenes = build(args)
    sched = S.schedule(scenes)
    total = S.total_duration(scenes)
    grid = Grid(w, h)
    em = Emitter(w, h)
    t = 0.0
    frames = 0
    cpu = 0.0
    cpu_max = 0.0
    prev = None
    while t < total - 1e-9:
        i = S.locate_idx(sched, t)
        a, _b, scene = sched[i]
        lt = t - a
        c0 = time.perf_counter()
        scene.render(grid, lt, "")
        c1 = time.perf_counter()
        em.diff(grid)
        c2 = time.perf_counter()
        d = (c2 - c0)
        cpu += d
        cpu_max = max(cpu_max, d)
        frames += 1
        nt = a + scene.next_change(lt, w)
        if nt <= t + 1e-6:
            nt = t + MIN_QUANTUM
        t = min(nt, total)
    print("逻辑帧压测（%dx%d，整条时间线）" % (w, h))
    print("  总时长        %.2f s" % total)
    print("  实际渲染帧数  %d 帧（平均 %.1f 帧/秒，即只渲染会变的画面）" % (frames, frames / total))
    print("  渲染+编码     %.3f ms/帧 平均，最差 %.3f ms" % (cpu / frames * 1000, cpu_max * 1000))
    print("  输出量        %.1f KB/帧，合计 %.1f MB" % (em.kb_per_frame(), em.bytes_out / 1048576))
    print("  等价帧率上限  %.0f fps（60fps 预算 16.7ms/帧）" % (1.0 / (cpu / frames)))
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.list:
        return do_list(args)
    if args.snap:
        return do_snap(args)
    if args.bench:
        return do_bench(args)
    term.init_console()
    if not args.headless:
        term.set_title("SYSTEM DIAGNOSTIC")
    if args.width or args.height:
        w = args.width or 132
        h = args.height or 42
    else:
        w, h = term.size()
    p = Player(args, w, h)
    print(p.ctx.describe())
    if p.ctx.corpus is not None and args.random == "on":
        st = p.ctx.corpus.stats()
        print("  语料库 %s：原始 %d 条 → 去重 %d 条（%d 条带原因）"
              % (os.path.basename(st["path"]), st["raw"], st["distinct"], st["with_reason"]))
    if not args.headless and not sys.stdout.isatty() and not args.record:
        print("提示：当前 stdout 不是交互式终端，动画不会正常显示。"
              "自检请用 --snap 5,20 或 --bench；出片请用 --headless --record out/demo.jsonl",
              file=sys.stderr)
    return p.run()


if __name__ == "__main__":
    raise SystemExit(main())
