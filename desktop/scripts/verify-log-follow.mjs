import { _electron as electron } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const appIndex = process.argv.indexOf('--app-dir')
const executablePath = appIndex < 0 ? undefined : path.resolve(process.argv[appIndex + 1], '物价补丁.exe')
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-log-follow-'))
const reportDir = path.join(root, 'test-results/log-follow-093')
await fs.mkdir(reportDir, { recursive: true })
const env = { ...process.env, POE_DESKTOP_DATA: sandbox }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ executablePath, args: executablePath ? [] : [root], env })
const evidence = { executablePath: executablePath || root, checks: [], errors: [] }
try {
  const page = await app.firstWindow()
  page.on('pageerror', (error) => evidence.errors.push(error.message))
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000))
  const log = page.getByRole('log', { name: '运行日志' })
  const follow = page.getByRole('checkbox', { name: '跟随输出' })
  const emit = (message) => app.evaluate(({ BrowserWindow }, text) => {
    BrowserWindow.getAllWindows()[0].webContents.send('patch:progress', {
      runId: 'log-layout-verification', stream: 'stdout', message: text, at: new Date().toISOString()
    })
  }, message)
  async function atBottom(check) {
    await page.waitForFunction(() => {
      const el = document.querySelector('[role="log"]')
      return el && el.scrollHeight > el.clientHeight && Math.abs(el.scrollHeight - el.clientHeight - el.scrollTop) <= 2
    })
    evidence.checks.push(check)
  }
  assert.equal(await follow.isChecked(), true)
  await emit(Array.from({ length: 180 }, (_, i) => `日志 ${i}：写入及回读校验，中文路径和较长输出。${'校验通过 '.repeat(15)}\n`).join(''))
  await atBottom('默认跟随首批长日志到底部')
  await emit('最新输出 A\n')
  await log.getByText('最新输出 A', { exact: false }).waitFor()
  await atBottom('新增日志后保持底部')
  await follow.uncheck()
  await log.evaluate((el) => { el.scrollTop = 0 })
  await emit('暂停跟随时的输出 B\n')
  await log.getByText('暂停跟随时的输出 B', { exact: false }).waitFor()
  assert.equal(await log.evaluate((el) => el.scrollTop), 0)
  evidence.checks.push('取消跟随后新增输出不抢滚动位置')
  await follow.check()
  await atBottom('重新勾选立即跳到最新日志')
  await page.getByRole('button', { name: '运行记录', exact: true }).click()
  await page.getByRole('button', { name: '物价补丁', exact: true }).click()
  await atBottom('切换页面返回后自动显示最新日志')
  await page.getByRole('button', { name: '运行记录', exact: true }).click()
  await emit('离开工作页面期间的输出 C\n')
  await page.getByRole('button', { name: '物价补丁', exact: true }).click()
  await log.getByText('离开工作页面期间的输出 C', { exact: false }).waitFor()
  await atBottom('后台新增日志后返回定位底部')
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(860, 680))
  await page.waitForFunction(() => window.innerWidth === 860)
  await atBottom('缩小窗口及文本重排后保持底部')
  await page.screenshot({ path: path.join(reportDir, 'latest-output.png') })
  assert.deepEqual(evidence.errors, [])
} finally {
  await fs.writeFile(path.join(reportDir, 'evidence.json'), JSON.stringify(evidence, null, 2))
  await app.close()
}
console.log(JSON.stringify(evidence, null, 2))
