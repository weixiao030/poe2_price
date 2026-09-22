// Explicitly opt in with both real client directories. Never start a game.
import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, all) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), all[i + 1]])
  return pairs
}, []))
for (const required of ['international-dir', 'china-dir', 'app-dir', 'report-dir'])
  assert.ok(options[required] && !options[required].startsWith('--'), `Missing --${required}`)
const appDir = path.resolve(options['app-dir'])
const report = path.resolve(options['report-dir'])
const scenario = options.scenario || 'full'
assert.ok(['full', 'smoke'].includes(scenario), 'Unsupported --scenario')
await fs.mkdir(report, { recursive: false }) // Preserve earlier evidence, never overwrite it.
const evidence = { appDir, scenario, startedAt: new Date().toISOString(), clients: [], completed: false }
const profile = path.join(report, 'profile')
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
let app, current, pending = Promise.resolve()
const readJson = async (file) => JSON.parse((await fs.readFile(file, 'utf8')).replace(/^\ufeff/, ''))
async function inspect(gameDirectory, output, patchZip = '') {
  await fs.mkdir(output, { recursive: true })
  const args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(desktop, 'scripts/inspect-poe2-resources.ps1'),
    '-Engine', path.join(appDir, 'resources/engine'), '-GameDirectory', gameDirectory, '-OutputDirectory', output]
  if (patchZip) args.push('-PatchZip', patchZip)
  await new Promise((resolve, reject) => {
    const process = spawn('powershell.exe', args, { windowsHide: true })
    let outputText = ''
    process.stdout.on('data', (data) => { outputText += data.toString() })
    process.stderr.on('data', (data) => { outputText += data.toString() })
    const timer = setTimeout(() => { process.kill(); reject(new Error('readback timeout')) }, 300_000)
    process.on('error', reject)
    process.on('exit', async (code) => {
      clearTimeout(timer)
      await fs.writeFile(path.join(output, 'extract.log'), outputText)
      code === 0 ? resolve() : reject(new Error(`Readback failed (${code}): ${outputText.slice(-1800)}`))
    })
  })
  return readJson(path.join(output, 'resources.json'))
}
try {
  app = await electron.launch({ executablePath: path.join(appDir, '物价补丁.exe'), env, timeout: 60000 })
  const page = await app.firstWindow()
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000))
  assert.equal(await app.evaluate(({ app }) => app.getVersion()), '0.9.2')
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false, autoUpdate: false }))
  await page.exposeFunction('saveProgress', (event) => {
    if (current) {
      const file = path.join(current, 'progress.jsonl')
      pending = pending.then(() => fs.appendFile(file, JSON.stringify(event) + '\n'))
    }
  })
  await page.evaluate(() => window.desktop.onProgress(window.saveProgress))
  for (const [name, directory] of [['international', options['international-dir']], ['china', options['china-dir']]]) {
    const gameDirectory = path.resolve(directory)
    const clientReport = path.join(report, name)
    await fs.mkdir(clientReport)
    const client = await page.evaluate((dir) => window.desktop.inspectGame('poe2', dir, 'auto'), gameDirectory)
    assert.equal(client.isChina, name === 'china')
    const record = { name, client, cases: [], restored: false }
    evidence.clients.push(record)
    const persistent = path.join(gameDirectory, '.poe2-price-patch')
    await fs.cp(persistent, path.join(clientReport, 'before-restore-materials'), { recursive: true, errorOnExist: true, force: false })
    record.before = await inspect(gameDirectory, path.join(clientReport, 'before-resources'))
    const leagues = await page.evaluate((china) => window.desktop.getLeagues('poe2', china), client.isChina)
    const league = leagues.find((item) => item.IsCurrent && !item.DiscoveryFallback)
    assert.ok(league, 'Current live league must be discovered')
    await fs.writeFile(path.join(clientReport, 'leagues.json'), JSON.stringify(leagues, null, 2))
    async function run(caseName, operation, scope = 'all', hints = false) {
      current = path.join(clientReport, caseName)
      await fs.mkdir(current)
      const request = { operation, gameVersion: 'poe2', gameDirectory, languageMode: 'auto', patchScope: scope,
        islandRumourHints: hints, league: league.ScoutLeague || '', poeNinjaLeague: league.PoeNinjaLeague || '',
        poeCurrencySeason: league.PoeCurrencySeason || '', leagueIsCurrent: true, leagueMode: 'fixed' }
      console.log('REAL_CASE_START', name, caseName)
      const result = await page.evaluate((request) => window.desktop.runOperation(request), request)
      await pending
      await fs.writeFile(path.join(current, 'result.json'), JSON.stringify({ request, result }, null, 2))
      record.cases.push({ caseName, exitCode: result.exitCode, durationMs: result.durationMs })
      assert.equal(result.exitCode, 0, `${name}/${caseName}: ${result.stderr || result.stdout.slice(-3500)}`)
      if (operation === 'update') {
        const output = path.join(profile, 'engine/output/poe2_price_patch_latest')
        const patch = path.join(current, 'patch.zip')
        await fs.copyFile(path.join(output, '物价补丁.zip'), patch)
        for (const file of await fs.readdir(output))
          if (/\.json$/.test(file)) await fs.copyFile(path.join(output, file), path.join(current, file))
        const resources = await inspect(gameDirectory, path.join(current, 'readback'), patch)
        record.cases.at(-1).verifiedResources = resources.length
      }
      console.log('REAL_CASE_PASSED', name, caseName, result.durationMs)
      await fs.writeFile(path.join(report, 'evidence.json'), JSON.stringify(evidence, null, 2))
    }
    await run('00-clean-baseline', 'restore')
    const baseline = await inspect(gameDirectory, path.join(clientReport, 'clean-baseline'))
    try {
      const cases = [['01-all', 'all', true], ['02-repeat-all', 'all', true],
        ['03-currency-no-hints', 'currency', false], ['04-uniques-hints', 'uniques', true], ['05-hints-only', 'none', true]]
      for (const [caseName, scope, hints] of scenario === 'smoke' ? cases.slice(0, 1) : cases)
        await run(caseName, 'update', scope, hints)
    } finally {
      await run('06-final-restore', 'restore')
      const restored = await inspect(gameDirectory, path.join(clientReport, 'restored'))
      assert.deepEqual(restored, baseline, 'All restored core resources must match the clean baseline')
      record.restored = true
    }
    await page.screenshot({ path: path.join(clientReport, 'restored.png'), fullPage: true })
  }
  evidence.completed = true
} catch (error) {
  evidence.failure = String(error)
  throw error
} finally {
  await pending
  if (app) await app.close()
  evidence.finishedAt = new Date().toISOString()
  await fs.writeFile(path.join(report, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
console.log(JSON.stringify({ completed: evidence.completed, clients: evidence.clients.map(({ name, cases, restored }) => ({ name, cases, restored })) }, null, 2))
