"""音频：一条不间断的噪声床 + 复用这台机器上真实的系统音效。

整体结构（改过两轮，这一版是最终形态）：

  **噪声床**（`bed.py`）—— 整片都在响的那层底噪，类似 BGM。
      机箱风扇、磁带嘶声、电源工频嗡鸣，混在一起，电平压得很低。
      **所有故障音都是对这条床的操作**，不是另起的音效：
      滤波器关下去、位深掉到 3bit、门"啪"地掐断、带宽塌成单声道。
      为什么要这样：故障是"从正在响的东西里长出来"的，比凭空一个音效真实。

  **系统音效**（`reuse` 引擎，默认）—— 日志行红/黄时触发。
      Windows Critical Stop / Exclamation，是这台机器上真实存在的声音。
      自己合成的两个正弦听着"不对味"，干脆复用。

  **坏掉的系统音**（`rot`）—— 把 Windows Background 反复碾碎：
      循环读入、降采样、降位深、丢帧。集体衰竭那段它一直在响，
      跳杀那一刻被掐断。音频和电脑一起坏掉。

三种音色之外的一切都是噪声床的手势：

    tick     底噪被瞬间提亮（日志底噪、闪烁）
    static   宽、亮、带降位深的沙（字符噪声、坏点）
    warp     塌成窄带 + 环形调制 + 立体声塌陷（行位移、同形异码）
    impact   先关门 7ms 再放的低频撞击（闪白、硬切、跳杀）
    hum      只剩一根低频在响（扫描线、停滞）
    cut      磁带机被拔电：门关得比开快得多
    stutter  门按 23Hz 开合（卡带抖动）
    crush    3bit + 18 倍采样保持（数字死亡）
    sweep    上行扫频（越来越坏）
    muffle   闷掉：带宽塌到 260Hz、电平掉一半（熄灭、压暗）

单独试听：

    python -m erranim.audio --list
    python -m erranim.audio --test bed          # 连续听一遍床和所有手势
    python -m erranim.audio --test error --repeat 5 --interval 0.55
    python -m erranim.audio --wav out/audio     # 每个手势导一份 wav，离线试听
    python -m erranim.audio --stats             # 打印峰值/有效值，不需要声卡
"""

from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import wave

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from .bed import PATTERNS, GlitchVoice, NoiseBed, NoiseSource

SR = 48000
BLOCK = 1024
FFPLAY = os.environ.get("FFPLAY") or shutil.which("ffplay") or r"ffplay"


def _need_numpy():
    if np is None:
        raise SystemExit("音效需要 numpy：python -m pip install numpy")


# --------------------------------------------------------------------------
# 音色
# --------------------------------------------------------------------------


class Voice:
    """一个发声单元。子类实现 render(n) -> float32 单声道块，以及 finished。"""

    name = "voice"
    chokeable = False

    def __init__(self, sr: int = SR, gain: float = 1.0, seed: int = 0):
        self.sr = sr
        self.gain = gain
        self.rng = random.Random(seed)
        self.nprng = None if np is None else np.random.default_rng(seed)
        self.t = 0.0
        self.fade = 1.0          # 抢占淡出系数
        self.fading = False
        self.dead = False

    def choke(self, fade_s: float = 0.008) -> None:
        """被新音抢占：快速淡出而不是硬切（硬切会爆音）。"""
        self.fading = True
        self.fade_step = 1.0 / max(1.0, fade_s * self.sr)

    def _apply_fade(self, out):
        if not self.fading:
            return out
        n = len(out)
        ramp = np.clip(1.0 - self.fade_step * (np.arange(n) + 1), 0.0, 1.0)
        out *= ramp * self.fade
        self.fade = float(ramp[-1]) if n else self.fade
        if self.fade <= 0.001:
            self.dead = True
        return out

    def render(self, n: int):  # pragma: no cover - 抽象
        raise NotImplementedError

    @property
    def finished(self) -> bool:
        return self.dead


class WarnVoice(Voice):
    """复古工业固件/主板警告蜂鸣（闷哑、窄带、带继电器吸合声与电压跌落）：
    完全摒弃现代 Windows 清脆和弦，模拟隔着厚重 CRT 机壳与老化磁带录下的压电蜂鸣器单音。"""

    name = "warn"
    chokeable = True
    DUR = 0.46

    def __init__(self, sr=SR, gain=1.0, seed=0, freq=285.0, sev=0.0):
        super().__init__(sr, gain, seed)
        self.f0 = freq * (1.0 - 0.06 * min(1.0, max(0.0, sev)))
        self.sev = min(1.0, max(0.0, sev))
        self.lp1 = 0.0
        self.lp2 = 0.0
        self.dc = (0.0, 0.0)

    def render(self, n):
        t = self.t + np.arange(n, dtype=np.float32) / self.sr
        self.t += n / self.sr
        d = self.DUR
        active = (t < d).astype(np.float32)

        # 1) 继电器机械触点闷响（前 14ms 低频阻尼脉冲，像机箱内部电磁铁吸合）
        relay_env = np.exp(-np.clip(t, 0, None) / 0.0045) * active
        relay = 0.45 * relay_env * np.sin(2 * math.pi * 88.0 * t)

        # 2) 老式主板压电蜂鸣器：非对称占空比方波（36% 占空比），随电容放电音高轻微下坠
        sag = 1.0 - 0.045 * np.clip(t / d, 0, 1) - 0.015 * self.sev * np.sin(2 * math.pi * 19.0 * t)
        f = self.f0 * sag
        ph = (np.cumsum(f) / self.sr) % 1.0
        pulse = np.where(ph < 0.36, 0.85, -0.55).astype(np.float32)
        # 叠一点 50Hz 电源纹波串扰，让蜂鸣声带真实的旧电路污浊感
        hum_mod = 1.0 + 0.14 * np.sin(2 * math.pi * 50.0 * t)

        atk = np.clip((t - 0.006) / 0.008, 0, 1)
        rel = np.exp(-np.clip(t - (d - 0.09), 0, None) / 0.032)
        env = atk * rel * (t >= 0.006) * active

        raw = (relay + 0.55 * pulse * hum_mod * env) * self.gain

        # 3) 8kHz 采样保持 + 6-bit 量化 + 二极管非对称过载
        decim = 6 + int(4 * self.sev)
        if len(raw) >= decim:
            held = np.repeat(raw[::decim], decim)[:n]
            if len(held) < n:
                held = np.pad(held, (0, n - len(held)), mode="edge")
            raw = held
        levels = max(10.0, 28.0 - 12.0 * self.sev)
        raw = np.round(raw * levels) / levels
        raw = np.tanh((raw + 0.06) * 2.4) - math.tanh(0.06 * 2.4)

        # 4) 两级陡峭低通（截止 ~980Hz）：彻底切掉刺耳高频，做出"隔着机箱与磁带"的闷哑感
        from . import dsp
        a = dsp.lp1_coef(980.0, self.sr)
        y, self.lp1 = dsp.lp1(raw, self.lp1, a)
        y, self.lp2 = dsp.lp1(y, self.lp2, a)
        y, self.dc = dsp.dc_block(y, self.dc, r=0.985)

        self.dead = self.t >= d
        return self._apply_fade((y * 0.52).astype(np.float32))


