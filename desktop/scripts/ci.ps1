$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
function Invoke-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
Invoke-Checked { npm ci }
Invoke-Checked { npm run prepare:runtime }
Invoke-Checked { npm run test:migration }
Invoke-Checked { npm test }
Invoke-Checked { node scripts/verify-auto-lock.mjs }
Invoke-Checked { npm run test:runtime }
Invoke-Checked { npm run build }
Invoke-Checked { node scripts/verify-startup.mjs }
Invoke-Checked { npm run test:desktop }
Invoke-Checked { npx electron-builder --publish never }
Invoke-Checked { node scripts/verify-package.mjs --ci }
Invoke-Checked { node scripts/verify-startup.mjs --packaged }
Invoke-Checked { node scripts/verify-update-recovery.mjs --packaged }
