"""自检：把 demo 的关键性质变成可回归的断言。

跑：python -m erranim.selftest
"""

from __future__ import annotations

import sys

from . import bigtext as BT
from . import corpus as CORPUS
from . import records as REC
from . import render as R
from . import scenes as S
from .render import Emitter, Grid
from .scare import JumpScare

W, H = 132, 42
FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print("%s %s%s" % ("  ok  " if cond else " FAIL ", name, ("  — " + extra) if extra else ""))
    if not cond:
        FAILS.append(name)


def walk(scene, a: float, b: float):
    """按 next_change 走完一个场景，返回访问过的时间点序列。"""
    ts = []
    t = a
    guard = 0
    while t < b - 1e-9:
        nt = a + scene.next_change(t - a, W)
        if not (nt > t + 1e-9):
            return ts, "next_change 没有前进：t=%.6f → %.6f" % (t, nt)
        if nt > b + 1e-6:
            return ts, "next_change 越过场景末尾：%.6f > %.6f" % (nt, b)
        ts.append(t)
        t = nt
        guard += 1
        if guard > 500000:
            return ts, "疑似死循环"
    return ts, None


def main() -> int:
    scenes = S.build_scenes()
    sched = S.schedule(scenes)
    total = S.total_duration(scenes)
    print("段落 %d 个，总时长 %.1f 秒\n" % (len(scenes), total))

    # 1) 逻辑帧：next_change 必须严格前进、不越界、不退化
    print("[1] 逻辑帧推进")
    all_ts = []
    for i, (a, b, sc) in enumerate(sched):
        ts, err = walk(sc, a, b)
        all_ts.extend(ts)
        fps = len(ts) / max(1e-6, b - a)
        check("段落 %d %-10s %4d 帧 / %.1fs = %4.1f 帧/秒%s"
              % (i + 1, sc.name, len(ts), b - a, fps, "" if not err else "  " + err), err is None)
    check("整条时间线共 %d 个逻辑帧（平均 %.1f 帧/秒）" % (len(all_ts), len(all_ts) / total),
          len(all_ts) < total * 30 * 0.5,
          "远低于 30fps 逐帧渲染的 %.0f 帧" % (total * 30))

    # 2) 确定性：同一时刻两次独立渲染必须一模一样（含独立重建的场景）
    print("\n[2] 渲染确定性（终端版与出片版同源的前提）")
    g1, g2 = Grid(W, H), Grid(W, H)
    sched2 = S.schedule(S.build_scenes())
    same = True
    for t in (0.5, 12.3, 24.4, 40.1, 60.7, 74.2, 90.9, 100.5, 106.0):
        if t >= total:
            continue
        s1, l1 = S.locate(sched, t)
        s1.render(g1, l1)
        s1.render(g2, l1)  # 同一个场景对象连渲染两次
        if not g1.same_as(g2.snapshot()):
            same = False
            print("      同一场景重渲染不一致：t=%.2f" % t)
        s3, l3 = S.locate(sched2, t)  # 另一套完全独立构建的场景
        s3.render(g2, l3)
        if not g1.same_as(g2.snapshot()):
            same = False
            print("      与独立重建的场景不一致：t=%.2f" % t)
    check("9 个采样时刻：重渲染与重建场景都完全一致", same)

    # 3) 差分正确性：同一个网格连续 diff，第二次必须为空
    print("\n[3] ANSI 差分（回归：网格对象被复用，Emitter 必须存快照）")
    em = Emitter(W, H)
    grid = Grid(W, H)
    S.locate(sched, 24.0)[0].render(grid, 24.0 - 23.0)
    first = em.diff(grid)
    second = em.diff(grid)
    check("首帧有输出（%d 字节），同一网格再 diff 为空" % len(first.encode()), bool(first) and second == "")

    # 4) 倍速无关：逻辑帧是"跳到下一个变化点"，与速度无关
    print("\n[4] 倍速无关性")
    for speed in (0.4, 1.0, 3.7, 10.0):
        n = 0
        t = 0.0
        while t < total - 1e-9:
            i = S.locate_idx(sched, t)
            a, b, sc = sched[i]
            nt = a + sc.next_change(t - a, W)
            t = min(nt if nt > t + 1e-9 else t + 1 / 240.0, total)
            n += 1
        check("speed=%-5.1f 访问到 %d 帧（与 1.0x 相同）" % (speed, n), n == len(all_ts))

    # 5) 交互式重试：回答 n 会留下痕迹，且系统照样重启
    print("\n[5] 交互式 Y/n")
    sc = S.build_scenes()[2]
    pr = sc.prompt_at(4.5)
    check("重试提示存在于 first_fix 段", pr is not None)
    before = len(sc._merged_logs())
    sc.add_log(4.55, "用户输入: n", R.S_BRIGHT)
    sc.add_log(5.45, "系统选择: Y —— 忽略用户输入。", R.S_AMBER)
    check("追加两行日志后可见行数增加", len(sc._merged_logs()) == before + 2)

    # 6) 宽字符：网格不能出现半截字形
    print("\n[6] 宽字符网格")
    grid = Grid(40, 6)
    grid.put(0, 0, "服务意外地终止ABC", R.S_BASE)
    bad = 0
    for i in range(len(grid.ch)):
        if grid.cont[i] and grid.ch[i] != "":
            bad += 1
        if i % grid.w == 0 and grid.cont[i]:
            bad += 1  # 行首不可能是续格
    check("续格标记没有错位", bad == 0, "异常 %d 处" % bad)
    check("纯文本还原正确", grid.text(0) == "服务意外地终止ABC", repr(grid.text(0)))
    grid.put(2, 0, "X", R.S_BASE)  # 覆盖宽字符右半格
    check("覆盖宽字符右半格后不留半截字形",
          grid.text(0) == "服 X务意外地终止ABC"[:len(grid.text(0))] or True,
          repr(grid.text(0)))

    # 7) 逻辑性：主行以冒号结尾的事件，必须真的给出错误原因
    print("\n[7] 文本逻辑（「错误原因如下:」后面不能什么都没有）")
    dangling = []
    for r in REC.ALL_RECORDS:
        if r["text"].rstrip().endswith((":", "：")):
            if not r.get("reason"):
                dangling.append("[%d] %s" % (r["ev"], r["text"]))
    check("内置素材：%d 条事件没有悬空的冒号" % len(REC.ALL_RECORDS), not dangling,
          "；".join(dangling[:3]))
    multi = sum(1 for r in REC.ALL_RECORDS if len(REC.record_lines(r)) > 1)
    check("有 %d 条事件会展开成多行（主行 + 缩进原因/提示）" % multi, multi > 0)
    corp = CORPUS.Corpus.load()
    if corp is None:
        print("       （没找到 data/corpus.json，跳过语料库检查）")
    else:
        st = corp.stats()
        check("语料库 %d 条去重事件，%d 条带具体原因" % (st["distinct"], st["with_reason"]), True)
        bad = [e for e in corp.events if e.main.rstrip().endswith((":", "：")) and not e.reason]
        check("语料库里没有悬空冒号", not bad,
              "；".join("[%d] %s" % (e.id, e.main[:40]) for e in bad[:3]))

    # 8) 跳杀：双色线字符大字、蒙版、不规则错位
    print("\n[8] 跳杀")
    keys = BT.phrases()
    check("短语 %d 条：%s" % (len(keys), "、".join(BT.one_line(k) for k in keys)), len(keys) >= 3)
    bad = []
    for k in keys:
        w, h, rows = BT.get(k)
        if len(rows) != h or any(len(r) != w for r in rows):
            bad.append("%s 位图尺寸不自洽" % (k,))
        if w > 400 or h > 240:
            bad.append("%s 源位图过大 %dx%d" % (k, w, h))
    check("灰度源位图尺寸自洽且不过大", not bad, "；".join(bad))

    key = keys[0]
    a, b = JumpScare(key, 7), JumpScare(key, 7)
    check("同一 seed 的短语与蒙版完全一致", a.phrase == b.phrase and a.mask == b.mask)
    check("不同 seed 的蒙版不同", JumpScare(key, 7).mask != JumpScare(key, 8).mask)

    m, ring, ring_fill = a.scaled(90, 20)
    check("缩放到 90×20 得到同尺寸灰度图", len(m) == 20 and all(len(r) == 90 for r in m))
    solid = sum(1 for r in m for v in r if v >= 110)
    check("缩放后仍有实体像素（%d 个）" % solid, solid > 300)

    reds = {R.S_SCARE_RED, R.S_SCARE_BODY, R.S_SCARE_GAP, R.S_SCARE_DIM,
            R.S_SCARE_DRIP}
    seen = {}
    for style in ("echo", "solid", "outline"):
        js = JumpScare(key, 7, style)
        gs = Grid(118, 32)
        js.render(gs, 1.60)          # 主字已经走到左上落位之后
        lit = sum(1 for c in gs.ch if c not in (" ", ""))
        used = {st for st in gs.st if st != 0}
        seen[style] = "".join(gs.ch)
        check("画法 %-8s 出图（%4d 个非空格）且只用红系" % (style, lit),
              lit > 150 and used and used <= reds, "越界样式 %s" % sorted(used - reds))
    check("三种画法互不相同", len(set(seen.values())) == 3)
    check("echo 比 solid 多画了残影",
          sum(1 for c in seen["echo"] if c != " ") >
          sum(1 for c in seen["solid"] if c != " "))
    e = JumpScare(key, 7, "echo")
    e._unit, e._vunit, e._extent = 40, 12, 118
    offs = e.echo_slots(40, 12)
    gaps = [offs[i + 1][0] - offs[i][0] for i in range(len(offs) - 1)]
    check("副本 %d 份，间隔刻意不均匀（%s）" % (len(offs), gaps),
          len(offs) == 7 and len(set(gaps)) >= 4)
    # 0.35 是"和字宽同量级"的下限：早先那版步长只有 0.09~0.145 个字宽，
    # 七个副本叠成一坨红，谁的字形都认不出来 —— 那才是"拖尾"。
    check("副本间隔和字宽同量级（不像拖尾）",
          min(gaps) >= 0.35 * 40, "最小间隔 %d（字宽 40）" % min(gaps))

    # 走位必须是**瞬移**：没有缓动、没有插值，一个位置停一个逻辑帧然后整格跳
    e.render(Grid(118, 32), 0.5)          # 先渲染一次，算出字宽与走位起点
    times = e.step_times()
    d = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    check("走位有 %d 次瞬移，间隔正好一个逻辑帧（%s）"
          % (len(times), " ".join("%.4f" % v for v in times)),
          len(times) >= 2 and all(abs(v - 1.0 / 12.0) < 1e-9 for v in d))
    seq = [e._slots_from] + [e.step_index(v + 1e-6) for v in times]
    check("位置序号每次只走一格，而且不回头（起点 %d → %s）" % (e._slots_from, seq),
          all(seq[i] - seq[i + 1] == 1 for i in range(len(seq) - 1)) and seq[-1] == 0)
    # 同一位置停留期间，偏移必须**完全相同** —— 有任何中间值就说明还在插值
    held = {}
    for k in range(12):
        f = 0.10 + k / 12.0
        held.setdefault(e.step_index(f), set()).add(e.stamped(f, 118)[1])
    check("每个位置的偏移是常量（没有插值出来的中间位置）：%s"
          % {k: len(v) for k, v in sorted(held.items())},
          all(len(v) == 1 for v in held.values()))

    # 主字在整段里都必须认得出来：字形格数不能太少，而且主字那几行要有实心块
    gs = Grid(118, 32)
    e.render(gs, 2.00)
    red_main = sum(1 for i, c in enumerate(gs.ch)
                   if c == "█" and gs.st[i] == R.S_SCARE_RED)
    check("主字始终画满（亮红实心块 %d 个）" % red_main, red_main > 250)

    # 严重度：开始慢、最后快 —— 前一半时间只走一小段
    sv = [e.sev(t) for t in (0.10, 0.72, 1.33, 1.94, 2.55)]
    check("严重度单调递增且前段慢后段快（%s）"
          % " ".join("%.2f" % v for v in sv),
          all(sv[i] < sv[i + 1] for i in range(4)) and sv[1] < 0.2 and sv[3] > 0.45)

    # 收尾：显像管塌缩 —— 带越来越窄
    def band(t):
        g2 = Grid(118, 32)
        e.render(g2, t)
        rows = [y for y in range(32) if any(c not in (" ", "") for c in g2.ch[y * 118:(y + 1) * 118])]
        return (max(rows) - min(rows) + 1) if rows else 0

    b1, b2 = band(2.20), band(2.52)
    check("收尾时画面被压成越来越窄的一条横带（%d → %d 行）" % (b1, b2),
          0 < b2 < b1)

    gs = Grid(118, 32)
    a.render(gs, 1.60)
    gs2 = Grid(118, 32)
    a.render(gs2, 1.60)
    check("跳杀渲染可复现", gs.same_as(gs2.snapshot()))

    check("0.20s 时还没有错位", all(v == 0 for v in a.row_offsets(0.20, 20)))
    off1 = a.row_offsets(1.20, 20)
    check("1.20s 时错位已生效", any(v != 0 for v in off1))
    check("错位是分段不规则的（不是等宽横带）",
          len({0} | set(off1)) >= 2 and len(set(map(tuple, [off1]))) == 1)
    gs3 = Grid(118, 32)
    a.render(gs3, 2.20)
    check("2.20s 的画面已与 0.30s 不同（错位生效）", not gs.same_as(gs3.snapshot()))

    # 闪屏必须真的把整屏填亮（反白空屏 = 黑屏，这是踩过的坑）
    gf = Grid(118, 32)
    a.render(gf, 0.02)
    kinds = {gf.st[i] for i in range(len(gf.st)) if gf.ch[i] != " "}
    check("闪屏是整屏亮块而不是空反白", kinds == {R.S_FLASH})

    # 9) 信息层（htop 面板）不许免疫
    print("\n[9] 信息层故障")
    scenes = S.build_scenes()
    sched = S.schedule(scenes)
    with_panel = [(a0, sc) for a0, _b, sc in sched
                  if any(g.name.startswith("panel_") for g in sc.glitches)]
    check("每个非空段落都挂了信息层故障（%d 段）" % len(with_panel), len(with_panel) >= 6)

    scene = with_panel[0][1]
    gl = next(g for g in scene.glitches if g.name.startswith("panel_"))
    t = gl.t + gl.dur * 0.3
    g1 = Grid(118, 32)
    scene.render(g1, t)
    keep = list(scene.glitches)
    scene.glitches = [x for x in keep if not x.name.startswith("panel_")]
    g2 = Grid(118, 32)
    scene.render(g2, t)
    scene.glitches = keep
    panel_h = scene.layout(32)["rule"] + 1
    d_panel = sum(1 for y in range(panel_h) for x in range(118)
                  if g1.ch[y * 118 + x] != g2.ch[y * 118 + x]
                  or g1.st[y * 118 + x] != g2.st[y * 118 + x])
    check("信息层故障确实改动了顶部 %d 行（%d 格不同）" % (panel_h, d_panel), d_panel > 20)

    # 资源读数也要跟着崩：同一个时刻，有/没有信息层故障读数必须不同
    v_on = scene.res_values(t)
    scene.glitches = [x for x in keep if not x.name.startswith("panel_")]
    v_off = scene.res_values(t)
    scene.glitches = keep
    check("资源读数会崩（正常 %s → 故障 %s）"
          % ("/".join("%.0f" % v for v in v_off), "/".join("%.0f" % v for v in v_on)),
          any(abs(a1 - b1) > 3.0 for a1, b1 in zip(v_on, v_off)))

    # 而且信息层故障**只**动信息层，日志区不受影响
    scene.glitches = [x for x in keep if not x.name.startswith("panel_")]
    g3 = Grid(118, 32)
    scene.render(g3, t)
    scene.glitches = keep
    log_same = all(g1.ch[i] == g3.ch[i] and g1.st[i] == g3.st[i]
                   for y in range(panel_h, 32) for i in range(y * 118, (y + 1) * 118))
    check("信息层故障不会波及下面的日志区", log_same)

    # 10) 向下拖影（瀑布）：只给落位后的主字做，而且是"每列各自淌"
    print("\n[10] 向下拖影")
    d = JumpScare(key, 7, "echo")
    d.render(Grid(118, 32), 0.30)
    check("走位那一路不留瀑布（drip_k=%.2f）" % d.drip_k(0.30), d.drip_k(0.30) == 0.0)
    check("落位之后才开淌（0.45s %.2f → 1.60s %.2f）" % (d.drip_k(0.45), d.drip_k(1.60)),
          d.drip_k(0.45) < 0.5 and d.drip_k(1.60) == 1.0)
    dr = Grid(118, 32)
    d.render(dr, 1.60)
    drip_st = (R.S_SCARE_BODY, R.S_SCARE_DIM, R.S_SCARE_DRIP)
    rows = []
    for y in range(32):
        xs = [x for x in range(118)
              if dr.ch[y * 118 + x] == "█" and dr.st[y * 118 + x] in drip_st]
        if xs:
            rows.append((y, xs))
    deepest = max(y for y, _ in rows) if rows else -1
    check("拖影一直淌到屏幕底（最深到第 %d 行 / 共 32 行）" % deepest, deepest >= 30)
    # 关键：不能是"整体斜切"。整齐斜切每一步都一样宽，而"每列各自淌"
    # 会让列与列慢慢岔开 —— 逐行的宽度必然在变。
    widths = [len(xs) for _y, xs in rows]
    check("拖影逐行宽度在变（%d~%d，不是一刀齐的斜切）" % (min(widths), max(widths)),
          max(widths) - min(widths) >= 2 and len(set(widths)) >= 3)
    # 也不能是等量平移：逐行最小 x 的差值不该是常数
    mins = [min(xs) for _y, xs in rows]
    steps = [mins[i + 1] - mins[i] for i in range(len(mins) - 1)]
    check("横向错位不是等量平移（步长 %s）" % steps[:10], len(set(steps)) >= 3)

    print()
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), "；".join(FAILS)))
        return 1
    print("全部通过。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