class ErrorVoice(Voice):
    """复古 BIOS / 工业固件致命错误音（两声低沉闷哑的硬件故障脉冲 + 继电器跳闸声）：
    模拟 90s 工控机/服务器主板在内存耗尽或看门狗超时时的双音故障报警，频带严格限制在 100Hz–1050Hz。"""

    name = "error"
    chokeable = True
    DUR = 0.72
    HIT2_AT = 0.22

    def __init__(self, sr=SR, gain=1.0, seed=0, base=212.0, sev=0.0):
        super().__init__(sr, gain, seed)
        self.sev = min(1.0, max(0.0, sev))
        self.base = base * (1.0 - 0.07 * self.sev)
        self.lp1 = 0.0
        self.lp2 = 0.0
        self.dc = (0.0, 0.0)

    def _pulse(self, local, freq, amp, dur):
        active = ((local >= 0.0) & (local < dur)).astype(np.float32)
        if not np.any(active):
            return np.zeros_like(local, dtype=np.float32)
        # 供电电压下坠：第二声比第一声更吃力
        sag = 1.0 - 0.055 * np.clip(local / max(1e-4, dur), 0, 1)
        ph = (np.cumsum(freq * sag) / self.sr) % 1.0
        # 窄占空比混合奇偶次谐波，模拟老化压电片/扬声器锥盆非线性
        wave = np.where(ph < 0.34, 0.90, -0.60).astype(np.float32)
        wave += 0.25 * np.sin(2 * math.pi * (freq * 0.5) * local)  # 八度下分频共振
        # 50Hz 工频调制
        ripple = 1.0 + (0.18 + 0.15 * self.sev) * np.sin(2 * math.pi * 50.0 * local)
        atk = np.clip(local / 0.005, 0, 1)
        rel = np.exp(-np.clip(local - (dur - 0.045), 0, None) / 0.022)
        # 继电器吸合瞬态（低频闷击，不含高频白噪）
        clunk = 0.55 * np.exp(-np.clip(local, 0, None) / 0.005) * np.sin(2 * math.pi * 74.0 * local)
        return amp * active * (wave * ripple * atk * rel + clunk)

    def render(self, n):
        t = self.t + np.arange(n, dtype=np.float32) / self.sr
        self.t += n / self.sr
        out = np.zeros(n, dtype=np.float32)
        # 第一声：212Hz 闷响
        out += self._pulse(t, self.base, 0.62, 0.19)
        # 第二声：掉到 156Hz（压抑的下行硬件故障音程，留足长度给故障门切割）
        out += self._pulse(t - self.HIT2_AT, self.base * 0.735, 0.58, 0.46)
        out *= (t < self.DUR) * self.gain

        # 采样率劣化 + 量化 + 二极管软饱和
        decim = 6 + int(6 * self.sev)
        if len(out) >= decim:
            held = np.repeat(out[::decim], decim)[:n]
            if len(held) < n:
                held = np.pad(held, (0, n - len(held)), mode="edge")
            out = held
        levels = max(8.0, 24.0 - 12.0 * self.sev)
        out = np.round(out * levels) / levels
        out = np.tanh((out + 0.08) * 2.6) - math.tanh(0.08 * 2.6)

        # 两级低通压在 1020Hz 以下，彻底消灭现代数码清脆感
        from . import dsp
        a = dsp.lp1_coef(1020.0 - 180.0 * self.sev, self.sr)
        y, self.lp1 = dsp.lp1(out, self.lp1, a)
        y, self.lp2 = dsp.lp1(y, self.lp2, a)
        y, self.dc = dsp.dc_block(y, self.dc, r=0.985)

        self.dead = self.t >= self.DUR
        return self._apply_fade((y * 0.58).astype(np.float32))


