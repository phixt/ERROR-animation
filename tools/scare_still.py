"""只出一张跳杀静帧（含视频端污渍），不跑全片。

用法：python tools/scare_still.py --t 106.5 --out out/scare_final.png
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from erranim import film as F  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="out/demo.jsonl")
    ap.add_argument("--t", type=float, default=106.5, help="全局时刻（秒）")
    ap.add_argument("--glitch", type=int, default=3)
    ap.add_argument("--layer", default="pixel", choices=("pixel", "grid"),
                    help="pixel = 出片的矢量层；grid = 终端看到的字符层")
    ap.add_argument("--out", default="out/scare_still.png")
    args = ap.parse_args(argv)

    meta, frames = F.load_record(args.record)
    w, h = int(meta["w"]), int(meta["h"])
    atlas = F.Atlas(18)
    fw, fh = w * atlas.cell_w, h * atlas.cell_h

    if args.layer == "grid":
        # 终端那条路：重新构建场景，这次**不**跳过跳杀，渲染出来的就是字符版
        from erranim import scenes as S
        from erranim.render import Grid
        scenes = S.build_scenes(jumpscare=True, seed=int(meta.get("seed", 0) or 0),
                                scare_text=None,
                                scare_style=meta.get("scare_style", "echo"))
        sched = S.schedule(scenes)
        g = Grid(w, h)
        F.render_at_grid = None  # 占位，避免误用
        scene, lt = S.locate(sched, args.t)
        scene.render(g, lt, skip_scare=False)
        rows = [g.row_runs(y) for y in range(h)]
        img = F.compose(rows, atlas, w, h)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        Image.fromarray(img.astype(np.uint8), "RGB").save(args.out)
        print("终端字符层  t=%.2fs  场景 %s" % (args.t, scene.name))
        print("→ %s" % args.out)
        return 0

    # 取最接近的逻辑帧
    i = min(range(len(frames)), key=lambda k: abs(frames[k][0] - args.t))
    t, rows = frames[i]
    frame = F.compose(rows, atlas, w, h)

    scare = meta.get("scare")
    applied = 0
    if scare:
        t0 = float(scare[0])
        if args.glitch:
            progs = F.build_glitch_programs(fw, fh, args.glitch,
                                            int(meta.get("seed", 0) or 0))
            want = -1
            for k in range(len(progs)):
                if t >= t0 + 0.85 + k * 0.55:
                    want = k
            if want >= 0:
                F.apply_glitch(frame, progs[want])
                applied = want + 1
        # 跳杀按像素画矢量版（和出片走的是同一条路）
        from erranim.scare import JumpScare
        ph = meta.get("scare_phrase")
        js = JumpScare(tuple(ph) if ph else None, int(meta.get("seed", 0) or 0),
                       meta.get("scare_style", "echo"))
        lt = t - t0
        if 0.0 <= lt < js.CUT_END:
            js.render_pixels(frame, lt)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    Image.fromarray(frame.astype(np.uint8), "RGB").save(args.out)
    print("逻辑帧 #%d  t=%.2fs  解码失败 %d 级  跳杀矢量层 %s"
          % (i, t, applied, "已叠加" if scare else "无"))
    print("→ %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
