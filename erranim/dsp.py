"""DSP 原语：给噪声床用。

约定：全部按**块**处理，一次吃 n 个样本（n = Mixer 的 block，1024），
块与块之间靠调用方持有的 state 接上 —— 滤波器是有记忆的，状态断了就会"咔"。

这里只放数学，不放编排。所有函数都是纯函数：给定 (输入, 状态) 必然得到
(输出, 新状态)，不读全局、不碰文件、不看时间 —— 这样离线渲染和实时播放
走的是同一段代码，出片的音轨和终端听到的必然一致。

性能上的取舍：
  * 一阶低通写成 `itertools.accumulate` 的递推 —— 循环在 C 里跑，比自己
    写 for 快一个数量级。粉噪声的 7 级滤波器串起来也是靠它。
  * 唯一必须逐样本递推的是带共振的梯形滤波器：它的反馈是非线性的
    （tanh），输入依赖上一刻的输出，没法向量化。它只在共振量大的时候
    才上场（低共振走两级一阶的快路）。

这一版不再有扫频/梳状延迟/降位深那些原语了 —— 声音设计收窄成了
"一条恒定噪声 + 不同节奏的打断"，所以 dsp 里只留下底噪真正用到的东西。
"""

from __future__ import annotations

import math
from itertools import accumulate

import numpy as np

TAU = 2.0 * math.pi


def lp1_coef(fc: float, sr: int) -> float:
    """一阶低通系数：fc 处 -3dB。"""
    return float(1.0 - math.exp(-TAU * max(0.5, fc) / sr))


def lp1(x, y0: float, a: float):
    """一阶低通。y[n] = (1-a)·y[n-1] + a·x[n]。"""
    a = float(min(max(a, 1e-6), 1.0))
    b = 1.0 - a
    f = lambda acc, xi: b * acc + a * xi  # noqa: E731
    out = np.fromiter(accumulate(x, f, initial=float(y0)), np.float32, len(x) + 1)
    return out[1:], float(out[-1])


def ladder(x, st, g: float, k: float, makeup: bool = True):
    """四极点梯形低通（Moog 式）：一阶低通串四级 + tanh 非线性 + 反馈共振。

    为什么不用双二阶（biquad）：biquad 太干净。数字滤波器算出来的共振是
    数学上的尖峰，听感是"塑料"的；而这里每一级都有 tanh，共振扫过时会
    自己生出谐波，扫频有真实的"啾"声。噪声床要的"质感"就是从这来的。

    st: (y1, y2, y3, y4)；g: 每级系数；k: 反馈量（0..4.2，>4 自激）。
    """
    g = float(min(max(g, 1e-6), 0.92))
    k = float(min(max(k, 0.0), 4.4))
    y1, y2, y3, y4 = st
    n = len(x)
    out = np.empty(n, np.float32)
    tanh = math.tanh
    for i in range(n):
        u = tanh(float(x[i]) - k * y4)
        y1 += g * (u - y1)
        y2 += g * (y1 - y2)
        y3 += g * (y2 - y3)
        y4 += g * (y3 - y4)
        out[i] = y4
    if makeup:
        out *= 1.0 + 0.35 * k      # 反馈吃掉的那部分增益补回来
    return out, (y1, y2, y3, y4)


def lowpass(x, st, fc: float, res: float, sr: int):
    """按共振量自动选实现。

    共振小的时候用两级一阶（accumulate，快一个数量级）；共振大才上梯形
    滤波器。底色下共振只有 0.2，走的是快路 —— 而这时候的"非线性"由后面
    的整形级提供，不会因为省掉 tanh 就变干净。
    """
    if res < 0.35:
        # 两级一阶串起来，-3dB 点会掉到约 0.64·fc，这里补回来
        a = lp1_coef(fc * 1.55, sr)
        y, s1 = lp1(x, st[1], a)
        y, s2 = lp1(y, st[3], a)
        return y, (0.0, s1, 0.0, s2)
    g = 1.0 - math.exp(-TAU * max(8.0, fc) / sr)
    # 四级一阶在低切时衰减过快，这里把系数往上抬一点，让通带位置对得上
    return ladder(x, st, g * 1.35, res * 4.2)


# --------------------------------------------------------------------------
# 噪声源（预生成，避免每块都算）
# --------------------------------------------------------------------------


