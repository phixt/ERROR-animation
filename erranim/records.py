"""素材：给定的 SCM 崩溃日志记录 + 必要的正常示例文本。

原始来源：
    <LOCAL_LOG_ARCHIVE>
    不觉得这很酷吗，死机的日志有模拟恐怖的味道.md

**逻辑修正**：那份 md 是"去重摘要"，只保留了每条事件的主行，把紧随其后的具体
错误原因丢掉了。于是出现「错误原因如下:」后面什么都没有 —— 逻辑上不成立。
这里按真实事件日志补回了 `reason` / `hint`（取自 data/corpus.json 的采集结果），
渲染时作为**缩进的细节行**跟在主行下面：

    [7038] netprofm 服务无法使用当前配置的密码以 NT AUTHORITY\\NetworkService 身份登录，错误原因如下:
           内存资源不足，无法处理此命令。
           要确保服务配置正确，请使用 Microsoft 管理控制台(MMC)中的服务管理单元。

另一部分事件（7031/7034/7009/7011）本来就是单行的，没有原因行，保持原样。

`data/corpus.json` 存在时，`corpus.Corpus` 会提供完整语料库与随机采样；
不存在时全部走本文件的兜底数据。
"""

from __future__ import annotations

INDENT = 7  # 细节行缩进，正好对齐 "[7038] " 之后

_HINT_MMC = "要确保服务配置正确，请使用 Microsoft 管理控制台(MMC)中的服务管理单元。"
_REASON_NOMEM = "内存资源不足，无法处理此命令。"
_REASON_LOGON = "由于登录失败而无法启动服务。"
_REASON_NOFILE = "系统找不到指定的文件。"
_REASON_NORES = "系统资源不足，无法完成请求的服务。"
_REASON_PAGEFILE = "页面文件太小，无法完成操作。"
_REASON_NORESP = "服务没有及时响应启动或控制请求。"

# 记录格式：
#   n=去重计数, ev=事件 ID, svc=服务名, text=主行,
#   reason=错误原因（真实缩进展示）, hint=补充提示, ms=修正等待毫秒, times=已出现次数

