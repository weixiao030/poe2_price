import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import assert from 'node:assert/strict'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const { version } = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
const evidence = path.resolve(root, '../verification/desktop-v' + version)
const profile = path.join(evidence, 'real-profile')
const args = process.argv.slice(2)
const appIndex = args.indexOf('--app-dir')
const appDirectory =
  appIndex < 0 ? path.join(root, 'dist/win-unpacked') : path.resolve(args.splice(appIndex, 2)[1])
const cases = args
if (!cases.length)
  throw new Error('Specify real test cases: poe1-all poe2-currency poe1-restore ...')
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({
  executablePath: path.join(appDirectory, '物价补丁.exe'),
  env,
  timeout: 60000
})
const page = await app.firstWindow()
let current,
  sequence = Promise.resolve()
await page.exposeFunction('recordRealProgress', (event) => {
  if (current)
    sequence = sequence.then(() =>
      fs.appendFile(path.join(current, 'progress.jsonl'), JSON.stringify(event) + '\n')
    )
  for (const line of event.message.split(/\r?\n/))
    if (
      /^(==>|\[进度\]|.*已安装|.*还原|.*完成|.*失败|Replaced:|Error|错误|警告)/.test(line) &&
      !line.trim().startsWith('"')
    )
      console.log(line)
})
await page.evaluate(() => window.desktop.onProgress(window.recordRealProgress))
try {
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  assert.equal(await app.evaluate(({ app }) => app.getVersion()), version)
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false, autoUpdate: false }))
  for (const name of cases) {
    const [gameVersion, mode, ...languageParts] = name.split('-')
    const language = languageParts.join('-') || 'auto'
    const gameDirectory = gameVersion === 'poe1' ? 'D:\\poe1' : 'D:\\poe2'
    const operation = ['restore', 'localize'].includes(mode) ? mode : 'update'
    const patchScope = operation === 'update' ? mode : 'all'
    current = path.join(
      evidence,
      'real-jobs',
      `${new Date().toISOString().replace(/[:.]/g, '-')}-${name}`
    )
    await fs.mkdir(current, { recursive: true })
    const client = await page.evaluate(
      ({ gameVersion, gameDirectory, language }) =>
        window.desktop.inspectGame(gameVersion, gameDirectory, language),
      { gameVersion, gameDirectory, language }
    )
    await fs.writeFile(path.join(current, 'client.json'), JSON.stringify(client, null, 2))
    let league = {}
    if (operation === 'update' && patchScope !== 'none') {
      const leagues = await page.evaluate(
        ({ gameVersion, china }) => window.desktop.getLeagues(gameVersion, china),
        { gameVersion, china: client.isChina }
      )
      await fs.writeFile(path.join(current, 'leagues.json'), JSON.stringify(leagues, null, 2))
      league =
        leagues.find((item) => item.IsCurrent && !item.DiscoveryFallback) ||
        leagues.find((item) => !item.DiscoveryFallback)
      assert.ok(league, 'Live league discovery must succeed before real updates')
    }
    const request = {
      operation,
      gameVersion,
      gameDirectory,
      patchScope,
      languageMode: language,
      league: (gameVersion === 'poe1' ? league.PoeNinjaLeague : league.ScoutLeague) || '',
      poeNinjaLeague: league.PoeNinjaLeague || '',
      poeCurrencySeason: league.PoeCurrencySeason || '',
      leagueIsCurrent: league.IsCurrent ?? true,
      islandRumourHints: gameVersion === 'poe2' && ['all', 'none'].includes(mode)
    }
    await fs.writeFile(path.join(current, 'request.json'), JSON.stringify(request, null, 2))
    console.log('REAL_OPERATION_START', JSON.stringify(request))
    const result = await page.evaluate((r) => window.desktop.runOperation(r), request)
    await sequence
    await fs.writeFile(path.join(current, 'result.json'), JSON.stringify(result, null, 2))
    const snapshot = await page.evaluate(() => window.desktop.getSnapshot())
    await fs.writeFile(path.join(current, 'snapshot.json'), JSON.stringify(snapshot, null, 2))
    await page.screenshot({ path: path.join(current, 'desktop.png') })
    console.log(
      'REAL_OPERATION_RESULT',
      JSON.stringify({
        name,
        exitCode: result.exitCode,
        durationMs: result.durationMs,
        evidence: current
      })
    )
    assert.equal(result.exitCode, 0, result.stderr || result.stdout.slice(-3000))
    const effectiveLanguage = result.stdout.includes('__POE_LANGUAGE_MODE__localization')
      ? 'localization'
      : language
    if (effectiveLanguage !== language && snapshot.settings.gameVersion === gameVersion)
      assert.equal(snapshot.settings.languageMode, effectiveLanguage)
    const readback = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        path.join(root, 'scripts/real-engine-inspect.ps1'),
        '-GameVersion',
        gameVersion,
        '-GameDirectory',
        gameDirectory,
        '-OutputDirectory',
        path.join(current, 'readback'),
        '-Language',
        effectiveLanguage
      ],
      { encoding: 'utf8', windowsHide: true, timeout: 180000 }
    )
    await fs.writeFile(
      path.join(current, 'readback-command.json'),
      JSON.stringify(
        {
          args: readback.spawnargs,
          status: readback.status,
          stdout: readback.stdout,
          stderr: readback.stderr
        },
        null,
        2
      )
    )
    assert.equal(readback.status, 0, readback.stderr)
    async function capture(dir, destination) {
      for (const entry of await fs.readdir(dir, { withFileTypes: true }).catch(() => [])) {
        const source = path.join(dir, entry.name),
          target = path.join(destination, entry.name)
        if (entry.isDirectory()) await capture(source, target)
        else if (/\.(zip|json)$/.test(entry.name)) {
          await fs.mkdir(destination, { recursive: true })
          await fs.copyFile(source, target)
        }
      }
    }
    if (gameVersion === 'poe1')
      await capture(path.join(profile, 'engine/output/poe1'), path.join(current, 'engine-output'))
    else
      for (const folder of ['poe2_price_patch_latest', 'price_patch_cache', 'restore'])
        await capture(
          path.join(profile, 'engine/output', folder),
          path.join(current, 'engine-output', folder)
        )
    await capture(
      path.join(gameDirectory, `.${gameVersion}-price-patch`),
      path.join(current, 'client-restore')
    )
    console.log('REAL_READBACK_OK', name)
  }
} finally {
  await sequence
  await app.close()
}