class RotVoice(Voice):
    """卡断坏掉：持续污染噪声，随时间越来越碎，可以一直响。"""

    name = "rot"
    chokeable = False

    def __init__(self, sr=SR, gain=1.0, seed=7, ramp=2.0):
        super().__init__(sr, gain, seed)
        self.ramp = ramp
        self.hold = 0.0
        self.phase = 0
        self.last_block = None
        self.stutter = 0
        self.dropout = 0
        self.lp = 0.0

    def _severity(self, t: float) -> float:
        """0..1，随时间推进恶化。"""
        return min(1.0, max(0.0, t / self.ramp))

    def render(self, n):
        s = self._severity(self.t)
        t = self.t + np.arange(n) / self.sr
        self.t += n / self.sr

        # 1) 降采样（采样保持）：保持长度随恶化程度增长 1 -> 24 个样本
        decim = max(1, int(1 + 23 * s))
        k = n // decim + 2
        vals = self.nprng.uniform(-1.0, 1.0, k)
        noise = np.repeat(vals, decim)
        off = self.phase % decim
        block = noise[off:off + n]
        if len(block) < n:
            block = np.pad(block, (0, n - len(block)), mode="edge")
        self.phase = (self.phase + n) % decim

        # 2) 降位深：量化台阶随恶化程度变粗
        levels = max(2.0, 64.0 * (1.0 - 0.92 * s))
        block = np.round(block * levels) / levels

        # 3) 低频轰鸣：一根慢慢升起的低频，像机箱在共振
        rumble_f = 38.0 + 26.0 * s
        rumble = 0.55 * np.sin(2 * math.pi * rumble_f * t) + 0.25 * np.sin(2 * math.pi * rumble_f * 1.5 * t)

        # 4) 丢帧 / 卡帧：坏掉的缓冲欠载
        if self.stutter > 0:
            self.stutter -= 1
            if self.last_block is not None and len(self.last_block) == n:
                block = self.last_block
        elif self.dropout > 0:
            self.dropout -= 1
            block = block * 0.05
        else:
            r = self.rng.random()
            if r < 0.010 * (0.25 + s):
                self.stutter = self.rng.randint(1, 3)
            elif r < 0.028 * (0.25 + s):
                self.dropout = self.rng.randint(1, 4)
        self.last_block = block.copy()

        # 5) 一点点低通，免得纯噪声太"白"太数码
        a = 0.55
        out = np.empty(n)
        prev = self.lp
        for i in range(0, n, 256):  # 分块递推，够用且快
            seg = block[i:i + 256]
            acc = np.empty(len(seg))
            for j, v in enumerate(seg):
                prev = prev + a * (v - prev)
                acc[j] = prev
            out[i:i + len(seg)] = acc
        self.lp = prev

        env = 0.30 + 0.70 * s
        mix = (0.62 * out + 0.38 * rumble) * env
        return self._apply_fade((0.34 * mix).astype(np.float32))


PATCHES = {
    "warn": WarnVoice,
    "error": ErrorVoice,
    "rot": RotVoice,
}


# --------------------------------------------------------------------------
# 复用系统经典音效
# --------------------------------------------------------------------------
# 自己合成的那套听下来"不对味"。经典错误音效的听感是有具体设计的：
#   Windows Exclamation   1.36s，两声轻提示（0.04s / 0.45s）—— 温和，正合"黄色警告"
#   Windows Critical Stop 0.90s，经典的两下"严重停止" —— 不安，正合"红色错误"
#   Windows Error         0.97s，平滑的下行两音
# 与其模仿，不如直接复用 —— 保真度 100%，而且是这台机器上真实存在的系统音。

MEDIA = os.environ.get("WINDIR", r"C:\Windows") + r"\Media"

# 音色 -> (文件名, 归一化后的增益)
SOUND_MAP = {
    "warn": ("Windows Exclamation.wav", 0.50),
    "error": ("Windows Critical Stop.wav", 0.60),
    "rot": ("Windows Background.wav", 0.55),
}

_SOUND_CACHE: dict = {}


def read_wav_mono(path: str):
    """读任意位深/声道的 wav，混成单声道 float32（-1..1）。"""
    with wave.open(path, "rb") as w:
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    if sw == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError("不支持的位深：%d" % sw)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def resample_linear(x, sr_from: int, sr_to: int):
    if sr_from == sr_to or len(x) == 0:
        return x
    n = int(len(x) * sr_to / sr_from)
    idx = np.linspace(0, len(x) - 1, n)
    i0 = np.floor(idx).astype(np.int64)
    i1 = np.minimum(i0 + 1, len(x) - 1)
    frac = (idx - i0).astype(np.float32)
    return (x[i0] * (1 - frac) + x[i1] * frac).astype(np.float32)


def load_sound(name: str, sr: int):
    """取某个音色对应的系统音效，重采样到混音器采样率并归一化。"""
    key = (name, sr)
    if key in _SOUND_CACHE:
        return _SOUND_CACHE[key]
    item = SOUND_MAP.get(name)
    if not item:
        _SOUND_CACHE[key] = None
        return None
    fn, gain = item
    path = os.path.join(MEDIA, fn)
    if not os.path.exists(path):
        _SOUND_CACHE[key] = None
        return None
    x, sr0 = read_wav_mono(path)
    x = resample_linear(x, sr0, sr)
    peak = float(np.max(np.abs(x))) or 1.0
    x = (x / peak * gain).astype(np.float32)
    _SOUND_CACHE[key] = x
    return x


class SampleVoice(Voice):
    """播一段系统音效。除了来源不同，抢占/淡出逻辑和合成音色完全一致。"""

    chokeable = True

    def __init__(self, name: str, sr: int = SR, gain: float = 1.0, seed: int = 0, **kw):
        super().__init__(sr, gain, seed)
        self.name = name
        self.data = load_sound(name, sr)
        self.pos = 0
        if self.data is None:
            self.dead = True

    def render(self, n):
        if self.data is None or self.dead:
            return np.zeros(n, dtype=np.float32)
        seg = self.data[self.pos:self.pos + n]
        self.pos += n
        if len(seg) < n:
            seg = np.pad(seg, (0, n - len(seg)))
            self.dead = True
        return self._apply_fade((seg * self.gain).astype(np.float32))


