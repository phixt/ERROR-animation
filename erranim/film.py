"""A 线出片：把 player 落盘的逻辑帧渲染成视频。

同一份帧数据既驱动终端也驱动这里，所以终端版和视频版永远一致。
逻辑帧 -> numpy 合成 -> 原始 RGB 直接管道喂给 ffmpeg（按真实停留时长补帧）。
不落中间图、不用 concat 时长，因此视频时间轴与逻辑时间轴严格一致。

用法：
    python -m erranim.player --headless --record out/demo.jsonl
    python -m erranim.film --record out/demo.jsonl --out out/demo.mp4 --crt
    python -m erranim.film --record out/demo.jsonl --png 24,50,92      # 只出预览图
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import render as R

FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or r"ffmpeg"

MONO_BOLD = [
    r"C:\Windows\Fonts\consolab.ttf",
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]
MONO_REGULAR = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
CJK_CANDIDATES = [
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

# --------------------------------------------------------------------------
# 模拟恐怖后期链
# --------------------------------------------------------------------------
# 之前 brightness 是负的、暗角又重，屏幕边缘的字被压得看不清，恐怖的点就传不到。
# 现在整体提亮、暗角大幅减弱，并补上三样"扫描"相关的动态：
#   1) 隔行扫描线：相位按 2Hz 周期性翻动（确定性，不是随机抖）
#   2) 逐行扫描的滚动带：一条缓慢下移的暗带 + 前沿亮线
#      —— 它决定成片的帧率下限，所以走得很慢（约 20 秒一趟）
#   3) 偶现色带：一次性生成的事件表，固定复用，颜色保守
# 其余（晕开/色差/颗粒）都压得很轻。

BAND_COLORS = ["0x00ffc8", "0xff2b9c", "0xff5555", "0xffb000", "0x55ddff"]

# 实心块元素直接按几何矩形画，不走字体 —— 字体里的 █ 未必填满格子，
# 相邻格子之间会留出细缝；跳杀的大字要求"没有空隙"。
BLOCK_RECTS = {
    "█": (0.0, 0.0, 1.0, 1.0),
    "▀": (0.0, 0.0, 1.0, 0.5),
    "▄": (0.0, 0.5, 1.0, 1.0),
    "▌": (0.0, 0.0, 0.5, 1.0),
    "▐": (0.5, 0.0, 1.0, 1.0),
    "▏": (0.0, 0.0, 0.25, 1.0),
    "▕": (0.75, 0.0, 1.0, 1.0),
}

# 线字符与阴影块也必须几何绘制：字体里的 ─│╔═╗ 在等宽格子里并不接续，
# 走字体会断成虚线，只有自己按像素几何画才连得上、才像真实固件/SCADA 屏幕。
BOX_CHARS = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬╱╲·"
SHADE_CHARS = {"░": 0.22, "▒": 0.48, "▓": 0.76}

# (left, right, up, down) -> 0=无, 1=单线, 2=双线
_BOX_SPEC: dict[str, tuple[int, int, int, int]] = {
    "─": (1, 1, 0, 0), "│": (0, 0, 1, 1),
    "┌": (0, 1, 0, 1), "┐": (1, 0, 0, 1), "└": (0, 1, 1, 0), "┘": (1, 0, 1, 0),
    "├": (0, 1, 1, 1), "┤": (1, 0, 1, 1), "┬": (1, 1, 0, 1), "┴": (1, 1, 1, 0),
    "┼": (1, 1, 1, 1),
    "═": (2, 2, 0, 0), "║": (0, 0, 2, 2),
    "╔": (0, 2, 0, 2), "╗": (2, 0, 0, 2), "╚": (0, 2, 2, 0), "╝": (2, 0, 2, 0),
    "╠": (0, 2, 2, 2), "╣": (2, 0, 2, 2), "╦": (2, 2, 0, 2), "╩": (2, 2, 2, 0),
    "╬": (2, 2, 2, 2),
}


class AnalogHorrorEngine:
    """像素级模拟恐怖失真引擎（NumPy 矢量化，终端预览与视频成片共用）：

    1. NTSC 复合视频色度右向拖尾（Chroma Smear）与动态 RGB 色差分离
    2. CRT 荧光屏过曝辉光（Phosphor Halation / Bloom）
    3. 跨帧 P 帧动态矢量撕裂与宏块残留（Stateful Datamoshing）
    4. VHS 行同步失锁撕裂（H-Sync Jitter & Tearing）
    5. 纵向滚屏失锁与消隐带（V-Sync Roll & VBI Bar）
    6. 磁带掉磁雪花横纹（Tape Dropouts & Snow Burst）
    7. 底部磁头切换噪波带（VHS Head-Switching Noise）
    8. 预计算 LUT 的 CRT 曲面屏桶形畸变（Barrel Curvature）、扫描线与圆角暗角遮罩
    """

    def __init__(self, fw: int, fh: int, seed: int = 0, duration: float = 108.7):
        self.fw = fw
        self.fh = fh
        self.seed = seed
        self.duration = max(1.0, duration)
        self.prev_frame: np.ndarray | None = None
        self._build_crt_lut()

    def _build_crt_lut(self) -> None:
        h, w = self.fh, self.fw
        yy, xx = np.meshgrid(
            np.linspace(-1.0, 1.0, h, dtype=np.float32),
            np.linspace(-1.0, 1.0, w, dtype=np.float32),
            indexing="ij",
        )
        r2 = xx * xx + yy * yy
        # 桶形曲面畸变（中心微凸，四角向内收）
        k1, k2 = 0.055, 0.018
        scale = 1.0 + k1 * r2 + k2 * (r2 * r2)
        sx = ((xx * scale + 1.0) * 0.5 * (w - 1)).astype(np.int32)
        sy = ((yy * scale + 1.0) * 0.5 * (h - 1)).astype(np.int32)
        oob = (sx < 0) | (sx >= w) | (sy < 0) | (sy >= h)
        sx = np.clip(sx, 0, w - 1)
        sy = np.clip(sy, 0, h - 1)
        self.barrel_idx = (sy * w + sx).reshape(-1)

        # 圆角显像管边框遮罩 + 扫描线 + 暗角，一次性合成到 (H, W, 1) float32
        corner = (np.abs(xx) ** 6 + np.abs(yy) ** 6)
        bezel = np.clip(1.0 - np.maximum(0.0, corner - 0.92) * 14.0, 0.0, 1.0)
        bezel[oob] = 0.0
        vig = np.clip(1.04 - 0.24 * r2, 0.62, 1.04)
        scan = np.where((np.arange(h) % 2 == 0)[:, None], 1.04, 0.78).astype(np.float32)
        self.crt_mask = (bezel * vig * scan)[:, :, None].astype(np.float32)

    def severity_at(self, t: float) -> float:
        """按全局时间轴返回模拟信号恶化强度 0..1。"""
        # 静默段（95.0..104.5s）：画面维持高压极简冷寂，只保留底层的微弱磁带颤动
        if 95.0 <= t < 104.5:
            return 0.14
        if t >= 104.5:
            return 0.95
        base = min(0.88, 0.12 + 0.72 * ((t / 95.0) ** 1.45))
        # 在关键崩溃节点（超时冻结、身份丢失、输入抑制、全面雪崩）制造信号尖峰
        spikes = (
            (16.0, 1.2, 0.25),
            (32.5, 1.5, 0.35),
            (41.5, 2.2, 0.55),  # timeout 冻结期
            (61.5, 2.5, 0.50),  # identity 崩溃
            (72.5, 2.0, 0.60),  # abandon 输入锁定
            (81.0, 4.0, 0.75),  # cascade 前段
            (89.0, 5.5, 0.92),  # cascade 末段全面失锁
        )
        boost = 0.0
        for tc, width, amp in spikes:
            d = abs(t - tc)
            if d < width:
                boost = max(boost, amp * (1.0 - d / width))
        return min(1.0, base + boost)

    def process(self, frame: np.ndarray, t: float, glitch_progs=None,
                glitch_t0: float = 0.0, scare=None) -> np.ndarray:
        """对单帧执行完整模拟恐怖像素后期，返回新 (H,W,3) uint8。"""
        h, w = self.fh, self.fw
        out = frame.copy()
        sev = self.severity_at(t)
        q = int(round(t * 15.0))
        rng = random.Random(self.seed ^ (q * 2654435761 & 0xFFFFFFFF))

        # 1) 跳杀窗口的宏块损坏 + 矢量大字
        if glitch_progs and t >= glitch_t0:
            want = -1
            for i in range(len(glitch_progs)):
                if t >= glitch_t0 + 0.45 + i * 0.50:
                    want = i
            if want >= 0:
                apply_glitch(out, glitch_progs[want])
        if scare is not None and t >= glitch_t0:
            lt = t - glitch_t0
            if 0.0 <= lt < scare.CUT_END:
                scare.render_pixels(out, lt)

        # 2) 跨帧 P 帧动态矢量撕裂（Datamoshing）：在重故障窗口保留上一帧宏块并沿运动矢量拖拽
        if self.prev_frame is not None and sev >= 0.42 and not (95.0 <= t < 104.5):
            n_blocks = int((sev - 0.38) * 28)
            bs = max(24, w // 22)
            for _ in range(n_blocks):
                bx = rng.randrange(0, max(bs, w - bs * 2), bs)
                by = rng.randrange(0, max(bs, h - bs * 2), bs)
                bw = min(w - bx, bs * rng.randint(1, 3))
                bh = min(h - by, bs * rng.randint(1, 2))
                mvx = rng.randint(-24, 24)
                mvy = rng.randint(-12, 12)
                sx = max(0, min(w - bw, bx + mvx))
                sy = max(0, min(h - bh, by + mvy))
                blk = self.prev_frame[sy:sy + bh, sx:sx + bw]
                if rng.random() < 0.35:
                    # 色度通道锁定，只残余高反差红色边沿
                    out[by:by + bh, bx:bx + bw, 0] = np.maximum(out[by:by + bh, bx:bx + bw, 0], blk[:, :, 0])
                    out[by:by + bh, bx:bx + bw, 1] = blk[:, :, 1] // 2
                else:
                    out[by:by + bh, bx:bx + bw] = blk

        # 3) NTSC 色度拖尾（红/琥珀色向右渗色）与动态 RGB 色差分离
        shift_px = 1 + int(sev * 3.5) + (2 if rng.random() < sev * 0.4 else 0)
        r_ch = out[:, :, 0].astype(np.int32)
        g_ch = out[:, :, 1].astype(np.int32)
        b_ch = out[:, :, 2].astype(np.int32)
        # 红色与琥珀色高亮向右拖尾（复合视频低色度带宽特征）
        smear = (np.roll(r_ch, 3, axis=1) * 4 + np.roll(r_ch, 7, axis=1) * 2) // 10
        out[:, :, 0] = np.clip(np.maximum(np.roll(r_ch, shift_px, axis=1), smear), 0, 255).astype(np.uint8)
        out[:, :, 2] = np.roll(b_ch, -shift_px, axis=1).astype(np.uint8)

        # 4) CRT 荧光辉光（4 倍降采样快速盒式模糊叠加）
        small = out[::4, ::4].astype(np.int32)
        bloom = (small + np.roll(small, 1, axis=1) + np.roll(small, -1, axis=1) +
                 np.roll(small, 1, axis=0)) // 4
        bloom_up = np.repeat(np.repeat(bloom, 4, axis=0), 4, axis=1)[:h, :w]
        out = np.clip(out.astype(np.int32) + (bloom_up * int(18 + 20 * sev)) // 100, 0, 255).astype(np.uint8)

        # 5) VHS 行同步撕裂（H-Sync Jitter & Horizontal Tearing）
        n_tears = 1 + int(sev * 9)
        for _ in range(n_tears):
            ty = rng.randrange(0, max(1, h - 24))
            th = rng.randrange(2, max(4, int(6 + 26 * sev)))
            dx = int(rng.uniform(-1.0, 1.0) * (6 + 65 * (sev ** 1.4)))
            if dx != 0:
                out[ty:ty + th] = np.roll(out[ty:ty + th], dx, axis=1)
                if abs(dx) > 18 and rng.random() < 0.5:
                    # 行同步丢失前沿亮线
                    out[ty:ty + 1, :, 0] = np.clip(out[ty:ty + 1, :, 0].astype(np.int32) + 95, 0, 255).astype(np.uint8)

        # 6) 纵向滚屏失锁（V-Sync Roll & VBI 消隐带）：在极端失锁时刻画面上下翻滚
        if sev >= 0.72 and rng.random() < 0.42:
            v_roll = int((math.sin(t * 7.3) * 0.5 + 0.5) * h * 0.38) + rng.randint(18, 60)
            out = np.roll(out, v_roll, axis=0)
            vbi_y = v_roll % h
            vbi_h = min(14, h - vbi_y)
            if vbi_h > 2:
                out[vbi_y:vbi_y + vbi_h] = 10
                # VBI VITC 时间码白点
                for vx in range(16, w - 16, 18):
                    if rng.random() < 0.65:
                        out[vbi_y + vbi_h // 2:vbi_y + vbi_h // 2 + 2, vx:vx + 8] = 210

        # 7) 磁带掉磁横纹（Tape Dropouts）与雪花噪波（Analog Snow）
        if rng.random() < 0.35 + 0.55 * sev:
            for _ in range(1 + int(sev * 4)):
                dy = rng.randrange(8, h - 24)
                dh = rng.randint(1, 2)
                dx0 = rng.randrange(0, max(1, w - 80))
                dw = rng.randint(35, min(w - dx0, int(120 + 260 * sev)))
                out[dy:dy + dh, dx0:dx0 + dw] = rng.randint(175, 240)
                if dx0 + dw + 12 < w:
                    out[dy:dy + dh, dx0 + dw:dx0 + dw + 12] //= 3

        # 8) 底部 VHS 磁头切换噪波带（Head-Switching Noise Bar）
        if not (scare is not None and (t - glitch_t0) >= scare.CUT_END):
            hs_h = 14 + (q % 5)
            hs_y = h - hs_h
            for row_i in range(hs_y, h):
                skew = int(14 + 22 * math.sin(row_i * 0.7 + t * 31.0)) + rng.randint(-6, 6)
                out[row_i] = np.roll(out[row_i], skew, axis=1)
            npr = np.random.default_rng(self.seed ^ (q * 1103515245 & 0xFFFFFFFF))
            snow = npr.integers(30, 195, size=(3, w), dtype=np.uint8)
            out[hs_y:hs_y + 3, :, 0] = np.maximum(out[hs_y:hs_y + 3, :, 0], snow)
            out[hs_y:hs_y + 3, :, 1] = np.maximum(out[hs_y:hs_y + 3, :, 1], snow // 2)
            out[hs_y:hs_y + 3, :, 2] = np.maximum(out[hs_y:hs_y + 3, :, 2], snow)

        self.prev_frame = out.copy()

        # 9) CRT 曲面屏桶形畸变 + 隔行扫描线 + 显像管圆角暗角遮罩
        warped = out.reshape(-1, 3)[self.barrel_idx].reshape(h, w, 3)
        warped = np.clip(warped.astype(np.float32) * self.crt_mask, 0, 255).astype(np.uint8)
        return warped


def crt_chain(duration: float, frame_h: int, seed: int = 0,
              bands: int = 7, bright: float = 0.045, final_scale: bool = True) -> str:
    rng = random.Random(seed ^ 0xBADC0DE)
    parts: list[str] = []

    # 1) 隔行扫描线 + 周期性相位翻动
    parts.append("drawgrid=w=iw:h=2:t=1:c=black@0.16:y='mod(floor(t*2),2)'")

    # 2) 逐行扫描的滚动带（暗带 + 前沿亮线），约 20 秒一趟
    roll_expr = "mod(t*%.2f,ih+150)-150" % max(8.0, frame_h / 20.0)
    parts.append("drawbox=x=0:y='%s':w=iw:h=110:c=black@0.13:t=fill" % roll_expr)
    parts.append("drawbox=x=0:y='%s':w=iw:h=3:c=white@0.05:t=fill" % roll_expr)

    # 3) 偶现色带：生成一次，之后每帧只是复用同一张事件表
    for _ in range(max(0, bands)):
        t0 = rng.uniform(4.0, max(6.0, duration - 3.0))
        dur = rng.uniform(0.08, 0.34)
        y = rng.randrange(0, max(1, frame_h - 60))
        h = rng.randrange(6, 44)
        col = rng.choice(BAND_COLORS)
        alpha = rng.uniform(0.06, 0.15)
        parts.append(
            "drawbox=x=0:y=%d:w=iw:h=%d:color=%s@%.2f:t=fill:enable='between(t,%.2f,%.2f)'"
            % (y, h, col, alpha, t0, t0 + dur)
        )

    # 4) 色差（很便宜，保留）
    parts.append("chromashift=cbh=1:crh=-1")

    # 5) 整体提亮（关键：原来 brightness 为负 + 重暗角 = 边缘字看不清）
    parts.append("eq=contrast=1.02:saturation=0.95:brightness=%.3f:gamma=1.06" % bright)

    # 6) 颗粒。
    #    只用 allf=u（静态图案）而不是 t+u（逐帧变化）：
    #    逐帧噪点既费 CPU，又会让每一帧都不可预测，x264 完全压不动。
    parts.append("noise=alls=5:allf=u")

    # 7) 暗角：大幅减弱，边缘留得住字
    parts.append("vignette=a=PI/7")
    if final_scale:
        parts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    return ",".join(parts)


# --------------------------------------------------------------------------
# 编码器：默认走 GPU
# --------------------------------------------------------------------------
# 之前用 libx264 preset=medium，整条链的像素运算全压在 CPU 上，散热扛不住。
# 这台机器是 AMD，h264_amf 实测 1180x704 能跑到实时两倍以上。

ENCODER_PREFERENCE = ("h264_amf", "h264_qsv", "h264_nvenc", "libx264")

# 每个编码家族里，硬件优先、软件兜底。
# AV1 对噪点友好得多：同样的颗粒感，AV1 需要的码率明显低于 H.264。
CODEC_CHAIN = {
    "h264": ("h264_amf", "h264_qsv", "h264_nvenc", "libx264"),
    "hevc": ("hevc_amf", "hevc_qsv", "hevc_nvenc", "libx265"),
    "av1": ("av1_amf", "av1_qsv", "av1_nvenc", "libsvtav1"),
}


def list_encoders() -> str:
    """把 ffmpeg -encoders 的输出抓到临时文件再读（避免依赖管道）。"""
    tmp = os.path.join(tempfile.gettempdir(), "erranim-encoders.txt")
    try:
        with open(tmp, "w", encoding="utf-8", errors="replace") as f:
            subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                           stdout=f, stderr=subprocess.STDOUT, timeout=30)
        with open(tmp, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def pick_encoder(prefer: str = "", codec: str = "h264") -> str:
    if prefer:
        return prefer
    txt = list_encoders()
    for name in CODEC_CHAIN.get(codec, CODEC_CHAIN["h264"]):
        if name in txt:
            return name
    return "libx264"


def encoder_args(name: str, quality: int) -> list[str]:
    """quality 沿用 crf 的直觉（越小越好），按各家编码器换算。

    注意量程不同：H.264/HEVC 的 QP 是 0–51，AV1 的 QP 是 0–255。
    一开始给 AV1 也传 20，等于快无损，码率直接翻倍。
    """
    if name.endswith("_amf"):
        if name.startswith("av1"):
            qp = max(20, min(255, int(quality) * 3 + 18))
        else:
            qp = max(10, min(45, int(quality) + 2))
        return ["-c:v", name, "-quality", "quality", "-rc", "cqp",
                "-qp_i", str(qp), "-qp_p", str(qp + 4), "-qp_b", str(qp + 8)]
    if name.endswith("_qsv"):
        return ["-c:v", name, "-global_quality", str(max(10, min(50, quality + 3))),
                "-look_ahead", "0"]
    if name.endswith("_nvenc"):
        return ["-c:v", name, "-preset", "p5", "-rc", "vbr",
                "-cq", str(max(10, min(50, quality + 3))), "-b:v", "0"]
    if name == "libx265":
        # 颗粒感内容用 grain 调优，能省不少码率
        return ["-c:v", "libx265", "-preset", "medium", "-crf", str(quality),
                "-tune", "grain", "-tag:v", "hvc1"]
    if name == "libsvtav1":
        return ["-c:v", "libsvtav1", "-preset", "6", "-crf", str(quality),
                "-svtav1-params", "tune=0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(quality)]


# --------------------------------------------------------------------------
# 解码失败式的块状损坏（只在视频里做）
# --------------------------------------------------------------------------
# 关键：真实的解码损坏**不是纯色块**。宏块丢的是交流系数、只剩直流分量，
# 于是每一块变成"该块自己的平均色"被填平 —— 看起来像被抹平的一块图像，
# 而不是一个绿色/品红的色块。再叠上运动矢量出错（整块从别处搬来）
# 和切片位移。整体接近单色，最多带一点偏色。
#
# 说清楚：这和 CRT 质感其实不相符 —— 但正是这种"不对"，才像机器真的坏了。
#
# 实现不走 ffmpeg 的 overlay：三路 `-loop 1` PNG 实测 10 秒成片多吃 11 秒 CPU
# （整链从 2.3 核涨到 6.1 核）。这里直接在 numpy 帧上按 op 列表改，
# 只有跳杀窗口里那几十个逻辑帧会真的算。

# 偶尔的极端值：解码器给出的"垃圾块"，但也要接近黑白而不是饱和色
GLITCH_COLORS = [
    (0x08, 0x0A, 0x0D),   # 黑
    (0xE8, 0xE8, 0xE8),   # 白
    (0x2A, 0x22, 0x2E),   # 近黑偏紫
    (0xC8, 0xC2, 0xCE),   # 近白偏紫
]


def build_glitch_programs(w: int, h: int, count: int, seed: int, outdir: str = "") -> list:
    """生成 count 级"解码失败"程序，逐级累加（后一级包含前面的）。"""
    rng = random.Random(seed ^ 0x9E3779B9)
    bs = max(24, w // 20)          # 宏块尺寸：参考图里的块相当大
    ops: list = []
    levels = []
    for level in range(count):
        # 1) DC 填平 / 运动矢量错位 —— 这两样才是主体
        for _ in range(5 + level * 9):
            bx = rng.randrange(0, max(bs, w - bs), bs)
            by = rng.randrange(0, max(bs, h - bs), bs)
            bw = min(w - bx, bs * rng.randint(1, 3))
            bh = min(h - by, bs * rng.randint(1, 3))
            if bw <= 0 or bh <= 0:
                continue
            r = rng.random()
            if r < 0.55:
                ops.append(("dc", by, by + bh, bx, bx + bw))
            elif r < 0.88:
                sx = rng.randrange(0, max(1, w - bw))
                sy = rng.randrange(0, max(1, h - bh))
                ops.append(("copy", by, by + bh, bx, bx + bw, sy, sx))
            else:
                ops.append(("fill", by, by + bh, bx, bx + bw, rng.choice(GLITCH_COLORS), 1.0))
        # 2) 横向切片位移：像丢帧错位
        for _ in range(1 + level):
            sy = rng.randrange(0, max(1, h - 4))
            sh = rng.randrange(3, max(4, h // 5))
            ops.append(("shift", sy, min(h, sy + sh), rng.randint(-w // 5, w // 5)))
        # 3) 整体轻微去饱和 + 偏紫：真实损坏的画面会褪色
        ops.append(("tint", 0.22 * (level + 1) / count))
        levels.append(list(ops))

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        with open(os.path.join(outdir, "glitch_ops.txt"), "w", encoding="utf-8") as f:
            for i, prog in enumerate(levels):
                f.write("# level %d: %d ops\n" % (i, len(prog)))
                for op in prog[:40]:
                    f.write("  %s\n" % (op,))
    return levels


def apply_glitch(frame, prog) -> None:
    """在 RGB 帧上原地执行一串解码失败操作。"""
    for op in prog:
        kind = op[0]
        if kind == "dc":
            # 只保留直流分量：整块填成它自己的平均色
            _, y0, y1, x0, x1 = op
            region = frame[y0:y1, x0:x1]
            if region.size:
                frame[y0:y1, x0:x1] = region.reshape(-1, 3).mean(axis=0)
        elif kind == "fill":
            _, y0, y1, x0, x1, col, alpha = op
            if alpha >= 0.999:
                frame[y0:y1, x0:x1, 0] = col[0]
                frame[y0:y1, x0:x1, 1] = col[1]
                frame[y0:y1, x0:x1, 2] = col[2]
            else:
                for c in range(3):
                    seg = frame[y0:y1, x0:x1, c]
                    frame[y0:y1, x0:x1, c] = seg * (1 - alpha) + col[c] * alpha
        elif kind == "copy":
            _, y0, y1, x0, x1, sy, sx = op
            bh, bw = y1 - y0, x1 - x0
            frame[y0:y1, x0:x1] = frame[sy:sy + bh, sx:sx + bw]
        elif kind == "shift":
            _, y0, y1, dx = op
            frame[y0:y1] = np.roll(frame[y0:y1], dx, axis=1)
        elif kind == "darken":
            _, y0, y1, f = op
            frame[y0:y1] = frame[y0:y1] * f
        elif kind == "tint":
            # 往灰和紫偏一点：真实损坏的画面会褪色
            _, k = op
            g = frame.mean(axis=2, keepdims=True)
            frame[:] = frame * (1 - k) + (g * 0.72 + g * 0.28) * k


def is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _load_font(candidates, size):
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=0), p
            except Exception:
                continue
    raise SystemExit("找不到可用字体，试过：%s" % candidates)


def load_record(path: str):
    frames = []
    meta = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if "meta" in o:
                meta = o["meta"]
                continue
            frames.append((float(o["t"]), o["rows"]))
    if not frames:
        raise SystemExit("录制文件里没有帧：%s" % path)
    return meta, frames


class Atlas:
    """按 (字符, 样式) 缓存格子位图。用 numpy 合成，比逐字绘制快一个数量级。"""

    def __init__(self, font_size: int):
        self.mono, self.mono_path = _load_font(MONO_REGULAR, font_size)
        self.mono_b = _load_font(MONO_BOLD, font_size)[0]
        self.cjk, self.cjk_path = _load_font(CJK_CANDIDATES, font_size)
        a, d = self.mono.getmetrics()
        ca, cd = self.cjk.getmetrics()
        self.ascent = max(a, ca)
        descent = max(d, cd)
        self.cell_w = max(4, int(round(self.mono.getlength("M"))))
        self.cell_h = max(6, int(round(self.cell_w * 2.15)))
        pad = max(0, (self.cell_h - (self.ascent + descent)) // 2)
        self.baseline = pad + self.ascent
        self.cache: dict[tuple[str, int], np.ndarray] = {}

    def get(self, ch: str, style: int) -> np.ndarray:
        key = (ch, style)
        img = self.cache.get(key)
        if img is not None:
            return img
        st = R.PALETTE[style] if 0 <= style < len(R.PALETTE) else R.PALETTE[0]
        fg, bg = st.film
        wide = is_wide(ch)
        w = self.cell_w * (2 if wide else 1)
        box = Image.new("RGB", (w, self.cell_h), bg)
        d = ImageDraw.Draw(box)
        rect = BLOCK_RECTS.get(ch)
        if rect is not None:
            x0, y0, x1, y1 = rect
            # 水平方向一律外扩 1px，整格再上下各外扩 1px：相邻格子互相咬合，缝隙消失
            grow_x = 1
            grow_y = 1 if ch == "█" else 0
            d.rectangle(
                [int(x0 * w) - grow_x, int(y0 * self.cell_h) - grow_y,
                 int(x1 * w) - 1 + grow_x, int(y1 * self.cell_h) - 1 + grow_y],
                fill=fg,
            )
        elif ch in SHADE_CHARS:
            density = SHADE_CHARS[ch]
            arr_sh = np.empty((self.cell_h, w, 3), dtype=np.uint8)
            arr_sh[:, :] = bg
            yy, xx = np.meshgrid(np.arange(self.cell_h), np.arange(w), indexing="ij")
            if density < 0.3:
                mask = ((xx % 2 == 0) & (yy % 2 == 0))
            elif density < 0.6:
                mask = ((xx + yy) % 2 == 0)
            else:
                mask = ~((xx % 2 == 1) & (yy % 2 == 1))
            arr_sh[mask] = fg
            self.cache[key] = arr_sh
            return arr_sh
        elif ch in BOX_CHARS:
            t = max(1, self.cell_w // 6)
            e = 2  # 外扩让相邻格子的双线/单线完全咬合
            cx, cy = w // 2, self.cell_h // 2
            spec = _BOX_SPEC.get(ch)
            if spec is not None:
                left, right, up, down = spec
                gap = max(2, t + 1)

                def _hseg(x_a: int, x_b: int, mode: int) -> None:
                    if mode == 1:
                        d.rectangle([x_a, cy - t // 2, x_b, cy - t // 2 + t - 1], fill=fg)
                    elif mode == 2:
                        d.rectangle([x_a, cy - gap - t // 2, x_b, cy - gap - t // 2 + t - 1], fill=fg)
                        d.rectangle([x_a, cy + gap - t // 2, x_b, cy + gap - t // 2 + t - 1], fill=fg)

                def _vseg(y_a: int, y_b: int, mode: int) -> None:
                    if mode == 1:
                        d.rectangle([cx - t // 2, y_a, cx - t // 2 + t - 1, y_b], fill=fg)
                    elif mode == 2:
                        d.rectangle([cx - gap - t // 2, y_a, cx - gap - t // 2 + t - 1, y_b], fill=fg)
                        d.rectangle([cx + gap - t // 2, y_a, cx + gap - t // 2 + t - 1, y_b], fill=fg)

                if left:
                    _hseg(-e, cx + (gap if up == 2 or down == 2 else 0), left)
                if right:
                    _hseg(cx - (gap if up == 2 or down == 2 else 0), w + e, right)
                if up:
                    _vseg(-e, cy + (gap if left == 2 or right == 2 else 0), up)
                if down:
                    _vseg(cy - (gap if left == 2 or right == 2 else 0), self.cell_h + e, down)
            elif ch == "·":
                r = max(1, t // 2)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fg)
            elif ch == "╱":
                d.line([(-e, self.cell_h + e), (w + e, -e)], fill=fg, width=t)
            else:  # ╲
                d.line([(-e, -e), (w + e, self.cell_h + e)], fill=fg, width=t)
        elif ch != " ":
            if wide:
                d.text((self.cell_w, self.baseline), ch, font=self.cjk, fill=fg, anchor="ms")
            else:
                font = self.mono_b if st.bold else self.mono
                d.text((0, self.baseline), ch, font=font, fill=fg, anchor="ls")
        arr = np.asarray(box, dtype=np.uint8)
        self.cache[key] = arr
        return arr


def compose(rows, atlas: Atlas, w: int, h: int) -> np.ndarray:
    cw, chh = atlas.cell_w, atlas.cell_h
    frame = np.empty((h * chh, w * cw, 3), dtype=np.uint8)
    frame[:, :] = R.bg_rgb()
    for y, runs in enumerate(rows):
        if y >= h:
            break
        x = 0
        base = y * chh
        for st, text in runs:
            for ch in text:
                wdt = 2 if is_wide(ch) else 1
                if x + wdt > w:
                    break
                if ch != " ":
                    img = atlas.get(ch, st)
                    frame[base:base + chh, x * cw:x * cw + img.shape[1]] = img
                x += wdt
    return frame


def frame_plan(frames, fps: float, total: float | None = None):
    """每个逻辑帧在成片里重复几次 —— 就是它的真实停留时长。

    用"累计目标帧号"而不是逐帧四舍五入，否则上千次的舍入误差会累积成好几秒。
    total 给出时间线总长，最后一帧（通常是黑场尾巴）才不会被截短。
    """
    n = len(frames)
    t0 = frames[0][0]
    t_end = total if total and total > frames[-1][0] else frames[-1][0] + 0.6
    plan = []
    assigned = 0
    for i in range(n):
        end = (frames[i + 1][0] if i < n - 1 else t_end)
        target = int(round((end - t0) * fps))
        rep = max(0, target - assigned)
        plan.append(rep)
        assigned += rep
    return plan


def encode(frames, plan, atlas, w, h, out: str, fps: float, vf: str, crf: int,
           log_path: str, glitch=None, glitch_t0: float = 0.0,
           encoder: str = "", limit_s: float = 0.0, quiet: bool = False,
           benchmark: bool = False, filter_threads: int = 4,
           start_s: float = 0.0, scare=None, audio: str = "",
           analog: AnalogHorrorEngine | None = None) -> int:
    cw, chh = atlas.cell_w, atlas.cell_h
    fw, fh = w * cw, h * chh
    enc = encoder or pick_encoder("")
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "warning",
    ]
    if filter_threads > 0:
        # 给滤镜线程数设上限：这台机器散热吃紧，宁可慢一点也别把峰值功率顶上去
        cmd += ["-filter_threads", str(filter_threads)]
    cmd += [
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "%dx%d" % (fw, fh), "-r", str(fps), "-i", "-",
    ]
    if audio:
        # 音轨是 audiotrack.py 离线渲染 + ffmpeg 后期出来的（见那边的说明）。
        # 视频这边只负责封装 —— 实时播放那条路是干声，两条路内容一致。
        # --start-seconds 是从半路开始编码，音轨必须跟着 seek，否则声画差 N 秒。
        if start_s > 0:
            cmd += ["-ss", "%.3f" % start_s]
        cmd += ["-i", os.path.abspath(audio)]
    cmd += ["-vf", vf]
    if limit_s > 0:
        cmd += ["-t", "%.3f" % limit_s]
    cmd += encoder_args(enc, crf)
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", os.path.abspath(out)]
    if benchmark:
        # -benchmark 的统计行是 INFO 级，必须放开 loglevel 才看得到
        cmd = [c if c != "warning" else "info" for c in cmd]
        cmd.insert(3, "-benchmark")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    total_out = sum(plan)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        done = 0
        try:
            for (t, rows), rep in zip(frames, plan):
                if t < start_s:
                    continue          # 直接从指定时刻开始喂，省掉前面的合成与滤镜
                base_frame = compose(rows, atlas, w, h)
                if analog is not None:
                    # 长停留帧（如 2 秒死锁冻结）按 ~10Hz 切片刷新 VHS 磁头噪波与行抖动
                    step_rep = max(2, int(round(fps / 10.0)))
                    rem = rep
                    sub_i = 0
                    while rem > 0:
                        chunk = min(rem, step_rep) if rep > step_rep else rem
                        sub_t = t + (sub_i * step_rep) / fps
                        processed = analog.process(base_frame, sub_t, glitch_progs=glitch,
                                                   glitch_t0=glitch_t0, scare=scare)
                        raw = processed.tobytes()
                        for _ in range(chunk):
                            p.stdin.write(raw)
                        rem -= chunk
                        sub_i += 1
                else:
                    frame = base_frame
                    if glitch:
                        want = -1
                        for i in range(len(glitch)):
                            if t >= glitch_t0 + 0.85 + i * 0.55:
                                want = i
                        if want >= 0:
                            apply_glitch(frame, glitch[want])
                    if scare is not None:
                        lt = t - glitch_t0
                        if 0.0 <= lt < scare.CUT_END:
                            scare.render_pixels(frame, lt)
                    raw = frame.tobytes()
                    for _ in range(rep):
                        p.stdin.write(raw)
                done += rep
                if done % (int(fps) * 10) < rep:
                    print("  已输出 %d/%d 帧（%.0f%%）" % (done, total_out, done * 100.0 / total_out),
                          flush=True)
        except BrokenPipeError:
            pass
        try:
            p.stdin.close()
        except Exception:
            pass
        rc = p.wait()
    if benchmark:
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f.read().splitlines():
                    if "bench:" in line or "utime=" in line:
                        print("  ffmpeg " + line.strip())
        except Exception:
            pass
    return rc


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m erranim.film",
                                description="把录制好的逻辑帧渲染成视频（ffmpeg 后期）")
    p.add_argument("--record", default="out/demo.jsonl", help="player --record 生成的 JSONL")
    p.add_argument("--out", default="out/demo.mp4", help="输出视频")
    p.add_argument("--fps", type=float, default=30.0, help="成片帧率（逻辑帧不受影响，只是补帧）")
    p.add_argument("--font-size", type=int, default=18, help="字符字号")
    p.add_argument("--crf", type=int, default=18, help="x264 质量，越小越好")
    p.add_argument("--no-crt", action="store_true", help="不做扫描线/色差/噪点等 CRT 后期")
    p.add_argument("--bands", type=int, default=7, help="偶现色带的条数（0 = 关闭，默认 7）")
    p.add_argument("--brightness", type=float, default=0.045, help="整体提亮量（默认 0.045）")
    p.add_argument("--glitch", type=int, default=3,
                   help="跳杀期间叠加的解码失败级数（0 = 关闭，默认 3；只在视频里做）")
    p.add_argument("--codec", default="h264", choices=("h264", "hevc", "av1"),
                   help="编码家族：h264（默认）/ hevc / av1。AV1 对噪点最省码率")
    p.add_argument("--encoder", default="",
                   help="直接指定编码器（覆盖 --codec 的自动选择）")
    p.add_argument("--limit-seconds", type=float, default=0.0,
                   help="只编码前 N 秒，用来估算耗时与温度（0 = 全片）")
    p.add_argument("--start-seconds", type=float, default=0.0,
                   help="从第 N 秒开始编码（配合 --limit-seconds，可单独看某一段）")
    p.add_argument("--benchmark", action="store_true",
                   help="让 ffmpeg 自报 CPU 时间（utime/stime），用来查谁在烧 CPU")
    p.add_argument("--filter-threads", type=int, default=4,
                   help="ffmpeg 滤镜线程上限（默认 4；散热吃紧时调小，0 = 不限）")
    p.add_argument("--png", default="", help="只导预览图：逗号分隔的全局时间点，然后退出")
    p.add_argument("--dump-frames", action="store_true", help="额外把每个逻辑帧存成 PNG")
    p.add_argument("--audio", default="", help="音轨 wav（erranim.audiotrack 生成的），封装成 AAC")
    p.add_argument("--ffmpeg", default="", help="指定 ffmpeg 路径")
    return p.parse_args(argv)


def main(argv=None) -> int:
    global FFMPEG
    args = parse_args(argv)
    if args.ffmpeg:
        FFMPEG = args.ffmpeg
    meta, frames = load_record(args.record)
    w = int(meta.get("w") or 132)
    h = int(meta.get("h") or 42)
    atlas = Atlas(args.font_size)
    outdir = os.path.dirname(os.path.abspath(args.record)) or "."
    print("逻辑帧 %d 个，%dx%d 格，格子 %dx%d，字体 %s / %s"
          % (len(frames), w, h, atlas.cell_w, atlas.cell_h,
             os.path.basename(atlas.mono_path), os.path.basename(atlas.cjk_path)))

    dur = float(meta.get("duration") or 0) or (frames[-1][0] + 0.6)
    fw = w * atlas.cell_w
    fh = h * atlas.cell_h
    seed = int(meta.get("seed", 0) or 0)
    scare_obj = None
    glitch_t0 = 0.0
    if meta.get("scare"):
        from .scare import JumpScare
        ph = meta.get("scare_phrase")
        scare_obj = JumpScare(tuple(ph) if ph else None, seed, meta.get("scare_style", "echo"))
        glitch_t0 = float(meta["scare"][0])
    glitch = None
    if not args.no_crt and args.glitch > 0 and meta.get("scare"):
        glitch = build_glitch_programs(fw, fh, args.glitch, seed, os.path.join(outdir, "glitch"))
    analog = None if args.no_crt else AnalogHorrorEngine(fw, fh, seed=seed, duration=dur)

    if args.png:
        for part in args.png.split(","):
            part = part.strip()
            if not part:
                continue
            t = float(part)
            i = min(range(len(frames)), key=lambda k: abs(frames[k][0] - t))
            if analog is not None and i > 0:
                # 先喂前一帧建立跨帧 Datamosh 状态，保证单张预览也带真实的 P 帧宏块撕裂
                analog.prev_frame = compose(frames[max(0, i - 2)][1], atlas, w, h)
            raw_img = compose(frames[i][1], atlas, w, h)
            if analog is not None:
                raw_img = analog.process(raw_img, t, glitch_progs=glitch,
                                         glitch_t0=glitch_t0, scare=scare_obj)
            img = Image.fromarray(raw_img, "RGB")
            path = os.path.join(outdir, "preview_%s.png" % part.replace(".", "_"))
            img.save(path)
            print("  t=%.2fs（实际取第 %d 帧 @ %.2fs）→ %s" % (t, i, frames[i][0], path))
        return 0

    if args.dump_frames:
        fdir = os.path.join(outdir, "frames")
        os.makedirs(fdir, exist_ok=True)
        for i, (t, rows) in enumerate(frames):
            raw_img = compose(rows, atlas, w, h)
            if analog is not None:
                raw_img = analog.process(raw_img, t, glitch_progs=glitch,
                                         glitch_t0=glitch_t0, scare=scare_obj)
            Image.fromarray(raw_img, "RGB").save(
                os.path.join(fdir, "f%05d.png" % i))
        print("  已导出 %d 张逻辑帧 → %s" % (len(frames), fdir))

    if not os.path.exists(FFMPEG):
        raise SystemExit("找不到 ffmpeg：%s（用 --ffmpeg 指定或设 FFMPEG）" % FFMPEG)
    plan = frame_plan(frames, args.fps, total=float(meta.get("duration") or 0) or None)
    frame_h = fh
    if args.no_crt:
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    else:
        vf = crt_chain(dur, frame_h, seed=seed,
                       bands=args.bands, bright=args.brightness, final_scale=True)
    enc = pick_encoder(args.encoder, args.codec)

    print("覆盖 %.1f 秒 → 成片 %.0f fps / %d 帧 / 质量 %d / %s / %s / 滤镜线程 %d%s"
          % (dur, args.fps, sum(plan), args.crf, args.codec, enc, args.filter_threads,
             "" if args.no_crt else " / VHS+CRT+Datamosh 模拟恐怖后期（%d 条色带%s）"
             % (args.bands, "，%d 级解码失败特效" % len(glitch) if glitch else "")))
    if args.limit_seconds > 0:
        print("（只编码前 %.1f 秒，用于估时）" % args.limit_seconds)
    log_path = os.path.join(outdir, "ffmpeg.log")
    rc = encode(frames, plan, atlas, w, h, args.out, args.fps, vf, args.crf, log_path,
                glitch, glitch_t0, encoder=enc, limit_s=args.limit_seconds,
                benchmark=args.benchmark, filter_threads=args.filter_threads,
                start_s=args.start_seconds, scare=scare_obj, audio=args.audio,
                analog=analog)
    if rc != 0:
        print("ffmpeg 失败（退出码 %d），日志：%s" % (rc, log_path), file=sys.stderr)
        return rc
    size = os.path.getsize(args.out) if os.path.exists(args.out) else 0
    shown = sum(plan) / args.fps
    if args.start_seconds > 0 or args.limit_seconds > 0:
        shown = min(shown, args.limit_seconds) if args.limit_seconds > 0 else shown - args.start_seconds
    print("→ %s（%.1f MB，%.1f 秒）%s"
          % (args.out, size / 1048576, shown,
             "  音轨 %s" % args.audio if args.audio else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
