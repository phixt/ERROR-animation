"""噪声引擎：**一条恒定噪声** + 不同节奏的打断。

## 这一版的声音设计

用户最后一轮的要求把整套东西收窄成了一句话：

    一个几乎恒定的白噪声，不同的故障只是**暂停的方式**略有区别
    （比如骤停爆音，或者停顿一下、放一下、再卡一下、再正常）

所以这一版**没有扫频、没有滤波器扫、没有降位深、没有梳状延迟**。
整片的声音只有一层：一条电平恒定的噪声。所谓"故障音"只是这条噪声被
**打断的节奏**不同：

    恒定噪声 ──► [门] ──► 底噪电平 ──► 输出
                  ▲
                  └── 每个故障 = 一串 (时长, 门开度, 爆音量) 段

  * 门开度 < 1 = 噪声被压下去 / 掐掉（这就是"暂停"）
  * 门开度 > 1 = 噪声被"放一下"（回来的时候比正常响一点）
  * 爆音量 = 段首那一下的"啪"（骤停爆音 / 回来那一下）

门是**所有活跃故障的乘积**，所以两个故障叠在一起只会切得更深，不会互相调制。

## 为什么不要扫频

底噪的职责是"在那儿"。它会扫频的时候，人就一直在等它扫回来 —— 那是主角的
行为。取消之后它才真的成了背景，而**打断**才成了唯一的表达手段：你注意到的
不是噪声本身，而是它什么时候停、停多久、怎么回来。

## 噪声的循环周期

四个噪声缓冲的长度取四个互质的素数秒（41 / 43 / 53 / 59），合起来几小时才
重合一次。单个缓冲之间靠 0.25 秒交叉淡化接回开头，所以接缝听不出来。
"""

from __future__ import annotations

import math
import zlib

import numpy as np

from . import dsp

SR = 48000
SUB = 64                # 控制参数每 64 个样本更新一次（1.3ms）—— 再粗就会听到台阶


# --------------------------------------------------------------------------
# 噪声源
# --------------------------------------------------------------------------


class Loop:
    """一段可循环的噪声缓冲。左右用不同长度，合起来的周期长到听不出来。"""

    def __init__(self, buf: np.ndarray):
        self.buf = buf
        self.n = len(buf)
        self.pos = 0

    def take(self, n: int) -> np.ndarray:
        if self.n == 0:
            return np.zeros(n, np.float32)
        if self.pos + n <= self.n:
            out = self.buf[self.pos:self.pos + n]
        else:
            k = self.n - self.pos
            out = np.concatenate([self.buf[self.pos:], self.buf[:n - k]])
        self.pos = (self.pos + n) % self.n
        return out


class NoiseSource:
    """一条立体声噪声。**所有声音都从这一条上取。**

    每块只 `take()` 一次，取到的同一批样本分给底噪和所有故障声部 ——
    这就是"对白噪声做处理"的字面意思：不是给每个音效单独生成噪声，
    而是对同一条噪声下手。

    四个缓冲的长度取四个互质的素数秒。合起来的循环周期是它们的最小公倍数
    —— 41×43×53×59 秒 ≈ 46 小时，所以在这片子里听不到任何重复。
    """

    #: 四个缓冲的长度（秒）。互质，所以叠加后的周期极长。
    LENS = (41.0, 43.0, 53.0, 59.0)

    def __init__(self, sr: int = SR, seed: int = 0):
        self.sr = sr
        rng = np.random.default_rng(zlib.crc32(("noise|%d" % seed).encode()))
        hl, hr, ll, lr = self.LENS
        # 两声道分开生成：完全一样的噪声在立体声里会缩成中间一个点。
        # alpha 取 0.7 而不是 1.0 —— 纯粉噪声的 -3dB/oct 在低频堆了太多能量，
        # 听感上是"闷"的；往上提 1dB/oct 才是磁带嘶声那种"沙"。
        self.hi_l = Loop(dsp.shaped_noise(int(sr * hl), 0.7, rng, rms=0.25, sr=sr))
        self.hi_r = Loop(dsp.shaped_noise(int(sr * hr), 0.7, rng, rms=0.25, sr=sr))
        self.lo_l = Loop(dsp.shaped_noise(int(sr * ll), 2.0, rng, hp=18.0, rms=0.30, sr=sr))
        self.lo_r = Loop(dsp.shaped_noise(int(sr * lr), 2.0, rng, hp=18.0, rms=0.30, sr=sr))

    def take(self, n: int) -> np.ndarray:
        """取 n 个样本，(n,2) float32。调一次，所有人共用。"""
        hl, hr = self.hi_l.take(n), self.hi_r.take(n)
        ll, lr = self.lo_l.take(n), self.lo_r.take(n)
        return np.stack([hl * 0.95 + ll * 0.11, hr * 0.88 + lr * 0.14], axis=1)


