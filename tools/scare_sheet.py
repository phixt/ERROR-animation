"""把跳杀结尾的关键时刻排成一张联络表（contact sheet），一眼看完整段。

调结尾的时候最烦的是"改一行、渲一张、来回切"。这个工具把 12 个时间点
排成 3×4 的网格输出一张 PNG，并且**同一条代码路径**（先解码失败、再矢量层），
所以看到的就是成片里会出现的画面。

用法：
    python tools/scare_sheet.py --out out/scare_sheet.png
    python tools/scare_sheet.py --layer grid --out out/scare_sheet_grid.png
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from erranim import film as F  # noqa: E402

# 场景内相对秒。前四个点专门卡在**瞬移的那几帧**上（0.1833 / 0.2667 / 0.35），
# 塌缩那段（2.27–2.55）也多放几个点 —— 那里变化最快。
TIMES = [0.05, 0.13, 0.19, 0.27, 0.36, 0.60, 1.20, 1.90, 2.22, 2.38, 2.50, 2.62]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="out/demo.jsonl")
    ap.add_argument("--out", default="out/scare_sheet.png")
    ap.add_argument("--layer", default="pixel", choices=("pixel", "grid"))
    ap.add_argument("--glitch", type=int, default=3)
    ap.add_argument("--scale", type=float, default=0.42, help="每格缩放比例")
    ap.add_argument("--font-size", type=int, default=18)
    args = ap.parse_args(argv)

    meta, frames = F.load_record(args.record)
    w, h = int(meta["w"]), int(meta["h"])
    atlas = F.Atlas(args.font_size)
    fw, fh = w * atlas.cell_w, h * atlas.cell_h
    seed = int(meta.get("seed", 0) or 0)
    style = meta.get("scare_style", "echo")
    ph = meta.get("scare_phrase")
    scare_win = meta.get("scare") or [0.0, 0.0]
    t0 = float(scare_win[0])

    progs = F.build_glitch_programs(fw, fh, args.glitch, seed) if args.glitch else []
    analog = F.AnalogHorrorEngine(fw, fh, seed=seed)
    from erranim.scare import JumpScare
    js = JumpScare(tuple(ph) if ph else None, seed, style)

    grid_scene = None
    if args.layer == "grid":
        from erranim import scenes as S
        from erranim.render import Grid
        scenes = S.build_scenes(jumpscare=True, seed=seed, scare_text=None,
                                scare_style=style)
        grid_scene = (S.schedule(scenes), Grid(w, h))

    tiles = []
    for lt in TIMES:
        if args.layer == "grid":
            sched, g = grid_scene
            scene, slt = S.locate(sched, t0 + lt)
            scene.render(g, slt, skip_scare=False)
            img = F.compose([g.row_runs(y) for y in range(h)], atlas, w, h)
        else:
            i = min(range(len(frames)), key=lambda k: abs(frames[k][0] - (t0 + lt)))
            raw = F.compose(frames[i][1], atlas, w, h)
            img = analog.process(raw, t0 + lt, glitch_progs=progs, glitch_t0=t0, scare=js)
        tiles.append((lt, Image.fromarray(img.astype(np.uint8), "RGB")))

    sw = max(1, int(fw * args.scale))
    sh = max(1, int(fh * args.scale))
    cols, rows = 3, 4
    sheet = Image.new("RGB", (cols * sw + 8, rows * (sh + 16) + 8), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for k, (lt, im) in enumerate(tiles):
        cx, cy = k % cols, k // cols
        x = 4 + cx * sw
        y = 4 + cy * (sh + 16)
        sheet.paste(im.resize((sw, sh), Image.LANCZOS), (x, y))
        d.text((x + 3, y + sh + 2), "t=+%.2fs" % lt, fill=(220, 220, 220))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sheet.save(args.out)
    print("%s 层 %d 格 → %s" % (args.layer, len(tiles), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
