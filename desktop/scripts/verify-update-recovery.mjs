import { _electron as electron } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const packaged = process.argv.includes('--packaged')
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-update-recovery-'))
const profile = path.join(sandbox, 'profile')
const config = path.join(profile, 'desktop-settings.json')
const game = path.join(sandbox, 'Path of Exile 2')
const engine = path.join(profile, 'engine')
await fs.mkdir(path.join(game, 'Bundles2'), { recursive: true })
await fs.writeFile(path.join(game, 'Bundles2/_.index.bin'), 'inert fixture, never patched')
await fs.cp(path.join(root, '.runtime'), engine, { recursive: true })
const manifest = JSON.parse(await fs.readFile(path.join(engine, 'manifest.json'), 'utf8'))
await fs.writeFile(path.join(engine, '.ready'), manifest.id)
// Only the disposable profile contains this sentinel. The production worker still
// validates the client, checks running games, and acquires the directory mutex.
await fs.writeFile(
  path.join(engine, 'tools/update_price_patch.ps1'),
  '\ufeffparam([string]$Poe2Dir,[string]$PatchScope,[string]$League,[string]$PoeNinjaLeague,[string]$PoeCurrencySeason,[bool]$LeagueIsCurrent,[switch]$IslandRumourHints,[switch]$SkipGameDirectoryMutex)\nWrite-Output "recovery-fixture-success"\nexit 0\n'
)
const request = {
  operation: 'update',
  gameVersion: 'poe2',
  gameDirectory: game,
  patchScope: 'all',
  languageMode: 'auto',
  league: 'Fixture',
  poeNinjaLeague: 'Fixture',
  poeCurrencySeason: '',
  leagueIsCurrent: true,
  islandRumourHints: true
}
const seed = {
  settings: {
    gameVersion: 'poe2',
    directories: { poe1: '', poe2: game },
    languageMode: 'auto',
    patchScope: 'all',
    islandRumourHints: true,
    autoStart: false,
    autoUpdate: true,
    closeToTray: true,
    theme: 'light',
    backgroundOpacity: 20
  },
  confirmed: {
    request,
    installKind: 'Intl-Bundles2',
    successAt: new Date(Date.now() - 7200_000).toISOString()
  },
  history: []
}
await fs.writeFile(config, JSON.stringify(seed))
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
let application
const evidence = { packaged, sandbox, checks: [] }
async function launch() {
  application = await electron.launch({
    ...(packaged ? { executablePath: path.join(root, 'dist/win-unpacked/物价补丁.exe') } : {}),
    args: [...(packaged ? [] : [root]), '--hidden'],
    env,
    timeout: 30000
  })
}
async function savedWhen(predicate) {
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    const saved = JSON.parse(await fs.readFile(config, 'utf8'))
    if (predicate(saved)) return saved
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Persisted state did not reach expected state')
}
try {
  await launch()
  const first = await savedWhen((state) => state.history.length === 1)
  assert.equal(first.history[0].exitCode, 0, JSON.stringify(first.history[0]))
  assert.equal(first.history[0].automatic, true)
  assert.match(first.history[0].stdout, /recovery-fixture-success/)
  assert.equal(
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length),
    0
  )
  const due = first.autoUpdateSchedule.nextAttemptAt
  assert.ok(Date.parse(due) > Date.now())
  evidence.checks.push('过期计划在真实后台启动后补更一次，零窗口，结果和下次执行点写入磁盘')
  await application.close()
  application = null
  await launch()
  await new Promise((resolve) => setTimeout(resolve, 1500))
  const restarted = JSON.parse(await fs.readFile(config, 'utf8'))
  assert.equal(restarted.history.length, 1)
  assert.equal(restarted.autoUpdateSchedule.nextAttemptAt, due)
  evidence.checks.push('重启保留未到期计划，不重复更新、不推迟执行点')
  await application.evaluate(({ powerMonitor }) => {
    globalThis.__recoveryNow = Date.now
    const future = Date.now() + 3600_001
    Date.now = () => future
    powerMonitor.emit('resume')
  })
  const resumed = await savedWhen((state) => state.history.length === 2)
  assert.equal(resumed.history[0].exitCode, 0, JSON.stringify(resumed.history[0]))
  assert.equal(resumed.history[0].automatic, true)
  await application.evaluate(() => {
    Date.now = globalThis.__recoveryNow
  })
  evidence.checks.push('真实 powerMonitor 恢复事件触发过期补更，完成后重新安排一小时')
  await application.close()
  application = null
  await fs.writeFile(
    config,
    JSON.stringify({ ...seed, confirmed: { request: { ...request, operation: 'restore' } } })
  )
  await launch()
  const invalid = await savedWhen((state) => state.confirmed === null)
  assert.equal(invalid.settings.autoUpdate, true)
  assert.equal(invalid.autoUpdateSchedule, null)
  assert.deepEqual(invalid.history, [])
  evidence.checks.push('损坏/非更新确认配置被清除，保留自动更新开关并等待重新手动确认')
  assert.equal(
    await fs.readFile(path.join(game, 'Bundles2/_.index.bin'), 'utf8'),
    'inert fixture, never patched'
  )
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  if (application) await application.close()
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, `test-results/update-recovery-${packaged ? 'packaged' : 'dev'}.json`),
    JSON.stringify(evidence, null, 2)
  )
}
