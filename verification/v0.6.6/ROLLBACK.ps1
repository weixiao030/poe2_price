param([Parameter(Mandatory=$true)][string]$TargetCopy)
$dir=Split-Path -Parent $TargetCopy
$baseline=Join-Path $dir 'ORIGINAL_Program.cs'
if(!(Test-Path $baseline)){throw "baseline missing"}
Copy-Item $baseline $TargetCopy -Force