class RotSampleVoice(Voice):
    """把系统音效反复碾碎：循环读一段系统音，逐级降采样、降位深、丢帧。

    "音频连同电脑一起坏掉" —— 坏掉的素材最好是系统自己的声音，
    而不是白噪声。这里循环的是 Windows Background。
    """

    chokeable = False

    def __init__(self, sr: int = SR, gain: float = 1.0, seed: int = 7, ramp: float = 2.0, **kw):
        super().__init__(sr, gain, seed)
        self.name = "rot"
        self.src = load_sound("rot", sr)
        self.ramp = ramp
        self.pos = 0.0
        self.phase = 0
        self.lp = 0.0
        self.last_block = None
        self.stutter = 0
        self.dropout = 0

    def _severity(self, t: float) -> float:
        return min(1.0, max(0.0, t / self.ramp))

    def render(self, n):
        s = self._severity(self.t)
        t = self.t + np.arange(n) / self.sr
        self.t += n / self.sr
        if self.src is None or len(self.src) == 0:
            return np.zeros(n, dtype=np.float32)

        # 循环读取
        src = self.src
        idx = (np.arange(n) + self.pos).astype(np.int64) % len(src)
        block = src[idx].copy()
        self.pos = (self.pos + n) % len(src)

        # 降采样（采样保持）：保持长度随恶化程度增长
        decim = max(1, int(1 + 18 * s))
        if decim > 1:
            hold = block[::decim]
            block = np.repeat(hold, decim)[:n]
            if len(block) < n:
                block = np.pad(block, (0, n - len(block)), mode="edge")

        # 降位深
        levels = max(2.0, 40.0 * (1.0 - 0.9 * s))
        block = np.round(block * levels) / levels

        # 低频轰鸣：机箱在共振
        rumble_f = 38.0 + 26.0 * s
        rumble = 0.5 * np.sin(2 * math.pi * rumble_f * t) + 0.25 * np.sin(2 * math.pi * rumble_f * 1.5 * t)

        # 丢帧 / 卡帧
        if self.stutter > 0:
            self.stutter -= 1
            if self.last_block is not None and len(self.last_block) == n:
                block = self.last_block
        elif self.dropout > 0:
            self.dropout -= 1
            block = block * 0.05
        else:
            r = self.rng.random()
            if r < 0.012 * (0.25 + s):
                self.stutter = self.rng.randint(1, 3)
            elif r < 0.030 * (0.25 + s):
                self.dropout = self.rng.randint(1, 4)
        self.last_block = block.copy()

        # 一阶低通，压掉最刺耳的高频
        a = 0.5
        out = np.empty(n)
        prev = self.lp
        for i in range(0, n, 256):
            seg = block[i:i + 256]
            acc = np.empty(len(seg))
            for j, v in enumerate(seg):
                prev = prev + a * (v - prev)
                acc[j] = prev
            out[i:i + len(seg)] = acc
        self.lp = prev

        env = 0.45 + 0.55 * s
        mix = 0.72 * out + 0.28 * rumble
        return self._apply_fade((0.5 * env * mix * self.gain).astype(np.float32))


SAMPLE_PATCHES = {
    "warn": lambda sr, seed, **kw: SampleVoice("warn", sr, **kw),
    "error": lambda sr, seed, **kw: SampleVoice("error", sr, **kw),
    "rot": lambda sr, seed, **kw: RotSampleVoice(sr, seed=seed, **kw),
}




# --------------------------------------------------------------------------
# 画面故障 -> 打断的方式
# --------------------------------------------------------------------------
# 声音跟着**画面上的故障**走，不是跟着日志颜色走。
# 每个故障就是这条恒定噪声被"停"的一种节奏，见 bed.PATTERNS。

VOICE_FOR_GLITCH = {
    "char_noise": "stutter",
    "dead_pixels": "skip",
    "escape_literal": "tick",
    "row_flip": "skip",
    "row_shift": "stutter",
    "row_dup": "skip",
    "homoglyph": "dropout",
    "row_invert": "skip",
    "bright_rows": "tick",
    "scanlines": "dropout",   # 扫描线改用低频跌落，不用 26Hz flicker 免得像扫描蜂鸣
    "flash": "impact",
    "blackout": "halt",       # 黑屏 = 骤停（停多久由故障时长决定）
    "dim_all": "dropout",     # 压暗 = 掉下去再爬回来
    # 结构性 UI 崩坏与面板故障
    "border_melt": "stutter",
    "meter_overflow": "deny",
    "popup_cascade": "impact",
    "hsync_wave": "stutter",
    "hex_flood": "dropout",
    "panel_noise": "skip",
    "panel_corrupt": "tick",
    "panel_garbage": "stutter",
    "panel_invert": "skip",
    "panel_dim": "dropout",
}

# 红/黄警告改用**复古 BIOS / 工业固件蜂鸣器与继电器闷响**（WarnVoice / ErrorVoice），
# 彻底停用现代 Windows 11 的清脆系统提示音，且保持在独立总线上不干扰底噪。
WARNING_VOICES = {
    "error": ("BIOS_FAULT_BUZZER", 0.48),
    "warn": ("FIRMWARE_RELAY_BEEP", 0.42),
}


# --------------------------------------------------------------------------
# 混音器
# --------------------------------------------------------------------------


