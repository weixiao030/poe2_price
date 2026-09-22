import { _electron as electron } from 'playwright'
import { spawn } from 'node:child_process'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const index = process.argv.indexOf('--app-dir')
assert.ok(index >= 0, '需要 --app-dir 发行目录')
const source = path.resolve(process.argv[index + 1])
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-single-instance-'))
const second = path.join(sandbox, '另一份免安装目录')
await fs.cp(source, second, { recursive: true })
const env = { ...process.env, POE_DESKTOP_DATA: path.join(sandbox, 'userdata') }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ executablePath: path.join(source, '物价补丁.exe'), env })
const evidence = { checks: [] }
try {
  const page = await app.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await app.evaluate(({ app, BrowserWindow }) => {
    globalThis.__secondLaunches = 0
    app.on('second-instance', () => { globalThis.__secondLaunches++ })
    BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000)
  })
  async function duplicate(directory, args) {
    const child = spawn(path.join(directory, '物价补丁.exe'), args, { env, windowsHide: true, stdio: 'ignore' })
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { child.kill(); reject(new Error('重复实例未退出')) }, 15000)
      child.once('error', (error) => { clearTimeout(timeout); reject(error) })
      child.once('exit', (code) => { clearTimeout(timeout); code === 0 ? resolve() : reject(new Error(`重复实例退出码 ${code}`)) })
    })
  }
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].hide())
  await duplicate(source, ['--hidden'])
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), false)
  evidence.checks.push('重复后台启动退出，并保持原窗口隐藏')
  await duplicate(source, [])
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), true)
  evidence.checks.push('重复手动启动退出，并唤醒原窗口')
  await duplicate(second, [])
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 1)
  assert.equal(await app.evaluate(() => globalThis.__secondLaunches), 3)
  evidence.checks.push('不同安装目录共用同一用户配置时只保留一个主实例')
} finally {
  await app.close()
  const report = path.join(desktop, 'test-results/single-instance-093')
  await fs.mkdir(report, { recursive: true })
  await fs.writeFile(path.join(report, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
console.log(JSON.stringify(evidence, null, 2))