RECORDS: list[dict] = [
    dict(n=10, ev=7000, svc="Network List Service", reason=_REASON_LOGON,
         text="由于下列错误，Network List Service 服务启动失败:"),
    dict(n=8, ev=7038, svc="netprofm", reason=_REASON_NOMEM, hint=_HINT_MMC,
         text="netprofm 服务无法使用当前配置的密码以 NT AUTHORITY\\NetworkService 身份登录，错误原因如下:"),
    dict(n=3, ev=7011, svc="WSLService",
         text="等待来自 WSLService 服务的事务处理响应超时(30000 毫秒)。"),
    dict(n=2, ev=7024, svc="Routing and Remote Access",
         reason="请求的名称有效，但是找不到请求的类型的数据。",
         text="Routing and Remote Access 服务由于下列服务特定错误而终止:"),
    dict(n=2, ev=7000, svc="KPICService_Web", reason=_REASON_NOFILE,
         text="由于下列错误，KPICService_Web 服务启动失败:"),
    dict(n=1, ev=7009, svc="Windows Push Notifications User Service_4d9f4c31",
         text="等待 Windows Push Notifications User Service_4d9f4c31 服务的连接超时(30000 毫秒)。"),
    dict(n=1, ev=7031, svc="Windows Error Reporting Service", ms=120000, times=1,
         text="Windows Error Reporting Service 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 120000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="Windows 推送通知系统服务", ms=1000, times=1,
         text="Windows 推送通知系统服务 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 1000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="Universal Device Client Service", ms=60000, times=1,
         text="Universal Device Client Service 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 60000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="Network List Service", ms=10000, times=2,
         text="Network List Service 服务意外地终止，这种情况已经出现了 2 次。"
              "以下的修正操作将在 10000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="Network List Service", ms=1000, times=1,
         text="Network List Service 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 1000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7038, svc="DiagTrack", reason=_REASON_NOMEM, hint=_HINT_MMC,
         text="DiagTrack 服务无法使用当前配置的密码以 NT AUTHORITY\\SYSTEM 身份登录，错误原因如下:"),
    dict(n=1, ev=7031, svc="Connected User Experiences and Telemetry", ms=30000, times=1,
         text="Connected User Experiences and Telemetry 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 30000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7038, svc="CDPSvc", reason=_REASON_NOMEM, hint=_HINT_MMC,
         text="CDPSvc 服务无法使用当前配置的密码以 NT AUTHORITY\\LocalService 身份登录，错误原因如下:"),
    dict(n=1, ev=7031, svc="AppX Deployment Service (AppXSVC)", ms=120000, times=1,
         text="AppX Deployment Service (AppXSVC) 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 120000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7000, svc="Windows 推送通知系统服务", reason=_REASON_PAGEFILE,
         text="由于下列错误，Windows 推送通知系统服务 服务启动失败:"),
    dict(n=1, ev=7031, svc="Windows Push Notifications User Service_4d9f4c31", ms=1000, times=1,
         text="Windows Push Notifications User Service_4d9f4c31 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 1000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7000, svc="inpoutx64", reason=_REASON_NORES,
         text="由于下列错误，inpoutx64 服务启动失败:"),
    dict(n=1, ev=7000, svc="Connected User Experiences and Telemetry", reason=_REASON_NORESP,
         text="由于下列错误，Connected User Experiences and Telemetry 服务启动失败:"),
    dict(n=1, ev=7000, svc="连接设备平台用户服务_4d9f4c31", reason=_REASON_NORES,
         text="由于下列错误，连接设备平台用户服务_4d9f4c31 服务启动失败:"),
    dict(n=1, ev=7000, svc="连接设备平台服务", reason=_REASON_LOGON,
         text="由于下列错误，连接设备平台服务 服务启动失败:"),
    dict(n=1, ev=7031, svc="连接设备平台用户服务_4d9f4c31", ms=3000, times=1,
         text="连接设备平台用户服务_4d9f4c31 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 3000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="连接设备平台服务", ms=3000, times=1,
         text="连接设备平台服务 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 3000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7040, svc="Overlay Tunnel Service",
         text="Overlay Tunnel Service 服务的启动类型从 自动启动 更改为 自动启动(延迟启动)。"),
    dict(n=1, ev=7034, svc="WSL Service",
         text="服务 WSL Service 意外停止。这发生了 1 次。"),
    dict(n=1, ev=7034, svc="FileIndex_Daemon",
         text="服务 FileIndex_Daemon 意外停止。这发生了 1 次。"),
    dict(n=1, ev=7034, svc="AudioFX_API_Service",
         text="服务 AudioFX_API_Service 意外停止。这发生了 1 次。"),
    dict(n=1, ev=7031, svc="主机网络服务", ms=120000, times=1,
         text="主机网络服务 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 120000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="Overlay Tunnel Service", ms=60000, times=1,
         text="Overlay Tunnel Service 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 60000 毫秒内运行: 重新启动服务。"),
]

# --------------------------------------------------------------------------
# 采集到的、md 里没有的事件（补进语料，让"日常"更真、让随机模式更有料）
# 第三方软件名按脱敏要求：仅保留 ZCode / GameViewer (UU) 等核心叙事锚点，其余用通用名
# --------------------------------------------------------------------------

