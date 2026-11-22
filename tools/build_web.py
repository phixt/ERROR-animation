"""编译单文件零依赖 HTML5 Canvas + WebAudio 纯净沉浸式终端网页：web/index.html。

以 Python 引擎（erranim.scenes / erranim.render / erranim.bigtext / erranim.glitch）
为唯一真源，导出全部 9 段场景时间线、调色板与跳杀字模，打包进单一静态 HTML 文件。

交互设计：
  - 开场仅展示极简终端说明与按键表（点击或回车后自动解锁 WebAudio 并进入纯终端画面）；
  - 进入后全视口（100vw × 100vh）只保留居中终端屏幕，不展示任何外部网页控件或说明杂物；
  - 播放期间按 Esc / H 可随时呼出极简终端帮助/暂停层，平时完全不可见。

用法：
    python tools/build_web.py
    python tools/build_web.py --out web/index.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from erranim import bigtext as BT
from erranim import glitch as G
from erranim import render as R
from erranim import scenes as S
from erranim.scare import JumpScare


def rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def export_payload(seed: int = S.SEED) -> dict:
    scenes = S.build_scenes(seed=seed, scare_style="echo")
    sched = S.schedule(scenes)

    palette = []
    for st in R.PALETTE:
        fg, bg = st.film
        palette.append({
            "fg": rgb_hex(fg),
            "bg": rgb_hex(bg),
            "bold": bool(st.bold),
        })

    sc_list = []
    for a, b, sc in sched:
        logs = [[round(float(t), 4), str(txt), int(st)] for t, txt, st in sc.logs]
        bars = []
        for bp in sc.bars:
            bars.append({
                "t0": round(bp.t0, 4),
                "t1": round(bp.t1, 4),
                "level": int(bp.level),
                "ms": bp.ms,
                "outcome": bp.outcome,
                "label": bp.label,
                "tail": bp.tail,
                "levels": [[round(float(tt), 4), int(lv)] for tt, lv in bp.levels],
                "segs": [[round(float(tt), 4), round(float(ff), 4)] for tt, ff in bp.segs()],
            })
        prompts = []
        for pr in sc.prompts:
            prompts.append({
                "t0": round(pr.t0, 4),
                "t1": round(pr.t1, 4),
                "text": pr.text,
                "auto": pr.auto,
            })
        modals = []
        for m in sc.modals:
            modals.append({
                "t0": round(float(m[0]), 4),
                "t1": round(float(m[1]), 4),
                "title": m[2],
                "lines": list(m[3]),
                "code": m[4],
                "buttons": m[5] if len(m) > 5 else "[ Retry (Y) ]   [ Ignore (N) ]",
            })
        glitches = []
        for gl in sc.glitches:
            glitches.append({
                "t": round(float(gl.t), 4),
                "dur": round(float(gl.dur), 4),
                "name": gl.name,
                "seed": int(gl.seed),
                "p": gl.p,
            })
        sc_list.append({
            "name": sc.name,
            "title": sc.title,
            "start": round(a, 4),
            "end": round(b, 4),
            "duration": round(sc.duration, 4),
            "bare": bool(sc.bare),
            "log_align": sc.log_align,
            "cursor": bool(sc.cursor),
            "res_seed": round(sc.res_seed, 6),
            "logs": logs,
            "bars": bars,
            "prompts": prompts,
            "modals": modals,
            "glitches": glitches,
            "status": [[round(float(t), 4), str(txt)] for t, txt in sc.status],
            "clears": [round(float(c), 4) for c in sc.clears],
            "holds": [[round(float(x0), 4), round(float(x1), 4)] for x0, x1 in sc.holds],
            "ts_jumps": [[round(float(t), 4), round(float(v), 4)] for t, v in sc.ts_jumps],
        })

    js_scare = JumpScare(None, seed, "echo")
    sw, sh = 100, 40
    m, ring, ring_fill = js_scare.scaled(sw, sh)
    scare_rows = []
    for y in range(sh):
        row = []
        for x in range(sw):
            if ring[y][x] == 0:
                row.append("E")
            elif ring_fill[y][x] >= 0:
                row.append("F")
            else:
                row.append(".")
        scare_rows.append("".join(row))

    return {
        "cols": 118,
        "rows": 32,
        "seed": seed,
        "total": round(S.total_duration(scenes), 3),
        "bg": rgb_hex(R.BG),
        "ts_base_ms": int(S.TS_BASE.timestamp() * 1000),
        "palette": palette,
        "homoglyph": G.HOMOGLYPH,
        "modal_pool": [
            {"title": t, "lines": ls, "code": c}
            for t, ls, c in G._MODAL_POOL
        ],
        "scare": {
            "phrase": list(js_scare.phrase),
            "text": js_scare.text,
            "w": sw,
            "h": sh,
            "rows": scare_rows,
            "mask": [[1 if v else 0 for v in row] for row in js_scare.mask],
            "mw": js_scare.mw,
            "mh": js_scare.mh,
        },
        "scenes": sc_list,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>ERROR-animation</title>
<style>
  :root {
    --bg: #040507;
    --term-bg: #080a0d;
    --text: #c8d2e0;
    --dim: #6e7b8c;
    --border: #2a3442;
    --amber: #ffb000;
    --red: #ff5555;
    --mono: "Cascadia Mono", "Consolas", "JetBrains Mono", Menlo, Monaco, "Microsoft YaHei", monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    width: 100%;
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    overflow: hidden;
    user-select: none;
  }

  /* Pure Full-Viewport Terminal Container */
  .viewport {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #030406;
  }
  .crt-frame {
    position: relative;
    width: min(100vw, calc(100vh * 118 / 64));
    height: min(100vh, calc(100vw * 64 / 118));
    background: var(--term-bg);
    overflow: hidden;
    box-shadow: 0 0 60px rgba(0, 0, 0, 0.95);
  }
  #termCanvas {
    width: 100%;
    height: 100%;
    display: block;
    image-rendering: pixelated;
  }
  .crt-overlay {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
      radial-gradient(ellipse at center, transparent 60%, rgba(0, 0, 0, 0.52) 100%),
      repeating-linear-gradient(0deg, rgba(0, 0, 0, 0.22) 0px, rgba(0, 0, 0, 0.22) 1px, transparent 1px, transparent 3px);
    mix-blend-mode: multiply;
    opacity: 0.9;
    transition: opacity 0.15s;
  }
  .crt-frame.flat .crt-overlay { opacity: 0; }

  /* Boot Splash & Esc Menu (Minimal Terminal Box Only) */
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(4, 5, 7, 0.96);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 20px;
  }
  .overlay.hidden { display: none; }
  .box {
    width: min(640px, 100%);
    background: #080a0d;
    border: 1px solid var(--border);
    padding: 26px 28px;
    line-height: 1.75;
    font-size: 13px;
    box-shadow: 0 18px 60px rgba(0, 0, 0, 0.9);
  }
  .box h1 {
    font-size: 15px;
    font-weight: 700;
    color: #eef3fa;
    letter-spacing: 0.08em;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid #1c2430;
  }
  .box p {
    color: #aebac9;
    margin-bottom: 10px;
  }
  .warn {
    color: var(--amber);
    font-size: 12px;
    margin-bottom: 16px;
  }
  .keys {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px 18px;
    margin: 14px 0 22px;
    padding: 12px 14px;
    background: #0b0e13;
    border: 1px solid #1b222e;
    font-size: 12px;
    color: var(--dim);
  }
  .keys kbd {
    display: inline-block;
    min-width: 44px;
    color: #e2eaf4;
    font-family: var(--mono);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }
  .tbtn {
    appearance: none;
    background: #121822;
    border: 1px solid #3c4b61;
    color: #eef3fa;
    font-family: var(--mono);
    font-size: 13px;
    padding: 8px 18px;
    cursor: pointer;
    letter-spacing: 0.04em;
  }
  .tbtn:hover { background: #1d2736; border-color: #7c92b0; }
  .tbtn.primary {
    background: #8f1218;
    border-color: #ff4d4d;
    color: #ffffff;
    font-weight: 700;
  }
  .tbtn.primary:hover { background: #b3161e; }
  .hint-small {
    color: var(--dim);
    font-size: 11px;
    margin-left: auto;
  }
  @media (max-width: 560px) {
    .keys { grid-template-columns: 1fr; }
    .hint-small { margin-left: 0; }
  }
</style>
</head>
<body>

<div class="viewport">
  <div id="crtFrame" class="crt-frame">
    <canvas id="termCanvas"></canvas>
    <div class="crt-overlay"></div>
  </div>
</div>

<!-- Opening Splash: brief description + keybindings only -->
<div id="splash" class="overlay">
  <div class="box">
    <h1>ERROR-animation // NT-SCM TERMINAL</h1>
    <p>基于真实 Windows 服务控制管理器（SCM）、内存耗尽与显示内核死锁事件日志生成的终端动画。</p>
    <p>实时合成底层持续噪声、故障门控与主板告警音，无任何外部媒体依赖。</p>
    <p class="warn">提示：结尾包含短暂高反差闪屏与强对比视觉刺激；点击下方按钮后将开启音频并进入全屏纯终端界面。</p>
    <div class="keys">
      <div><kbd>1 - 9</kbd> 跳转段落</div>
      <div><kbd>Space</kbd> 暂停 / 继续</div>
      <div><kbd>+ / -</kbd> 调节倍速 (0.4x–10x)</div>
      <div><kbd>0</kbd> 倍速复位 1.0x</div>
      <div><kbd>Y / N</kbd> 回答重试提示</div>
      <div><kbd>M</kbd> 音频静音 / 开启</div>
      <div><kbd>C</kbd> 开关 CRT 滤镜</div>
      <div><kbd>Esc</kbd> 呼出 / 关闭菜单</div>
    </div>
    <div class="actions">
      <button id="btnStart" class="tbtn primary" type="button">[ ENTER // 启动会话 ]</button>
      <button id="btnStartMute" class="tbtn" type="button">[ 静音启动 ]</button>
      <span class="hint-small">按 Enter 键可直接开始</span>
    </div>
  </div>
</div>

<!-- Minimal Pause / Help Menu (Hidden unless Esc or H is pressed) -->
<div id="menu" class="overlay hidden">
  <div class="box">
    <h1>SESSION MENU // PAUSED</h1>
    <div class="keys">
      <div><kbd>1 - 9</kbd> 跳转段落</div>
      <div><kbd>Space</kbd> 暂停 / 继续</div>
      <div><kbd>+ / -</kbd> 调节倍速</div>
      <div><kbd>0</kbd> 倍速复位 1.0x</div>
      <div><kbd>Y / N</kbd> 回答重试提示</div>
      <div><kbd>M</kbd> 音频静音 / 开启</div>
      <div><kbd>C</kbd> 开关 CRT 滤镜</div>
      <div><kbd>Esc</kbd> 返回终端画面</div>
    </div>
    <div class="actions">
      <button id="btnResume" class="tbtn primary" type="button">[ 继续 ]</button>
      <button id="btnRestart" class="tbtn" type="button">[ 重新开始 ]</button>
      <button id="btnToggleAudio" class="tbtn" type="button">[ 音频: 开 ]</button>
      <button id="btnToggleCrt" class="tbtn" type="button">[ CRT: 开 ]</button>
    </div>
  </div>
</div>

<script>
const DATA = __ERRANIM_DATA__;

(() => {
  "use strict";

  // ------------------------------------------------------------------------
  // 1. Deterministic PRNG & Utilities
  // ------------------------------------------------------------------------
  function hashStr(s) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }

  class RNG {
    constructor(seed) { this.s = (seed >>> 0) || 1; }
    next() {
      let t = (this.s += 0x6d2b79f5) >>> 0;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    uniform(a, b) { return a + (b - a) * this.next(); }
    randrange(a, b) { return a + Math.floor(this.next() * Math.max(1, b - a)); }
    randint(a, b) { return a + Math.floor(this.next() * (b - a + 1)); }
    choice(arr) { return arr[Math.floor(this.next() * arr.length)]; }
  }

  function isWideChar(ch) {
    if (!ch) return false;
    const c = ch.codePointAt(0);
    return (
      (c >= 0x1100 && c <= 0x115f) ||
      (c >= 0x2e80 && c <= 0xa4cf && c !== 0x303f) ||
      (c >= 0xac00 && c <= 0xd7a3) ||
      (c >= 0xf900 && c <= 0xfaff) ||
      (c >= 0xfe10 && c <= 0xfe19) ||
      (c >= 0xfe30 && c <= 0xfe6f) ||
      (c >= 0xff00 && c <= 0xff60) ||
      (c >= 0xffe0 && c <= 0xffe6)
    );
  }
  function charWidth(ch) { return isWideChar(ch) ? 2 : 1; }
  function textWidth(s) { let w = 0; for (const ch of s) w += charWidth(ch); return w; }
  function truncate(s, cols) {
    let out = "", used = 0;
    for (const ch of s) {
      const cw = charWidth(ch);
      if (used + cw > cols) break;
      out += ch;
      used += cw;
    }
    return out;
  }

  const S_BASE = 0, S_DIM = 1, S_FAINT = 2, S_BRIGHT = 3, S_AMBER = 4, S_RED = 5,
    S_GREEN = 6, S_CYAN = 7, S_YELLOW = 8, S_TEAL = 9, S_MAGENTA = 10, S_INVERT = 11,
    S_BLOCK = 12, S_BLOCK_EMPTY = 13, S_HEAD = 14, S_SCARE_BODY = 15, S_SCARE_RED = 16,
    S_SCARE_DIM = 17, S_SCARE_GAP = 18, S_FLASH = 19, S_SCARE_DRIP = 20,
    S_HEADER_BAR = 21, S_ALERT_BAR = 22, S_WARN_BAR = 23, S_MODAL_BG = 24,
    S_MODAL_BORDER = 25, S_MODAL_TITLE = 26, S_SHADOW = 27, S_BORDER = 28,
    S_BORDER_HOT = 29, S_COMMIT_OVER = 30;

  const GLITCH_CHARS = "▓▒░█▄▀■□▪▫◢◣◤◥╳╱╲†‡¤§¶¥¢£¦¬±÷×※";
  const CORRUPT_CHARS = "▓▒░█▚▞▙▟⣿⣷⣯◇◆※¤§¶†‡";
  const CORRUPT_PCT = ["9999999%", "-0%", "NaN%", "112%", "--%", "4O%", "∞%", "  %", "1e9%"];
  const ESCAPE_LITERALS = ["ESC[2J", "\\x1b[31m", "ESC[?1049h", "^[[0m", "\\033[38;2;255;0;0m", "ESC[1;1H"];
  const BOX_SET = new Set("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬");
  const MELT_CHARS = "╬╫╨╥▓▒░│¦⋮╏╽╿";
  const PANEL_JUNK = "▒░█▄■□▪◢◤╳†¤§¶¥¢¬±÷×※#%@&$";
  const PANEL_EFFECTS = new Set(["panel_noise", "panel_corrupt", "panel_garbage", "panel_invert", "panel_dim"]);

  // ------------------------------------------------------------------------
  // 2. Wide-Character Terminal Grid
  // ------------------------------------------------------------------------
  class Grid {
    constructor(w, h) {
      this.w = w; this.h = h;
      this.ch = new Array(w * h);
      this.st = new Uint8Array(w * h);
      this.cont = new Uint8Array(w * h);
      this.clear();
    }
    clear() { this.ch.fill(" "); this.st.fill(0); this.cont.fill(0); }
    _clobber(i) {
      if (this.cont[i]) {
        this.cont[i] = 0; this.ch[i] = " ";
        if (i % this.w && this.cont[i - 1]) { this.cont[i - 1] = 0; this.ch[i - 1] = " "; }
      }
      if (i % this.w !== this.w - 1 && this.cont[i + 1]) { this.cont[i + 1] = 0; this.ch[i + 1] = " "; }
    }
    put(x, y, s, style = 0) {
      if (y < 0 || y >= this.h || x >= this.w) return x;
      if (x < 0) { s = truncate(s, textWidth(s) + x); x = 0; }
      let col = x, i = y * this.w + x;
      for (const ch of s) {
        if (col >= this.w) break;
        const cw = charWidth(ch);
        if (cw === 2) {
          if (col + 1 >= this.w) {
            this._clobber(i); this.ch[i] = " "; this.st[i] = style; col += 1; i += 1; break;
          }
          this._clobber(i);
          this.ch[i] = ch; this.st[i] = style;
          this.ch[i + 1] = ""; this.st[i + 1] = style; this.cont[i + 1] = 1;
        } else {
          this._clobber(i); this.ch[i] = ch; this.st[i] = style;
        }
        col += cw; i += cw;
      }
      return col;
    }
    fill(x0, y, x1, ch = " ", style = 0) {
      if (y < 0 || y >= this.h) return;
      const a = Math.max(0, x0), b = Math.min(this.w, x1);
      for (let x = a; x < b; x++) {
        const i = y * this.w + x;
        this._clobber(i); this.ch[i] = ch; this.st[i] = style;
      }
    }
  }

  // ------------------------------------------------------------------------
  // 3. Widgets
  // ------------------------------------------------------------------------
  function meterColor(frac) {
    if (frac < 0.50) return S_GREEN;
    if (frac < 0.80) return S_YELLOW;
    if (frac < 0.95) return S_AMBER;
    return S_RED;
  }

  function drawMeter(g, y, x, label, frac, inner, pctText) {
    frac = Math.max(0, Math.min(1, frac));
    const c = meterColor(frac);
    x = g.put(x, y, label, S_DIM);
    x = g.put(x, y, "[", S_FAINT);
    const filled = Math.round(frac * inner);
    x = g.put(x, y, "|".repeat(filled), c);
    x = g.put(x, y, "·".repeat(Math.max(0, inner - filled)), S_FAINT);
    const txt = pctText != null ? pctText : String(Math.round(frac * 100)).padStart(3, " ") + "%";
    x = g.put(x, y, " " + txt, c);
    x = g.put(x, y, "]", S_FAINT);
    return x;
  }

  function drawCommitBar(g, y, x, width, commitGb, maxGb, corruptK, rng, physGb = 31.2) {
    const frac = Math.max(0, Math.min(1, commitGb / Math.max(1e-6, maxGb)));
    const inner = Math.max(8, width - 2);
    const wall = Math.max(2, Math.min(inner - 2, Math.round((physGb / maxGb) * inner)));
    const filled = Math.round(frac * inner);
    const over = commitGb > physGb;
    x = g.put(x, y, "▕", over ? S_RED : S_DIM);
    for (let i = 0; i < inner; i++) {
      let ch = "░", st = S_FAINT;
      if (i === wall) {
        ch = (over && i < filled) ? "▓" : "│";
        st = over ? S_COMMIT_OVER : S_CYAN;
      } else if (i < filled) {
        if (corruptK > 0.25 && rng.next() < 0.22 * corruptK) {
          ch = rng.choice(CORRUPT_CHARS);
          st = rng.choice([S_RED, S_MAGENTA, S_INVERT]);
        } else if (i > wall) {
          ch = (commitGb < 74.0 || i % 2 === 0) ? "█" : "▓";
          st = (commitGb >= 68.0 && i >= inner - 3) ? S_COMMIT_OVER : S_RED;
        } else if (i >= Math.floor(wall * 0.80)) {
          ch = "█"; st = S_AMBER;
        } else {
          ch = "█"; st = over ? S_AMBER : S_GREEN;
        }
      }
      x = g.put(x, y, ch, st);
    }
    const endCh = (commitGb >= 74.0 && corruptK > 0.2) ? "▓" : "▏";
    x = g.put(x, y, endCh, commitGb >= 74.0 ? S_COMMIT_OVER : (over ? S_RED : S_DIM));
    return x;
  }

  function drawBar(g, y, x0, width, frac, level, rng, ghost) {
    frac = Math.max(0, Math.min(1, frac));
    if (level === 1) {
      const inner = Math.max(8, Math.min(width - 12, 26));
      let x = g.put(x0, y, "[", S_DIM);
      const filled = Math.round(frac * inner);
      x = g.put(x, y, "#".repeat(filled), S_AMBER);
      x = g.put(x, y, "-".repeat(inner - filled), S_DIM);
      x = g.put(x, y, "]  ", S_DIM);
      g.put(x, y, String(Math.floor(frac * 100)).padStart(3, " ") + "%", S_AMBER);
      return;
    }
    if (level === 2) {
      const inner = Math.max(16, width - 14);
      let x = g.put(x0, y, "▕", S_DIM);
      const filled = Math.round(frac * inner);
      const ghostCells = Math.max(0, Math.round(ghost * inner) - filled);
      if (ghostCells) x = g.put(x, y, "░".repeat(ghostCells), S_FAINT);
      const head = (filled > 0 && filled < inner) ? 1 : 0;
      x = g.put(x, y, "█".repeat(Math.max(0, filled - head)), S_BLOCK);
      if (head) x = g.put(x, y, "▓", S_HEAD);
      x = g.put(x, y, "░".repeat(Math.max(0, inner - filled)), S_FAINT);
      x = g.put(x, y, "▏ ", S_DIM);
      g.put(x, y, (frac * 100).toFixed(1).padStart(5, " ") + "%", S_AMBER);
      return;
    }
    const inner = Math.max(20, width - 16);
    let x = g.put(x0, y, "▕", S_RED);
    const f = Math.max(0, Math.min(1, frac + rng.uniform(-0.06, 0.06)));
    const edge = Math.floor(f * inner);
    const cut = (rng.next() < 0.25 && edge > 4) ? rng.randrange(1, Math.max(2, edge - 1)) : -1;
    for (let i = 0; i < inner; i++) {
      if (i === cut) { x = g.put(x, y, " ", S_BASE); continue; }
      if (i < edge) {
        const rv = rng.next();
        if (rv < 0.14) x = g.put(x, y, " ", S_BASE);
        else if (rv < 0.36) x = g.put(x, y, rng.choice(CORRUPT_CHARS), rng.choice([S_MAGENTA, S_TEAL, S_RED]));
        else x = g.put(x, y, "█", S_BLOCK);
      } else {
        if (rng.next() < 0.05) x = g.put(x, y, rng.choice(CORRUPT_CHARS), S_FAINT);
        else x = g.put(x, y, "░", S_FAINT);
      }
    }
    x = g.put(x, y, "▏ ", S_RED);
    const pct = rng.next() < 0.28 ? rng.choice(CORRUPT_PCT) : (frac * 100).toFixed(1).padStart(6, " ") + "%";
    g.put(x, y, pct, S_RED);
  }

  function drawModal(g, x0, y0, w, title, lines, code, buttons, corruptK, rng) {
    const h = lines.length + 4;
    w = Math.max(28, Math.min(g.w - 4, w));
    x0 = Math.max(1, Math.min(g.w - w - 2, x0));
    y0 = Math.max(1, Math.min(g.h - h - 1, y0));
    for (let sy = y0 + 1; sy < Math.min(g.h, y0 + h + 1); sy++) {
      for (let sx = x0 + 2; sx < Math.min(g.w, x0 + w + 2); sx++) {
        const idx = sy * g.w + sx;
        if (!g.cont[idx]) g.st[idx] = S_SHADOW;
      }
    }
    for (let yy = y0; yy < Math.min(g.h, y0 + h); yy++) g.fill(x0, yy, x0 + w, " ", S_MODAL_BG);
    const hz = (corruptK > 0.35 && rng.next() < corruptK) ? rng.choice(["═", "─", "▓", "▒"]) : "═";
    g.put(x0, y0, "╔" + hz.repeat(w - 2) + "╗", S_MODAL_BORDER);
    for (let yy = y0 + 1; yy < y0 + h - 1; yy++) {
      g.put(x0, yy, "║", S_MODAL_BORDER);
      g.put(x0 + w - 1, yy, "║", S_MODAL_BORDER);
    }
    g.put(x0, y0 + h - 1, "╚" + hz.repeat(w - 2) + "╝", S_MODAL_BORDER);
    const tStr = ` [!] ${title} (${code}) `;
    g.fill(x0 + 1, y0, x0 + w - 1, " ", S_MODAL_TITLE);
    g.put(x0 + 1, y0, truncate(tStr, w - 6), S_MODAL_TITLE);
    g.put(x0 + w - 4, y0, "[X]", S_MODAL_TITLE);
    for (let i = 0; i < lines.length; i++) {
      const yy = y0 + 1 + i;
      if (yy >= y0 + h - 2) break;
      g.put(x0 + 2, yy, truncate(lines[i], w - 4), S_MODAL_BG);
    }
    const by = y0 + h - 2;
    const bx = x0 + Math.max(2, Math.floor((w - textWidth(buttons)) / 2));
    g.put(bx, by, truncate(buttons, w - 4), corruptK > 0.2 ? S_ALERT_BAR : S_WARN_BAR);
  }

  // ------------------------------------------------------------------------
  // 4. Glitch Engine (Grid-Level)
  // ------------------------------------------------------------------------
  function rowVisible(g, y) {
    const out = [], base = y * g.w;
    for (let x = 0; x < g.w; x++) {
      const i = base + x;
      if (g.cont[i]) continue;
      const ch = g.ch[i];
      if (ch && ch !== " ") out.push([x, ch, g.st[i]]);
    }
    return out;
  }

  function applyGlitches(g, glitches, te, area, panel) {
    for (const gl of glitches) {
      if (te < gl.t || te >= gl.t + gl.dur) continue;
      const isPanel = PANEL_EFFECTS.has(gl.name);
      if (isPanel && !panel) continue;
      const [top, bot] = isPanel ? panel : area;
      const k = gl.dur > 0 ? Math.min(1, Math.max(0, (te - gl.t) / gl.dur)) : 0;
      const q = Math.floor(te * 15);
      const r = new RNG(hashStr(`${gl.name}@${q}|${gl.seed}|${gl.t.toFixed(4)}`));
      const p = gl.p || {};

      switch (gl.name) {
        case "char_noise": {
          const n = Math.floor((p.peak || 90) * (1 - 0.55 * k));
          for (let j = 0; j < n; j++) {
            g.put(r.randrange(0, g.w), r.randrange(top, bot), r.choice(GLITCH_CHARS), r.choice([S_MAGENTA, S_TEAL, S_RED, S_FAINT]));
          }
          break;
        }
        case "homoglyph": {
          const ratio = p.ratio || 0.3;
          for (let y = top; y < bot; y++) {
            for (const [x, ch, st] of rowVisible(g, y)) {
              if (DATA.homoglyph[ch] && r.next() < ratio) g.put(x, y, DATA.homoglyph[ch], st);
            }
          }
          break;
        }
        case "row_flip": {
          for (let j = 0; j < (p.rows || 2); j++) {
            const y = r.randrange(top, bot);
            const vis = rowVisible(g, y);
            if (vis.length < 4) continue;
            for (let m = 0; m < vis.length; m++) {
              const rev = vis[vis.length - 1 - m];
              g.put(vis[m][0], y, rev[1], rev[2]);
            }
          }
          break;
        }
        case "row_shift": {
          const dx = p.dx || 3;
          for (let j = 0; j < (p.rows || 2); j++) {
            const y = r.randrange(top, bot);
            const vis = rowVisible(g, y);
            if (!vis.length) continue;
            const sh = r.choice([-dx, dx]);
            g.fill(0, y, g.w, " ", S_BASE);
            for (const [x, ch, st] of vis) if (x + sh >= 0 && x + sh < g.w) g.put(x + sh, y, ch, st);
          }
          break;
        }
        case "row_invert": {
          for (let j = 0; j < (p.rows || 1); j++) {
            const y = r.randrange(top, bot);
            for (let x = 0; x < g.w; x++) g.st[y * g.w + x] = S_INVERT;
          }
          break;
        }
        case "scanlines": {
          const step = p.step || 2;
          for (let y = top + (p.phase ? 1 : 0); y < bot; y += step) {
            for (let x = 0; x < g.w; x++) {
              const i = y * g.w + x;
              if (g.st[i] !== S_INVERT && g.st[i] !== S_BLOCK) g.st[i] = S_DIM;
            }
          }
          break;
        }
        case "escape_literal": {
          const s = r.choice(ESCAPE_LITERALS);
          for (let j = 0; j < (p.n || 1); j++) {
            g.put(r.randrange(2, Math.max(3, g.w - s.length - 2)), r.randrange(top, bot), s, r.choice([S_MAGENTA, S_TEAL, S_RED]));
          }
          break;
        }
        case "blackout": {
          const y0 = top + Math.floor((bot - top) * (p.a || 0));
          const y1 = top + Math.floor((bot - top) * (p.b || 0.5));
          for (let y = y0; y < Math.max(y0 + 1, y1); y++) g.fill(0, y, g.w, " ", S_BASE);
          break;
        }
        case "flash": { g.st.fill(S_INVERT); break; }
        case "dim_all": {
          const stDim = (p.factor || 0.5) > 0.4 ? S_DIM : S_FAINT;
          for (let i = 0; i < g.st.length; i++) if (g.st[i] === S_BASE || g.st[i] === S_BRIGHT) g.st[i] = stDim;
          break;
        }
        case "border_melt": {
          const ratio = (p.ratio || 0.45) * (0.35 + 0.65 * k);
          for (let y = top; y < bot; y++) {
            for (const [x, ch] of rowVisible(g, y)) {
              if ((BOX_SET.has(ch) || x <= 1 || x >= g.w - 2) && r.next() < ratio) {
                g.put(x, y, r.choice(MELT_CHARS), r.choice([S_BORDER_HOT, S_RED, S_AMBER, S_FAINT]));
                const drip = r.randint(1, 3);
                for (let dy = 1; dy <= drip; dy++) {
                  if (y + dy < bot && r.next() < 0.7) g.put(x, y + dy, r.choice("│¦░·"), dy === 1 ? S_BORDER_HOT : S_FAINT);
                }
              }
            }
          }
          break;
        }
        case "meter_overflow": {
          const tags = [" [COMMIT 60.4/31.2GB SWAP]", " [COMMIT 77.4/31.2GB LOCK]", " [PAGEFILE_DEAD // IO 100%]", " [9999999% NaN]"];
          for (let j = 0; j < (p.rows || 2); j++) {
            const y = r.randrange(top, bot);
            const x0 = r.randrange(2, Math.max(4, Math.floor(g.w / 4)));
            const span = Math.floor((g.w - x0 - 2) * Math.min(1, 0.45 + 0.65 * k));
            const tag = r.choice(tags);
            const bLen = Math.max(4, span - tag.length);
            const bar = ("█".repeat(Math.floor(span * 0.62)) + "▓".repeat(Math.floor(span * 0.2)) + "▒░".repeat(Math.max(1, Math.floor(span * 0.1)))).slice(0, bLen);
            g.put(x0, y, bar + tag, r.choice([S_RED, S_COMMIT_OVER, S_AMBER, S_INVERT]));
          }
          break;
        }
        case "popup_cascade": {
          const total = Math.max(1, Math.round((p.count || 3) * (0.35 + 0.65 * k)));
          const baseX = p.x || Math.max(6, Math.floor(g.w / 5));
          const baseY = Math.max(top + 1, Math.min(bot - 8, p.y || top + 2));
          const mw = Math.min(g.w - 10, p.w || 54);
          const idx0 = p.modal || 0;
          for (let j = 0; j < total; j++) {
            const m = DATA.modal_pool[(idx0 + j) % DATA.modal_pool.length];
            const px = Math.min(g.w - mw - 3, baseX + j * 4 + r.randint(-1, 1));
            const py = Math.min(bot - 7, baseY + j * 2);
            if (py >= top && py + m.lines.length + 4 <= bot) {
              drawModal(g, px, py, mw, m.title, m.lines, m.code,
                ((idx0 + j) % 2) ? "[ ACCESS DENIED (SUPPRESSED) ]" : "[ Retry (Y) ]  [ Abort (N) ]",
                k * 0.8, r);
            }
          }
          break;
        }
        case "hsync_wave": {
          const amp = (p.amp || 6) * (0.4 + 0.6 * k);
          const freq = p.freq || 0.55;
          const phase = te * 19.0;
          for (let y = top; y < bot; y++) {
            let wave = Math.round(amp * Math.sin(y * freq + phase));
            if (r.next() < 0.28) wave += r.choice([-4, -2, 2, 4]);
            if (wave === 0) continue;
            const vis = rowVisible(g, y);
            if (!vis.length) continue;
            g.fill(0, y, g.w, " ", S_BASE);
            for (const [x, ch, st] of vis) if (x + wave >= 0 && x + wave < g.w) g.put(x + wave, y, ch, st);
            if (wave > 0) g.put(0, y, "░▒".slice(0, Math.min(2, wave)), S_FAINT);
            else g.put(Math.max(0, g.w + wave), y, "▒░".slice(0, Math.min(2, -wave)), S_FAINT);
          }
          break;
        }
        case "hex_flood": {
          const nRows = Math.max(2, Math.round((p.rows || 5) * (0.4 + 0.6 * k)));
          const y0 = r.randrange(top, Math.max(top + 1, bot - nRows));
          const tags = ["COMMIT_77.4_31.2GB", "PAGEFILE_0xC000012D", "S0IX_EXEC_STATE_507", "LKD_0x193_DWM_LOCK", "LKD_0x1CC_EXRES_TMO", "SHUTDOWN_0x000005B4"];
          for (let j = 0; j < nRows && y0 + j < bot; j++) {
            const addr = (0x03a00000 + (((y0 + j) * 0x1040 + Math.floor(te * 256)) & 0xffffff)).toString(16).toUpperCase().padStart(8, "0");
            let hb = [];
            for (let b = 0; b < 12; b++) hb.push(r.randrange(0, 256).toString(16).toUpperCase().padStart(2, "0"));
            const line = `  0xFFFFF800${addr}: ${hb.join(" ")}  |${tags[(j + Math.floor(te * 7)) % tags.length]}|`;
            const st = (j === 0 && r.next() < 0.4) ? S_INVERT : (j % 2 === 0 ? S_RED : S_FAINT);
            g.put(1, y0 + j, truncate(line, g.w - 2), st);
          }
          break;
        }
        case "panel_noise": {
          const n = Math.floor((p.peak || 26) * (0.35 + 0.65 * k));
          for (let j = 0; j < n; j++) {
            g.put(r.randrange(0, g.w), r.randrange(top, bot), r.choice(PANEL_JUNK), r.choice([S_MAGENTA, S_TEAL, S_RED, S_INVERT]));
          }
          break;
        }
        case "panel_corrupt": {
          const ratio = (p.ratio || 0.35) * (0.4 + 0.6 * k);
          const pool = p.chars || ".·:;'/\\|-_=+";
          for (let y = top; y < bot; y++) {
            for (const [x, _ch, st] of rowVisible(g, y)) if (r.next() < ratio) g.put(x, y, r.choice(pool), st);
          }
          break;
        }
        case "panel_garbage": {
          const y = r.randrange(top, Math.max(top + 1, bot));
          const ln = r.randint(6, Math.max(7, Math.floor(g.w / 4)));
          const x0 = r.randrange(0, Math.max(1, g.w - ln));
          let s = "";
          for (let j = 0; j < ln; j++) s += "0123456789ABCDEF"[r.randrange(0, 16)];
          g.put(x0, y, s, r.choice([S_RED, S_MAGENTA, S_INVERT]));
          break;
        }
        case "panel_invert": {
          for (let j = 0; j < (p.rows || 2); j++) {
            const y = r.randrange(top, bot);
            for (let x = 0; x < g.w; x++) g.st[y * g.w + x] = S_INVERT;
          }
          break;
        }
        case "panel_dim": {
          for (let y = top; y < bot; y++) {
            for (let x = 0; x < g.w; x++) {
              const i = y * g.w + x;
              if (g.st[i] === S_BASE || g.st[i] === S_BRIGHT || g.st[i] === S_DIM) g.st[i] = S_FAINT;
            }
          }
          break;
        }
      }
    }
  }

  // ------------------------------------------------------------------------
  // 5. Scene State Machine & Renderer
  // ------------------------------------------------------------------------
  const PHYS_TOTAL_GB = 31.2;
  const COMMIT_MAX_GB = 77.4;
  const RES_HZ = 4.0;

  const extraLogs = DATA.scenes.map(() => []);
  const promptAnswers = DATA.scenes.map(() => ({}));

  function locateScene(globalT) {
    for (let i = 0; i < DATA.scenes.length; i++) {
      const sc = DATA.scenes[i];
      if (globalT >= sc.start && globalT < sc.end) return [i, sc, globalT - sc.start];
    }
    const last = DATA.scenes.length - 1;
    return [last, DATA.scenes[last], DATA.scenes[last].duration];
  }

  function teffOf(sc, lt) {
    if (!sc.holds.length) return lt;
    let real = 0, eff = 0;
    for (const [a, b] of sc.holds) {
      if (lt < a) return eff + (lt - real);
      eff += (a - real);
      if (lt < b) return eff;
      real = b;
    }
    return eff + (lt - real);
  }

  function isFrozenAt(sc, lt) {
    for (const [a, b] of sc.holds) if (lt > a && lt < b) return true;
    return false;
  }

  function panelSev(sc, te) {
    let s = 0;
    for (const gl of sc.glitches) {
      if (PANEL_EFFECTS.has(gl.name) && te >= gl.t && te < gl.t + gl.dur) {
        s = Math.max(s, gl.p && gl.p.amp != null ? gl.p.amp : 1.0);
      }
    }
    return Math.min(1, s);
  }

  function memTelemetry(sc, te) {
    const q = Math.floor(te * RES_HZ) / RES_HZ;
    const gt = sc.start + q;
    const s = sc.res_seed;
    let phys, commit, rate, dio;
    if (gt < 7.0) {
      phys = 10.2 + gt * 0.09 + 0.06 * Math.sin(q * 0.8 + s);
      commit = 11.6 + gt * 0.16;
      rate = 12.4 + 2.4 * Math.sin(q * 1.1);
      dio = 4 + Math.floor(3 * Math.abs(Math.sin(q * 0.7 + s)));
    } else if (gt < 19.0) {
      const el = gt - 7.0, frac = el / 12.0;
      phys = Math.min(30.4, 10.8 + frac * 19.4 + 0.12 * Math.sin(q * 1.3 + s));
      commit = 12.7 + el * 1.84 + 0.25 * Math.sin(q * 0.9);
      rate = 150.4 + 6.2 * Math.sin(q * 1.37 + s);
      dio = Math.min(92, Math.floor(22 + frac * 68));
    } else if (gt < 65.0) {
      const el = gt - 19.0;
      phys = Math.min(30.9, 30.4 + el * 0.25);
      commit = Math.min(74.2, 34.8 + el * 0.855 + 0.30 * Math.sin(q * 0.7));
      rate = 152.1 + 5.8 * Math.sin(q * 1.37 + s);
      dio = Math.min(99, 92 + Math.floor(6 * Math.abs(Math.sin(q * 1.1 + s))));
    } else {
      const el = gt - 65.0;
      phys = 30.9;
      commit = Math.min(COMMIT_MAX_GB, 74.1 + el * 0.56);
      rate = commit < 77.35 ? (154.2 + 4.4 * Math.sin(q * 2.1 + s)) : 0.0;
      dio = 100;
    }
    const suppress = (gt >= 65.0 || sc.name === "abandon" || sc.name === "cascade") ? 1 : 0;
    return { phys, commit, rate, dio, suppress, gt, q };
  }

  function formatTs(sc, te) {
    let jump = 0;
    for (const [t, v] of sc.ts_jumps) if (te >= t) jump += v;
    const d = new Date(DATA.ts_base_ms + (sc.start + te + jump) * 1000);
    const p2 = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
  }

  function renderJumpScare(g, te) {
    if (te < 0.10) { for (let y = 0; y < g.h; y++) g.fill(0, y, g.w, "█", S_FLASH); return; }
    if (te >= 2.70) return;
    if (te >= 2.55) {
      const u = (te - 2.55) / 0.15;
      if ((u < 0.25) || (u >= 0.42 && u < 0.62) || (u >= 0.78 && u < 0.94)) {
        for (let y = 0; y < g.h; y++) g.fill(0, y, g.w, "█", S_FLASH);
      }
      return;
    }
    const sc = DATA.scare, sw = sc.w, sh = sc.h;
    const k = Math.max(0, Math.min(1, (te - 0.10) / 2.45));
    const sev = Math.pow(k, 2.6);
    const gw = 46, gh = 15;
    const stepX = [0, 29, 53, 88], stepY = [0, 5, 10, 15];
    const stepIdx = Math.max(0, 2 - Math.floor(Math.max(0, (te - 0.10) * 12)));
    const baseX = 4 + stepX[stepIdx], baseY = 3 + stepY[stepIdx];

    const tearR = new RNG(hashStr("tears|" + Math.floor(te * 12)));
    for (let b = 0; b < Math.floor(sev * 10); b++) {
      const ty = tearR.randrange(0, g.h), tx = tearR.randrange(0, g.w - 18);
      g.fill(tx, ty, tx + tearR.randrange(12, 42), "▒", S_SCARE_DIM);
    }

    const dripK = Math.max(0, Math.min(1, (te - 0.35) / 0.75));
    if (stepIdx === 0 && dripK > 0.01) {
      const drng = new RNG(918273);
      for (let cx = 0; cx < gw; cx++) {
        let lowY = -1;
        const sx = Math.floor((cx * sw) / gw);
        for (let cy = gh - 1; cy >= 0; cy--) {
          if (sc.rows[Math.floor((cy * sh) / gh)][sx] !== ".") { lowY = cy; break; }
        }
        const lean = drng.uniform(-0.18, 0.18);
        if (lowY < 0) continue;
        const maxDy = Math.floor((g.h - (baseY + lowY)) * dripK);
        let dxAcc = 0;
        for (let dy = 1; dy <= maxDy; dy++) {
          if (dy % 2 === 0) dxAcc += lean + drng.uniform(-0.22, 0.22);
          const gx = baseX + cx + Math.round(dxAcc), gy = baseY + lowY + dy;
          if (gx >= 0 && gx < g.w && gy >= 0 && gy < g.h) {
            g.put(gx, gy, "█", dy < 4 ? S_SCARE_BODY : (dy < 10 ? S_SCARE_DIM : S_SCARE_DRIP));
          }
        }
      }
    }

    const sliceOn = te >= 0.40;
    const srng = new RNG(hashStr("slice|" + Math.floor(te * 12)));
    const drawCopy = (ox, oy, isMain) => {
      for (let cy = 0; cy < gh; cy++) {
        const rowShift = (!isMain && sliceOn && srng.next() < 0.35 + 0.45 * sev) ? srng.randint(-4, 4) : 0;
        const sy = Math.floor((cy * sh) / gh);
        for (let cx = 0; cx < gw; cx++) {
          const sx = Math.floor((cx * sw) / gw);
          const px = sc.rows[sy][sx];
          if (px === ".") continue;
          const gx = ox + cx + rowShift, gy = oy + cy;
          if (gx < 0 || gx >= g.w || gy < 0 || gy >= g.h) continue;
          if (!isMain && sc.mask[Math.min(sc.mh - 1, Math.floor(sy / 4))][Math.min(sc.mw - 1, Math.floor(sx / 6))]) continue;
          g.put(gx, gy, "█", isMain ? (px === "E" ? S_SCARE_RED : S_SCARE_BODY) : S_SCARE_DIM);
        }
      }
    };
    for (let i = 3; i > stepIdx; i--) drawCopy(4 + stepX[i], 3 + stepY[i], false);
    drawCopy(baseX, baseY, true);

    if (te >= 2.27) {
      const u = Math.min(1, (te - 2.27) / 0.28);
      const keepH = Math.max(1, Math.round(g.h / Math.pow(1 + 13 * u, 1.3)));
      const mid = Math.floor(g.h / 2);
      const y0 = mid - Math.floor(keepH / 2), y1 = y0 + keepH;
      for (let y = 0; y < g.h; y++) if (y < y0 || y >= y1) g.fill(0, y, g.w, " ", S_BASE);
      if (keepH <= 2) g.fill(0, mid, g.w, "─", S_FLASH);
    }
  }

  function renderFrame(g, globalT, hudText) {
    g.clear();
    const [scIdx, sc, lt] = locateScene(globalT);
    const te = teffOf(sc, lt);
    const w = g.w, h = g.h;

    if (sc.name === "jumpscare") {
      renderJumpScare(g, te);
      return { scIdx, sc, lt, te, frozen: false, mem: memTelemetry(sc, te) };
    }

    const mem = memTelemetry(sc, te);
    const k = panelSev(sc, te);
    const prng = new RNG(Math.floor(sc.res_seed * 31337) + Math.floor(mem.q * 1000) + 7);
    let top = 0, bot = h, panel = null;

    if (sc.bare) {
      top = 1; bot = h - 1;
    } else {
      top = 5; bot = h - 5; panel = [0, 5];

      const overPhys = mem.commit > PHYS_TOTAL_GB;
      const barSt = (mem.commit >= 60.0 || k > 0.5 || mem.suppress) ? S_ALERT_BAR : (overPhys ? S_WARN_BAR : S_HEADER_BAR);
      g.fill(0, 0, w, " ", barSt);
      let sidTxt = "NT AUTHORITY\\SYSTEM";
      if (mem.commit >= 70.0 || sc.name === "abandon" || sc.name === "cascade") sidTxt = "UNAVAILABLE[0x8001012D]";
      else if (mem.commit >= 55.0 || sc.name === "identity") sidTxt = "AUTH_ERR[NO_MEM]";
      const rightBanner = ` │ ${formatTs(sc, te)} │ ${sc.title || "DIAGNOSTIC"} `;
      const rwB = textWidth(rightBanner);
      const leftBanner = ` ▐ NT-SCM // PID[14020] │ SID:${sidTxt} │ SUPPRESS:${mem.suppress}`;
      g.put(0, 0, truncate(leftBanner, Math.max(12, w - rwB - 1)), barSt);
      g.put(Math.max(2, w - rwB), 0, rightBanner, barSt);

      const c1 = Math.max(31, Math.min(37, Math.floor(w * 0.30)));
      const c2 = Math.max(c1 + 42, Math.min(w - 30, Math.floor(w * 0.72)));
      const bSt = (mem.commit >= 60.0 || k > 0.4) ? S_BORDER_HOT : S_BORDER;
      for (const yy of [1, 2, 3]) {
        g.put(0, yy, "║", bSt); g.put(c1, yy, "║", bSt);
        g.put(c2, yy, "║", bSt); g.put(w - 1, yy, "║", bSt);
      }

      const q = mem.q, s = sc.res_seed;
      let cpu = 48.0 + 22.0 * (0.55 * Math.sin(q * 0.37 + s) + 0.30 * Math.sin(q * 1.13 + s * 1.7) + 0.15 * Math.sin(q * 2.71 + s * 0.3));
      let gpu = 93.5 + 5.0 * (0.60 * Math.sin(q * 0.29 + s * 2.1) + 0.40 * Math.sin(q * 0.83 + s * 0.7));
      let ram = Math.min(99.0, (mem.phys / PHYS_TOTAL_GB) * 100.0);
      if (k > 0.01) {
        const rr = new RNG(Math.floor(s) * 7919 + Math.floor(q * 1000) + 13);
        cpu += rr.uniform(-60, 60) * k; gpu += rr.uniform(-95, 5) * k; ram += (100 - ram) * k;
      }
      cpu = Math.max(0, Math.min(100, cpu));
      gpu = Math.max(0, Math.min(100, gpu));
      ram = Math.max(0, Math.min(100, ram));
      const mInner = Math.max(8, c1 - 14);
      drawMeter(g, 1, 2, "CPU", cpu / 100, mInner);
      drawMeter(g, 2, 2, "GPU", gpu / 100, mInner);
      const ramInner = Math.max(5, c1 - 24);
      const ramPct = mem.phys >= 30.85 ? 99 : Math.round(ram);
      const rx = drawMeter(g, 3, 2, "RAM", ramPct / 100, ramInner, String(ramPct).padStart(3, " ") + "%");
      g.put(rx, 3, truncate(` ${mem.phys.toFixed(1).padStart(4, " ")}/31.2G`, Math.max(0, c1 - rx)),
        mem.phys >= 30.85 ? S_RED : (mem.phys >= 28.0 ? S_AMBER : S_DIM));

      const midW = c2 - c1 - 3;
      let mx = c1 + 2;
      if (k > 0.65 && prng.next() < 0.5) {
        mx = g.put(mx, 1, "COMMIT:", S_RED);
        mx = g.put(mx, 1, " 999.9 ", S_COMMIT_OVER);
        g.put(mx, 1, truncate("/ 31.2 GB [SWAP_OVERFLOW +NaN]", Math.max(0, c2 - 1 - mx)), S_RED);
      } else if (overPhys) {
        mx = g.put(mx, 1, "COMMIT:", S_DIM);
        mx = g.put(mx, 1, ` ${mem.commit.toFixed(1).padStart(4, " ")} `, S_COMMIT_OVER);
        const tail = mem.commit >= 77.35
          ? (midW >= 54 ? "/ 31.2 GB [PAGEFILE_LOCKED // DISK_IO 100%]" : "/ 31.2G [PAGEFILE_LOCKED // IO 100%]")
          : (midW >= 54 ? `/ 31.2 GB [SWAP THRASHING +${mem.rate.toFixed(1)} MB/s]` : `/ 31.2G [SWAP THRASH +${mem.rate.toFixed(1)}M/s]`);
        g.put(mx, 1, truncate(tail, Math.max(0, c2 - 1 - mx)), S_RED);
      } else {
        g.put(mx, 1, truncate(`COMMIT: ${mem.commit.toFixed(1).padStart(4, " ")} / 31.2 GB (+${mem.rate.toFixed(1)} MB/s)`, midW),
          mem.commit >= 25.0 ? S_AMBER : S_CYAN);
      }
      g.put(c1 + 2, 2, "VM_MAP: ", S_DIM);
      const bx = drawCommitBar(g, 2, c1 + 10, Math.max(10, midW - 15), mem.commit, COMMIT_MAX_GB, k, prng, PHYS_TOTAL_GB);
      const pctV = Math.round((mem.commit / PHYS_TOTAL_GB) * 100);
      g.put(bx + 1, 2, String(pctV).padStart(3, " ") + "%", pctV >= 190 ? S_COMMIT_OVER : (pctV > 100 ? S_RED : S_AMBER));

      const dioStr = String(mem.dio).padStart(2, "0");
      let pfTxt, pfSt;
      if (mem.gt < 7.0) { pfTxt = `PGFILE: AUTO_MANAGED [OK]    │ DISK_IO: ${dioStr}%`; pfSt = S_DIM; }
      else if (mem.gt < 19.0) { pfTxt = `PGFILE: SWAP_OUT [ACTIVE]    │ DISK_IO: ${dioStr}%`; pfSt = mem.phys >= 28 ? S_AMBER : S_CYAN; }
      else if (mem.gt < 65.0) { pfTxt = `PGFILE: LOW_COMMIT [7000]    │ DISK_IO: ${dioStr}%`; pfSt = mem.commit >= 55 ? S_RED : S_AMBER; }
      else { pfTxt = "PGFILE: EXHAUSTED [C000012D] │ DISK_IO:100%"; pfSt = S_RED; }
      g.put(c1 + 2, 3, truncate(pfTxt, midW), pfSt);

      const rw = w - c2 - 3;
      let monTxt, monSt;
      if (mem.gt >= 75 || sc.name === "cascade") { monTxt = "DISP : DWM_DEADLOCK [0x193]"; monSt = S_RED; }
      else if (mem.gt >= 65 || sc.name === "abandon") { monTxt = "DISP : MODE_ENUM [0x141 TDR]"; monSt = S_RED; }
      else if (mem.gt >= 49 || sc.name === "identity") { monTxt = "DISP : S0ix_RESUME [182ms]"; monSt = S_AMBER; }
      else if (mem.gt >= 35 || sc.name === "timeout") { monTxt = "DISP : NO_INFO [Win32k#263]"; monSt = S_AMBER; }
      else { monTxt = "DISP : 3200x2000@60 [OK]"; monSt = S_DIM; }
      g.put(c2 + 2, 1, truncate(monTxt, rw), monSt);

      const filledPg = Math.round((mem.commit / COMMIT_MAX_GB) * 10);
      let pgBar = "";
      for (let pi = 0; pi < 10; pi++) pgBar += pi < filledPg ? ((k > 0.4 && prng.next() < 0.35) ? prng.choice("╬▓?") : "█") : "·";
      const addrHi = (0xfffff800 + (Math.floor(mem.q * 16) % 0xff)).toString(16).toUpperCase();
      g.put(c2 + 2, 2, truncate(`PG_TBL: 0x${addrHi} [${pgBar}]`, rw), filledPg >= 8 ? S_RED : S_TEAL);

      let obsTxt, obsSt;
      if (mem.gt >= 75 || sc.name === "cascade") { obsTxt = "PWR  : SHUTDOWN_HANG [0x1CC]"; obsSt = S_RED; }
      else if (mem.suppress) { obsTxt = "INPUT: BLOCKED [SUPPRESS=1]"; obsSt = S_RED; }
      else if (mem.gt >= 49 || sc.name === "identity") { obsTxt = "WAKE : SET_EXEC_STATE [507]"; obsSt = S_AMBER; }
      else { obsTxt = "SESS : 0 [SERVICE_HOST]"; obsSt = S_DIM; }
      g.put(c2 + 2, 3, truncate(obsTxt, rw), obsSt);

      g.put(0, 4, "╠" + "═".repeat(c1 - 1) + "╩" + "═".repeat(c2 - c1 - 1) + "╩" + "═".repeat(w - c2 - 2) + "╣", bSt);

      const span = Math.max(1, bot - top);
      const thumbY = top + Math.min(span - 1, Math.floor((mem.commit / COMMIT_MAX_GB) * (span - 1)));
      for (let yy = top; yy < h - 2; yy++) {
        g.put(0, yy, "║", bSt); g.put(w - 1, yy, "║", bSt);
        if (yy >= top && yy < bot) g.put(w - 2, yy, yy === thumbY ? "█" : "░", (yy === thumbY && mem.commit >= 55) ? S_RED : S_FAINT);
      }
      g.put(0, h - 2, "╠" + "═".repeat(w - 2) + "╣", bSt);
    }

    const allLogs = extraLogs[scIdx].length ? sc.logs.concat(extraLogs[scIdx]).sort((a, b) => a[0] - b[0]) : sc.logs;
    let lastClear = -Infinity;
    for (const c of sc.clears) if (c <= te) lastClear = c;
    const vis = allLogs.filter(x => x[0] > lastClear && x[0] <= te);
    const rows = [];
    for (const [, text, st] of vis) {
      const parts = text.split("\n");
      rows.push([parts[0], st]);
      for (let pi = 1; pi < parts.length; pi++) rows.push([parts[pi].startsWith(" ") ? parts[pi] : "       " + parts[pi], S_DIM]);
    }
    const nRows = bot - top;
    const sliced = sc.log_align === "top" ? rows.slice(0, nRows) : rows.slice(-nRows);
    const baseY = sc.log_align === "top" ? top : bot - sliced.length;
    const maxW = sc.bare ? w - 4 : w - 5;
    for (let i = 0; i < sliced.length; i++) g.put(2, baseY + i, truncate(sliced[i][0], maxW), sliced[i][1]);
    if (sc.bare && sc.cursor && ((te % 1.0) < 0.5)) g.put(2, Math.min(bot - 1, 1 + sliced.length), "█", S_DIM);

    if (!sc.bare) {
      const labelY = h - 4, barY = h - 3, bw = w - 6;
      const jrng = new RNG((Math.floor(te * 12) * 2654435761) ^ DATA.seed);
      let bar = null;
      for (const b of sc.bars) if (b.t0 <= te) bar = b;
      let pr = null, prIdx = -1;
      for (let i = 0; i < sc.prompts.length; i++) {
        const p = sc.prompts[i];
        if (te >= p.t0 && te < p.t1 + 0.9) { pr = p; prIdx = i; break; }
      }
      const barFracAt = (b, t) => {
        const segs = b.segs;
        if (t <= segs[0][0]) return segs[0][1];
        if (t >= segs[segs.length - 1][0]) return segs[segs.length - 1][1];
        for (let i = 0; i < segs.length - 1; i++) {
          const [ta, fa] = segs[i], [tb, fb] = segs[i + 1];
          if (t >= ta && t <= tb) return tb <= ta ? fb : fa + (fb - fa) * (t - ta) / (tb - ta);
        }
        return segs[segs.length - 1][1];
      };
      const barLevelAt = (b, t) => {
        let lv = b.level;
        for (const [tt, l] of b.levels) if (t >= tt) lv = l;
        return lv;
      };

      if (pr) {
        let x = g.put(2, labelY, "» ", S_YELLOW);
        x = g.put(x, labelY, pr.text + "  ", S_YELLOW);
        const ans = promptAnswers[scIdx][prIdx] ? promptAnswers[scIdx][prIdx].toUpperCase() : (te >= pr.t1 ? pr.auto : "");
        if (ans) g.put(x, labelY, ans, S_BRIGHT);
        if (bar) drawBar(g, barY, 2, bw, barFracAt(bar, te), barLevelAt(bar, te), jrng, barFracAt(bar, Math.max(bar.t0, te - 0.45)));
      } else if (bar && te < bar.t1 + 1.4) {
        if (te < bar.t1) {
          const lv = barLevelAt(bar, te);
          g.put(2, labelY, truncate(bar.label, bw), lv < 3 ? S_AMBER : S_RED);
          drawBar(g, barY, 2, bw, barFracAt(bar, te), lv, jrng, barFracAt(bar, Math.max(bar.t0, te - 0.45)));
        } else {
          g.put(2, labelY, truncate(bar.tail, bw), S_AMBER);
        }
      }

      const mrng = new RNG((Math.floor(te * 8) * 1664525) ^ DATA.seed);
      for (let i = 0; i < sc.modals.length; i++) {
        const m = sc.modals[i];
        if (te >= m.t0 && te < m.t1) {
          const maxLine = Math.max(...m.lines.map(textWidth));
          const mw = Math.min(w - 10, Math.max(46, maxLine + 8));
          const mx = Math.max(4, Math.floor((w - mw) / 2) + ((i % 3) - 1) * 5);
          const my = Math.max(top + 1, Math.min(bot - m.lines.length - 5, top + 2 + i * 2));
          const mk = Math.min(1, (te - m.t0) / Math.max(0.1, m.t1 - m.t0));
          drawModal(g, mx, my, mw, m.title, m.lines, m.code, m.buttons,
            (sc.name === "identity" || sc.name === "abandon" || sc.name === "cascade") ? 0.35 * mk : 0, mrng);
        }
      }

      let stTxt = "未检测到任何用户。";
      for (const [tt, txt] of sc.status) if (te >= tt) stTxt = txt;
      const bSt = (mem.commit >= 60.0 || mem.suppress) ? S_BORDER_HOT : S_BORDER;
      g.put(0, h - 1, "╚═[ ", bSt);
      const endX = g.put(4, h - 1, truncate(stTxt, w - 42), mem.suppress ? S_RED : (mem.commit >= 48 ? S_AMBER : S_DIM));
      g.put(endX, h - 1, " ]" + "═".repeat(Math.max(1, w - endX - 3)), bSt);
      g.put(w - 1, h - 1, "╝", bSt);
      const rightTag = hudText ? `[ ${hudText} ]` : (mem.suppress ? "[ F1:DIAG  F3:INPUT_LOCKED  ESC:MENU ]" : "[ F1:DIAG  F3:INTERVENE  ESC:MENU ]");
      const rx = Math.max(endX + 3, w - textWidth(rightTag) - 2);
      if (rx + textWidth(rightTag) < w) g.put(rx, h - 1, rightTag, hudText ? S_AMBER : (mem.suppress ? S_RED : S_DIM));
    }

    applyGlitches(g, sc.glitches, te, [top, bot], panel);
    return { scIdx, sc, lt, te, frozen: isFrozenAt(sc, lt), mem };
  }

  // ------------------------------------------------------------------------
  // 6. Canvas 2D Geometric Terminal Renderer + CRT Post-Pass
  // ------------------------------------------------------------------------
  const BOX_SPEC = {
    "─": [1,1,0,0], "│": [0,0,1,1],
    "┌": [0,1,0,1], "┐": [1,0,0,1], "└": [0,1,1,0], "┘": [1,0,1,0],
    "├": [0,1,1,1], "┤": [1,0,1,1], "┬": [1,1,0,1], "┴": [1,1,1,0], "┼": [1,1,1,1],
    "═": [2,2,0,0], "║": [0,0,2,2],
    "╔": [0,2,0,2], "╗": [2,0,0,2], "╚": [0,2,2,0], "╝": [2,0,2,0],
    "╠": [0,2,2,2], "╣": [2,0,2,2], "╦": [2,2,0,2], "╩": [2,2,2,0], "╬": [2,2,2,2],
  };
  const BLOCK_RECT = {
    "█": [0, 0, 1, 1], "▀": [0, 0, 1, 0.5], "▄": [0, 0.5, 1, 1],
    "▌": [0, 0, 0.5, 1], "▐": [0.5, 0, 1, 1], "▏": [0, 0, 0.25, 1], "▕": [0.75, 0, 1, 1],
  };
  const SHADE_ALPHA = { "░": 0.24, "▒": 0.50, "▓": 0.78 };

  const CELL_W = 10, CELL_H = 20;
  const canvas = document.getElementById("termCanvas");
  const ctx = canvas.getContext("2d", { alpha: false });
  canvas.width = DATA.cols * CELL_W;
  canvas.height = DATA.rows * CELL_H;
  const offCanvas = document.createElement("canvas");
  offCanvas.width = canvas.width;
  offCanvas.height = canvas.height;
  const offCtx = offCanvas.getContext("2d", { alpha: false });

  function paintGrid(targetCtx, g) {
    targetCtx.fillStyle = DATA.bg;
    targetCtx.fillRect(0, 0, canvas.width, canvas.height);
    targetCtx.textBaseline = "middle";
    const fontReg = `14px "Cascadia Mono","Consolas","Microsoft YaHei",monospace`;
    const fontBold = `bold 14px "Cascadia Mono","Consolas","Microsoft YaHei",monospace`;
    let curFont = "";

    for (let y = 0; y < g.h; y++) {
      const py = y * CELL_H, base = y * g.w;
      for (let x = 0; x < g.w; x++) {
        const i = base + x;
        if (g.cont[i]) continue;
        const ch = g.ch[i];
        const pal = DATA.palette[g.st[i]] || DATA.palette[0];
        const px = x * CELL_W;
        const wide = (x + 1 < g.w && g.cont[i + 1]);
        const cw = wide ? CELL_W * 2 : CELL_W;

        if (pal.bg !== DATA.bg) {
          targetCtx.fillStyle = pal.bg;
          targetCtx.fillRect(px, py, cw, CELL_H);
        }
        if (!ch || ch === " ") continue;

        if (BLOCK_RECT[ch]) {
          const [rx0, ry0, rx1, ry1] = BLOCK_RECT[ch];
          targetCtx.fillStyle = pal.fg;
          targetCtx.fillRect(px + rx0 * CELL_W, py + ry0 * CELL_H, (rx1 - rx0) * CELL_W + 0.5, (ry1 - ry0) * CELL_H + 0.5);
        } else if (SHADE_ALPHA[ch]) {
          targetCtx.save();
          targetCtx.globalAlpha = SHADE_ALPHA[ch];
          targetCtx.fillStyle = pal.fg;
          targetCtx.fillRect(px, py, CELL_W, CELL_H);
          targetCtx.restore();
        } else if (BOX_SPEC[ch]) {
          const [l, r, u, d] = BOX_SPEC[ch];
          targetCtx.fillStyle = pal.fg;
          const mx = px + CELL_W / 2, my = py + CELL_H / 2;
          const drawH = (x0, x1, kind) => {
            if (kind === 1) targetCtx.fillRect(x0, my - 1, x1 - x0, 2);
            else if (kind === 2) { targetCtx.fillRect(x0, my - 3, x1 - x0, 2); targetCtx.fillRect(x0, my + 1, x1 - x0, 2); }
          };
          const drawV = (y0, y1, kind) => {
            if (kind === 1) targetCtx.fillRect(mx - 1, y0, 2, y1 - y0);
            else if (kind === 2) { targetCtx.fillRect(mx - 2.5, y0, 2, y1 - y0); targetCtx.fillRect(mx + 1, y0, 2, y1 - y0); }
          };
          if (l) drawH(px, mx + 2, l);
          if (r) drawH(mx - 1, px + CELL_W, r);
          if (u) drawV(py, my + 2, u);
          if (d) drawV(my - 1, py + CELL_H, d);
        } else {
          const f = pal.bold ? fontBold : fontReg;
          if (curFont !== f) { targetCtx.font = f; curFont = f; }
          targetCtx.fillStyle = pal.fg;
          targetCtx.fillText(ch, px + 0.5, py + CELL_H * 0.54);
        }
      }
    }
  }

  let crtEnabled = true;
  function compositeCRT(globalT, scName) {
    if (!crtEnabled) { ctx.drawImage(offCanvas, 0, 0); return; }
    const W = canvas.width, H = canvas.height;
    const sev = scName === "silence" ? 0.10 : (scName === "jumpscare" ? 0.92 : Math.min(0.85, 0.12 + 0.72 * Math.pow(globalT / 95.0, 1.45)));
    ctx.drawImage(offCanvas, 0, 0);

    if (sev > 0.35) {
      const shift = Math.round(1 + sev * 3.5);
      ctx.save();
      ctx.globalCompositeOperation = "screen";
      ctx.globalAlpha = 0.16 * sev;
      ctx.drawImage(offCanvas, shift, 0);
      ctx.drawImage(offCanvas, -shift, 0);
      ctx.restore();
    }
    if (sev > 0.45) {
      const tr = new RNG(Math.floor(globalT * 24) * 2654435761);
      for (let i = 0; i < Math.floor(sev * 4); i++) {
        if (tr.next() < 0.45) {
          const sy = tr.randrange(0, H - 24), sh = tr.randrange(4, 22);
          const dx = tr.randint(-Math.round(sev * 18), Math.round(sev * 18));
          ctx.drawImage(offCanvas, 0, sy, W, sh, dx, sy, W, sh);
        }
      }
    }
    const barY = ((globalT / 20.0) % 1.0) * (H + 90) - 45;
    const grad = ctx.createLinearGradient(0, barY - 35, 0, barY + 35);
    grad.addColorStop(0, "rgba(0,0,0,0)");
    grad.addColorStop(0.45, "rgba(0,0,0,0.16)");
    grad.addColorStop(0.55, "rgba(180,220,255,0.05)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, barY - 35, W, 70);
  }

  // ------------------------------------------------------------------------
  // 7. Native WebAudio Synth (Constant Pink+Brown+Crackle + Gate Cuts + Decoupled Buzzer)
  // ------------------------------------------------------------------------
  const GATE_PATTERNS = {
    tick:    [[0.014, 1.75, 0.35], [0.030, 1.0, 0]],
    note:    [[0.030, 1.10, 0.10], [0.055, 0.12, 0.20], [0.060, 1.0, 0]],
    skip:    [[0.045, 0.0, 0.40],  [0.040, 1.0, 0.08]],
    deny:    [[0.035, 1.15, 0.18], [0.060, 0.0, 0.55], [0.050, 1.30, 0.25], [0.045, 0.0, 0.30], [0.045, 1.0, 0]],
    stutter: [[0.038, 0.0, 0.35],  [0.052, 0.0, 0], [0.062, 1.30, 0.30], [0.030, 0.0, 0.20], [0.070, 1.0, 0.08]],
    halt:    [[0.005, 0.0, 0.85],  [0.220, 0.0, 0], [0.030, 1.0, 0.40], [0.040, 1.0, 0]],
    dropout: [[0.090, 0.0, 0.20],  [0.130, 0.45, 0], [0.170, 1.0, 0.05]],
    impact:  [[0.008, 0.0, 0.90],  [0.140, 1.90, 0.50], [0.120, 1.0, 0]],
  };
  const VOICE_FOR_GLITCH = {
    char_noise: "stutter", homoglyph: "skip", row_flip: "stutter", row_shift: "stutter",
    row_invert: "skip", scanlines: "dropout", escape_literal: "tick", blackout: "halt",
    flash: "impact", dim_all: "dropout", border_melt: "stutter", meter_overflow: "deny",
    popup_cascade: "deny", hsync_wave: "stutter", hex_flood: "skip",
    panel_noise: "tick", panel_corrupt: "skip", panel_garbage: "stutter", panel_invert: "skip", panel_dim: "dropout",
  };

  class SynthAudio {
    constructor() {
      this.ctx = null; this.enabled = false; this.bedGain = null; this.gateGain = null; this.warnBus = null;
      this.cut = false; this.lastBuzzer = -10; this.seenSigs = new Set();
      this.logCursor = {}; this.glitchCursor = {}; this.modalCursor = {};
      this.dimSeen = 0; this.scareHit = false; this.prevFrozen = false;
    }
    init() {
      if (this.ctx) return;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ac = new AC(); this.ctx = ac;
      const sr = ac.sampleRate, len = sr * 8;
      const buf = ac.createBuffer(2, len, sr);
      for (let ch = 0; ch < 2; ch++) {
        const d = buf.getChannelData(ch);
        let b0=0,b1=0,b2=0,b3=0,b4=0,b5=0,b6=0, lastOut=0;
        const rng = new RNG(20260924 + ch * 997);
        for (let i = 0; i < len; i++) {
          const w = rng.uniform(-1, 1);
          b0 = 0.99886 * b0 + w * 0.0555179;
          b1 = 0.99332 * b1 + w * 0.0750759;
          b2 = 0.96900 * b2 + w * 0.1538520;
          b3 = 0.86650 * b3 + w * 0.3104856;
          b4 = 0.55000 * b4 + w * 0.5329522;
          b5 = -0.7616 * b5 - w * 0.0168980;
          const pink = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
          b6 = w * 0.115926;
          lastOut = (lastOut + 0.02 * w) / 1.02;
          const crackle = rng.next() < 0.00035 ? rng.uniform(-0.65, 0.65) : 0;
          const hum = 0.055 * Math.sin((2 * Math.PI * 50 * i) / sr);
          d[i] = Math.tanh((pink * 0.62 + lastOut * 0.32 + crackle + hum) * 1.15);
        }
        const cf = Math.floor(sr * 0.2);
        for (let i = 0; i < cf; i++) { const f = i / cf; d[i] = d[i] * f + d[len - cf + i] * (1 - f); }
      }
      const src = ac.createBufferSource(); src.buffer = buf; src.loop = true;
      const lpf = ac.createBiquadFilter(); lpf.type = "lowpass"; lpf.frequency.value = 3600; lpf.Q.value = 0.7;
      const gate = ac.createGain(); gate.gain.value = 1.0;
      const bedGain = ac.createGain(); bedGain.gain.value = 0.0;
      src.connect(lpf); lpf.connect(gate); gate.connect(bedGain); bedGain.connect(ac.destination);
      src.start();

      const warnBus = ac.createGain(); warnBus.gain.value = 0.24;
      const warnLpf = ac.createBiquadFilter(); warnLpf.type = "lowpass"; warnLpf.frequency.value = 980;
      warnBus.connect(warnLpf); warnLpf.connect(ac.destination);
      this.gateGain = gate; this.bedGain = bedGain; this.warnBus = warnBus;
    }
    setEnabled(on) {
      if (on) this.init();
      this.enabled = on && !!this.ctx;
      if (!this.ctx) return;
      if (this.enabled && this.ctx.state === "suspended") this.ctx.resume();
      const now = this.ctx.currentTime;
      this.bedGain.gain.cancelScheduledValues(now);
      this.bedGain.gain.setTargetAtTime(this.enabled && !this.cut ? 0.11 : 0.0, now, 0.02);
    }
    resetCursors() {
      this.logCursor = {}; this.glitchCursor = {}; this.modalCursor = {};
      this.seenSigs.clear(); this.scareHit = false; this.prevFrozen = false; this.lastBuzzer = -10;
      this.setHardCut(false);
    }
    setHardCut(cutOn) {
      this.cut = cutOn;
      if (!this.ctx) return;
      const now = this.ctx.currentTime;
      this.bedGain.gain.cancelScheduledValues(now);
      this.bedGain.gain.setTargetAtTime(this.enabled && !cutOn ? 0.11 : 0.0, now, 0.004);
    }
    triggerGate(patternName, durOverride) {
      if (!this.enabled || !this.ctx || this.cut) return;
      const pat = GATE_PATTERNS[patternName];
      if (!pat) return;
      const now = this.ctx.currentTime, g = this.gateGain.gain;
      let t = now;
      g.cancelScheduledValues(now);
      for (let i = 0; i < pat.length; i++) {
        let [dur, lvl, pop] = pat[i];
        if (patternName === "halt" && i === 1 && durOverride) dur = Math.max(0.08, Math.min(1.2, durOverride));
        g.linearRampToValueAtTime(lvl, t + 0.003);
        if (pop > 0.25) this._pop(t, pop * 0.09);
        t += dur;
      }
      g.linearRampToValueAtTime(1.0, t + 0.008);
    }
    _pop(when, amp) {
      const ac = this.ctx, osc = ac.createOscillator(), gain = ac.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(92, when);
      osc.frequency.exponentialRampToValueAtTime(34, when + 0.018);
      gain.gain.setValueAtTime(amp, when);
      gain.gain.exponentialRampToValueAtTime(0.0001, when + 0.022);
      osc.connect(gain); gain.connect(this.bedGain);
      osc.start(when); osc.stop(when + 0.025);
    }
    triggerBuzzer(kind, sev) {
      if (!this.enabled || !this.ctx || this.cut) return;
      const ac = this.ctx, now = ac.currentTime;
      const playTone = (startAt, freq, dur, amp) => {
        const osc = ac.createOscillator(), sub = ac.createOscillator(), g = ac.createGain();
        osc.type = "square"; sub.type = "sine";
        osc.frequency.setValueAtTime(freq, startAt);
        osc.frequency.linearRampToValueAtTime(freq * 0.95, startAt + dur);
        sub.frequency.setValueAtTime(freq * 0.5, startAt);
        g.gain.setValueAtTime(0.0001, startAt);
        g.gain.linearRampToValueAtTime(amp, startAt + 0.006);
        g.gain.setValueAtTime(amp * 0.88, startAt + Math.max(0.01, dur - 0.04));
        g.gain.exponentialRampToValueAtTime(0.0001, startAt + dur);
        osc.connect(g); sub.connect(g); g.connect(this.warnBus);
        osc.start(startAt); sub.start(startAt);
        osc.stop(startAt + dur + 0.02); sub.stop(startAt + dur + 0.02);
      };
      if (kind === "error") {
        const f0 = 212 * (1 - 0.07 * sev);
        playTone(now, f0, 0.18, 0.42);
        playTone(now + 0.21, f0 * 0.735, 0.40, 0.38);
      } else {
        playTone(now, 285 * (1 - 0.06 * sev), 0.34, 0.30);
      }
    }
    step(globalT, state) {
      if (!this.enabled) return;
      const { scIdx, sc, te, frozen } = state;
      const sev = Math.min(1, Math.max(0, globalT / 92.0));
      if (sc.name === "silence") { if (!this.cut) this.setHardCut(true); return; }
      if (sc.name === "jumpscare") {
        if (!this.scareHit) {
          this.scareHit = true; this.setHardCut(false);
          this.triggerGate("impact"); this._pop(this.ctx.currentTime + 0.01, 0.55);
        }
        return;
      }
      if (this.cut) this.setHardCut(false);
      if (frozen !== this.prevFrozen) {
        this.prevFrozen = frozen;
        if (frozen) this.triggerGate("halt", 1.8); else this.triggerGate("impact");
      }
      let li = this.logCursor[scIdx] || 0;
      while (li < sc.logs.length && sc.logs[li][0] <= te) {
        const [, text, st] = sc.logs[li++];
        const sig = text.slice(0, 22), isNew = !this.seenSigs.has(sig);
        this.seenSigs.add(sig);
        if (st === S_RED || st === S_MAGENTA) {
          this.triggerGate("deny");
          if (isNew && globalT - this.lastBuzzer >= 4.8) { this.triggerBuzzer("error", sev); this.lastBuzzer = globalT; }
        } else if (st === S_YELLOW || st === S_AMBER) {
          this.triggerGate("note");
          if (isNew && globalT - this.lastBuzzer >= 4.8) { this.triggerBuzzer("warn", sev); this.lastBuzzer = globalT; }
        } else if (++this.dimSeen % 7 === 0) {
          this.triggerGate("tick");
        }
      }
      this.logCursor[scIdx] = li;
      let mi = this.modalCursor[scIdx] || 0;
      while (mi < sc.modals.length && sc.modals[mi].t0 <= te) {
        mi++; this.triggerGate("deny");
        this.triggerBuzzer("error", Math.min(1, sev + 0.25)); this.lastBuzzer = globalT;
      }
      this.modalCursor[scIdx] = mi;
      let gi = this.glitchCursor[scIdx] || 0;
      while (gi < sc.glitches.length && sc.glitches[gi].t <= te) {
        const gl = sc.glitches[gi++];
        if (VOICE_FOR_GLITCH[gl.name]) this.triggerGate(VOICE_FOR_GLITCH[gl.name], gl.dur);
      }
      this.glitchCursor[scIdx] = gi;
    }
  }

  // ------------------------------------------------------------------------
  // 8. Pure Terminal Session Control
  // ------------------------------------------------------------------------
  const grid = new Grid(DATA.cols, DATA.rows);
  const audio = new SynthAudio();
  let started = false;
  let playing = false;
  let menuOpen = false;
  let curT = 0.0;
  let speed = 1.0;
  let hudMsg = "";
  let hudUntil = 0;
  let lastPerf = performance.now();

  const splashEl = document.getElementById("splash");
  const menuEl = document.getElementById("menu");
  const crtFrame = document.getElementById("crtFrame");
  const btnToggleAudio = document.getElementById("btnToggleAudio");
  const btnToggleCrt = document.getElementById("btnToggleCrt");

  function setHud(msg, ms = 2000) { hudMsg = msg; hudUntil = performance.now() + ms; }

  function syncMenuLabels() {
    btnToggleAudio.textContent = audio.enabled ? "[ 音频: 开 ]" : "[ 音频: 关 ]";
    btnToggleCrt.textContent = crtEnabled ? "[ CRT: 开 ]" : "[ CRT: 关 ]";
  }

  function seekTo(t) {
    curT = Math.max(0, Math.min(DATA.total, t));
    audio.resetCursors();
    const [scIdx, sc, lt] = locateScene(curT);
    const te = teffOf(sc, lt);
    let li = 0; while (li < sc.logs.length && sc.logs[li][0] <= te) li++;
    audio.logCursor[scIdx] = li;
    let mi = 0; while (mi < sc.modals.length && sc.modals[mi].t0 <= te) mi++;
    audio.modalCursor[scIdx] = mi;
    let gi = 0; while (gi < sc.glitches.length && sc.glitches[gi].t <= te) gi++;
    audio.glitchCursor[scIdx] = gi;
  }

  function startSession(withAudio) {
    started = true;
    playing = true;
    menuOpen = false;
    splashEl.classList.add("hidden");
    menuEl.classList.add("hidden");
    audio.setEnabled(withAudio);
    syncMenuLabels();
    lastPerf = performance.now();
  }

  function setMenu(open) {
    if (!started) return;
    menuOpen = open;
    menuEl.classList.toggle("hidden", !open);
    playing = !open;
    if (audio.ctx && audio.enabled) {
      const now = audio.ctx.currentTime;
      audio.bedGain.gain.cancelScheduledValues(now);
      audio.bedGain.gain.setTargetAtTime(open || audio.cut ? 0.0 : 0.11, now, 0.02);
    }
    syncMenuLabels();
  }

  function toggleAudio() {
    audio.setEnabled(!audio.enabled);
    syncMenuLabels();
    setHud(audio.enabled ? "AUDIO ON" : "AUDIO OFF");
  }

  function toggleCrt() {
    crtEnabled = !crtEnabled;
    crtFrame.classList.toggle("flat", !crtEnabled);
    syncMenuLabels();
    setHud(crtEnabled ? "CRT ON" : "CRT OFF");
  }

  function answerPrompt(ans) {
    const [scIdx, sc, lt] = locateScene(curT);
    const te = teffOf(sc, lt);
    for (let i = 0; i < sc.prompts.length; i++) {
      const p = sc.prompts[i];
      if (te >= p.t0 && te < p.t1 + 0.9) {
        if (promptAnswers[scIdx][i]) return;
        promptAnswers[scIdx][i] = ans;
        extraLogs[scIdx].push([te + 0.05, `用户输入: ${ans}`, S_BRIGHT]);
        if (ans === "n") extraLogs[scIdx].push([p.t1 + 0.05, "系统选择: Y —— 忽略用户输入。", S_AMBER]);
        setHud(`INPUT ${ans.toUpperCase()}`);
        audio.triggerGate("deny");
        return;
      }
    }
  }

  document.getElementById("btnStart").addEventListener("click", () => startSession(true));
  document.getElementById("btnStartMute").addEventListener("click", () => startSession(false));
  document.getElementById("btnResume").addEventListener("click", () => setMenu(false));
  document.getElementById("btnRestart").addEventListener("click", () => {
    for (let i = 0; i < extraLogs.length; i++) { extraLogs[i] = []; promptAnswers[i] = {}; }
    seekTo(0);
    setMenu(false);
    setHud("RESTART");
  });
  btnToggleAudio.addEventListener("click", toggleAudio);
  btnToggleCrt.addEventListener("click", toggleCrt);

  window.addEventListener("keydown", (ev) => {
    const k = ev.key;
    if (!started) {
      if (k === "Enter" || k === " ") { ev.preventDefault(); startSession(true); }
      return;
    }
    if (k === "Escape" || k === "h" || k === "H") { ev.preventDefault(); setMenu(!menuOpen); return; }
    if (menuOpen) return;
    if (k >= "1" && k <= "9") {
      const idx = parseInt(k, 10) - 1;
      if (idx < DATA.scenes.length) { seekTo(DATA.scenes[idx].start); setHud(`SCENE ${idx + 1}`); }
    } else if (k === " " || k === "p" || k === "P") {
      ev.preventDefault();
      playing = !playing;
      setHud(playing ? "RESUME" : "PAUSE");
    } else if (k === "+" || k === "=") {
      speed = Math.round(Math.min(10.0, speed + 0.1) * 10) / 10;
      setHud(`SPD ${speed.toFixed(1)}x`);
    } else if (k === "-" || k === "_") {
      speed = Math.round(Math.max(0.4, speed - 0.1) * 10) / 10;
      setHud(`SPD ${speed.toFixed(1)}x`);
    } else if (k === "0") {
      speed = 1.0; setHud("SPD 1.0x");
    } else if (k === "m" || k === "M") {
      toggleAudio();
    } else if (k === "c" || k === "C") {
      toggleCrt();
    } else if (k === "y" || k === "Y") {
      answerPrompt("y");
    } else if (k === "n" || k === "N") {
      answerPrompt("n");
    }
  });

  // Render initial frame behind splash so canvas is never blank
  const initState = renderFrame(grid, 0.0, "");
  paintGrid(offCtx, grid);
  compositeCRT(0.0, initState.sc.name);

  function tick(now) {
    const dt = Math.min(0.1, (now - lastPerf) / 1000);
    lastPerf = now;
    if (started && playing) {
      curT += dt * speed;
      if (curT >= DATA.total) {
        curT = 0;
        for (let i = 0; i < extraLogs.length; i++) { extraLogs[i] = []; promptAnswers[i] = {}; }
        audio.resetCursors();
      }
      const hud = now < hudUntil ? hudMsg : (Math.abs(speed - 1.0) > 1e-6 ? `SPD ${speed.toFixed(1)}x` : "");
      const state = renderFrame(grid, curT, hud);
      audio.step(curT, state);
      paintGrid(offCtx, grid);
      compositeCRT(curT, state.sc.name);
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
</script>
</body>
</html>
"""


def build_web(out_path: str, seed: int = S.SEED) -> None:
    payload = export_payload(seed=seed)
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__ERRANIM_DATA__", data_json)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    kb = os.path.getsize(out_path) / 1024.0
    print("-> Built single-file web terminal: %s (%.1f KB, %d scenes, total %.1fs)"
          % (out_path, kb, len(payload["scenes"]), payload["total"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build standalone web/index.html for ERROR-animation")
    ap.add_argument("--out", default=os.path.join(ROOT, "web", "index.html"), help="Output HTML path")
    ap.add_argument("--seed", type=int, default=S.SEED, help="Deterministic seed")
    args = ap.parse_args(argv)
    build_web(args.out, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
