import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const runtime = path.join(root, '.runtime')
const reportDir = path.join(root, 'test-results')
await fs.mkdir(reportDir, { recursive: true })
const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-runtime-qa-'))
const results = []
async function run(command, args) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: runtime,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1', __COMPAT_LAYER: 'RunAsInvoker' }
    })
    const stdout = [],
      stderr = []
    child.stdout.on('data', (chunk) => stdout.push(chunk))
    child.stderr.on('data', (chunk) => stderr.push(chunk))
    child.once('error', reject)
    child.once('close', (exitCode) => {
      const result = {
        command: [command, ...args],
        exitCode,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
        durationMs: Date.now() - started
      }
      results.push(result)
      resolve(result)
    })
  })
}
const manifest = JSON.parse(await fs.readFile(path.join(runtime, 'manifest.json'), 'utf8'))
for (const [relative, expected] of Object.entries(manifest.files))
  assert.equal(
    crypto
      .createHash('sha256')
      .update(await fs.readFile(path.join(runtime, relative)))
      .digest('hex'),
    expected,
    relative
  )
const python = await run(path.join(runtime, 'tools/python/poe_python.exe'), [
  '-c',
  'import sys,json,ssl,urllib.request,zipfile,decimal,html; print(json.dumps({"version":sys.version,"ssl":ssl.OPENSSL_VERSION,"imports":"ok"}))'
])
assert.equal(python.exitCode, 0)
const dotnet = await run(path.join(runtime, 'tools/dotnet-runtime/dotnet.exe'), ['--list-runtimes'])
assert.equal(dotnet.exitCode, 0)
assert.ok(dotnet.stdout.includes('Microsoft.NETCore.App 8.'))
if (process.argv.includes('--live')) {
  const queries = [
    { gameVersion: 'poe1', china: false },
    { gameVersion: 'poe2', china: false },
    { gameVersion: 'poe1', china: true },
    { gameVersion: 'poe2', china: true }
  ]
  const output = await Promise.allSettled(
    queries.map(async (query, i) => {
      const file = path.join(temp, `${i}.json`)
      await fs.writeFile(file, JSON.stringify({ action: 'leagues', ...query }))
      const result = await run(
        path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'),
        [
          '-NoLogo',
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          path.join(runtime, 'worker.ps1'),
          '-RequestPath',
          file
        ]
      )
      assert.equal(result.exitCode, 0)
      const data = JSON.parse(
        result.stdout
          .split(/\r?\n/)
          .find((x) => x.startsWith('__POE_RESULT__'))
          .slice(14)
      )
      assert.ok(Array.isArray(data) && data.length)
      return {
        ...query,
        count: data.length,
        fallback: !!data[0].DiscoveryFallback,
        first: data[0].Label
      }
    })
  )
  console.log(JSON.stringify({ liveLeagues: output }, null, 2))
  for (const result of output) assert.equal(result.status, 'fulfilled')
}
await fs.writeFile(
  path.join(reportDir, 'runtime-evidence.json'),
  JSON.stringify(
    { manifest: manifest.id, files: Object.keys(manifest.files).length, results },
    null,
    2
  )
)
console.log(
  JSON.stringify(
    {
      verifiedFiles: Object.keys(manifest.files).length,
      python: python.stdout.trim(),
      dotnet: dotnet.stdout.trim()
    },
    null,
    2
  )
)
