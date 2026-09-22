import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import https from 'node:https'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { buildPackage, signRelease } from './build-software-update'
import { APP_ID, hashFile, verifyInventory } from '../src/main/software-update-protocol'
import type { SoftwareRelease } from '../src/shared/software-update'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const appArgument = process.argv.indexOf('--app-dir')
const sourceApp = appArgument >= 0 ? path.resolve(process.argv[appArgument + 1]) : path.join(root, 'dist/win-unpacked')
const reportDir = path.join(root, 'test-results/software-updates')
await fs.mkdir(reportDir, { recursive: true })
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-software-真实更新-'))
const before = path.join(sandbox, 'current'),
  after = path.join(sandbox, 'target')
const userdata = path.join(sandbox, 'userdata'),
  published = path.join(sandbox, 'published')
const certificate = spawnSync(
  'python',
  ['-X', 'utf8', path.join(root, 'scripts/make-update-test-cert.py'), sandbox],
  { windowsHide: true, encoding: 'utf8' }
)
if (certificate.status !== 0) throw new Error(certificate.stderr)
const transportRequests: string[] = []
const server = https.createServer(
  {
    key: await fs.readFile(path.join(sandbox, 'local-key.pem')),
    cert: await fs.readFile(path.join(sandbox, 'local-cert.pem'))
  },
  async (req, res) => {
    try {
      transportRequests.push(req.url!)
      if (req.url!.startsWith('/primary/')) {
        res.writeHead(503); res.end(); return
      }
      const name = path.basename(new URL(req.url!, 'https://localhost').pathname)
      const bytes = await fs.readFile(path.join(published, name))
      res.writeHead(200, { 'Content-Length': bytes.length, 'Cache-Control': 'no-store' })
      res.end(bytes)
    } catch {
      res.writeHead(404)
      res.end()
    }
  }
)
await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
const baseUrl = `https://127.0.0.1:${(server.address() as { port: number }).port}/`
const keypair = crypto.generateKeyPairSync('ed25519')
const privateKey = keypair.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
const publicKey = keypair.publicKey.export({ type: 'spki', format: 'pem' }).toString()
const evidence: Record<string, unknown> = { sandbox, checks: [], screenshots: [], errors: [] }
const checks = evidence.checks as string[],
  errors = evidence.errors as string[]
