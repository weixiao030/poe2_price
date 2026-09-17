import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const directory = process.argv[2]
const expectClosed = process.argv.includes('--closed')
if (!directory) throw Error('Pass the authorized, currently running game directory')
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-running-guard-'))
const request = path.join(temporary, 'request.json')
// A deliberately invalid script ensures a missed process guard can never modify game files.
await fs.writeFile(
  request,
  JSON.stringify({
    action: 'run',
    automatic: true,
    request: {
      gameVersion: 'poe2',
      gameDirectory: directory,
      languageMode: 'auto',
      operation: 'update'
    },
    script: '__never_execute__',
    arguments: {}
  })
)
const result = spawnSync(
  'powershell.exe',
  [
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    path.join(root, '.runtime/worker.ps1'),
    '-RequestPath',
    request
  ],
  { encoding: 'utf8', windowsHide: true }
)
const evidence = {
  command: 'production worker run, automatic=true, forbidden script sentinel',
  directory,
  stdout: result.stdout,
  stderr: result.stderr,
  exitCode: result.status
}
await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
await fs.writeFile(
  path.join(root, 'test-results/running-game-guard.json'),
  JSON.stringify(evidence, null, 2)
)
console.log(JSON.stringify(evidence, null, 2))
if (expectClosed) {
  assert.equal(result.status, 1)
  assert.match(result.stderr, /无效脚本/)
  assert.doesNotMatch(result.stdout, /当前游戏正在运行/)
} else {
  assert.equal(result.status, 2)
  assert.match(result.stdout, /当前游戏正在运行/)
}
