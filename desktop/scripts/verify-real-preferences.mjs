// Explicit target only: real markets, packaged workers, game writes and exact readback.
import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const options = Object.fromEntries(process.argv.slice(2).reduce((out, value, i, all) => {
  if (value.startsWith('--')) out.push([value.slice(2), all[i + 1]])
  return out
}, []))
assert.ok(options['game-dir'] && options['report-dir'])
const gameDirectory = path.resolve(options['game-dir'])
const report = path.resolve(options['report-dir'])
const profile = path.join(report, 'profile')
const appDirectory = path.join(root, 'dist/win-unpacked')
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
await fs.mkdir(report, { recursive: true })
let app, page, current, sequence = Promise.resolve()
const checks = []
const readJson = async name => JSON.parse((await fs.readFile(name, 'utf8')).replace(/^\ufeff/, ''))
if (options.resume === 'true') {
  const previous = await readJson(path.join(report, 'result.json'))
  checks.push(...previous.checks)
}
async function launch() {
  app = await electron.launch({ executablePath: path.join(appDirectory, '物价补丁.exe'), env, timeout: 60000 })
  page = await app.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.exposeFunction('recordPreferencesProgress', event => {
    if (current) sequence = sequence.then(() => fs.appendFile(path.join(current, 'progress.jsonl'), JSON.stringify(event) + '\n'))
    for (const line of event.message.split(/\r?\n/))
      if (/^\[进度\]|^__POE_|^==>|^碑牌|^通货|^传奇|^岛屿|^READBACK/.test(line)) console.log(line)
  })
  await page.evaluate(() => window.desktop.onProgress(window.recordPreferencesProgress))
}
async function runShell(command, args, log) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' } })
    let output = ''
    child.stdout.on('data', data => { output += data.toString() })
    child.stderr.on('data', data => { output += data.toString() })
    child.on('error', reject)
    child.on('close', async code => {
      await fs.writeFile(log, output)
      code === 0 ? resolve() : reject(new Error(output.slice(-3500)))
    })
  })
}
try {
  await launch()
  const client = await page.evaluate(dir => window.desktop.inspectGame('poe2', dir, 'auto'), gameDirectory)
  await fs.writeFile(path.join(report, 'client.json'), JSON.stringify(client, null, 2))
  await page.evaluate(dir => window.desktop.saveSettings({ gameVersion: 'poe2', directories: { poe1: '', poe2: dir },
    patchScope: 'all', tabletPrices: true, tabletAffixPrices: true, islandRumourHints: true, closeToTray: false, autoUpdate: false }), gameDirectory)
  const cases = options['scope-matrix'] === 'true' ? [
    ['currency-tablets', true, true, 'currency'], ['uniques-tablets', true, true, 'uniques'],
    ['island-tablets', true, true, 'none'], ['island-names', true, false, 'none'],
    ['island-affixes', false, true, 'none'], ['island-no-tablets', false, false, 'none'],
    ['automatic-saved', false, true, 'none'], ['all-on-final', true, true, 'all']
  ] : [
    ['all-on', true, true], ['names-only', true, false], ['affixes-only', false, true], ['all-off', false, false],
    ['automatic-saved', false, true], ['restore', false, true], ['all-on-final', true, true]
  ]
  for (const [name, tabletPrices, tabletAffixPrices, patchScope = 'all'] of cases) {
    if (checks.some(check => check.name === name)) continue
    current = path.join(report, name)
    await fs.mkdir(current, { recursive: true })
    const before = await page.evaluate(() => window.desktop.getSnapshot())
    await page.evaluate(p => window.desktop.saveSettings(p), { tabletPrices, tabletAffixPrices, patchScope })
    console.log(`REAL_CASE ${name} ${gameDirectory}`)
    let result
    if (name === 'automatic-saved') {
      // Leave the previous successful request with both disabled, then restart
      // with newly saved affixes enabled and a due deadline in the test profile.
      await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: true }))
      await app.close(); app = undefined
      const configPath = path.join(profile, 'desktop-settings.json')
      const persisted = await readJson(configPath)
      assert.equal(persisted.confirmed.request.tabletAffixPrices, false)
      assert.equal(persisted.settings.tabletAffixPrices, true)
      persisted.autoUpdateSchedule = { nextAttemptAt: new Date(Date.now() - 1000).toISOString(), failures: 0, reason: 'startup' }
      await fs.writeFile(configPath, JSON.stringify(persisted, null, 2))
      await launch()
      const deadline = Date.now() + 1200000
      while (Date.now() < deadline) {
        const state = await page.evaluate(() => window.desktop.getSnapshot())
        if (!state.active && state.history[0]?.runId !== before.history[0]?.runId && state.history[0]?.automatic) {
          result = state.history[0]
          break
        }
        await new Promise(resolve => setTimeout(resolve, 1000))
      }
      assert.ok(result, 'Automatic update did not finish before the deadline')
      await fs.writeFile(path.join(current, 'result.json'), JSON.stringify(result, null, 2))
      assert.equal(result.exitCode, 0, result.stderr || result.stdout.slice(-3000))
      await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: false }))
      const saved = await readJson(configPath)
      assert.equal(saved.confirmed.request.tabletAffixPrices, true)
      assert.equal(saved.confirmed.request.tabletPrices, false)
    } else {
      const request = { operation: name === 'restore' ? 'restore' : 'update', gameVersion: 'poe2', gameDirectory,
        patchScope, tabletPrices, tabletAffixPrices, islandRumourHints: true,
        languageMode: 'auto', league: '', poeNinjaLeague: '', poeCurrencySeason: '', leagueIsCurrent: true, leagueMode: 'auto' }
      result = await page.evaluate(r => window.desktop.runOperation(r), request)
    }
    await sequence
    await fs.writeFile(path.join(current, 'result.json'), JSON.stringify(result, null, 2))
    assert.equal(result.exitCode, 0, result.stderr || result.stdout.slice(-3000))
    assert.equal(result.cancelled, false)
    const engine = path.join(profile, 'engine')
    const output = path.join(engine, 'output/poe2_price_patch_latest')
    const patch = path.join(output, '物价补丁.zip')
    const args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(root, 'scripts/inspect-poe2-resources.ps1'),
      '-Engine', engine, '-GameDirectory', gameDirectory, '-OutputDirectory', path.join(current, 'readback')]
    if (name !== 'restore') args.push('-PatchZip', patch)
    await runShell('powershell.exe', args, path.join(current, 'readback.log'))
    if (name !== 'restore') {
      await fs.cp(output, path.join(current, 'output'), { recursive: true })
      const summary = await readJson(path.join(output, 'summary.json'))
      assert.equal(summary.tablet_prices_enabled, tabletPrices)
      assert.equal(summary.tablet_affix_prices_enabled, tabletAffixPrices)
      assert.equal(summary.patch_scope, patchScope)
      assert.equal(summary.tablet_affixes.resources?.length > 0, tabletAffixPrices)
      assert.equal(summary.whole_tablets.base_names?.length > 0, tabletPrices)
      if (client.isChina && tabletPrices) assert.ok(summary.whole_tablets.unique_names.length > 0)
      assert.equal(summary.matched_items > 0, ['all', 'currency'].includes(patchScope))
      assert.equal(summary.unique_words_patched > 0, ['all', 'uniques'].includes(patchScope) || tabletPrices)
    }
    await runShell('python', [path.join(root, 'scripts/check-preference-readback.py'), path.join(current, 'readback'),
      name === 'restore' ? 'false' : String(tabletPrices), name === 'restore' ? 'false' : String(tabletAffixPrices), name === 'restore' ? 'none' : patchScope], path.join(current, 'semantic-check.json'))
    checks.push({ name, patchScope, tabletPrices, tabletAffixPrices, runId: result.runId, automatic: result.automatic, readback: true })
    await fs.writeFile(path.join(report, 'result.json'), JSON.stringify({ checks, completed: false }, null, 2))
    console.log('CASE_PASSED', name)
  }
  await fs.writeFile(path.join(report, 'result.json'), JSON.stringify({ checks, completed: true }, null, 2))
} finally { if (app) await app.close() }