class Mixer:
    """三层，各自独立：

        噪声总线  恒定噪声 × 所有故障的门  +  爆音        → 自己限幅
        警告总线  Windows Critical Stop / Exclamation      → 自己限幅
        ────────────────────────────────────────────────────────────
        相加

    **各自限幅**很关键：上一版把噪声和音效一起送进同一个 `tanh`，于是每次
    红/黄警告一响，软限幅就把整条噪声一起压下去 —— 听起来像"底噪被吓了一跳"。
    现在警告再响也碰不到噪声，两者只在最后相加。
    """

    def __init__(self, sr: int = SR, block: int = BLOCK, gain: float = 0.9,
                 player: str = FFPLAY, quiet: bool = False,
                 bed: bool = True, bed_level: float = 1.0, seed: int = 0,
                 warnings: bool = True):
        _need_numpy()
        self.sr = sr
        self.block = block
        self.gain = gain
        self.player = player
        self.quiet = quiet
        self.warnings = bool(warnings)
        self.source = NoiseSource(sr=sr, seed=seed)
        self.bed = NoiseBed(sr=sr, seed=seed, level=bed_level) if bed else None
        self.voices: list = []
        self._lock = threading.Lock()
        self._proc = None
        self._thread = None
        self._running = False
        self._written = 0
        self._t0 = 0.0
        self.level = 0.0
        self.steals = 0
        self._offline_pos = 0
        self._seq = 0
        self._cut = False            # 骤停：整条音频被掐死（静默段）
        self._cut_fade = 1.0
        self.glitch_count = 0
        self.last_noise = np.zeros((0, 2), np.float32)   # 自检用
        self.last_warn = np.zeros((0, 2), np.float32)

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        if not os.path.exists(self.player):
            raise SystemExit("找不到 ffplay：%s（用 --player 指定，或设 FFPLAY）" % self.player)
        cmd = [
            self.player, "-hide_banner", "-loglevel", "quiet" if self.quiet else "error",
            "-nodisp", "-autoexit", "-fflags", "nobuffer", "-flags", "low_delay",
            # 注意：ffplay 没有 -ac，声道数要用 -ch_layout
            "-f", "s16le", "-ar", str(self.sr), "-ch_layout", "stereo", "-i", "-",
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._running = True
        self._t0 = time.perf_counter()
        self._written = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=1.0)
            except Exception:
                self._proc.kill()
        self._proc = None
        self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()

    # -- 触发 ----------------------------------------------------------
    def now(self) -> float:
        return self._written / self.sr if self._running else self._offline_pos / self.sr

    def spawn(self, voice: str, gain: float = 1.0, hold: float = 0.0):
        """起一次打断。"""
        self._seq += 1
        v = GlitchVoice(voice, sr=self.sr, seed=self._seq, gain=gain, hold=hold)
        with self._lock:
            self.voices.append(v)
        return v

    def glitch(self, name: str, dur: float = 0.0) -> None:
        """画面故障 → 打断。name 可以是故障名，也可以是模式名本身。"""
        target = VOICE_FOR_GLITCH.get(name, name)
        if target in PATTERNS:
            self.spawn(target, hold=dur)
            self.glitch_count += 1

    def hold_bed(self, seconds: float, until: float | None = None) -> None:
        """把噪声按住一段时间（冻结这种状态用它）。"""
        end = (until if until is not None else self.now()) + seconds
        self._gate_at = max(getattr(self, "_gate_at", 0.0), end)

    def hard_cut(self, on: bool) -> None:
        """骤停 / 解除。整个音频被掐死（静默段用）。"""
        self._cut = bool(on)
        self._cut_fade = 1.0
        with self._lock:
            self.voices.clear()

    def kill(self, name: str | None = None) -> None:
        with self._lock:
            if name is None:
                self.voices.clear()
            else:
                self.voices = [v for v in self.voices
                               if getattr(v, "name", "") != name]

    def stop_all(self, fade_s: float = 0.02) -> None:
        with self._lock:
            self.voices.clear()

    def trigger(self, name: str, **kw):
        """红/黄警告：挂一个复古 BIOS / 工业固件蜂鸣声（独立总线，不进底噪的门）。"""
        if not self.warnings:
            return None
        item = WARNING_VOICES.get(name)
        if item is None:
            return None
        _label, g = item
        sev = float(kw.pop("sev", 0.0))
        seed = int(kw.pop("seed", self._seq))
        gain = g * float(kw.pop("gain", 1.0))
        cls = ErrorVoice if name == "error" else WarnVoice
        v = cls(sr=self.sr, gain=gain, seed=seed, sev=sev)
        with self._lock:
            # 同一时刻只留一个蜂鸣器发声，旧的快速淡出抢占，避免叠成一团
            for old in self.voices:
                if getattr(old, "chokeable", False) and not isinstance(old, GlitchVoice):
                    old.choke(0.012)
            self.voices.append(v)
        return v

    # -- 内部 ----------------------------------------------------------
    def mix(self, n: int):
        """混一块，返回 (n,2) float32。"""
        _need_numpy()
        src = self.source.take(n)

        gate = None
        extra = None
        warn = np.zeros((n, 2), np.float32)
        with self._lock:
            alive = []
            for v in self.voices:
                try:
                    if isinstance(v, GlitchVoice):
                        g, e = v.step(n, src)
                        gate = g if gate is None else gate * g
                        extra = e if extra is None else extra + e
                    else:
                        warn += np.repeat(v.render(n)[:, None], 2, axis=1)
                except Exception:
                    continue
                if not v.finished:
                    alive.append(v)
            self.voices = alive

        hold_active = self.now() < getattr(self, '_gate_at', 0.0)
        if self.bed is not None:
            self.bed.hold_gate(0.0 if hold_active else 1.0)
        gated = src if gate is None else src * gate[:, None]
        # 底噪那一级才是"电平"。没有底噪（自检用）时噪声就是静的 ——
        # 否则裸声源会直接从总线漏出去。
        noise = (self.bed.render(gated) if self.bed is not None
                 else np.zeros((n, 2), np.float32))
        if extra is not None:
            noise = noise + extra

        # 提示音同样吃故障效果与骤停门控（但反过来绝不污染 last_noise，保持噪声总线隔离）：
        # 1) 骤停/冻结门（hold_bed）与故障切刀门（gate）同步掐断/切割提示音；
        # 2) 当故障门正在剧烈动作时，对提示音施加额外的采样保持破碎、噪声互调与波形折叠。
        if np.any(warn != 0.0):
            if hold_active:
                warn = warn * (self.bed.gate if self.bed is not None else 0.0)
            if gate is not None:
                g_int = float(np.mean(np.abs(gate - 1.0)))
                if g_int > 0.02:
                    step = max(2, int(3 + 22 * min(1.0, g_int)))
                    if len(warn) >= step:
                        held = np.repeat(warn[::step], step, axis=0)[:n]
                        if len(held) < n:
                            held = np.pad(held, ((0, n - len(held)), (0, 0)), mode="edge")
                        warn = held
                    # 故障期间与底噪声源发生脏互调 + 刀口爆音串扰
                    warn = warn * (0.72 + 0.48 * src)
                    if extra is not None:
                        warn = warn + extra * 0.28
                warn = warn * gate[:, None]

        # 两条总线各自限幅 —— 警告再响也碰不到噪声
        noise = np.tanh(noise * 1.15)
        warn = np.tanh(warn * 1.20)
        self.last_noise = noise
        self.last_warn = warn
        out = noise + warn
        if self._cut:
            if self._cut_fade > 0.0:
                out = out * np.linspace(self._cut_fade, 0.0, n, dtype=np.float32)[:, None]
                self._cut_fade = 0.0
            else:
                out = out * 0.0
        return (out * self.gain).astype(np.float32)

    def _loop(self) -> None:
        n = self.block
        while self._running:
            block = self.mix(n)
            self.level = float(np.max(np.abs(block))) if len(block) else 0.0
            pcm = np.clip(block * 32767.0, -32768, 32767).astype("<i2")
            try:
                self._proc.stdin.write(pcm.tobytes())
                self._proc.stdin.flush()
            except Exception:
                break
            self._written += n
            target = self._t0 + self._written / self.sr
            sleep = target - time.perf_counter()
            if sleep > 0.001:
                time.sleep(min(sleep, 0.05))

    # -- 离线渲染 ------------------------------------------------------
    def render_upto(self, t: float):
        """离线：渲染到绝对时刻 t（秒），返回这中间新增的样本。"""
        _need_numpy()
        want = int(round(t * self.sr))
        if want <= self._offline_pos:
            return np.zeros((0, 2), dtype=np.float32)
        chunks = []
        while self._offline_pos < want:
            n = min(self.block, want - self._offline_pos)
            chunks.append(self.mix(n).copy())
            self._offline_pos += n
        return np.concatenate(chunks) if chunks else np.zeros((0, 2), dtype=np.float32)

    def render_to_array(self, seconds: float):
        return self.render_upto(self._offline_pos / self.sr + seconds)


