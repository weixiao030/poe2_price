param([Parameter(Mandatory=$true)][string]$Path, [Parameter(Mandatory=$true)][string]$Region)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class OverlayCapture {
  [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr h);
  [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr h, IntPtr dc);
  [DllImport("gdi32.dll")] public static extern bool BitBlt(IntPtr dest,int x,int y,int w,int h,IntPtr source,int sx,int sy,uint op);
}
'@
$r = $Region.Split(',') | ForEach-Object { [int]$_ }
$bitmap = New-Object System.Drawing.Bitmap($r[2], $r[3])
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
  $source = [OverlayCapture]::GetDC([IntPtr]::Zero)
  $destination = $graphics.GetHdc()
  try {
    if (-not [OverlayCapture]::BitBlt($destination,0,0,$r[2],$r[3],$source,$r[0],$r[1],0x40CC0020)) { throw 'CaptureBlt failed' }
  } finally { $graphics.ReleaseHdc($destination); [OverlayCapture]::ReleaseDC([IntPtr]::Zero,$source) | Out-Null }
  $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Output $Path
} finally { $graphics.Dispose(); $bitmap.Dispose() }
