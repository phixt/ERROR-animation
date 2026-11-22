"""终端底层：VT 转义、UTF-8、尺寸、备用屏、按键读取。零第三方依赖。

本机实测：控制台代码页是 936(GBK)，必须显式切到 65001 并 reconfigure
stdout，否则中文日志会乱码。
"""

from __future__ import annotations

import os
import shutil
import sys
import time

IS_WIN = os.name == "nt"

# SetConsoleMode 标志
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
ENABLE_PROCESSED_OUTPUT = 0x0001

STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12

# 备用屏 / 光标
ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"
CUR_HIDE = "\x1b[?25l"
CUR_SHOW = "\x1b[?25h"
CUR_HOME = "\x1b[1;1H"
RESET = "\x1b[0m"
CLEAR = "\x1b[2J"


def init_console() -> None:
    """打开 VT 支持、切 UTF-8 代码页、把 stdout 固定成 utf-8。"""
    if IS_WIN:
        try:
            import ctypes

            k = ctypes.windll.kernel32
            mode = ctypes.c_uint32()
            for sid in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
                h = k.GetStdHandle(sid)
                if h and k.GetConsoleMode(h, ctypes.byref(mode)):
                    k.SetConsoleMode(
                        h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT
                    )
            k.SetConsoleOutputCP(65001)
            k.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def set_title(title: str) -> None:
    if IS_WIN:
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass
    else:
        sys.stdout.write("\x1b]0;%s\x07" % title)
        sys.stdout.flush()


def size(fallback=(132, 42)) -> tuple[int, int]:
    """(列, 行)。非 TTY 时用 fallback，便于 --snap/--record 复现。"""
    try:
        s = shutil.get_terminal_size(fallback)
        cols, rows = int(s.columns), int(s.lines)
    except Exception:
        cols, rows = fallback
    if cols < 60 or rows < 16:
        cols, rows = fallback
    return max(60, min(cols, 400)), max(16, min(rows, 200))


def write(s: str) -> None:
    sys.stdout.write(s)


def flush() -> None:
    try:
        sys.stdout.flush()
    except Exception:
        pass


def alt_screen(on: bool) -> None:
    write((ALT_ON if on else ALT_OFF) + (CUR_HIDE if on else CUR_SHOW))
    flush()


def hide_cursor(hide: bool) -> None:
    write(CUR_HIDE if hide else CUR_SHOW)
    flush()


# --------------------------------------------------------------------------
# 按键
# --------------------------------------------------------------------------

if IS_WIN:
    import msvcrt

    def poll_key() -> str | None:
        """非阻塞取一个键；方向键等扩展键返回其名称。"""
        if not msvcrt.kbhit():
            return None
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {72: "UP", 80: "DOWN", 75: "LEFT", 77: "RIGHT"}.get(ord(code), "EXT")
        return ch

    def read_line(prompt: str = "") -> str:
        if prompt:
            write(prompt)
            flush()
        buf: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                write("\r\n")
                flush()
                return "".join(buf)
            if ch == "\x08":
                if buf:
                    buf.pop()
                    write("\b \b")
                    flush()
                continue
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            buf.append(ch)
            write(ch)
            flush()

else:
    import select
    import termios
    import tty

    def poll_key() -> str | None:
        if not select.select([sys.stdin], [], [], 0)[0]:
            return None
        ch = sys.stdin.read(1)
        return ch or None

    def read_line(prompt: str = "") -> str:
        return input(prompt)


def drain_keys() -> None:
    """丢掉积压的按键，避免启动瞬间的输入被当成指令。"""
    for _ in range(64):
        if poll_key() is None:
            return


def sleep_until(deadline: float) -> None:
    """睡到 perf_counter 的 deadline；剩余时间长就粗睡，短就自旋。"""
    while True:
        remain = deadline - time.perf_counter()
        if remain <= 0:
            return
        if remain > 0.002:
            time.sleep(remain - 0.001)
        else:
            time.sleep(0)
