"""离线渲染整片音轨，并用 ffmpeg 做后期。

**为什么要离线渲染一份**：终端实时播放那条路只能听到"干声" —— 加混响、
压缩、限幅都会引入延迟，而且 `loudnorm` 必须看完整个流才算得准。
但出片的时候这些都是免费的，所以：

    终端实时  = 干声（噪声床 + 系统音效），零延迟
    出片      = 同一份干声 → ffmpeg 后期链 → 压进 mp4

两条路共用 `director.py` 的事件逻辑，所以听到的**内容**完全一致，
只是出片那份多了一层空间感和动态处理。

后期链在做的事（按顺序）：

    firequalizer   低频切干净（60Hz 以下软切）+ 4kHz 以上渐进滚降
                   —— 这一条就是"模拟味"和"数码味"的分界线。
                      数字味的特征恰恰是 20Hz–20kHz 平直。
    equalizer      50Hz 抬一点（机箱）、180Hz 收一点（去浑）、3.2kHz 抬一点（临场）
    acompressor    压住动态，让"停住"和"炸开"的差距更明显
    aphaser        极慢的相位漂移 —— 磁带/显像管那种"不稳"
    aecho          几个稀疏的早期反射，做一个假房间
    stereowiden    展宽
    asoftclip      4 倍过采样的 tanh 软削波（这一步 ffmpeg 比自己写强：
                   过采样之后不会产生混叠）
    alimiter       -1dBFS 限幅
    loudnorm       统一到 -16 LUFS（视频平台的常用目标）

用法：

    python -m erranim.audiotrack --out out/demo.wav            # 渲染 + 后期
    python -m erranim.audiotrack --out out/demo.wav --no-polish # 只要干声
    python -m erranim.audiotrack --stats                       # 只看事件普查
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from . import audio as A
from .audio import _need_numpy

FFMPEG = os.environ.get("FFMPEG") or r"ffmpeg"

# ffmpeg 的参数单位很容易搞错，记在这里：
#   acompressor.threshold 是**线性**的（0.09 ≈ -20.9dB）
#   alimiter.limit        是**线性**的（0.891 = -1dB）
#   acrusher.bits         是整数
#   firequalizer 的 gain 是一段表达式，f 是频率
# 后期链：只做**静态**的模拟磁带/老旧机箱频响塑形与软磁饱和，
# 严禁使用 aphaser / flanger / 带反馈的 stereowiden / 强压缩呼吸，
# 否则会在恒定白/粉底噪上制造周期性的"呼——吸——背景扫描声"！
POLISH_CHAIN = (
    "firequalizer=gain="
    "'if(lt(f,40),-60,if(lt(f,65),-6*(65-f)/25,if(lt(f,2400),0,-14*(f-2400)/10000)))'"
    ":delay=0.05:accuracy=10:zero_phase=1,"
    "equalizer=f=50:width_type=o:width=1.1:g=2.0,"
    "equalizer=f=180:width_type=o:width=1.0:g=-2.5,"
    "equalizer=f=1100:width_type=o:width=1.2:g=1.5,"
    "asoftclip=type=tanh:threshold=0.82:output=0.95:param=1.3:oversample=4,"
    "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=120:asc=1:asc_level=0.6,"
    "loudnorm=I=-16:LRA=11:TP=-1.0:print_format=summary"
)


def build_schedule(args):
    """复刻 player 的场景装配，保证音轨和画面出自同一套参数。"""
    from . import player as P
    sc = P.build(args)
    from . import scenes as S
    return S.schedule(sc), S.total_duration(sc)


def render(sched, total: float, sr: int = A.SR, seed: int = 0,
           bed_level: float = 1.0, warnings: bool = True, step: float = 1 / 120.0,
           progress: bool = True):
    """按时间轴一块一块地长出来。返回 ((N,2) float32, Director)。"""
    _need_numpy()
    from .director import Director
    m = A.Mixer(sr=sr, seed=seed, bed_level=bed_level, warnings=warnings, quiet=True)
    d = Director(sched, m)
    chunks = []
    t = 0.0
    last_report = 0.0
    while t < total:
        d.step(t)
        c = m.render_upto(t)
        if len(c):
            chunks.append(c)
        t += step
        if progress and t - last_report >= 15.0:
            last_report = t
            print("  ..%.0f/%.0f s" % (t, total), flush=True)
    d.step(total)
    c = m.render_upto(total)
    if len(c):
        chunks.append(c)
    out = np.concatenate(chunks) if chunks else np.zeros((0, 2), np.float32)
    return out, d


def polish(src: str, dst: str, ffmpeg: str = FFMPEG, quiet: bool = False) -> int:
    """跑一遍后期链。"""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error" if quiet else "warning",
           "-i", os.path.abspath(src), "-af", POLISH_CHAIN,
           "-ar", str(A.SR), "-c:a", "pcm_s16le", os.path.abspath(dst)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-2000:])
    return p.returncode


def main(argv=None) -> int:
    _need_numpy()
    from . import player as P
    ap = argparse.ArgumentParser(prog="python -m erranim.audiotrack",
                                 description="离线渲染整片音轨（噪声床 + 系统音效 + ffmpeg 后期）")
    ap.add_argument("--out", default="out/demo.wav", help="输出 wav")
    ap.add_argument("--no-polish", action="store_true", help="不做 ffmpeg 后期，只要干声")
    ap.add_argument("--keep-dry", default="", help="额外保留一份干声（给 A/B 对比）")
    ap.add_argument("--sr", type=int, default=A.SR, help="采样率")
    ap.add_argument("--bed-level", type=float, default=1.0, help="噪声床电平倍数")
    ap.add_argument("--stats", action="store_true", help="只做事件普查，不写文件")
    ap.add_argument("--ffmpeg", default=FFMPEG, help="ffmpeg 路径")
    # 和 player 相同的场景参数，保证音画同源
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--corpus", default="")
    ap.add_argument("--random", choices=("on", "off"), default="off")
    ap.add_argument("--no-jumpscare", action="store_true")
    ap.add_argument("--scare-text", default="")
    ap.add_argument("--scare-style", default="echo", choices=("echo", "solid", "outline"))
    args = ap.parse_args(argv)

    # 借用 player 的参数解析：音轨必须和画面用一模一样的场景参数
    pav = ["--headless", "--seed", str(args.seed if args.seed is not None else 20260924)]
    if args.corpus:
        pav += ["--corpus", args.corpus]
    pav += ["--random", args.random, "--scare-style", args.scare_style]
    if args.no_jumpscare:
        pav += ["--no-jumpscare"]
    if args.scare_text:
        pav += ["--scare-text", args.scare_text]
    pa = P.parse_args(pav)

    sched, total = build_schedule(pa)
    print("场景 %d 段，总长 %.1f 秒，目标 %d Hz" % (len(sched), total, args.sr))
    t0 = time.perf_counter()
    x, d = render(sched, total, sr=args.sr, seed=pa.seed, bed_level=args.bed_level,
                  progress=not args.stats)
    dt = time.perf_counter() - t0
    print("渲染完成：%.2f 秒音频，用时 %.1f 秒 CPU（%.2f 核）"
          % (len(x) / args.sr, dt, dt / max(1e-6, len(x) / args.sr)))

    top = sorted(d.counts.items(), key=lambda kv: -kv[1])
    print("事件普查：" + "  ".join("%s=%d" % kv for kv in top))
    print("床手势合计 %d 次" % (d.mixer.glitch_count if hasattr(d, "mixer") else 0))
    if args.stats:
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    if args.keep_dry:
        dry = args.keep_dry
    elif args.no_polish:
        dry = args.out
    else:
        dry = os.path.splitext(args.out)[0] + "_dry.wav"
    A.write_wav(dry, x, args.sr)
    print("干声 → %s" % dry)
    if args.no_polish:
        return 0
    rc = polish(dry, args.out, ffmpeg=args.ffmpeg)
    print("后期 → %s  (ffmpeg rc=%d)" % (args.out, rc))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
