"""跳杀样张：把几种画法拼成一张对比图，方便挑。

用法：
    python tools/scare_samples.py                 # 写 out/scare_samples.png
    python tools/scare_samples.py --phrase 1      # 用第 N 条短语
    python tools/scare_samples.py --list
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from erranim import bigtext as BT  # noqa: E402
from erranim import film as F  # noqa: E402
from erranim.render import Grid  # noqa: E402
from erranim.scare import STYLES, JumpScare  # noqa: E402

W, H = 118, 32
LABEL_H = 26


def shot(phrase, style: str, t: float, atlas, seed: int = 7) -> Image.Image:
    g = Grid(W, H)
    JumpScare(phrase, seed, style).render(g, t)
    rows = [g.row_runs(y) for y in range(H)]
    # film.compose 现在直接返回 numpy 帧
    return Image.fromarray(F.compose(rows, atlas, W, H), "RGB")


def labelled(img: Image.Image, text: str, font) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + LABEL_H), (0x08, 0x0A, 0x0D))
    out.paste(img, (0, LABEL_H))
    d = ImageDraw.Draw(out)
    d.text((6, 5), text, font=font, fill=(0xC8, 0xD2, 0xE2))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跳杀画法样张")
    ap.add_argument("--list", action="store_true", help="列出短语")
    ap.add_argument("--phrase", type=int, default=0, help="第几条短语（0 起）")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="out/scare_samples.png")
    ap.add_argument("--style", default="", choices=[""] + list(STYLES),
                    help="只出一张（原分辨率），不拼对比图")
    ap.add_argument("--time", type=float, default=0.45, help="配合 --style 的取样时刻")
    ap.add_argument("--zoom", type=int, default=1, help="放大倍数（只对单张有效）")
    args = ap.parse_args(argv)

    keys = BT.phrases()
    if args.list:
        for i, k in enumerate(keys):
            w, h, _ = BT.get(k)
            print("%2d  %-28s 源位图 %dx%d" % (i, " / ".join(k), w, h))
        return 0

    phrase = keys[args.phrase % len(keys)]
    atlas = F.Atlas(18)

    if args.style:
        img = shot(phrase, args.style, args.time, atlas, args.seed)
        if args.zoom > 1:
            img = img.resize((img.width * args.zoom, img.height * args.zoom), Image.NEAREST)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        img.save(args.out)
        print("短语：%s  画法：%s  t=%.2fs" % (" / ".join(phrase), args.style, args.time))
        print("→ %s（%dx%d）" % (args.out, img.width, img.height))
        return 0

    label_font = ImageFont.truetype(atlas.mono_path, 15)

    # 三行 = 三种画法；两列 = 干净时刻 / 错位发作中
    tiles = []
    for style in STYLES:
        for t, tag in ((0.45, "静止"), (2.10, "错位中")):
            img = shot(phrase, style, t, atlas, args.seed)
            tiles.append(labelled(img, "%-8s  t=%.2fs  %s" % (style, t, tag), label_font))

    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    cw = max(t.width for t in tiles)
    ch = max(t.height for t in tiles)
    sheet = Image.new("RGB", (cw * cols, ch * rows), (0x10, 0x12, 0x16))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * cw, (i // cols) * ch))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sheet.save(args.out)
    print("短语：%s" % " / ".join(phrase))
    print("→ %s（%dx%d）" % (args.out, sheet.width, sheet.height))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