EXTRA_RECORDS: list[dict] = [
    dict(n=1, ev=7038, svc="WerSvc", reason=_REASON_NOMEM, hint=_HINT_MMC,
         text="WerSvc 服务无法使用当前配置的密码以 NT AUTHORITY\\SYSTEM 身份登录，错误原因如下:"),
    dict(n=1, ev=7006, svc="ScRegSetValueExW", reason="拒绝访问。",
         text="由于下列错误，ScRegSetValueExW 调用无法运行 Start:"),
    dict(n=1, ev=7001, svc="RasMan", reason="服务已返回特定的服务错误代码。",
         text="与 RemoteAccess 服务相依的 RasMan 服务因下列错误而无法启动:"),
    dict(n=1, ev=7024, svc="RasMan", reason="由于超时时间已过，该操作返回。",
         text="RasMan 服务由于下列服务特定错误而终止:"),
    dict(n=1, ev=7030, svc="Telemetry Uploader Service",
         text="Telemetry Uploader Service 服务标记为交互服务。"
              "但是系统配置成不允许交互服务。这项服务可能无法正常操作。"),
    dict(n=1, ev=7034, svc="Network Setup Service", text="服务 Network Setup Service 意外停止。这发生了 1 次。"),
    dict(n=1, ev=7034, svc="PMF Power Service", text="服务 PMF Power Service 意外停止。这发生了 1 次。"),
    dict(n=1, ev=7031, svc="Local Proxy Tunnel Service", ms=5000, times=1,
         text="Local Proxy Tunnel Service 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 5000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7031, svc="Secure Socket Tunneling Protocol Service", ms=120000, times=1,
         text="Secure Socket Tunneling Protocol Service 服务意外地终止，这种情况已经出现了 1 次。"
              "以下的修正操作将在 120000 毫秒内运行: 重新启动服务。"),
    dict(n=1, ev=7000, svc="Network List Service", reason=_REASON_PAGEFILE,
         text="由于下列错误，Network List Service 服务启动失败:"),
    dict(n=1, ev=7000, svc="Connected User Experiences and Telemetry", reason=_REASON_LOGON,
         text="由于下列错误，Connected User Experiences and Telemetry 服务启动失败:"),
    # 增补多维系统遗言（Win32k / DCOM / Kernel-Power / Schannel / AppError / VSS / Display / WER）
    dict(n=47, ev=263, svc="Win32k",
         text="指针设备没有有关其连接的监视器的信息。"),
    dict(n=27, ev=700, svc="Win32k",
         text="电源管理器请求阻止所有输入(INPUT_SUPPRESS_REQUEST=1)"),
    dict(n=33, ev=10001, svc="DistributedCOM",
         reason="系统资源不足，无法完成请求的服务 (SID: UNAVAILABLE)。",
         text="无法作为 不可用/不可用 启动 DCOM 服务器: {C53A4F16-787E-42A4-B304-29EFFB4BF597}。错误:"),
    dict(n=247, ev=10010, svc="DistributedCOM",
         text="服务器 {9BA05972-F6A8-11CF-A442-00A0C90A8F39} 没有在要求的超时时间内向 DCOM 注册。"),
    dict(n=356, ev=36884, svc="Schannel",
         text="从远程服务器上收到的证书不包含一个预期的名称。因此我们不能确定是否连接到了正确的服务器。TLS 连接请求失败。"),
    dict(n=58, ev=1000, svc="atieclxx.exe",
         reason="Faulting module: atieclxx.exe (32.0.32015.7029), ExceptionCode: 0xc0000005 @ offset 0x000000000002ab20.",
         text="出错应用程序名称: atieclxx.exe，版本: 32.0.32015.7029，时间戳: 0x6ad1496d:"),
    dict(n=14, ev=8193, svc="VSS",
         reason="hr = 0x8007045b, 系统正在关机 (ERROR_SHUTDOWN_IN_PROGRESS)。",
         text="卷影复制服务错误: 调用程序 CoCreateInstance 时的意外错误:"),
    dict(n=7, ev=1, svc="Universal Print",
         text="Failed to GetUserSid. hr: 0x8001012d (NO_SECURITY_CONTEXT_AVAILABLE)."),
    dict(n=12, ev=507, svc="Kernel-Power",
         text="系统正在退出新型待机状态。原因: SetThreadExecutionState。监视器通电时间: 182 毫秒。"),
    dict(n=8, ev=4107, svc="Display",
         text="GameViewer Virtual Display Adapter 调用 SetDisplayConfig(SDC_FORCE_MODE_ENUMERATION)。"),
    dict(n=4, ev=141, svc="WER-LiveKernel",
         reason="LKD_0x141_Tdr:C_IMAGE_amdkmdag.sys -> LKD_0x193_DxgkrnlLiveDump (dxgkrnl!ProcessDeadlockThread)。",
         text="视频引擎超时且恢复失败，已生成实时内核转储:"),
    dict(n=2, ev=460, svc="WER-LiveKernel",
         reason="pnputil /restart-device: 需要重新启动系统才能完成配置操作。shutdown.exe /r /t 0 /f: 操作超时 (0x000005B4)。",
         text="内核显示与电源路径超时 (LKD_0x1cc_EXRESOURCE_TIMEOUT_win32kbase):"),
    dict(n=6, ev=41, svc="Kernel-Power",
         reason="BugcheckCode: 0x00000133 (DPC_WATCHDOG_VIOLATION)。COMMIT: 77.4 / 31.2 GB。",
         text="系统已在未先正常关机的情况下重新启动。如果系统停止响应、发生崩溃或意外断电，则可能会导致此错误:"),
    dict(n=3, ev=2004, svc="Resource-Exhaustion-Detector",
         reason="godot.exe (PID: 8842) 已提交 24812 MB，zcode.exe 已提交 3140 MB。物理内存使用率 99% (30.9 / 31.2 GB)。",
         text="Windows 成功诊断出虚拟内存不足的情况。下列程序消耗了最多的虚拟内存:"),
]