# --------------------------------------------------------------------------
# 底噪
# --------------------------------------------------------------------------

# 底色：机器通电、磁带空转、风扇在转。整片都在这上面，而且**恒定**。
IDLE = {
    "cut": 3600.0,      # 底噪的截止（固定，不扫）
    "res": 0.16,
    "shape": 0.20,
    "level": 0.085,     # 电平：低到"听得见但不抢戏"
    "hum": 0.085,
    "grain": 0.075,
}


class NoiseBed:
    """常驻底噪。电平很低、只做慢速滤波和轻微整形，永远不死。"""

    name = "bed"
    chokeable = False
    stereo = True
    uses_source = True

    def __init__(self, sr: int = SR, seed: int = 0, level: float = 1.0):
        self.sr = sr
        self.user_level = float(level)
        self.grng = np.random.default_rng(zlib.crc32(("grain|%d" % seed).encode()))
        self.t = 0.0
        self.fst = [(0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)]
        self.dcst = ((0.0, 0.0), (0.0, 0.0))
        self.hph = [0.0, 0.0, 0.0, 0.0]
        self.gph = 0.0
        self.gate = 1.0
        self.gate_held = 1.0
        self.duck = 1.0          # 外部压低（黑屏/压暗用），平滑后生效
        self.duck_sm = 1.0

    @property
    def finished(self) -> bool:
        return False

    def choke(self, fade_s: float = 0.008) -> None:
        pass

    def hold_gate(self, v: float) -> None:
        """外部强制按住的门（0 = 彻底掐掉）。用于"骤停"这种状态。"""
        self.gate_held = float(max(0.0, min(1.0, v)))

    def render(self, src: np.ndarray) -> np.ndarray:
        """处理已经取好的声源块，(n,2) → (n,2)。"""
        n = len(src)
        out = np.zeros((n, 2), np.float32)
        i = 0
        while i < n:
            k = min(SUB, n - i)
            out[i:i + k] = self._chunk(src[i:i + k], self.t + i / self.sr)
            i += k
        self.t += n / self.sr
        return out

    def _chunk(self, x: np.ndarray, t: float) -> np.ndarray:
        sr = self.sr
        n = len(x)
        # 噼啪/颗粒：磁带、静电。**单样本脉冲**，不是"沙" —— 这是底噪里
        # 唯一"活着"的东西（滤波器不扫了，电平也不呼吸了）。
        g = IDLE["grain"]
        if g > 0.01:
            x = x.copy()
            x[:, 0] += dsp.crackle(n, self.grng, 26.0 * g, 1.5 * g, sr)
            x[:, 1] += dsp.crackle(n, self.grng, 22.0 * g, 1.5 * g, sr)

        # 截止固定，**不扫**。底噪的职责是"在那儿"。
        fc = IDLE["cut"]
        yl, self.fst[0] = dsp.lowpass(x[:, 0], self.fst[0], fc, IDLE["res"], sr)
        yr, self.fst[1] = dsp.lowpass(x[:, 1], self.fst[1], fc, IDLE["res"], sr)
        st = np.stack([yl, yr], axis=1)

        sh = dsp.shape_k(IDLE["shape"])
        if sh > 0.02:
            st = np.stack([dsp.shape(st[:, 0], "soft", sh),
                           dsp.shape(st[:, 1], "soft", sh)], axis=1)

        h = IDLE["hum"]
        if h > 0.005:
            hum, self.hph = dsp.hum(n, self.hph, 50.0, sr)
            st[:, 0] += hum * h
            st[:, 1] += hum * h * 0.92

        # 门：外部"骤停"状态（自检/静默段用）
        gate = min(self.gate_held, 1.0)
        gs, self.gate = dsp.gate_smooth(np.full(n, gate, np.float32), self.gate,
                                        0.0020, 0.0050, sr)
        st *= gs[:, None]
        # 外部压低也要平滑，否则"压暗"的瞬间会有一声轻响
        self.duck_sm += 0.12 * (self.duck - self.duck_sm)
        st = st * np.float32(IDLE["level"] * self.user_level * self.duck_sm)
        st, self.dcst = dsp.dc_block(st, self.dcst)
        return st.astype(np.float32)



