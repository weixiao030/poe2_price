import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { spawnSync } from 'node:child_process'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
const appDirectory = process.argv.includes('--app-dir')
  ? path.resolve(process.argv[process.argv.indexOf('--app-dir') + 1])
  : path.join(root, 'dist/win-unpacked')
const executablePath = path.join(appDirectory, '物价补丁.exe')
const resource = path.join(appDirectory, 'resources/engine')
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-packaged-qa-'))
const env = { ...process.env, POE_DESKTOP_DATA: path.join(sandbox, 'profile') }
delete env.ELECTRON_RUN_AS_NODE
const manifest = JSON.parse(await fs.readFile(path.join(resource, 'manifest.json'), 'utf8'))
for (const [relative, hash] of Object.entries(manifest.files))
  assert.equal(
    crypto
      .createHash('sha256')
      .update(await fs.readFile(path.join(resource, relative)))
      .digest('hex'),
    hash
  )
const start = performance.now()
const app = await electron.launch({ executablePath, args: [], cwd: sandbox, env, timeout: 30_000 })
const evidence = {
  executablePath,
  sandbox,
  verifiedResourceFiles: Object.keys(manifest.files).length,
  checks: []
}
try {
  const page = await app.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  evidence.startupMs = Math.round(performance.now() - start)
  assert.equal(await app.evaluate(({ app }) => app.isPackaged), true)
  assert.equal(await app.evaluate(({ app }) => app.getPath('userData')), env.POE_DESKTOP_DATA)
  evidence.checks.push('打包 EXE 启动成功，app.isPackaged=true，隔离配置目录')
  await page.screenshot({ path: path.join(root, 'test-results/packaged-desktop.png') })
  evidence.clients = []
  if (process.argv.includes('--ci')) await page.evaluate(() => window.desktop.discoverGames('poe2'))
  for (const version of process.argv.includes('--ci') ? [] : ['poe1', 'poe2']) {
    const game = `D:\\${version}`
    const client = await page.evaluate(
      ({ version, game }) => window.desktop.inspectGame(version, game, 'auto'),
      { version, game }
    )
    assert.equal(client.path, game)
    assert.equal(client.gameVersion, version)
    evidence.clients.push(client)
    const wrongVersion = await page.evaluate(
      async ({ version, game }) => {
        try {
          await window.desktop.inspectGame(version === 'poe1' ? 'poe2' : 'poe1', game, 'auto')
          return ''
        } catch (e) {
          return String(e)
        }
      },
      { version, game }
    )
    assert.ok(wrongVersion)
  }
  evidence.checks.push(
    process.argv.includes('--ci')
      ? '打包资源首次释放、实际 PowerShell 目录发现调用通过（CI 无游戏安装）'
      : '打包资源首次释放；实际 D:\\poe1、D:\\poe2 识别与版本错配拒绝通过'
  )
  const initialLogin = await app.evaluate(
    ({ app }) =>
      app.getLoginItemSettings({ path: app.getPath('exe'), args: ['--hidden'] }).openAtLogin
  )
  try {
    await page.evaluate(() => window.desktop.saveSettings({ autoStart: true }))
    const enabled = await app.evaluate(({ app }) =>
      app.getLoginItemSettings({ path: app.getPath('exe'), args: ['--hidden'] })
    )
    assert.equal(enabled.openAtLogin, true)
    await app.evaluate(({ app }) =>
      app.setLoginItemSettings({
        openAtLogin: true,
        enabled: false,
        path: app.getPath('exe'),
        args: ['--hidden']
      })
    )
    await page.evaluate(() => window.desktop.saveSettings({ autoStart: true }))
    assert.match(
      (await page.evaluate(() => window.desktop.getSnapshot())).autoStartStatus,
      /Windows 禁用/
    )
    assert.equal(
      await app.evaluate(
        ({ app }) =>
          app.getLoginItemSettings({
            path: app.getPath('exe'),
            args: ['--hidden']
          }).executableWillLaunchAtLogin
      ),
      false
    )
    evidence.checks.push('真实 Windows StartupApproved 禁用可见，普通核对不会擅自重新启用')
    await page.evaluate(() => window.desktop.saveSettings({ autoStart: false }))
    assert.equal(
      await app.evaluate(
        ({ app }) =>
          app.getLoginItemSettings({ path: app.getPath('exe'), args: ['--hidden'] }).openAtLogin
      ),
      false
    )
    const oldExecutable = path.join(sandbox, 'previous-location', '物价补丁.exe')
    await app.evaluate(
      ({ app }, oldPath) =>
        app.setLoginItemSettings({
          openAtLogin: true,
          path: oldPath,
          args: ['--hidden']
        }),
      oldExecutable
    )
    await page.evaluate(() => window.desktop.saveSettings({ autoStart: false }))
    assert.equal(
      await app.evaluate(
        ({ app }, oldPath) =>
          app.getLoginItemSettings({
            path: oldPath,
            args: ['--hidden']
          }).openAtLogin,
        oldExecutable
      ),
      false
    )
    evidence.checks.push('关闭自启会删除同一启动项的历史路径，移动免安装目录后无残留')
    await app.evaluate(
      ({ app }, oldPath) =>
        app.setLoginItemSettings({
          openAtLogin: true,
          path: oldPath,
          args: ['--hidden']
        }),
      oldExecutable
    )
    await page.evaluate(() => window.desktop.saveSettings({ autoStart: true }))
    assert.equal(
      await app.evaluate(
        ({ app }) =>
          app.getLoginItemSettings({
            path: app.getPath('exe'),
            args: ['--hidden']
          }).openAtLogin
      ),
      true
    )
    assert.equal(
      await app.evaluate(
        ({ app }, oldPath) =>
          app.getLoginItemSettings({
            path: oldPath,
            args: ['--hidden']
          }).openAtLogin,
        oldExecutable
      ),
      false
    )
    await page.evaluate(() => window.desktop.saveSettings({ autoStart: false }))
    evidence.checks.push('开启自启自动迁移同一启动项到当前 EXE 和 --hidden 参数')
    evidence.checks.push('发布 EXE 开机启动设置真实写入、读回、关闭通过；未重启 Windows')
  } finally {
    await page.evaluate((autoStart) => window.desktop.saveSettings({ autoStart }), initialLogin)
  }
  const runtimePython = path.join(env.POE_DESKTOP_DATA, 'engine/tools/python/poe_python.exe')
  const check = spawnSync(
    runtimePython,
    ['-c', 'import sys,ssl,urllib.request; print(sys.version.split()[0])'],
    { windowsHide: true, encoding: 'utf8' }
  )
  assert.equal(check.status, 0)
  evidence.python = check.stdout.trim()
  evidence.checks.push('发布目录内置 Python 独立运行成功')
  evidence.sizeBytes = (await fs.stat(executablePath)).size
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await fs.writeFile(
    path.join(root, 'test-results/package-evidence.json'),
    JSON.stringify(evidence, null, 2)
  )
  await app.close()
}