def shaped_noise(n: int, alpha: float, rng, hp: float = 8.0, sr: int = 48000,
                 rms: float = 0.25):
    """用 FFT 直接塑形噪声频谱：幅度按 f^(-alpha/2)。

    alpha=0 白噪声，1 粉噪声（-3dB/oct），2 布朗噪声（-6dB/oct）。
    比逐样本的滤波器便宜得多，而且频谱是想怎样就怎样。

    两个细节：
      * 8Hz 高通是必须的。布朗噪声在极低频的能量是发散的，不去掉就变成
        一条缓慢漂移的直流，扬声器看不见但会吃掉全部动态余量。
      * 归一到 **有效值** 而不是峰值。峰值归一的话，越"红"的噪声听起来
        越轻 —— 能量都藏在几个尖峰里。
    末尾 0.25s 交叉淡化接回开头，循环播放时听不出接缝。
    """
    m = 1 << int(math.ceil(math.log2(max(64, n + 1))))
    spec = rng.standard_normal(m // 2 + 1) + 1j * rng.standard_normal(m // 2 + 1)
    fr = np.fft.rfftfreq(m, 1.0 / sr)
    shape = np.zeros_like(fr)
    nz = fr > 0.0
    shape[nz] = fr[nz] ** (-alpha / 2.0)
    if hp > 0:
        shape *= (fr / (fr + hp)) ** 2
    shape[0] = 0.0
    x = np.fft.irfft(spec * shape, m).astype(np.float32)
    r = float(np.sqrt(np.mean(x * x)))
    if r > 0:
        x *= rms / r
    x = x[:n].copy()
    xf = min(n // 4, int(0.25 * sr))
    if xf > 8:
        w = np.linspace(0.0, 1.0, xf, dtype=np.float32)
        x[:xf] = x[:xf] * w + x[-xf:] * (1.0 - w)
        x = x[:-xf]
    return x


# --------------------------------------------------------------------------
# 波形处理
# --------------------------------------------------------------------------


def gate_smooth(target: np.ndarray, y0: float, atk: float, rel: float, sr: int):
    """把逐样本的门限包络再平滑一次（非对称：关得比开得快）。

    硬切会产生宽频"咔"。开关都必须有 3~10ms 的斜边 ——
    但"掐断"要的是干脆，所以关的斜率取得比开更陡。
    """
    a_atk = lp1_coef(1.0 / (TAU * max(1e-4, atk)), sr)
    a_rel = lp1_coef(1.0 / (TAU * max(1e-4, rel)), sr)
    y = y0
    out = np.empty(len(target), np.float32)
    for i in range(len(target)):
        t = float(target[i])
        a = a_atk if t > y else a_rel
        y += a * (t - y)
        out[i] = y
    return out, y


def crackle(n: int, rng, rate: float, amp: float, sr: int):
    """稀疏脉冲（噼啪/静电）：单位时间内的泊松事件。rng 是 numpy Generator。"""
    k = int(rng.poisson(rate * n / sr))
    out = np.zeros(n, np.float32)
    if k <= 0:
        return out
    idx = rng.integers(0, n, k)
    out[idx] = rng.uniform(-amp, amp, k).astype(np.float32)
    return out


def hum(n: int, ph: list, f0: float, sr: int, partials=(1.0, 2.0, 3.0, 5.0)):
    """工频嗡鸣：50Hz 及其谐波。电子设备"通电"的声音。"""
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, np.float32)
    for i, h in enumerate(partials):
        amp = 1.0 / (h ** 1.35)
        f = f0 * h * (1.0 + 0.004 * (i - 1))
        out += amp * np.sin(TAU * f * t + ph[i])
        ph[i] = (ph[i] + TAU * f * n / sr) % TAU
    return out, ph


def osc(n: int, ph: float, f: float, sr: int):
    """相位连续的振荡器。返回 (波形, 新相位)。"""
    t = np.arange(n, dtype=np.float32) / sr
    w = TAU * f
    out = np.sin(w * t + ph).astype(np.float32)
    return out, (ph + w * n / sr) % TAU


def rms(x) -> float:
    x = np.asarray(x, dtype=np.float32)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


# --------------------------------------------------------------------------
# 波形整形（质感的另一半）
# --------------------------------------------------------------------------
# 参考 strudel / SuperDough 的 waveshaper 表。关键在于它用**一个连续参数**
# 控制失真量，而且归一化的方式让 k 大时不会把电平一起顶上去：
#
#     k = 2*shape / (1-shape)        shape 0.15 -> k 0.35（几乎没有）
#                                    shape 0.90 -> k 18  （揉烂）
#
# 不同 kind 的谐波结构完全不同，这是"质感"的来源：
#   soft    对称 tanh，只有奇次谐波 —— 干净，像过载
#   scurve  软饱和，比 tanh 更"方"，中频更冲
#   diode   二极管削波，**偶次谐波** —— 变压器/电子管坏了的声音
#   asym    不对称，直流偏置引入偶次谐波 —— "坏掉的电源"
#   fold    波形折叠，折叠处产生大量尖锐边沿 —— 数字尖叫
#   cheb    切比雪夫多项式，金属感
# 模拟恐怖要的是 diode / asym / fold，不是 soft。

def shape_k(shape: float) -> float:
    """SuperDough 的 shape -> k 映射。shape 0..0.95。"""
    s = min(max(float(shape), 0.0), 0.95)
    return 2.0 * s / (1.0 - s)


def _squash(x):
    return x / (1.0 + x)


def sh_soft(x, k):
    return np.tanh(x * (1.0 + k))


def sh_scurve(x, k):
    return ((1.0 + k) * x) / (1.0 + k * np.abs(x))


def sh_hard(x, k):
    return np.clip((1.0 + k) * x, -1.0, 1.0)


def sh_fold(x, k):
    return 1.0 - np.abs(np.mod((1.0 + 0.5 * k) * x + 1.0, 4.0) - 2.0)


def sh_asym(x, k):
    """不对称削波：正负半周削的量不一样，于是生出偶次谐波。"""
    bias = 0.07 * _squash(math.log1p(k))
    return sh_soft(x + bias, 2.0 * k) - sh_soft(bias, 2.0 * k)


def sh_diode(x, k):
    g = 1.0 + 2.0 * k
    t = _squash(math.log1p(k))
    bias = 0.07 * t
    pos = sh_soft(x + bias, 2.0 * k)
    neg = sh_soft(-x + bias, 2.0 * k)
    sech = 1.0 / math.cosh(g * bias)
    denom = max(1e-8, 2.0 * g * sech * sech)
    return sh_soft((pos - neg) / denom, k)


SHAPERS = {
    "soft": sh_soft, "scurve": sh_scurve, "hard": sh_hard,
    "fold": sh_fold, "asym": sh_asym, "diode": sh_diode,
}


def shape(x, kind: str, k: float):
    fn = SHAPERS.get(kind)
    if fn is None or k <= 0.01:
        return x
    return fn(x, float(k)).astype(np.float32)


# --------------------------------------------------------------------------
# 谐振带通 / 梳状延迟
# --------------------------------------------------------------------------
# 这两个是"故障有身体"的关键。纯低通扫频听起来像"音量被拧小"，
# 而一个窄带谐振扫过去，听起来像**金属在受力** —— 因为能量集中在
# 一个会移动的窄峰上，峰的位置本身就是信息。


def dc_block(x, st, r: float = 0.995):
    """隔直流：y[n] = x[n] - x[n-1] + r·y[n-1]（约 38Hz 高通）。

    整形器（尤其是不对称那种）会注入直流。直流本身听不见，但它会吃掉
    动态余量，而且在门的开关边沿会"砰"一声。
    支持 (n,) 和 (n,2)：声道各留一份状态。
    """
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        out = np.empty(len(x), np.float32)
        px, py = st
        for i in range(len(x)):
            xi = float(x[i])
            y = xi - px + r * py
            px, py = xi, y
            out[i] = y
        return out, (px, py)
    ch = x.shape[1]
    if len(st) != ch or not isinstance(st[0], tuple):
        st = tuple((0.0, 0.0) for _ in range(ch))
    out = np.empty_like(x)
    new = []
    for c in range(ch):
        px, py = st[c]
        col = x[:, c]
        o = out[:, c]
        for i in range(len(col)):
            xi = float(col[i])
            y = xi - px + r * py
            px, py = xi, y
            o[i] = y
        new.append((px, py))
    return out, tuple(new)
