"""音频导演：把时间轴上的事件翻译成"对噪声的操作"。

**为什么单独一个模块**：终端实时播放和出片是两条路，但必须听到同一个东西。
事件检测只写一次，两条路都调 `Director.step(t)`。

    # 实时
    d = Director(sched, mixer); d.step(t)
    # 离线出片
    while t < total: d.step(t); out.append(mixer.render_upto(t)); t += 1/60

四类事件，都按**绝对时间**推进（游标 + 比较，不回溯、不缓存）：

  1. 日志行 —— 红/品红 → `deny`，黄/琥珀 → `note`，淡色每 7 行 → `tick`。
     这三个都是**噪声声部**，不是采样。用户的原话："就算没有特殊音效也可以" ——
     与其挂一排玩具音效，不如让它们也只是"对这条噪声做点什么"。
  2. 画面故障 —— 每种故障对应一个声部，见 `audio.VOICE_FOR_GLITCH`。
  3. 停顿（时间冻结）—— 把底噪的门按住。**不是加音效，是抽掉声音。**
  4. 段落状态 —— 集体衰竭加速恶化；**静默段骤停**；跳杀那一刻解冻并撞击。

## 骤停

"静默"段（第 8 段）从第 95.0 秒开始。这一段的画面叫"系统已就绪。/
未检测到任何用户。"，而音频在这里**必须已经死了** —— 用户明确说这些声音
"在闪白出现服务就绪之前就该骤停了"。所以：

    95.00  骤停（4ms 斜边，之后是死的静音，连故障声部也清空）
   104.50  跳杀：解冻 + 撞击 —— 9.5 秒的死寂之后的那一下

9.5 秒一点声音都没有，是故意的。静默之所以不安，就是因为什么都没了。
"""

from __future__ import annotations

from . import render as R
from . import scenes as S

# 画面故障 -> 声部。名字统一放在 audio 里（那里才是"声音是什么"的权威），
# 这里只负责"什么时候放"。
from .audio import VOICE_FOR_GLITCH  # noqa: F401  （对外re-export，便于查表）

# 淡色日志行的底噪：每 N 行给一个极轻的 tick
DIM_EVERY = 7

# 集体衰竭段的恶化加速：从第 RAMP_START 秒起，打断之间的间隔从 SLOW 收到 FAST。
# 用的都是"停顿"类模式 —— 这一段的表现手段就是**噪声越来越频繁地断**。
RAMP_START = 9.0
RAMP_SLOW = 1.30
RAMP_FAST = 0.22
RAMP_CYCLE = ("skip", "stutter", "dropout", "stutter", "halt")

# 跳杀那一刻叠的打断
SCARE_VOICES = ("impact",)


# 关键节点蜂鸣器冷却时间（秒）：普通刷屏日志只对底噪做继电器切刀打断（deny / note），
# 只有新错误首次出现（且过了冷却期）或弹出模态故障框时，才触发复古 BIOS/固件蜂鸣器。
BUZZER_COOLDOWN = 4.8