ALL_RECORDS = RECORDS + EXTRA_RECORDS

BY_SVC: dict[str, list[dict]] = {}
for _r in ALL_RECORDS:
    BY_SVC.setdefault(_r["svc"], []).append(_r)


ALIASES = {}


def find(svc: str, ev: int | None = None) -> dict:
    svc_key = ALIASES.get(svc, svc)
    for r in BY_SVC.get(svc_key, []):
        if ev is None or r["ev"] == ev:
            return r
    raise KeyError("%s / %s" % (svc, ev))


def record_lines(rec: dict, indent: int = INDENT, hint: bool = True) -> list[str]:
    """一条记录展开成符合逻辑的多行：主行 + 缩进的原因 + 缩进的提示。"""
    out = [rec["text"]]
    pad = " " * indent
    if rec.get("reason"):
        out.append(pad + rec["reason"])
    if hint and rec.get("hint"):
        out.append(pad + rec["hint"])
    return out


def record_text(rec: dict, indent: int = INDENT, hint: bool = True) -> str:
    return "\n".join(record_lines(rec, indent, hint))


# --------------------------------------------------------------------------
# 正常示例文本（同一套官僚口吻，用来做"日常"对照）
# 措辞按本机 7040/7036 的真实输出校准过
# --------------------------------------------------------------------------

