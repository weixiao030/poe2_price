import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const appDirectory = path.resolve(process.argv[2])
const settingsSource = process.argv[3] && path.resolve(process.argv[3])
const sourceBytes = settingsSource && (await fs.readFile(settingsSource))
const stored = sourceBytes && JSON.parse(sourceBytes.toString('utf8'))
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-installed-startup-'))
const evidence = { executable: path.join(appDirectory, '物价补丁.exe'), checks: [] }
const expectedVersion = JSON.parse(
  await fs.readFile(path.join(root, 'package.json'), 'utf8')
).version

for (const mode of stored ? ['fresh', 'existing-settings-copy'] : ['fresh']) {
  const userData = path.join(sandbox, mode)
  await fs.mkdir(userData)
  if (mode !== 'fresh') {
    const copy = structuredClone(stored)
    // Keep the user's real files untouched. A diagnostic startup must not run a game patch.
    copy.settings.autoUpdate = false
    await fs.writeFile(path.join(userData, 'desktop-settings.json'), JSON.stringify(copy))
  }
  const env = { ...process.env, POE_DESKTOP_DATA: userData }
  delete env.ELECTRON_RUN_AS_NODE
  const errors = []
  const app = await electron.launch({ executablePath: evidence.executable, env, timeout: 30000 })
  try {
    const page = await app.firstWindow()
    page.on('pageerror', (error) => errors.push(error.message))
    await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
    const snapshot = await page.evaluate(() => window.desktop.getSnapshot())
    assert.equal(snapshot.version, expectedVersion)
    assert.equal(snapshot.active, null)
    if (mode !== 'fresh') {
      assert.deepEqual(snapshot.settings.directories, stored.settings.directories)
      assert.deepEqual(snapshot.history, stored.history)
      assert.equal(snapshot.settings.gameVersion, stored.settings.gameVersion)
    }
    for (const label of ['运行记录', '引用设置', '检查更新', '物价补丁']) {
      await page
        .getByRole('navigation', { name: '主导航' })
        .getByRole('button', { name: new RegExp('^' + label) })
        .click()
      await page.getByRole('heading', { name: label, exact: true }).waitFor()
    }
    await page.screenshot({ path: path.join(root, `test-results/installed-${mode}.png`) })
    assert.deepEqual(errors, [])
    evidence.checks.push({
      mode,
      version: snapshot.version,
      historyCount: snapshot.history.length,
      pages: 4,
      uncaughtErrors: errors.length
    })
  } finally {
    await app.close()
  }
}
if (sourceBytes) assert.deepEqual(await fs.readFile(settingsSource), sourceBytes)
await fs.writeFile(
  path.join(root, 'test-results/installed-startup.json'),
  JSON.stringify(evidence, null, 2)
)
console.log(JSON.stringify(evidence, null, 2))
