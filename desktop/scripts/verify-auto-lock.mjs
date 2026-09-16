import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-lock-check-'))
const game = path.join(temporary, 'Path of Exile 2')
await fs.mkdir(path.join(game, 'Bundles2'), { recursive: true })
await fs.writeFile(path.join(game, 'Bundles2/_.index.bin'), 'lock-test-no-game-data')
const quote = (value) => "'" + value.replaceAll("'", "''") + "'"
const holder = path.join(temporary, 'hold.ps1')
await fs.writeFile(holder, '\ufeff' + `. ${quote(path.join(root, '.runtime/tools/poe2_patch_common.ps1'))}\n$m = Enter-Poe2GameDirectoryMutex -Poe2Dir ${quote(game)}\nWrite-Output 'LOCK_HELD'\ntry { [Console]::ReadLine() | Out-Null } finally { $m.ReleaseMutex(); $m.Dispose() }\n`)
const argumentsFor = (file) => ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', file]
const child = spawn('powershell.exe', argumentsFor(holder), { windowsHide: true, stdio: 'pipe' })
try {
  await new Promise((resolve, reject) => {
    let data = ''
    child.stdout.on('data', (chunk) => { data += chunk; if (data.includes('LOCK_HELD')) resolve() })
    child.once('error', reject)
    child.once('exit', () => reject(new Error('Lock holder exited before verification')))
  })
  const request = path.join(temporary, 'request.json')
  await fs.writeFile(request, JSON.stringify({ action: 'run', automatic: true, expectedKind: 'Intl-Standalone-Bundles2',
    script: 'update_price_patch.ps1', arguments: { Poe2Dir: game },
    request: { gameVersion: 'poe2', gameDirectory: game, languageMode: 'auto', operation: 'update' } }))
  // The expected type is obtained from the real detection code; no update script is replaced.
  const payload = JSON.parse(await fs.readFile(request, 'utf8'))
  delete payload.expectedKind
  await fs.writeFile(request, JSON.stringify(payload))
  const worker = spawn('powershell.exe', [...argumentsFor(path.join(root, '.runtime/worker.ps1')), '-RequestPath', request], { windowsHide: true })
  let stdout = '', stderr = ''
  worker.stdout.on('data', (chunk) => { stdout += chunk })
  worker.stderr.on('data', (chunk) => { stderr += chunk })
  const exitCode = await new Promise((resolve, reject) => { worker.once('close', resolve); worker.once('error', reject) })
  assert.equal(exitCode, 2, stdout + stderr)
  assert.match(stdout, /同一游戏目录已有更新任务/)
  assert.equal(await fs.readFile(path.join(game, 'Bundles2/_.index.bin'), 'utf8'), 'lock-test-no-game-data')
  const evidence = { exitCode, stdout, stderr, unchanged: true }
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(path.join(root, 'test-results/auto-lock-evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify(evidence))
} finally {
  child.stdin.end('\n')
  await new Promise((resolve) => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve) })
}