let running: Awaited<ReturnType<typeof electron.launch>> | undefined
try {
  await fs.cp(sourceApp, before, { recursive: true })
  await fs.writeFile(
    path.join(before, 'resources/update-config.json'),
    JSON.stringify({ manifestUrls: [baseUrl + 'latest.json'], publicKey,
      github: { repository: 'owner/update-test', mirrorPrefixes: [baseUrl + 'primary/', baseUrl + 'backup/'] } })
  )
  await fs.cp(before, after, { recursive: true })
  const asar = createRequire(import.meta.url)('@electron/asar')
  const extracted = path.join(sandbox, 'asar-source')
  asar.extractAll(path.join(after, 'resources/app.asar'), extracted)
  const packageFile = path.join(extracted, 'package.json')
  const pkg = JSON.parse(await fs.readFile(packageFile, 'utf8'))
  const originalVersion = pkg.version
  const [major, minor, patch] = originalVersion.split('.').map(Number)
  pkg.version = `${major}.${minor}.${patch + 1}`
  await fs.writeFile(packageFile, JSON.stringify(pkg))
  await asar.createPackage(extracted, path.join(after, 'resources/app.asar'))
  await fs.writeFile(
    path.join(after, 'resources/current-release.json'),
    JSON.stringify({ version: pkg.version, notes: ['隔离验证：软件增量更新与自动重启。'] })
  )
  const asset = await buildPackage({
    to: after,
    from: before,
    version: pkg.version,
    fromVersion: originalVersion,
    output: published,
    baseUrl
  })
  const release: SoftwareRelease = {
    appId: APP_ID,
    version: pkg.version,
    publishedAt: new Date().toISOString(),
    notes: ['隔离验证：下载签名增量包，并在更新后自动重启。'],
    packages: [asset]
  }
  await fs.writeFile(
    path.join(published, 'latest.json'),
    JSON.stringify(signRelease(release, privateKey))
  )
  await fs.writeFile(path.join(before, '玩家自存文件.txt'), '不得修改')
  evidence.package = asset
  const executableHash = await hashFile(path.join(before, '物价补丁.exe'))
  const env = {
    ...process.env,
    POE_DESKTOP_DATA: userdata,
    NODE_EXTRA_CA_CERTS: path.join(sandbox, 'local-cert.pem')
  }
  delete env.ELECTRON_RUN_AS_NODE
  running = await electron.launch({
    executablePath: path.join(before, '物价补丁.exe'),
    env,
    timeout: 30_000
  })
  // Packaged Electron may ignore NODE_EXTRA_CA_CERTS. Trust only this test CA,
  // inside this disposable process; production TLS verification stays enabled.
  await running.evaluate(
    (_, pem) => {
      const tls = process.getBuiltinModule('node:tls')
      tls.setDefaultCACertificates([...tls.getCACertificates('default'), pem])
    },
    await fs.readFile(path.join(sandbox, 'local-cert.pem'), 'utf8')
  )
  let page = await running.firstWindow()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await running.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000)
  )
  page.on('pageerror', (error) => errors.push(error.message))
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  const navigation = page.getByRole('navigation', { name: '主导航' }).getByRole('button')
  assert.equal(await navigation.count(), 4)
  assert.equal(await navigation.nth(3).innerText(), '检查更新')
  await navigation.nth(3).click()
  let available = await page.evaluate(() => window.desktop.getSoftwareUpdate())
  const checkDeadline = Date.now() + 30_000
  while (!['available', 'error'].includes(available.status) && Date.now() < checkDeadline) {
    await new Promise((resolve) => setTimeout(resolve, 250))
    available = await page.evaluate(() => window.desktop.getSoftwareUpdate())
  }
  assert.equal(available.status, 'available', available.message)
  assert.equal(available.packageKind, 'delta')
  await page.locator('.appreciation-image img').evaluate(async (image: HTMLImageElement) => {
    await image.decode()
  })
  const imageBox = await page.locator('.appreciation-image').boundingBox()
  const button = page.getByRole('button', { name: '立即更新', exact: true })
  const buttonBox = await button.boundingBox()
  evidence.initialLayout = {
    imageBox,
    buttonBox,
    viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight }))
  }
  assert.ok(
    imageBox && buttonBox && imageBox.y + imageBox.height < buttonBox.y,
    '扫码与更新按钮不能重叠'
  )
  assert.ok(
    buttonBox.y + buttonBox.height <= (await page.evaluate(() => innerHeight)),
    '更新按钮须在首屏内'
  )
  assert.ok(await button.isEnabled())
  await page.screenshot({
    path: path.join(reportDir, 'updates-available-light.png'),
    fullPage: true
  })
  await page.getByRole('button', { name: '查看完整赞赏码' }).click()
  await page
    .locator('.appreciation-modal img')
    .evaluate(async (image: HTMLImageElement) => image.decode())
  await page.keyboard.press('Escape')
  await page.locator('.feedback-link').click()
  assert.equal(await running.evaluate(({ clipboard }) => clipboard.readText()), '168887742')
  await page.locator('.n-message').waitFor({ state: 'hidden' })
  checks.push('真实发行版第四导航、更新说明、原图赞赏码和反馈群复制可用')
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'dark' }))
  await page.locator('.theme-root.dark').waitFor()
  await page.screenshot({
    path: path.join(reportDir, 'updates-available-dark.png'),
    fullPage: true
  })
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'light' }))
  await running.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(820, 620))
  await page.waitForFunction(() => innerWidth < 900)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  for (const selector of ['.appreciation-image', '.software-update-buttons']) {
    const box = await page.locator(selector).boundingBox()
    assert.ok(
      box && box.y >= 0 && box.y + box.height <= (await page.evaluate(() => innerHeight)),
      `${selector} 须完整出现在紧凑窗口首屏`
    )
  }
  await page.screenshot({ path: path.join(reportDir, 'updates-compact.png'), fullPage: true })
  checks.push('浅色、深色、820×620紧凑布局，无横向溢出')
  evidence.screenshots = [
    'updates-available-light.png',
    'updates-available-dark.png',
    'updates-compact.png'
  ]
  await running.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1200, 860))
  const oldProcess = running.process()
  const closed = new Promise<void>((resolve) => oldProcess.once('exit', () => resolve()))
  await button.click()
  const installDeadline = Date.now() + 30_000
  while (Date.now() < installDeadline && oldProcess.exitCode === null) {
    const installing = await page
      .evaluate(() => window.desktop.getSoftwareUpdate())
      .catch(() => undefined)
    if (installing?.status === 'error') throw new Error(installing.message)
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  let exitTimer: ReturnType<typeof setTimeout>
  try {
    await Promise.race([
      closed,
      new Promise((_, reject) => {
        exitTimer = setTimeout(() => reject(new Error('旧版本未自动退出')), 60_000)
      })
    ])
  } finally {
    clearTimeout(exitTimer!)
  }
  running = undefined
  const transactionRoot = path.join(userdata, 'software-updates')
  const { token } = JSON.parse(
    await fs.readFile(path.join(transactionRoot, 'last-update.json'), 'utf8')
  )
  const transaction = path.join(transactionRoot, token)
  let result
  const deadline = Date.now() + 90_000
  while (Date.now() < deadline) {
    result = JSON.parse(
      await fs.readFile(path.join(transaction, 'result.json'), 'utf8').catch(() => '{}')
    )
    if (result.status) break
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  assert.equal(result?.status, 'completed', JSON.stringify(result))
  const health = JSON.parse(await fs.readFile(path.join(transaction, 'health.json'), 'utf8'))
  assert.equal(health.version, pkg.version)
  const plan = JSON.parse(await fs.readFile(path.join(transaction, 'plan.json'), 'utf8'))
  await verifyInventory(before, plan.targetFiles)
  assert.equal(await hashFile(path.join(before, '物价补丁.exe')), executableHash)
  assert.equal(await fs.readFile(path.join(before, '玩家自存文件.txt'), 'utf8'), '不得修改')
  evidence.health = health
  evidence.result = result
  checks.push(
    `真实HTTPS读取签名说明、只下载变化文件、旧进程退出、外部安装、新版本${pkg.version}界面启动回执成功`
  )
  for (const resource of ['latest.json', new URL(asset.url).pathname.split('/').pop()!]) {
    const primary = transportRequests.findIndex(url => url.startsWith('/primary/') && url.endsWith('/' + resource))
    const backup = transportRequests.findIndex(url => url.startsWith('/backup/') && url.endsWith('/' + resource))
    assert.ok(primary >= 0 && backup > primary, `${resource} 应先主源失败再从备用源成功`)
  }
  evidence.transportRequests = transportRequests
  checks.push('实际 Electron 更新中，主源返回 503，备用源提供同一签名清单和更新包，安装与重启完成')
  checks.push('完整目标发行文件逐一哈希回读通过，Electron可执行文件未改动，玩家自存文件保留')
  assert.deepEqual(errors, [])
} catch (error) {
  evidence.failure = String(error)
  if (running) {
    const page = await running.firstWindow().catch(() => undefined)
    evidence.failureState = await page
      ?.evaluate(() => window.desktop.getSoftwareUpdate())
      .catch(() => undefined)
  }
  throw error
} finally {
  if (running) await running.close().catch(() => {})
  server.closeAllConnections()
  server.close()
  // Only terminate processes whose executable is inside this disposable test application.
  const cleanupScript = path.join(sandbox, 'close-test-app.ps1')
  await fs.writeFile(
    cleanupScript,
    '\ufeffparam([string]$TestExe)\nGet-Process | Where-Object { $_.Path -eq $TestExe } | Stop-Process -Force -ErrorAction SilentlyContinue\n'
  )
  spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      cleanupScript,
      '-TestExe',
      path.join(before, '物价补丁.exe')
    ],
    { windowsHide: true }
  )
  await fs.writeFile(path.join(reportDir, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
console.log(JSON.stringify(evidence, null, 2))
