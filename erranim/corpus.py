"""语料库：结构化读取真实 SCM 事件，并提供"有逻辑的错误出现"采样。

原始 md 是去重摘要，只留了主行，丢掉了紧随其后的具体错误原因 —— 于是出现
「错误原因如下:」后面什么都没有，逻辑上不成立。这里把真实的多行事件完整取回：
    主行
        原因（真实缩进）
        提示（若有）

`data/corpus.json` 由 `tools/harvest_scm.ps1` 从 Windows 事件日志采集。
文件不存在时全部退化到 `records.py` 里内嵌的兜底数据，代码不会崩。

随机机制：`Corpus.sequence()` 按严重度递增收敛地采样一串事件，
既能当背景噪声，也能当"逻辑错误链"。用 `--random on|off` 开关。
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field

# 数据文件默认位置：<repo>/data/corpus.json
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(os.path.dirname(_HERE), "data", "corpus.json")

INDENT = 7  # 细节行的缩进，正好对齐 "[7038] " 之后

# 事件 ID -> (种类, 严重度)。严重度就是叙事里的排序依据。
KINDS: dict[int, tuple[str, int]] = {
    7040: ("noise", 0),
    7036: ("noise", 0),
    7045: ("noise", 0),
    506: ("noise", 0),
    507: ("noise", 0),
    7000: ("startfail", 2),
    7001: ("startfail", 2),
    7006: ("startfail", 2),
    1008: ("startfail", 2),
    7030: ("interactive", 3),
    7024: ("specific", 3),
    11: ("specific", 3),
    153: ("specific", 3),
    7009: ("timeout", 3),
    7011: ("timeout", 3),
    10010: ("timeout", 3),
    10016: ("authfail", 3),
    36884: ("authfail", 3),
    7038: ("authfail", 4),
    10001: ("authfail", 4),
    1: ("authfail", 4),
    7031: ("terminated", 4),
    1000: ("terminated", 4),
    1002: ("terminated", 4),
    13: ("stopped", 4),
    8193: ("stopped", 4),
    7034: ("stopped", 5),
    263: ("observer", 5),
    700: ("observer", 5),
    701: ("observer", 3),
    41: ("fatal", 5),
    109: ("fatal", 5),
}

KIND_LABEL = {
    "noise": "日常",
    "startfail": "启动失败",
    "interactive": "交互服务被拒",
    "specific": "服务特定错误",
    "timeout": "超时",
    "authfail": "身份验证失败",
    "terminated": "意外终止（有修正动作）",
    "stopped": "意外停止（无修正动作）",
    "observer": "输入抑制与监视器异常",
    "fatal": "内核电源致命崩溃",
    "unknown": "其它",
}


@dataclass
class Event:
    id: int
    main: str
    reason: str = ""
    hint: str = ""
    count: int = 1
    first: str = ""
    last: str = ""
    params: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return KINDS.get(self.id, ("unknown", 1))[0]

    @property
    def severity(self) -> int:
        return KINDS.get(self.id, ("unknown", 1))[1]

    @property
    def service(self) -> str:
        return str(self.params.get("param1", "") or "")

    def lines(self, indent: int = INDENT) -> list[str]:
        """一行事件展开成真正符合逻辑的多行：主行 + 缩进的原因 + 缩进的提示。"""
        out = [self.main]
        pad = " " * indent
        if self.reason:
            out.append(pad + self.reason)
        if self.hint:
            out.append(pad + self.hint)
        return out

    def text(self, indent: int = INDENT) -> str:
        return "\n".join(self.lines(indent))

    def tag(self) -> str:
        return "[%d] " % self.id


class Corpus:
    def __init__(self, meta: dict, events: list[Event], path: str = ""):
        self.meta = meta or {}
        self.events = events
        self.path = path

    # -- 读取 ----------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "Corpus | None":
        p = path or DEFAULT_PATH
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        evs = []
        for e in data.get("events", []):
            if isinstance(e, list):  # 单条时 ConvertTo-Json 可能不套数组
                continue
            evs.append(Event(
                id=int(e.get("id", 0)),
                main=str(e.get("main", "")),
                reason=str(e.get("reason", "") or ""),
                hint=str(e.get("hint", "") or ""),
                count=int(e.get("count", 1) or 1),
                first=str(e.get("firstTime", "") or ""),
                last=str(e.get("lastTime", "") or ""),
                params=dict(e.get("params", {}) or {}),
            ))
        return cls(data.get("meta", {}), evs, p)

    def __len__(self) -> int:
        return len(self.events)

    # -- 查询 ----------------------------------------------------------
    def of_kind(self, *kinds: str) -> list[Event]:
        want = set(kinds)
        return [e for e in self.events if e.kind in want]

    def by_severity(self, lo: int = 0, hi: int = 99) -> list[Event]:
        return [e for e in self.events if lo <= e.severity <= hi]

    def by_service(self, name: str) -> list[Event]:
        return [e for e in self.events if e.service == name]

    def find(self, service: str, ev: int | None = None) -> Event | None:
        for e in self.events:
            if e.service == service and (ev is None or e.id == ev):
                return e
        return None

    # -- 采样 ----------------------------------------------------------
    def noise(self, rng: random.Random) -> Event:
        pool = self.of_kind("noise") or self.events
        # 权重封顶：不然 7040（本机 1700 条里占 1574 条）会把背景刷成一句话
        weights = [max(1, min(e.count, 30)) for e in pool]
        return rng.choices(pool, weights=weights, k=1)[0]

    def sample(self, rng: random.Random, kinds=None, weighted: bool = True) -> Event:
        pool = self.of_kind(*kinds) if kinds else self.events
        if not pool:
            pool = self.events
        if not weighted:
            return rng.choice(pool)
        # 按真实出现次数加权：真实频率本身就有说服力
        weights = [max(1, e.count) for e in pool]
        return rng.choices(pool, weights=weights, k=1)[0]

    def sequence(self, rng: random.Random, n: int, ladder: bool = True) -> list[Event]:
        """生成一串"有逻辑"的事件。

        ladder=True 时按严重度递增收敛（像一次真实的故障演进）：
        先在低严重度里挑，越往后越往高严重度走。
        """
        out: list[Event] = []
        for i in range(max(0, n)):
            if ladder:
                # 目标严重度随进度上移，但留一点随机回落，避免死板
                frac = i / max(1, n - 1)
                target = 0.6 + frac * 4.6 + rng.uniform(-0.7, 0.7)
                hi = int(max(0, min(5, round(target))))
                pool = self.by_severity(max(0, hi - 1), hi) or self.events
            else:
                pool = self.events
            weights = [max(1, e.count) for e in pool]
            out.append(rng.choices(pool, weights=weights, k=1)[0])
        return out

    # -- 展示 ----------------------------------------------------------
    def summary(self, limit: int = 0) -> str:
        rows = []
        for e in sorted(self.events, key=lambda x: (x.severity, -x.count)):
            rows.append("%4d x%-4d [%-10s sev%d] %s" % (e.id, e.count, e.kind, e.severity, e.main))
            if e.reason:
                rows.append("%s└─ 原因: %s" % (" " * 11, e.reason))
            if e.hint:
                rows.append("%s└─ 提示: %s" % (" " * 11, e.hint))
        if limit:
            rows = rows[:limit]
        return "\n".join(rows)

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for e in self.events:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        return {
            "distinct": len(self.events),
            "raw": self.meta.get("raw_count", 0),
            "with_reason": sum(1 for e in self.events if e.reason),
            "kinds": kinds,
            "path": self.path,
        }