NORMAL: list[dict] = [
    dict(ev=7040, text="Windows Push Notifications User Service_4d9f4c31 服务的启动类型从 自动启动 更改为 按需启动。"),
    dict(ev=7036, text="Network List Service 服务处于 正在运行 状态。"),
    dict(ev=7040, text="Connected User Experiences and Telemetry 服务的启动类型从 按需启动 更改为 自动启动。"),
    dict(ev=7036, text="Windows Error Reporting Service 服务处于 正在运行 状态。"),
    dict(ev=7045, text="服务已安装在系统中。"),
    dict(ev=7036, text="连接设备平台服务 服务处于 正在运行 状态。"),
    dict(ev=7040, text="Overlay Tunnel Service 服务的启动类型从 自动启动 更改为 自动启动(延迟启动)。"),
    dict(ev=7036, text="WSL Service 服务处于 正在运行 状态。"),
    dict(ev=7040, text="AppX Deployment Service (AppXSVC) 服务的启动类型从 手动 更改为 按需启动。"),
    dict(ev=7036, text="Universal Device Client Service 服务处于 正在运行 状态。"),
    dict(ev=7040, text="Network List Service 服务的启动类型从 自动启动 更改为 按需启动。"),
    dict(ev=7036, text="AudioFX_API_Service 服务处于 正在运行 状态。"),
    dict(ev=7040, text="主机网络服务 服务的启动类型从 自动启动 更改为 按需启动。"),
    dict(ev=7036, text="Windows 推送通知系统服务 服务处于 正在运行 状态。"),
    dict(ev=7036, text="Appinfo 服务处于 正在运行 状态。"),
    dict(ev=7040, text="Routing and Remote Access 服务的启动类型从 已禁用 更改为 按需启动。"),
    dict(ev=7040, text="Background Intelligent Transfer Service 服务的启动类型从 按需启动 更改为 自动启动。"),
    dict(ev=7036, text="AMD PMF Service 服务处于 正在运行 状态。"),
]

BOOT_LINES: list[str] = [
    "服务控制管理器 —— 会话开始",
    "正在枚举服务。此操作可能需要一些时间。",
    "正在读取服务配置。",
    "正在验证服务账户凭据。",
    "正在恢复上次会话的未完成操作。",
    "本次会话没有可用的用户上下文。",
]


def normal_line(i: int) -> str:
    """第 i 条日常行（循环取用，制造无限刷屏感）。"""
    r = NORMAL[i % len(NORMAL)]
    text = "[%d] %s" % (r["ev"], r["text"])
    hint = r.get("hint")
    if hint:
        text += "\n" + " " * INDENT + hint
    return text


# 更"活"的诊断噪声：带数字的模板，让滚动长文有东西可读。
# 每个占位符给一个 (下界, 上界, 步长)，数字才落在合理量级。
NOISE_EXTRA: list[tuple[str, list[tuple[int, int, int]]]] = [
    ("服务数据库修订号 %d，已同步。", [(1000, 99000, 1)]),
    ("服务句柄表: %d 项，其中锁定 %d 项。", [(180, 4200, 1), (0, 40, 1)]),
    ("内存可用 %d KB，页面文件可用 %d KB。", [(120000, 900000, 1), (200000, 1600000, 1)]),
    ("等待 %d 个挂起的服务操作完成。", [(0, 12, 1)]),
    ("轮询服务状态，第 %d 轮。", [(1, 90000, 1)]),
    ("服务记录已刷入磁盘，偏移 0x%06X。", [(0, 0xFFFFFF, 1)]),
    ("服务控制管理器心跳 %d，间隔 %d 毫秒。", [(1, 90000, 1), (1000, 10000, 1000)]),
    ("已回收 %d 个空闲服务线程。", [(0, 64, 1)]),
]


def noise_line(i: int) -> str:
    """日常噪声：多数是无害的服务状态行，偶尔夹一条带数字的诊断行。"""
    if i % 4 != 3:
        return normal_line(i)
    tpl, ranges = NOISE_EXTRA[(i // 4) % len(NOISE_EXTRA)]
    k = (i * 7919) % 999983
    vals = []
    for m, (lo, hi, step) in enumerate(ranges):
        span = max(1, (hi - lo) // step + 1)
        vals.append(lo + step * ((k * (m + 3)) % span))
    return "[7036] " + (tpl % tuple(vals) if vals else tpl)


# --------------------------------------------------------------------------
# 与语料库对接
# --------------------------------------------------------------------------


def from_corpus_event(ev) -> dict:
    """把 corpus.Event 转成和 RECORDS 同构的 dict，方便共用渲染路径。"""
    return dict(
        n=getattr(ev, "count", 1), ev=ev.id, svc=ev.service, text=ev.main,
        reason=ev.reason, hint=ev.hint,
    )
