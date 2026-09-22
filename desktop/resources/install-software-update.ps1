param([Parameter(Mandatory=$true)][string]$PlanPath, [switch]$Recover, [switch]$Launch)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($Launch) {
  # Start-Process creates an independent hidden Windows console. PowerShell 5.1
  # invoked with Electron's DETACHED_PROCESS flag may exit without executing.
  $transactionDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($PlanPath))
  $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -PlanPath "' + $PlanPath + '"'
  Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $transactionDirectory 'installer-output.log') -RedirectStandardError (Join-Path $transactionDirectory 'installer-error.log') | Out-Null
  exit 0
}
$plan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$transaction = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($PlanPath))
$resultPath = Join-Path $transaction 'result.json'
$journalPath = Join-Path $transaction 'journal.json'
$root = [IO.Path]::GetFullPath([string]$plan.appRoot).TrimEnd('\')
$stage = [IO.Path]::GetFullPath([string]$plan.stageRoot).TrimEnd('\')
$backup = [IO.Path]::GetFullPath([string]$plan.backupRoot).TrimEnd('\')
$appProcess = $null
$restartOldApp = $false
function Write-JsonAtomic($Destination, $Value) {
  $temporary = $Destination + '.new'
  [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 15), [Text.UTF8Encoding]::new($false))
  if ([IO.File]::Exists($Destination)) { [IO.File]::Replace($temporary, $Destination, [NullString]::Value) }
  else { [IO.File]::Move($temporary, $Destination) }
}
function Resolve-SafeFile([string]$Base, [string]$Relative) {
  if (-not $Relative -or $Relative.Contains('\') -or $Relative.Length -gt 230) { throw '更新文件路径无效' }
  $cursor = $Base
  if ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '更新目录不能为链接' }
  foreach ($part in $Relative.Split('/')) {
    if (-not $part -or $part -in @('.', '..') -or $part -match '[<>:"|?*\x00-\x1f]' -or $part -match '[. ]$' -or $part -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)') { throw '更新文件路径无效' }
    $cursor = Join-Path $cursor $part
    if (Test-Path -LiteralPath $cursor) {
      if ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '更新路径不能包含链接' }
    }
  }
  $resolved = [IO.Path]::GetFullPath($cursor)
  if (-not $resolved.StartsWith($Base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '更新路径越界' }
  return $resolved
}
function Assert-File($Base, $File) {
  $target = Resolve-SafeFile $Base ([string]$File.path)
  if (-not [IO.File]::Exists($target) -or (Get-Item -LiteralPath $target).Length -ne $File.size) { throw ('文件校验失败：' + $File.path) }
  $algorithm = [Security.Cryptography.SHA256]::Create()
  $stream = [IO.File]::OpenRead($target)
  try { $hash = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
  finally { $stream.Dispose(); $algorithm.Dispose() }
  if ($hash -ne $File.sha256) { throw ('文件校验失败：' + $File.path) }
}
function Replace-File([string]$Source, [string]$Destination) {
  [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Destination)) | Out-Null
  $temporary = $Destination + '.poe-update-' + [Guid]::NewGuid().ToString('N')
  [IO.File]::Copy($Source, $temporary, $false)
  try {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
      try {
        if ([IO.File]::Exists($Destination)) { [IO.File]::Replace($temporary, $Destination, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Destination) }
        return
      } catch {
        if ($attempt -eq 39) { throw }
        Start-Sleep -Milliseconds 250
      }
    }
  } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}
function Rollback {
  foreach ($file in $plan.beforeFiles) {
    $target = Resolve-SafeFile $root ([string]$file.path)
    if ($file.exists) {
      Assert-File $backup $file
      Replace-File (Resolve-SafeFile $backup ([string]$file.path)) $target
      Assert-File $root $file
    } elseif ([IO.File]::Exists($target)) { [IO.File]::Delete($target) }
  }
}
try {
  if ($plan.schema -ne 1 -or $plan.executable -ne '物价补丁.exe' -or $plan.token -notmatch '^[a-f0-9-]{36}$' -or
      $root -eq $stage -or $root -eq $backup -or $transaction.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
      -not $stage.StartsWith($transaction + '\', [StringComparison]::OrdinalIgnoreCase) -or
      -not $backup.StartsWith($transaction + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '安装计划无效' }
  [IO.Directory]::CreateDirectory($backup) | Out-Null
  if ($Recover) {
    $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($journal.state -notin @('applying', 'rollback-failed')) { throw '此更新无需恢复' }
    Rollback
    Write-JsonAtomic $journalPath @{ state='rolled-back' }
    Write-JsonAtomic $resultPath @{ status='rolled-back'; message='已恢复更新前的软件文件'; version=$plan.version }
    exit 0
  }
  if (Test-Path -LiteralPath $journalPath) { throw '此安装计划已执行，不能重复安装' }
  foreach ($file in $plan.files) { Assert-File $stage $file }
  Write-JsonAtomic (Join-Path $transaction 'helper-ready.json') @{ ready=$true; token=$plan.token }
  $deadline = [DateTime]::UtcNow.AddSeconds(120)
  while ($plan.parentPid -gt 0 -and (Get-Process -Id $plan.parentPid -ErrorAction SilentlyContinue)) {
    if (Test-Path -LiteralPath (Join-Path $transaction 'abort')) { throw '安装已取消' }
    if ([DateTime]::UtcNow -gt $deadline) { throw '等待软件退出超时，尚未安装' }
    Start-Sleep -Milliseconds 200
  }
  if (Test-Path -LiteralPath (Join-Path $transaction 'abort')) { throw '安装已取消' }
  # The parent has exited after a validated handoff. Pre-commit failures must
  # reopen the unchanged application; cancelled/invalid handoffs must not.
  $restartOldApp = $plan.parentPid -gt 0
  foreach ($file in $plan.baseFiles) { Assert-File $root $file }
  foreach ($file in $plan.beforeFiles) {
    $target = Resolve-SafeFile $root ([string]$file.path)
    if ($file.exists) {
      Assert-File $root $file
      $saved = Resolve-SafeFile $backup ([string]$file.path)
      [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($saved)) | Out-Null
      [IO.File]::Copy($target, $saved, $false)
      Assert-File $backup $file
    } elseif (Test-Path -LiteralPath $target) { throw '更新目标在下载后发生变化' }
  }
  # Commit starts only after every pre-update file has a verified backup.
  Write-JsonAtomic $journalPath @{ state='applying'; version=$plan.version }
  foreach ($file in $plan.files) {
    Replace-File (Resolve-SafeFile $stage ([string]$file.path)) (Resolve-SafeFile $root ([string]$file.path))
  }
  foreach ($file in $plan.removeFiles) { [IO.File]::Delete((Resolve-SafeFile $root ([string]$file.path))) }
  foreach ($file in $plan.targetFiles) { Assert-File $root $file }
  if ($plan.restart) {
    $executable = Resolve-SafeFile $root ([string]$plan.executable)
    $appProcess = Start-Process -FilePath $executable -WorkingDirectory $root -ArgumentList @('--software-update-token=' + $plan.token) -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    $healthy = $false
    while ([DateTime]::UtcNow -lt $deadline) {
      $ack = Join-Path $transaction 'health.json'
      if (Test-Path -LiteralPath $ack) {
        $health = Get-Content -LiteralPath $ack -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($health.token -eq $plan.token -and $health.version -eq $plan.version) { $healthy = $true; break }
      }
      if ($appProcess.HasExited) { break }
      Start-Sleep -Milliseconds 250
      $appProcess.Refresh()
    }
    if (-not $healthy) { throw '新版本启动验证未通过' }
  }
  Write-JsonAtomic $journalPath @{ state='completed'; version=$plan.version }
  Write-JsonAtomic $resultPath @{ status='completed'; message='软件更新完成'; version=$plan.version }
} catch {
  $reason = $_.Exception.Message
  $state = 'failed'
  try {
    if ($appProcess -and -not $appProcess.HasExited) {
      $killer = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/taskkill.exe') -ArgumentList @('/PID', [string]$appProcess.Id, '/T', '/F') -WindowStyle Hidden -Wait -PassThru
    }
    if (Test-Path -LiteralPath $journalPath) {
      $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($journal.state -eq 'applying') {
        Rollback
        $state = 'rolled-back'
        Write-JsonAtomic $journalPath @{ state=$state; version=$plan.version }
      }
    }
  } catch {
    $state = 'rollback-failed'
    $reason += '; 恢复失败：' + $_.Exception.Message
    Write-JsonAtomic $journalPath @{ state=$state; version=$plan.version }
  }
  Write-JsonAtomic $resultPath @{ status=$state; message=$reason; version=$plan.version }
  if (($state -eq 'rolled-back' -or ($state -eq 'failed' -and $restartOldApp)) -and $plan.restart) {
    Start-Process -FilePath (Resolve-SafeFile $root ([string]$plan.executable)) -WorkingDirectory $root -WindowStyle Hidden | Out-Null
  }
  exit 1
}
