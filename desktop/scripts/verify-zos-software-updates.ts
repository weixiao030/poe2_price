import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import https from 'node:https'
import path from 'node:path'
import os from 'node:os'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { hashFile, verifyInventory, verifyRelease } from '../src/main/software-update-protocol'

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.dirname(desktop)
const option = (name: string, fallback: string) => {
  const index = process.argv.indexOf(name)
  return index < 0 ? fallback : path.resolve(process.argv[index + 1])
}
const baseline = option('--baseline', path.join(root, 'release-desktop/baselines/0.9.2/win-unpacked'))
const target = option('--target', path.join(root, 'release-desktop/zos-0.9.3-light-test/win-unpacked'))
const reportDir = option('--report-dir', path.join(desktop, 'test-results/zos-093-upgrade'))
await fs.mkdir(reportDir, { recursive: true })
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-zos-092-to-093-'))
const current = path.join(sandbox, 'current')
const userdata = path.join(sandbox, 'userdata')
const exe = path.join(current, '物价补丁.exe')
const releaseIndex = process.argv.indexOf('--release-dir')
const localRelease = releaseIndex >= 0 ? path.resolve(process.argv[releaseIndex + 1]) : undefined
let localServer: https.Server | undefined
let localBase = ''
let localCertificate = ''
const transportRequests: string[] = []
const readJson = async (file: string) => JSON.parse(await fs.readFile(file, 'utf8'))
const evidence: Record<string, any> = { sandbox, from: '0.9.2', to: '0.9.3', checks: [] }
let running: Awaited<ReturnType<typeof electron.launch>> | undefined
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
try {
  const config = await readJson(path.join(baseline, 'resources/update-config.json'))
  assert.equal(config.manifestUrls.length, 1, '测试基线必须配置单个公开更新清单地址')
  const manifestUrl = config.manifestUrls[0]
  assert.equal(new URL(manifestUrl).protocol, 'https:')
  let envelope
  if (localRelease) {
    const certificate = spawnSync('python', ['-X', 'utf8', path.join(desktop, 'scripts/make-update-test-cert.py'), sandbox], { windowsHide: true })
    assert.equal(certificate.status, 0)
    localCertificate = await fs.readFile(path.join(sandbox, 'local-cert.pem'), 'utf8')
    localServer = https.createServer({ key: await fs.readFile(path.join(sandbox, 'local-key.pem')), cert: localCertificate }, async (req, res) => {
      const name = path.basename(new URL(req.url!, 'https://localhost').pathname)
      transportRequests.push(name)
      try {
        const file = path.join(localRelease, name)
        const stat = await fs.stat(file)
        res.writeHead(200, { 'Content-Length': stat.size, 'Cache-Control': 'no-store' })
        createReadStream(file).pipe(res)
      } catch { res.writeHead(404); res.end() }
    })
    await new Promise<void>(resolve => localServer!.listen(0, '127.0.0.1', resolve))
    localBase = `https://127.0.0.1:${(localServer.address() as { port: number }).port}/`
    envelope = await readJson(path.join(localRelease, 'latest.json'))
  } else {
    const response = await fetch(manifestUrl, { headers: { 'Cache-Control': 'no-cache' }, signal: AbortSignal.timeout(30_000) })
    assert.equal(response.status, 200)
    envelope = await response.json()
  }
  const release = verifyRelease(envelope, config.publicKey)
  assert.equal(release.version, '0.9.3')
  const asset = release.packages.find((item) => item.kind === 'delta' && item.fromVersion === '0.9.2')
  assert.ok(asset)
  evidence.package = asset
  evidence.manifestUrl = manifestUrl
  await fs.cp(baseline, current, { recursive: true })
  await fs.writeFile(path.join(current, '玩家自存文件.txt'), 'ZOS 升级测试：保留此文件。')
  const env = { ...process.env, POE_DESKTOP_DATA: userdata }
  delete env.ELECTRON_RUN_AS_NODE
  running = await electron.launch({ executablePath: exe, cwd: current, env, timeout: 30_000 })
  if (localRelease) {
    // Route only these two public URLs to the local HTTPS staging server in this
    // disposable process. Release files, signatures and the baseline stay intact.
    await running.evaluate((_, staging) => {
      const tls = process.getBuiltinModule('node:tls')
      tls.setDefaultCACertificates([...tls.getCACertificates('default'), staging.certificate])
      const original = globalThis.fetch
      globalThis.fetch = (input, options) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        return original(staging.urls.includes(url) ? staging.base + new URL(url).pathname.split('/').pop() : input, options)
      }
    }, { certificate: localCertificate, base: localBase, urls: [manifestUrl, asset.url] })
  }
  const page = await running.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await running.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000))
  assert.equal(await running.evaluate(({ app }) => app.getVersion()), '0.9.2')
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button').nth(3).click()
  let available = await page.evaluate(() => window.desktop.getSoftwareUpdate())
  const checkDeadline = Date.now() + 35_000
  while (!['available', 'error'].includes(available.status) && Date.now() < checkDeadline) {
    await delay(250)
    available = await page.evaluate(() => window.desktop.getSoftwareUpdate())
  }
  assert.equal(available.status, 'available', available.message)
  assert.equal(available.packageKind, 'delta')
  assert.equal(available.totalBytes, asset.size)
  assert.equal(available.release?.version, '0.9.3')
  await page.screenshot({ path: path.join(reportDir, '092-found-093-delta.png'), fullPage: true })
  evidence.available = available
  evidence.checks.push(`原样 0.9.2 基线通过${localRelease ? '本地 HTTPS 暂存' : '生产 HTTPS'}和正式签名验证发现 0.9.3 增量包`)
  console.log(JSON.stringify({ phase: 'available', kind: available.packageKind, bytes: asset.size }))
  const downloaded = await page.evaluate(() => window.desktop.downloadSoftwareUpdate())
  assert.equal(downloaded.status, 'ready', downloaded.message)
  assert.equal(downloaded.downloadedBytes, asset.size)
  const transactionRoot = path.join(userdata, 'software-updates')
  const transactions = (await fs.readdir(transactionRoot, { withFileTypes: true })).filter((item) => item.isDirectory())
  assert.equal(transactions.length, 1)
  const transaction = path.join(transactionRoot, transactions[0].name)
  assert.equal(await hashFile(path.join(transaction, 'update.zip')), asset.sha256)
  await page.screenshot({ path: path.join(reportDir, '092-delta-ready.png'), fullPage: true })
  evidence.downloadedBytes = downloaded.downloadedBytes
  evidence.checks.push('真实下载增量包，大小、SHA-256、所有变化文件和 0.9.2 基线校验通过')
  console.log(JSON.stringify({ phase: 'downloaded', bytes: downloaded.downloadedBytes }))
  const oldProcess = running.process()
  const exited = new Promise<void>((resolve) => oldProcess.once('exit', () => resolve()))
  const installing = await page.evaluate(() => window.desktop.installSoftwareUpdate()).catch(() => undefined)
  if (installing?.status === 'error') throw new Error(installing.message)
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([exited, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('旧版未自动退出')), 60_000) })])
  } finally {
    if (timer) clearTimeout(timer)
  }
  running = undefined
  let result: Record<string, any> = {}
  const deadline = Date.now() + 120_000
  while (Date.now() < deadline) {
    result = await readJson(path.join(transaction, 'result.json')).catch(() => ({}))
    if (result.status) break
    await delay(500)
  }
  assert.equal(result.status, 'completed', JSON.stringify(result))
  const health = await readJson(path.join(transaction, 'health.json'))
  assert.equal(health.version, '0.9.3')
  const plan = await readJson(path.join(transaction, 'plan.json'))
  await verifyInventory(current, plan.targetFiles)
  await verifyInventory(target, plan.targetFiles)
  await verifyInventory(baseline, plan.baseFiles)
  assert.equal(await fs.readFile(path.join(current, '玩家自存文件.txt'), 'utf8'), 'ZOS 升级测试：保留此文件。')
  const asar = createRequire(import.meta.url)('@electron/asar')
  assert.equal(JSON.parse(asar.extractFile(path.join(current, 'resources/app.asar'), 'package.json').toString()).version, '0.9.3')
  evidence.result = result
  evidence.health = health
  evidence.changedFiles = plan.files.map((file: { path: string }) => file.path)
  evidence.targetFilesVerified = plan.targetFiles.length
  evidence.checks.push('旧版自动退出，外部安装器完成替换，新版自动启动并返回 0.9.3 界面健康回执')
  evidence.checks.push('完整目标文件回读一致，0.9.2 保存基线及玩家自存文件保持完整')
  evidence.completed = true
  if (localRelease) {
    assert.ok(transportRequests.includes('latest.json'))
    assert.ok(transportRequests.includes(new URL(asset.url).pathname.split('/').pop()!))
    evidence.transportRequests = transportRequests
    evidence.transport = 'local HTTPS staging of the exact signed release bytes'
  }
} catch (error) {
  evidence.completed = false
  evidence.failure = String(error)
  if (running) {
    const page = await running.firstWindow().catch(() => undefined)
    evidence.failureState = await page?.evaluate(() => window.desktop.getSoftwareUpdate()).catch(() => undefined)
    await page?.screenshot({ path: path.join(reportDir, 'failure.png'), fullPage: true }).catch(() => {})
  }
  throw error
} finally {
  if (running) await running.close().catch(() => {})
  localServer?.closeAllConnections()
  localServer?.close()
  const cleanup = path.join(sandbox, 'close-isolated-app.ps1')
  await fs.writeFile(cleanup, '\ufeffparam([string]$TestExe)\n$ErrorActionPreference="Stop"\nGet-Process | Where-Object { $_.Path -eq $TestExe } | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue; $_.WaitForExit(10000) | Out-Null }\nif (Get-Process | Where-Object { $_.Path -eq $TestExe }) { throw "Test application still running" }\n')
  const cleaned = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', cleanup, '-TestExe', await fs.realpath(exe)], { windowsHide: true })
  assert.equal(cleaned.status, 0, cleaned.stderr?.toString())
  evidence.testProcessesCleaned = true
  await fs.writeFile(path.join(reportDir, 'evidence.json'), JSON.stringify(evidence, null, 2) + '\n')
}
console.log(JSON.stringify(evidence, null, 2))
