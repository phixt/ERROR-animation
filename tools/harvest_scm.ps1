# 采集 Windows 事件日志（保留现有 SCM 语料库 + 增补近 N 天 SCM / Kernel-Power / Win32k / DCOM / WER / AppError 等多维系统遗言）。
#
# 用法：
#   pwsh -NoProfile -File tools\harvest_scm.ps1 -Days 60 -Out data\corpus.json

param(
    [int]$Days = 60,
    [string]$Out = "data/corpus.json",
    [switch]$MergeExisting = $true
)

$ErrorActionPreference = 'Stop'

$full = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Out))
$groups = @{}

if ($MergeExisting -and (Test-Path $full)) {
    try {
        $old = Get-Content $full -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($e in $old.events) {
            $key = "{0}|{1}|{2}" -f $e.id, $e.main, $e.reason
            $p = @{}
            if ($e.params) {
                foreach ($prop in $e.params.PSObject.Properties) {
                    $p[$prop.Name] = [string]$prop.Value
                }
            }
            $groups[$key] = [pscustomobject]@{
                id        = [int]$e.id
                main      = [string]$e.main
                reason    = [string]$e.reason
                hint      = [string]$e.hint
                count     = [int]$e.count
                firstTime = [string]$e.firstTime
                lastTime  = [string]$e.lastTime
                params    = $p
            }
        }
        Write-Host "已加载现有语料库 $($groups.Count) 条去重事件作为基底。"
    } catch {
        Write-Host "读取现有语料库失败，将全新构建：$($_)"
    }
}

$sources = @(
    @{ LogName = 'System';      ProviderName = 'Service Control Manager' },
    @{ LogName = 'System';      ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = @(41, 109, 506, 507) },
    @{ LogName = 'System';      ProviderName = 'Win32k'; Id = @(263, 700, 701) },
    @{ LogName = 'System';      ProviderName = 'Microsoft-Windows-DistributedCOM'; Id = @(10001, 10010, 10016) },
    @{ LogName = 'System';      ProviderName = 'Schannel'; Id = @(36884) },
    @{ LogName = 'System';      ProviderName = 'disk'; Id = @(11, 153) },
    @{ LogName = 'Application'; ProviderName = 'Application Error'; Id = @(1000) },
    @{ LogName = 'Application'; ProviderName = 'Application Hang'; Id = @(1002) },
    @{ LogName = 'Application'; ProviderName = 'Microsoft-Windows-Perflib'; Id = @(1008) },
    @{ LogName = 'Application'; ProviderName = 'VSS'; Id = @(13, 8193) },
    @{ LogName = 'Application'; ProviderName = 'Universal Print'; Id = @(1) }
)

$rawTotal = 0
$start = (Get-Date).AddDays(-$Days)

foreach ($src in $sources) {
    $fh = @{
        LogName      = $src.LogName
        ProviderName = $src.ProviderName
        StartTime    = $start
    }
    if ($src.ContainsKey('Id')) { $fh['Id'] = $src.Id }
    $evts = @(Get-WinEvent -FilterHashtable $fh -ErrorAction SilentlyContinue)
    if (-not $evts -or $evts.Count -eq 0) { continue }
    $rawTotal += $evts.Count
    Write-Host ("  + {0} / {1}: {2} 条" -f $src.LogName, $src.ProviderName, $evts.Count)

    foreach ($e in $evts) {
        $data = @{ provider = $src.ProviderName }
        try {
            $xml = [xml]$e.ToXml()
            foreach ($n in $xml.Event.EventData.Data) {
                if ($n.Name) { $data[$n.Name] = [string]$n.'#text' }
            }
        } catch { }

        $lines = @($e.Message -split "`r?`n" | ForEach-Object { $_.TrimEnd() } | Where-Object { $_ -ne '' })
        if ($lines.Count -eq 0) { continue }
        $main = $lines[0].Trim()
        $reason = ''
        $hint = ''
        if ($main -match '[:：]\s*$') {
            if ($lines.Count -ge 2) { $reason = $lines[1].Trim() }
            if ($lines.Count -ge 3) { $hint = $lines[2].Trim() }
            # 防止悬空冒号（自检要求：以冒号结尾的主行必须有 reason）
            if (-not $reason) {
                $reason = "未返回扩展错误上下文 (0x80004005 / E_FAIL)。"
            }
        } else {
            if ($lines.Count -ge 2 -and $e.Id -in @(1000, 1008, 41)) {
                $reason = $lines[1].Trim()
            }
            if ($lines.Count -ge 3 -and $e.Id -in @(1000, 41)) {
                $hint = $lines[2].Trim()
            }
        }

        $key = "{0}|{1}|{2}" -f $e.Id, $main, $reason
        $ts = $e.TimeCreated.ToString('o')
        if ($groups.ContainsKey($key)) {
            $g = $groups[$key]
            $g.count++
            if ($ts -lt [string]$g.firstTime) { $g.firstTime = $ts }
            if ($ts -gt [string]$g.lastTime) { $g.lastTime = $ts }
        } else {
            $groups[$key] = [pscustomobject]@{
                id        = $e.Id
                main      = $main
                reason    = $reason
                hint      = $hint
                count     = 1
                firstTime = $ts
                lastTime  = $ts
                params    = $data
            }
        }
    }
}

$events = $groups.Values | Sort-Object -Property @{Expression = 'count'; Descending = $true }, @{Expression = 'id'; Descending = $false }

$result = [pscustomobject]@{
    meta = [pscustomobject]@{
        generated = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        source    = 'Windows Event Log / Multi-Provider (SCM + Kernel-Power + Win32k + DCOM + AppError)'
        machine   = $env:COMPUTERNAME
        days      = $Days
        raw_count = $rawTotal
        distinct  = $events.Count
    }
    events = $events
}

$dir = [IO.Path]::GetDirectoryName($full)
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$json = $result | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($full, $json, [Text.UTF8Encoding]::new($false))
Write-Host "→ $full（合计 $($events.Count) 条去重事件）"