# --------------------------------------------------------------------------
# 故障 = 打断的方式
# --------------------------------------------------------------------------
# 每个故障就是一串 (时长秒, 门开度, 爆音量)。门开度作用在**同一条噪声**上：
#
#   1.0   正常
#   0.0   掐掉（这就是"暂停"）
#   0.4   压下去一截（半停）
#   1.3   放一下 —— 回来的时候比正常响一点
#
# 爆音量是段首那一下"啪"的大小（0 = 没有）。爆音用的是**同一条噪声**乘以
# 一个 3.5ms 的指数包络，所以它不是外挂音效，而是"这一刀切下去本身的声音"。
#
# 每串都以一个门开度 1.0 的短段收尾。这不是多余的：门是逐样本平滑的
# （0.4ms 斜边），如果最后一刀砍在 0 上、模式就结束了，平滑会被下一块的
# 默认值硬拽回 1，反而多出一次没设计的爆音。
PATTERNS = {
    # 一个极短的**突起**：底噪被顶一下。日志底噪、闪烁。
    "tick": dict(segs=[(0.014, 1.75, 0.45), (0.030, 1.0, 0.0)]),

    # 黄色日志：先亮 30ms 让提示音起振，再一刀压下去顿挫。
    "note": dict(segs=[(0.030, 1.10, 0.12), (0.055, 0.12, 0.25), (0.060, 1.0, 0.05)]),

    # 卡一下：很短的一次停顿。
    "skip": dict(segs=[(0.045, 0.0, 0.45), (0.040, 1.0, 0.10)], hold=0),

    # 红色日志：先亮 35ms 让蜂鸣器刚发声就被继电器连切两刀（响 → 骤停 → 冲高 → 再卡断 → 恢复）。
    "deny": dict(segs=[(0.035, 1.15, 0.20), (0.060, 0.0, 0.60), (0.050, 1.30, 0.30),
                       (0.045, 0.0, 0.35), (0.045, 1.0, 0.05)]),

    # 停顿一下、放一下、再卡一下、再正常 —— 用户原话就是这个节奏。
    "stutter": dict(segs=[(0.038, 0.0, 0.40), (0.052, 0.0, 0.0),
                          (0.062, 1.30, 0.35), (0.030, 0.0, 0.25),
                          (0.070, 1.0, 0.10)]),

    # 骤停爆音：一刀切到底（这一刀本身就是那声"啪"），停住，然后"哒"地回来。
    # hold=1 表示"停住"那一段会被故障时长顶掉 —— 黑屏 0.95 秒就停 0.95 秒。
    "halt": dict(segs=[(0.005, 0.0, 1.00), (0.150, 0.0, 0.0),
                       (0.030, 1.0, 0.45), (0.040, 1.0, 0.0)], hold=1),

    # 掉下去，再慢慢爬回来。压暗、停滞。
    "dropout": dict(segs=[(0.090, 0.0, 0.22), (0.130, 0.45, 0.0),
                          (0.170, 1.0, 0.06)], hold=0),

    # 快速开合：门不是关一次，是抖一阵。数字死亡、扫描线。
    "flicker": dict(kind="square", hz=26.0, dur=0.34, low=0.0, click=0.25),

    # 闪白 / 硬切 / 跳杀：先空 8ms，再"轰"回来，带低频冲击。
    "impact": dict(segs=[(0.008, 0.0, 0.0), (0.030, 1.0, 1.00),
                         (0.600, 1.0, 0.0)], sub=0.9),
}

