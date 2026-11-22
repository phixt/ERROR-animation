"""信息层（htop 面板）故障的联络表：只看画面顶部几行。

用法：
    python tools/panel_sheet.py --out out/panel_sheet.png
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

from erranim import film as F  # noqa: E402
from erranim import scenes as S  # noqa: E402
from erranim.render import Grid  # noqa: E402

# 每一行取一个"日志区"时刻和一个"信息层故障生效中"的时刻做对照
PAIRS = [
    (4.20, 5.70),
    (10.00, 11.20),
    (27.00, 28.90),
    (36.00, 37.20),
    (54.00, 55.50),
    (69.00, 70.70),
    (82.00, 83.90),
    (92.00, 93.10),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/panel_sheet.png")
    ap.add_argument("--rows", type=int, default=5, help="只看顶部几行")
    ap.add_argument("--font-size", type=int, default=18)
    ap.add_argument("--w", type=int, default=118)
    ap.add_argument("--h", type=int, default=32)
    args = ap.parse_args(argv)

    scenes = S.build_scenes()
    sched = S.schedule(scenes)
    atlas = F.Atlas(args.font_size)
    g = Grid(args.w, args.h)

    tiles = []
    for off, on in PAIRS:
        for t, tag in ((off, "对照"), (on, "故障")):
            scene, lt = S.locate(sched, t)
            scene.render(g, lt)
            rows = [g.row_runs(y) for y in range(args.rows)]
            img = F.compose(rows, atlas, args.w, args.rows)
            tiles.append((t, "%s @%.1fs" % (scene.name, t), tag, img))

    cw = tiles[0][3].shape[1] // 2
    chh = tiles[0][3].shape[0] // 2
    cols = 4
    nrow = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw + 8, nrow * (chh + 15) + 8), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for k, (t, label, tag, img) in enumerate(tiles):
        cx, cy = k % cols, k // cols
        x, y = 4 + cx * cw, 4 + cy * (chh + 15)
        sheet.paste(Image.fromarray(img, "RGB").resize((cw, chh), Image.LANCZOS), (x, y))
        d.text((x + 3, y + chh + 2), "%s %s" % (tag, label), fill=(210, 210, 210))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sheet.save(args.out)
    print("%d 格 → %s（左为对照，右为信息层故障生效中）" % (len(tiles), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
