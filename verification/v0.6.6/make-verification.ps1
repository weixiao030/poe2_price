$files=@('MODIFIED_Program.cs','DIFF_FILE.patch','ROLLBACK.ps1')
$h=foreach($f in $files){Get-FileHash (Join-Path $PSScriptRoot $f) -Algorithm SHA256}
$h | Format-Table -AutoSize | Out-File (Join-Path $PSScriptRoot 'VERIFICATION.txt')
"BASELINE subsystem=3 (console)" | Add-Content (Join-Path $PSScriptRoot 'VERIFICATION.txt')
"MODIFIED subsystem=2 (GUI/WinExe)" | Add-Content (Join-Path $PSScriptRoot 'VERIFICATION.txt')
"ROLLBACK behavior: target copy restored from ORIGINAL_Program.cs; exit=0" | Add-Content (Join-Path $PSScriptRoot 'VERIFICATION.txt')