# --------------------------------------------------------------------------
# 导出 / 试听
# --------------------------------------------------------------------------


def write_wav(path: str, samples, sr: int = SR) -> None:
    """写 16bit 立体声 wav。samples 可以是 (N,) 单声道，也可以是 (N,2)。"""
    _need_numpy()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 1:
        x = np.repeat(x[:, None], 2, axis=1)
    pcm = np.clip(x * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def render_voice(name: str, seconds: float = 2.0, at: float = 1.0, seed: int = 3,
                 bed_level: float = 1.0, hold: float = 0.0, warnings: bool = True):
    """离线渲染一个模式：先 at 秒的恒定噪声本身，再打断，方便 A/B。"""
    _need_numpy()
    m = Mixer(seed=seed, bed_level=bed_level, warnings=warnings)
    out = [m.render_to_array(at)]
    m.spawn(name, hold=hold)
    out.append(m.render_to_array(max(0.05, seconds - at)))
    return np.concatenate(out)


def render_bed(seconds: float, seed: int = 3, bed_level: float = 1.0,
               warnings: bool = True):
    _need_numpy()
    m = Mixer(seed=seed, bed_level=bed_level, warnings=warnings)
    return m.render_to_array(seconds)


def stats_of(x, sr: int = SR) -> dict:
    _need_numpy()
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if x.size == 0:
        return dict(seconds=0.0, peak=0.0, rms=0.0, centroid=0.0)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    cen = float((spec * freqs).sum() / max(1e-9, spec.sum()))
    return dict(seconds=len(x) / sr, peak=float(np.max(np.abs(x))),
                rms=float(np.sqrt((x ** 2).mean())), centroid=cen)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

VOICE_DOC = {
    "tick": "一个极短的突起：底噪被顶一下 —— 日志底噪、闪烁",
    "note": "轻轻压一下再回来 —— 黄色日志行（只在 --engine noise 下用）",
    "skip": "卡一下（45ms）—— 坏点、行复制",
    "deny": "停 → 放 → 再卡，三下像继电器 —— 红色日志行",
    "stutter": "停顿一下、放一下、再卡一下、再正常 —— 字符噪声、行位移",
    "halt": "骤停爆音：一刀切到底，停住，再哒地回来 —— 黑屏",
    "dropout": "掉下去再慢慢爬回来 —— 压暗、停滞",
    "flicker": "门快速开合 26Hz，抖一阵 —— 反白、扫描线",
    "impact": "先空 8ms，再轰回来（带 41Hz 冲击）—— 闪白、跳杀",
}


def _live(name: str, args) -> int:
    m = Mixer(gain=args.gain, player=args.player or FFPLAY,
              bed_level=args.bed_level, warnings=not args.no_warnings)
    m.start()
    try:
        if name == "bed":
            print("恒定噪声本身（整片都在这上面）：听 4 秒…")
            time.sleep(4.0)
            print("现在一个个模式过一遍。每个都是「噪声 + 一次打断」，注意噪声本身不该变：")
            for v in voice_names():
                print("  → %-8s %s" % (v, VOICE_DOC.get(v, "")))
                m.spawn(v)
                time.sleep(1.4)
            print("结束。")
            return 0
        if name == "bus":
            print("总线隔离：连发 6 次红警告（Windows Critical Stop），盯住噪声有没有被压。")
            for _ in range(6):
                m.trigger("error")
                time.sleep(0.32)
            time.sleep(1.6)
            return 0
        if name in PATTERNS:
            print("%s：先听 1.2 秒噪声本身，再打断。" % name)
            time.sleep(1.2)
            m.spawn(name, hold=args.seconds if args.seconds > 0 and name == "halt" else 0.0)
            time.sleep(max(1.0, args.seconds))
            return 0
        if name in ("warn", "error"):
            for _ in range(max(1, args.repeat)):
                m.trigger(name)
                time.sleep(args.interval)
            time.sleep(1.2)
            return 0
        print("没有这个模式：%s" % name)
        return 2
    except KeyboardInterrupt:
        print("\n中断。")
        return 0
    finally:
        m.stop()


def voice_names() -> list:
    return sorted(PATTERNS)


def do_check() -> int:
    """不需要声卡的自检。"""
    _need_numpy()
    fails = []

    def ck(name, cond, extra=""):
        print("%s %s%s" % ("  ok  " if cond else " FAIL ", name, ("  — " + extra) if extra else ""))
        if not cond:
            fails.append(name)

    # 1) 底噪恒定、低、是立体声
    idle = Mixer(seed=5, warnings=False).render_to_array(3.0)
    s = stats_of(idle)
    ck("恒定噪声常驻有声而且不抢戏（有效值 %.4f，峰值 %.3f）" % (s["rms"], s["peak"]),
       0.003 < s["rms"] < 0.06 and s["peak"] < 0.30)
    diff = float(np.mean(np.abs(idle[:, 0] - idle[:, 1])))
    ck("噪声是立体声（左右平均差 %.4f）" % diff, diff > 0.001)

    # 2) 取消扫频：分段的谱重心必须几乎不变
    seg = len(idle) // 6
    cens = [stats_of(idle[i * seg:(i + 1) * seg])["centroid"] for i in range(6)]
    spread = (max(cens) - min(cens)) / max(1.0, sum(cens) / len(cens))
    ck("没有扫频：6 段的谱重心几乎不变（%s，波动 %.1f%%）"
       % (" ".join("%.0f" % v for v in cens), spread * 100), spread < 0.06)

    # 3) 每个模式都改变噪声，且不削顶 / 不产生 NaN
    bad = []
    for v in voice_names():
        y = render_voice(v, 2.2, warnings=False)
        if not np.all(np.isfinite(y)):
            bad.append("%s(NaN)" % v)
        elif float(np.max(np.abs(y))) > 0.999:
            bad.append("%s(削顶 %.2f)" % (v, float(np.max(np.abs(y)))))
    ck("全部 %d 个模式都不削顶" % len(voice_names()), not bad, "；".join(bad))

    # 4) 每个模式确实**打断**了噪声：门低位期间的能量必须明显低于常态
    quiet = []
    for v in voice_names():
        m = Mixer(seed=6, warnings=False)
        m.render_to_array(1.0)
        vv = m.spawn(v, hold=0.0)
        base = float(np.sqrt((m.render_to_array(0.005) ** 2).mean()))
        lowest = 1e9
        for _ in range(18):
            lowest = min(lowest, float(np.sqrt((m.render_to_array(0.02) ** 2).mean())))
        quiet.append((v, base, lowest))
    silent = [v for v, b, lo in quiet if lo < b * 0.55]
    ck("多数模式确实把噪声按下去了（%d/%d）" % (len(silent), len(quiet)),
       len(silent) >= len(quiet) - 2,
       "；".join("%s %.4f→%.4f" % t for t in quiet if t[0] not in silent))

    # 5) **关键**：红/黄警告必须独立于噪声
    def noise_bus(m, seconds=1.0):
        out = []
        for _ in range(int(seconds * m.sr / m.block) + 1):
            m.mix(m.block)
            out.append(m.last_noise.copy())
        return np.concatenate(out)

    a = Mixer(seed=7, warnings=True)
    ref = noise_bus(a)
    b = Mixer(seed=7, warnings=True)
    for _ in range(6):
        b.trigger("error")
        b.trigger("warn")
    got = noise_bus(b)
    dev = float(np.max(np.abs(got - ref)))
    ck("连发 6 次红黄警告，噪声那一层逐样本不变（最大偏差 %.6f）" % dev, dev < 1e-6)

    # 6) 警告总线自己有声，而且不受噪声打断影响
    c = Mixer(seed=8, warnings=True, bed=False)
    c.trigger("error")
    w = c.render_to_array(1.0)
    ck("红警告总线有输出（峰值 %.3f）" % float(np.max(np.abs(w))),
       float(np.max(np.abs(w))) > 0.05)
    d = Mixer(seed=8, warnings=False, bed=False)
    d.trigger("error")
    ck("--no-warnings 之后警告总线是死的",
       float(np.max(np.abs(d.render_to_array(0.6)))) == 0.0)

    # 7) 骤停之后是**死的静音**，而且连打断也放不出来
    e = Mixer(seed=9)
    e.render_to_array(0.3)
    e.hard_cut(True)
    e.render_to_array(0.1)
    e.glitch("stutter")
    e.trigger("error")
    z = e.render_to_array(0.5)
    ck("骤停之后整条音频都是死的（峰值 %.5f）" % float(np.max(np.abs(z))),
       float(np.max(np.abs(z))) < 1e-6)

    # 8) 两个模式叠在一起是门的**乘积**，不是相加
    f = Mixer(seed=11, bed=False)
    f.spawn("halt")
    f.spawn("halt")
    both = f.render_to_array(0.4)
    ck("两个打断叠起来是乘积（仍然不削顶，峰值 %.3f）" % float(np.max(np.abs(both))),
       float(np.max(np.abs(both))) < 0.999)

    # 9) 黑屏的停顿时长跟着故障时长走
    g1 = GlitchVoice("halt", sr=SR, hold=0.0)
    g2 = GlitchVoice("halt", sr=SR, hold=0.9)
    ck("骤停的停顿时长跟故障时长走（%.2fs → %.2fs）" % (g1.total, g2.total),
       g2.total > g1.total + 0.6)

    # 10) 提示音必须受故障效果与骤停门控影响（不能在黑屏/卡顿期间独自干响）
    m_dry = Mixer(seed=12, warnings=True, bed=False)
    m_dry.trigger("error")
    w_dry = m_dry.render_to_array(0.35)
    m_cut = Mixer(seed=12, warnings=True, bed=False)
    m_cut.trigger("error")
    m_cut.spawn("halt", hold=0.30)
    w_cut = m_cut.render_to_array(0.35)
    rms_dry = float(np.sqrt(np.mean(w_dry[4000:14000] ** 2)))
    rms_cut = float(np.sqrt(np.mean(w_cut[4000:14000] ** 2)))
    ck("提示音受故障与骤停门控影响（正常有效值 %.4f → 骤停期 %.4f）" % (rms_dry, rms_cut),
       rms_dry > 0.03 and rms_cut < rms_dry * 0.15)

    print()
    if fails:
        print("失败 %d 项：%s" % (len(fails), "；".join(fails)))
        return 1
    print("音频自检全部通过。")
    return 0


def main(argv=None) -> int:
    _need_numpy()
    ap = argparse.ArgumentParser(prog="python -m erranim.audio",
                                 description="恒定噪声 + 不同节奏的打断（+ 独立的红黄警告）")
    ap.add_argument("--list", action="store_true", help="列出模式与映射")
    ap.add_argument("--check", action="store_true", help="不需要声卡的自检")
    ap.add_argument("--no-warnings", action="store_true", help="关掉红/黄系统警告音")
    ap.add_argument("--test", default="", help="试听：bed / bus / 模式名 / warn / error")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--interval", type=float, default=0.55)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--gain", type=float, default=0.9)
    ap.add_argument("--bed-level", type=float, default=1.0)
    ap.add_argument("--player", default=FFPLAY, help="ffplay 路径")
    ap.add_argument("--wav", default="", help="导出目录")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        print("整片只有一层声音：**一条电平恒定的噪声**。")
        print("  " + " + ".join("%.0f 秒" % v for v in NoiseSource.LENS)
              + " 四个互质长度的缓冲 → 周期约 46 小时，听不到重复")
        print("  没有扫频、没有滤波器扫、没有降位深、没有梳状延迟。")
        print()
        print("所谓「故障音」只是这条噪声被**打断的节奏**不同：")
        for v in voice_names():
            print("  %-8s %s" % (v, VOICE_DOC.get(v, "")))
        print()
        print("画面故障 -> 打断方式：")
        for k in sorted(VOICE_FOR_GLITCH):
            print("  %-16s %s" % (k, VOICE_FOR_GLITCH[k]))
        print()
        print("红/黄警告（独立总线，不进噪声的门）：")
        for k, (fn, g) in WARNING_VOICES.items():
            p = os.path.join(MEDIA, fn)
            print("  %-6s %-32s %s  增益 %.2f" % (k, fn, "存在" if os.path.exists(p) else "缺失", g))
        return 0

    if args.check:
        return do_check()

    if args.stats:
        print("%-10s %8s %8s %8s %10s" % ("模式", "时长s", "峰值", "有效值", "谱重心Hz"))
        for v in ["（恒定噪声）"] + voice_names():
            y = render_bed(3.0, warnings=False) if v == "（恒定噪声）" \
                else render_voice(v, 2.2, warnings=False)
            s = stats_of(y)
            print("%-10s %8.2f %8.3f %8.3f %10.0f"
                  % (v, s["seconds"], s["peak"], s["rms"], s["centroid"]))
        return 0

    if args.wav:
        os.makedirs(args.wav, exist_ok=True)
        jobs = [("bed_idle", lambda: render_bed(5.0, warnings=False))]
        for v in voice_names():
            jobs.append(("voice_%s" % v,
                         (lambda vv: lambda: render_voice(vv, 2.6, warnings=False))(v)))
        if not args.no_warnings:
            for k in ("warn", "error"):
                def _one(kk=k):
                    mm = Mixer(bed=False, warnings=True)
                    mm.trigger(kk)
                    return mm.render_to_array(1.6)
                jobs.append(("warn_%s" % k, _one))
        for name, fn in jobs:
            p = os.path.join(args.wav, name + ".wav")
            write_wav(p, fn())
            print("→ %s" % p)
        return 0

    if not args.test:
        ap.print_help()
        return 0
    return _live(args.test, args)


if __name__ == "__main__":
    raise SystemExit(main())