# 爆音和低频冲击的绝对刻度。不压一下的话，爆音会比底噪高 25dB ——
# "啪"要听得见，但不该把后面那 9.5 秒的静默衬成笑话。
CLICK_SCALE = 0.40
SUB_SCALE = 0.30


class GlitchVoice:
    """一次"打断"。不产生声音，只产生**门**和**爆音**。

    接口是 `step(n, src) -> (门 (n,), 爆音 (n,2))`：
    门由混音器乘到共享噪声上（多个故障叠起来就是乘积），爆音加在门之后。
    """

    chokeable = False
    stereo = True

    def __init__(self, name: str, sr: int = SR, seed: int = 0, gain: float = 1.0,
                 hold: float = 0.0):
        spec = PATTERNS.get(name)
        if spec is None:
            raise KeyError(name)
        if "segs" not in spec:
            # 方波门：把它展开成一串等长的开关段，好让下面的逻辑统一处理
            segs = []
            half = 0.5 / float(spec["hz"])
            n = max(1, int(round(float(spec["dur"]) / half)))
            low = float(spec.get("low", 0.0))
            for i in range(n):
                segs.append((half, low if i % 2 == 0 else 1.0,
                             float(spec.get("click", 0.0)) if i == 0 else 0.0))
            spec = dict(spec, segs=segs)
        self.name = name
        self.spec = spec
        self.segs = list(spec["segs"])
        if hold > 0.02 and spec.get("hold") is not None:
            # 故障时长顶掉"停住"那一段：黑屏多久就停多久
            i = int(spec["hold"])
            self.segs[i] = (float(hold), self.segs[i][1], self.segs[i][2])
        self.sr = sr
        self.gain = float(gain)
        self.sub = float(spec.get("sub", 0.0))
        self.t = 0.0
        self.total = sum(s[0] for s in self.segs)
        self.prev_gate = 1.0
        self.gph = 0.0
        self.dead = False
        # 爆音的衰减时间常数：3.5ms 是"啪"和"闷响"的分界
        self.click_tau = 0.0035

    @property
    def finished(self) -> bool:
        return self.dead

    def choke(self, fade_s: float = 0.006) -> None:
        self.dead = True

    def step(self, n: int, src: np.ndarray):
        """返回 (门 (n,) float32, 爆音 (n,2) float32)。"""
        sr = self.sr
        t0 = self.t
        tt = t0 + np.arange(n, dtype=np.float64) / sr
        gate = np.ones(n, np.float32)
        env = np.zeros(n, np.float32)
        acc = 0.0
        for dur, g, c in self.segs:
            s, e = acc, acc + dur
            m = (tt >= s) & (tt < e)
            if m.any():
                gate[m] = g
                if c > 0.0:
                    env[m] += c * np.exp(-(tt[m] - s) / self.click_tau)
            acc = e
        self.t += n / sr
        if self.t >= self.total + 0.05:
            self.dead = True

        # 门要平滑：0.4ms 斜边。不光滑的话每次开关都会多出一个"直流台阶"声，
        # 那种"咔"和我们要的"啪"不是一回事。
        a = dsp.lp1_coef(1.0 / (2.0 * math.pi * 0.0004), sr)
        sm = np.empty(n, np.float32)
        prev = self.prev_gate
        for i in range(n):
            prev += a * (float(gate[i]) - prev)
            sm[i] = prev
        self.prev_gate = float(prev)

        extra = src * (env * self.gain * CLICK_SCALE)[:, None]
        if self.sub > 0.0:
            so, self.gph = dsp.osc(n, self.gph, 41.0, sr)
            so = so * np.exp(-np.arange(n, dtype=np.float32) / (sr * 0.20))
            extra = extra + so[:, None] * (self.sub * self.gain * SUB_SCALE)
        return sm, extra.astype(np.float32)


def voice_names() -> list:
    return sorted(PATTERNS)
