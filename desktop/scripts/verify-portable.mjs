import { chromium } from 'playwright'
import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import net from 'node:net'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-portable-qa-'))
const { version } = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
const executable = path.join(root, `dist/POE-Price-Patch-${version}-x64-Portable.exe`)
const server = net.createServer()
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const port = server.address().port
await new Promise((resolve) => server.close(resolve))
const env = { ...process.env, POE_DESKTOP_DATA: path.join(sandbox, 'profile') }
delete env.ELECTRON_RUN_AS_NODE
const child = spawn(executable, [`--remote-debugging-port=${port}`], {
  env,
  windowsHide: true,
  stdio: 'ignore'
})
let browser
const start = Date.now()
const evidence = { executable, sandbox, port }
try {
  for (let i = 0; i < 60; i++) {
    try {
      browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 1000 })
      break
    } catch {
      if (child.exitCode !== null) throw new Error(`Portable exited ${child.exitCode}`)
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }
  assert.ok(browser, 'Portable did not expose a ready desktop')
  const page = browser.contexts()[0].pages()[0]
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  const snapshot = await page.evaluate(() => window.desktop.getSnapshot())
  assert.equal(snapshot.version, version)
  evidence.startupMs = Date.now() - start
  evidence.result = '免安装 EXE 实际解包启动，preload、Vue 页面、持久化 API 可用'
  await page.screenshot({ path: path.join(root, 'test-results/portable-desktop.png') })
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false }))
  console.log(JSON.stringify(evidence, null, 2))
  await page.evaluate(() => window.close()).catch(() => {})
} finally {
  await browser?.close().catch(() => {})
  if (child.exitCode === null && child.pid) {
    const killer = spawn(
      path.join(process.env.SystemRoot, 'System32/taskkill.exe'),
      ['/PID', String(child.pid), '/T', '/F'],
      { windowsHide: true, stdio: 'ignore' }
    )
    await new Promise((resolve) => {
      killer.once('exit', resolve)
      killer.once('error', resolve)
    })
  }
  await fs.writeFile(
    path.join(root, 'test-results/portable-evidence.json'),
    JSON.stringify(evidence, null, 2)
  )
}
