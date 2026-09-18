import { _electron as electron } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const appDirectory = process.argv.includes('--app-dir')
  ? path.resolve(process.argv[process.argv.indexOf('--app-dir') + 1])
  : path.join(root, 'dist/win-unpacked')
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-compatibility-'))
const env = { ...process.env, POE_DESKTOP_DATA: path.join(sandbox, 'profile') }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({
  executablePath: path.join(appDirectory, '物价补丁.exe'),
  args: [],
  env,
  timeout: 30000
})
const evidence = { appDirectory, sandbox, clients: [], leagues: [], checks: [] }
try {
  const page = await app.firstWindow()
  page.setDefaultTimeout(120000)
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  for (const gameVersion of ['poe1', 'poe2']) {
    for (const platform of ['official', 'steam', 'wegame']) {
      const china = platform === 'wegame'
      const game = path.join(
        sandbox,
        platform,
        gameVersion === 'poe1' ? 'Path of Exile' : 'Path of Exile 2'
      )
      await fs.mkdir(game, { recursive: true })
      if (platform === 'official')
        await fs.writeFile(path.join(game, 'Content.ggpk'), 'fixture, never patched')
      else {
        await fs.mkdir(path.join(game, 'Bundles2'))
        await fs.writeFile(path.join(game, 'Bundles2/_.index.bin'), 'fixture, never patched')
      }
      if (china) {
        await fs.writeFile(path.join(game, 'wegame.ini'), 'fixture')
        await fs.writeFile(path.join(game, 'rail_api64.dll'), 'fixture')
      } else if (platform === 'steam')
        await fs.writeFile(path.join(game, 'steam_api64.dll'), 'fixture')
      const suffix =
        platform === 'official'
          ? 'Intl-Standalone-GGPK'
          : china
            ? 'CN-WeGame-Bundles2'
            : 'Intl-Bundles2'
      const expectedKind = `${gameVersion === 'poe1' ? 'POE1-' : ''}${suffix}`
      for (const language of ['auto', 'localization', 'zh-CN', 'zh-TW', 'config']) {
        const client = await page.evaluate(
          ({ gameVersion, game, language }) =>
            window.desktop.inspectGame(gameVersion, game, language),
          { gameVersion, game, language }
        )
        assert.equal(client.gameVersion, gameVersion)
        assert.equal(client.path, game)
        assert.equal(client.installKind, expectedKind)
        assert.equal(client.isChina, china)
        if (china) assert.equal(client.language, 'Simplified Chinese')
        evidence.clients.push({
          gameVersion,
          platform,
          requestedLanguage: language,
          ...client,
          coverage: 'fixture-inspection'
        })
      }
      if (platform !== 'official') {
        const child = await page.evaluate(
          ({ gameVersion, game }) => window.desktop.inspectGame(gameVersion, game, 'auto'),
          { gameVersion, game: path.join(game, 'Bundles2') }
        )
        assert.equal(child.path, game)
      }
      const wrongVersion = gameVersion === 'poe1' ? 'poe2' : 'poe1'
      const error = await page.evaluate(
        async ({ gameVersion, game }) => {
          try {
            await window.desktop.inspectGame(gameVersion, game, 'auto')
            return ''
          } catch (error) {
            return String(error)
          }
        },
        { gameVersion: wrongVersion, game }
      )
      assert.ok(error, `${gameVersion}/${platform}: cross-version directory accepted`)
    }
  }
  evidence.checks.push(
    'POE1/POE2 各官方 GGPK、国际服 Steam Bundles2、国服 WeGame Bundles2；5 种语言请求、子目录规范化与跨游戏拒绝通过'
  )
  if (process.argv.includes('--live')) {
    for (const gameVersion of ['poe1', 'poe2']) {
      for (const china of [false, true]) {
        const leagues = await page.evaluate(
          ({ gameVersion, china }) => window.desktop.getLeagues(gameVersion, china),
          { gameVersion, china }
        )
        assert.ok(leagues.length > 0)
        const live = leagues.filter((league) => !league.DiscoveryFallback)
        assert.ok(
          live.length > 0,
          `${gameVersion}/${china ? 'CN' : 'Intl'}: live league discovery failed`
        )
        assert.ok(live.some((league) => league.IsCurrent))
        for (const league of live)
          assert.ok(
            china
              ? league.PoeCurrencySeason
              : gameVersion === 'poe1'
                ? league.PoeNinjaLeague
                : league.ScoutLeague || league.PoeNinjaLeague
          )
        evidence.leagues.push({ gameVersion, china, leagues, coverage: 'live-read-only' })
      }
    }
    evidence.checks.push('POE1/POE2 国际服和国服的实际赛季请求均返回非回退数据，赛季标识不混用')
  }
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await app.close()
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, 'test-results/compatibility-evidence.json'),
    JSON.stringify(evidence, null, 2)
  )
}