class Director:
    def __init__(self, sched, mixer):
        self.sched = sched
        self.mixer = mixer
        self.log_cursor: dict[int, int] = {}
        self.glitch_cursor: dict[int, int] = {}
        self.modal_cursor: dict[int, int] = {}
        self.seen_sigs: set[str] = set()
        self.last_buzzer_t = -10.0
        self.dim_seen = 0
        self.cut_on = False
        self.frozen = False
        self.scare_hit = False
        self.last_ramp = 0.0
        self.ramp_i = 0
        self.counts: dict[str, int] = {}

    def _bump(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def step(self, t: float) -> None:
        """把 <= t 的事件全部放出去。可以任意步长调用，不会重复也不会漏。"""
        scene, lt = S.locate(self.sched, t)
        te = scene.teff(lt)
        key = id(scene)
        m = self.mixer
        sev = min(1.0, max(0.0, t / 92.0))

        # 0) 静默段：整条音频骤停，什么都不放
        if scene.name == "silence":
            if not self.cut_on:
                m.hard_cut(True)
                self.cut_on = True
                self._bump("骤停")
            return

        # 1) 日志行：所有红/黄日志都对底噪做继电器打断（deny / note）；
        #    仅在首次遇到某类错误且距上次蜂鸣 >= BUZZER_COOLDOWN 时才响复古固件蜂鸣器。
        merged = scene._merged_logs()
        idx = self.log_cursor.get(key, 0)
        while idx < len(merged) and merged[idx][0] <= te:
            _tt, text, st = merged[idx]
            idx += 1
            sig = text[:22]
            is_new = sig not in self.seen_sigs
            self.seen_sigs.add(sig)
            if st in (R.S_RED, R.S_MAGENTA):
                m.glitch("deny")
                if m.warnings and is_new and (t - self.last_buzzer_t >= BUZZER_COOLDOWN):
                    m.trigger("error", sev=sev)
                    self.last_buzzer_t = t
                    self._bump("buzzer_err")
                self._bump("error")
            elif st in (R.S_YELLOW, R.S_AMBER):
                m.glitch("note")
                if m.warnings and is_new and (t - self.last_buzzer_t >= BUZZER_COOLDOWN):
                    m.trigger("warn", sev=sev)
                    self.last_buzzer_t = t
                    self._bump("buzzer_warn")
                self._bump("warn")
            else:
                # 淡色行底噪微点击
                self.dim_seen += 1
                if self.dim_seen % DIM_EVERY == 0:
                    m.glitch("tick")
                    self._bump("tick")
        self.log_cursor[key] = idx

        # 1b) 模态故障弹窗弹出瞬间：必定触发一次重度固件故障蜂鸣
        modals = getattr(scene, "modals", ())
        mi = self.modal_cursor.get(key, 0)
        while mi < len(modals) and modals[mi][0] <= te:
            mi += 1
            m.glitch("deny")
            if m.warnings:
                m.trigger("error", sev=min(1.0, sev + 0.25))
                self.last_buzzer_t = t
                self._bump("modal_buzzer")
        self.modal_cursor[key] = mi

        # 2) 画面故障 -> 声部
        gi = self.glitch_cursor.get(key, 0)
        gl = scene.glitches
        while gi < len(gl) and gl[gi].t <= te:
            g = gl[gi]
            gi += 1
            m.glitch(g.name, dur=g.dur)
            self._bump(g.name)
        self.glitch_cursor[key] = gi

        # 3) 停顿：时间冻结的两秒，底噪的门被按住
        frozen = scene.frozen_at(lt) is not None
        if frozen != self.frozen:
            self.frozen = frozen
            if frozen:
                self._bump("冻结")
            else:
                m.glitch("sweep")      # 解冻时扫上来，像机器重新通电
                self._bump("解冻")
        if frozen:
            m.hold_bed(0.35)

        # 4) 集体衰竭：越到后面恶化的间隔越短
        if scene.name == "cascade" and te >= RAMP_START:
            k = (te - RAMP_START) / max(1e-6, scene.duration - RAMP_START)
            gap = RAMP_SLOW + (RAMP_FAST - RAMP_SLOW) * min(1.0, k)
            if t - self.last_ramp >= gap:
                m.spawn(RAMP_CYCLE[self.ramp_i % len(RAMP_CYCLE)],
                        gain=0.5 + 0.5 * min(1.0, k))
                self.ramp_i += 1
                self.last_ramp = t
                self._bump("恶化")

        # 5) 跳杀：解冻 + 撞击。9.5 秒死寂之后的那一下
        if scene.name == "jumpscare" and not self.scare_hit:
            self.scare_hit = True
            m.hard_cut(False)
            for v in SCARE_VOICES:
                m.spawn(v)
                self._bump(v)
            self._bump("跳杀")
