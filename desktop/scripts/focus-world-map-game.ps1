param([Parameter(Mandatory=$true)][string]$Executable, [switch]$Minimize)
$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MapWindowCheck {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int command);
  [DllImport("user32.dll")] public static extern IntPtr GetWindowLongPtrW(IntPtr h, int index);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint processId);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
}
'@
$game = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($Executable)) | Where-Object { $_.Path -eq $Executable } | Select-Object -First 1
if (-not $game -or -not $game.MainWindowHandle) { throw 'Authorized game window unavailable' }
if ($Minimize) { [MapWindowCheck]::ShowWindowAsync($game.MainWindowHandle, 6) | Out-Null }
else {
  [MapWindowCheck]::ShowWindowAsync($game.MainWindowHandle, 9) | Out-Null
  [uint32]$foregroundProcess = 0
  $foregroundThread = [MapWindowCheck]::GetWindowThreadProcessId([MapWindowCheck]::GetForegroundWindow(), [ref]$foregroundProcess)
  $thread = [MapWindowCheck]::GetCurrentThreadId()
  $attached = [MapWindowCheck]::AttachThreadInput($thread, $foregroundThread, $true)
  try { [MapWindowCheck]::SetForegroundWindow($game.MainWindowHandle) | Out-Null }
  finally { if ($attached) { [MapWindowCheck]::AttachThreadInput($thread, $foregroundThread, $false) | Out-Null } }
}
Start-Sleep -Milliseconds 200
[pscustomobject]@{ focused = [MapWindowCheck]::GetForegroundWindow() -eq $game.MainWindowHandle } | ConvertTo-Json -Compress
