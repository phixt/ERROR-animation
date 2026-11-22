"""探针：打印 CRT 后期链里生成的偶现色带事件，方便核对时间点。"""
import re
import sys

from erranim.film import crt_chain

s = crt_chain(108.7, 32 * 22, seed=20260924, bands=7)
pat = re.compile(
    r"y=(\d+):w=iw:h=(\d+):color=(0x[0-9a-f]+)@([0-9.]+):t=fill:enable='between\(t,([0-9.]+),([0-9.]+)\)'"
)
evs = pat.findall(s)
print("色带事件数:", len(evs))
for y, h, c, a, t0, t1 in evs:
    print("  t=%6.2f - %5.2f   y=%-4s h=%-3s %s  alpha=%s" % (float(t0), float(t1), y, h, c, a))
with open("out/crt_chain.txt", "w", encoding="utf-8") as f:
    f.write(s)
print("链长 %d 字符，共 %d 个滤镜" % (len(s), s.count(",") + 1))
