param([switch]$Immediate, [string]$SettingsPath = "")
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8;$OutputEncoding=[Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'poe2_patch_common.ps1')
. (Join-Path $PSScriptRoot 'poe_patch_profiles.ps1')
$LogDir = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'PoePricePatch\logs'
function Write-WorkerLog([object]$Value) { try { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null; $file=Join-Path $LogDir ((Get-Date).ToString('yyyy-MM-dd') + '.jsonl'); Add-Content -LiteralPath $file -Value (($Value | ConvertTo-Json -Compress)); $info=Get-Item $file; if($info.Length -gt 1048576){$lines=Get-Content $file -Tail 1000; Set-Content -LiteralPath $file -Value $lines -Encoding UTF8} } catch {} }
$sw=[Diagnostics.Stopwatch]::StartNew(); $state=Get-PoePatchSettingsState -SettingsPath $SettingsPath
$script:GameDirectoryMutex = $null
function Result($status,$message,$extra=@{}) { $sw.Stop(); $o=[ordered]@{status=$status;message=$message;duration_seconds=[Math]::Round($sw.Elapsed.TotalSeconds,1);timestamp_utc=(Get-Date).ToUniversalTime().ToString('o')}; foreach($k in $extra.Keys){$o[$k]=$extra[$k]}; $json=$o|ConvertTo-Json -Compress; Write-Output $json; try { Set-PoePatchAutoUpdateResult -Status $status -Message $message -SettingsPath $SettingsPath } catch {}; Write-WorkerLog $o; if($null -ne $script:GameDirectoryMutex){try{$script:GameDirectoryMutex.ReleaseMutex()}catch{};try{$script:GameDirectoryMutex.Dispose()}catch{};$script:GameDirectoryMutex=$null}; exit $(if($status -eq 'success'){0}else{if($status -eq 'skipped'){2}else{1}}) }
if(-not [bool]$state.auto_update){ Result 'skipped' '自动更新未启用' }
$sel=$state.last_selection
if($null -eq $sel -or -not [bool]$sel.confirmed -or [string]::IsNullOrWhiteSpace([string]$sel.game_directory)){ Result 'skipped' '尚未完成手动补丁配置' }
$dir=[IO.Path]::GetFullPath([string]$sel.game_directory); if(-not (Test-Path -LiteralPath $dir -PathType Container)){ Result 'failed' "游戏目录不存在：$dir" }
$procs=@('PathOfExile','PathOfExile_x64','PathOfExileSteam','PathOfExile_x64Steam','PathOfExile2','PathOfExile2Steam')
$gameRoot = $dir.TrimEnd('\','/')
$running = @(Get-Process -Name $procs -ErrorAction SilentlyContinue | Where-Object {
    try {
        $path = $_.Path
        if ([string]::IsNullOrWhiteSpace($path)) { return $true }
        $full = [IO.Path]::GetFullPath($path)
        return $full.StartsWith($gameRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
            $full.StartsWith($gameRoot + [IO.Path]::AltDirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    } catch { return $true }
})
if($running.Count -gt 0){ Result 'skipped' '检测到当前游戏目录正在运行' @{game_directory=$dir} }
$ver=[string]$sel.game_version; $lang=[string]$sel.poe1_language_mode; if([string]::IsNullOrWhiteSpace($lang)){$lang='auto'}; $scope=[string]$sel.patch_scope; if([string]::IsNullOrWhiteSpace($scope)){$scope='all'}
try {
  $info = if ($ver -eq 'poe1') { Get-PoePatchInstallInfo -GameVersion $ver -GameDirectory $dir -Poe1LanguageMode $(if([string]::IsNullOrWhiteSpace($lang)){'auto'}else{$lang}) } else { Get-PoePatchInstallInfo -GameVersion $ver -GameDirectory $dir }
  if ($sel.install_kind -and [string]$sel.install_kind -ne [string]$info.InstallKind) { Result 'failed' "客户端类型已变化：记录为 $($sel.install_kind)，当前为 $($info.InstallKind)" @{game_version=$ver;game_directory=$dir} }
  if ($null -ne $sel.is_china -and [bool]$sel.is_china -ne [bool]$info.IsChina) { Result 'failed' '客户端服务器类型已变化，已停止自动更新' @{game_version=$ver;game_directory=$dir} }
  try { $script:GameDirectoryMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $dir } catch { Result 'skipped' '同一游戏目录已有更新任务，已跳过本轮' @{game_version=$ver;game_directory=$dir} }
  $args=@{}
  if($ver -eq 'poe1'){$scriptName='update_poe1_price_patch.ps1';$args=@{'Poe1Dir'=$dir;'Poe1LanguageMode'=$lang;'PatchScope'=$scope;'LeagueIsCurrent'=$true;'SkipGameDirectoryMutex'=$true}}
  else {$scriptName='update_price_patch.ps1';$args=@{'Poe2Dir'=$dir;'PatchScope'=$scope;'LeagueIsCurrent'=$true;'SkipGameDirectoryMutex'=$true}}
  if($ver -eq 'poe2' -and [bool]$sel.island_rumour_hints){$args['IslandRumourHints']=$true}
  $scriptPath=Join-Path $PSScriptRoot $scriptName
  $logPath=Join-Path $LogDir ((Get-Date).ToString('yyyy-MM-dd') + '-worker.log')
  $output = @(& $scriptPath @args 2>&1)
  ($output | Out-String) | Add-Content -LiteralPath $logPath -Encoding UTF8
  $resultExtra=@{game_version=$ver;game_directory=$dir;log_path=$logPath}
  $summaryRelative = if($ver -eq 'poe1'){'..\output\poe1_price_patch_latest\summary.json'}else{'..\output\poe2_price_patch_latest\summary.json'}
  $summaryPath=Join-Path $PSScriptRoot $summaryRelative
  if(Test-Path -LiteralPath $summaryPath -PathType Leaf){try{$summary=Get-Content -Raw $summaryPath|ConvertFrom-Json; if($summary.league){$resultExtra['league']=[string]$summary.league}; if($summary.poe_ninja_league){$resultExtra['poe_ninja_league']=[string]$summary.poe_ninja_league}}catch{}}
  if($LASTEXITCODE -ne 0){ Result 'failed' "更新脚本退出码：$LASTEXITCODE" $resultExtra }
  Result 'success' '自动更新成功' $resultExtra
} catch { Result 'failed' $_.Exception.Message @{game_version=$ver;game_directory=$dir} }
finally { if($null -ne $script:GameDirectoryMutex){try{$script:GameDirectoryMutex.ReleaseMutex()}catch{};try{$script:GameDirectoryMutex.Dispose()}catch{};$script:GameDirectoryMutex=$null} }
