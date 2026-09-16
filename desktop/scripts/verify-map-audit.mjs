import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const checks = []
async function source(file) {
  return fs.readFile(path.join(root, file), 'utf8')
}
async function scan(directory) {
  for (const entry of await fs.readdir(path.join(root, directory), { withFileTypes: true })) {
    if (['bin', 'obj'].includes(entry.name)) continue
    const file = `${directory}/${entry.name}`
    if (entry.isDirectory()) await scan(file)
    else if (/\.(cs|ts|vue)$/.test(file)) {
      assert.doesNotMatch(
        await source(file),
        /\b(WriteProcessMemory|VirtualAllocEx|CreateRemoteThread|SendInput|keybd_event|mouse_event|PROCESS_ALL_ACCESS)\b/,
        file
      )
    }
  }
}
await scan('world-map')
await scan('desktop/src')
checks.push('No remote memory write, allocation, injection or game-input APIs in shipped module')
const main = await source('desktop/src/main/index.ts')
assert.match(main, /event\.senderFrame !== window\.webContents\.mainFrame/)
assert.match(main, /pending\.token !== token/)
assert.match(main, /pending\.expires < Date\.now\(\)/)
assert.match(main, /consentVersion: MAP_CONSENT_VERSION/)
assert.doesNotMatch(
  main.match(/function schedule\(\)[\s\S]*?function showWindow/)[0],
  /worldMap\.enabled|mapChanging/
)
checks.push('Main-frame IPC boundary, explicit risk acceptance and independent hourly scheduling')
const overlay = await source('desktop/src/main/world-map-overlay.ts')
for (const expression of [
  /sandbox: true/,
  /contextIsolation: true/,
  /nodeIntegration: false/,
  /setIgnoreMouseEvents\(true/,
  /focusable: false/,
  /lastUpdate > 1000/
])
  assert.match(overlay, expression)
assert.doesNotMatch(await source('desktop/src/preload/overlay.ts'), /ipcRenderer\.(invoke|send)\(/)
checks.push(
  'Sandboxed, receive-only overlay bridge; no focus or mouse capture; stale-frame timeout'
)
assert.match(
  await source('world-map/Upstream/GameReader.cs'),
  /OpenProcess\(VmRead \| QueryInformation, false/
)
assert.match(await source('world-map/ClientGate.cs'), /us\.patch\.pathofexile2\.com/)
assert.match(await source('desktop/resources/worker.ps1'), /if \(\$Running\.Count -gt 0\)/)
checks.push(
  'Read/query-only process rights; positive international marker; patch running-game guard retained'
)
const result = {
  scope: ['world-map', 'desktop/src', 'desktop/resources/worker.ps1'],
  checks,
  limitation:
    'Targeted source assertions plus manual review, not a Semgrep/CodeQL certification; same-user filesystem replacement races remain outside the trust boundary.'
}
await fs.mkdir(path.join(root, 'desktop/test-results'), { recursive: true })
await fs.writeFile(
  path.join(root, 'desktop/test-results/world-map-audit.json'),
  JSON.stringify(result, null, 2)
)
console.log(JSON.stringify(result, null, 2))
