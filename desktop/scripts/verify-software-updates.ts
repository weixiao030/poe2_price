import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import { createReadStream } from 'node:fs'
import fs from 'node:fs/promises'
import https from 'node:https'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { _electron as electron } from 'playwright'
import { buildRelease } from './build-software-update'
import { installerName, hashFile } from '../src/main/software-update-protocol'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)
const { build: bundle } = require('esbuild')
const { build: pack, Platform, Arch } = require('electron-builder')
const asar = require('@electron/asar')
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-nsis-qa-'))
const runId = crypto.randomUUID().slice(0, 8)
const name = 'poe-price-patch-update-qa-' + runId
// NSIS also detects running apps by executable name, so isolate that identity too.
const executableName = name + '-验证'
const appId = 'com.poepricepatch.updaterqa.' + runId
const installed = path.join(sandbox, '已安装的验证程序')
const oldVersion = '1.0.0',
  newVersion = '2.4.0'
const oldOutput = path.join(sandbox, 'old'),
  newOutput = path.join(sandbox, 'new'),
  published = path.join(sandbox, 'published')
const entry = path.join(sandbox, 'fixture.cjs')
const project = path.join(sandbox, 'project')
const configPath = path.join(sandbox, 'qa-config.json')
const cache = path.join(process.env.LOCALAPPDATA!, name + '-updater')
const requests: { source: string; file: string; range?: string }[] = []
const modes: Record<string, string> = {}
const checks: string[] = []
let application: Awaited<ReturnType<typeof electron.launch>> | undefined
let bootPid: number | undefined

async function run(command: string, args: string[], env = process.env) {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    })
    let output = ''
    child.stdout.on('data', (bytes) => {
      output = (output + bytes).slice(-16000)
    })
    child.stderr.on('data', (bytes) => {
      output = (output + bytes).slice(-16000)
    })
    child.once('error', reject)
    child.once('exit', (code) =>
      code === 0
        ? resolve()
        : reject(new Error(`${path.basename(command)} exited ${code}: ${output}`))
    )
  })
}
async function until(check: () => Promise<boolean>, label: string, timeout = 60000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await check().catch(() => false)) return
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error('Timed out: ' + label)
}
const readVersion = () =>
  JSON.parse(
    asar.extractFile(path.join(installed, 'resources/app.asar'), 'package.json').toString()
  ).version
async function close() {
  if (application) {
    await application.close()
    application = undefined
  }
}
async function launch() {
  application = await electron.launch({
    executablePath: path.join(installed, executableName + '.exe'),
    env: {
      ...process.env,
      POE_INSTALLER_QA_CONFIG: configPath,
      NODE_EXTRA_CA_CERTS: path.join(sandbox, 'local-cert.pem')
    }
  })
  await until(() => application!.evaluate(() => !!(globalThis as any).qaReady), 'fixture startup')
}
async function command(method: 'check' | 'download' | 'install') {
  return application!.evaluate(
    async (_electron, action) => (globalThis as any).qaUpdater[action](),
    method
  )
}
async function clearPending() {
  // The cache identity belongs to this run only; never touch production updater caches.
  assert.equal(path.basename(cache), name + '-updater')
  const pending = path.join(cache, 'pending')
  for (const file of [installerName(newVersion), 'update-info.json', 'current.blockmap'])
    await fs.unlink(path.join(pending, file)).catch(() => {})
}

await run('python', ['-X', 'utf8', path.join(root, 'scripts/make-update-test-cert.py'), sandbox])
const cert = await fs.readFile(path.join(sandbox, 'local-cert.pem'))
const server = https.createServer(
  { key: await fs.readFile(path.join(sandbox, 'local-key.pem')), cert },
  async (req, res) => {
    const url = new URL(req.url!, 'https://127.0.0.1')
    const source = url.pathname.split('/')[1],
      file = path.basename(url.pathname)
    requests.push({ source, file, range: req.headers.range })
    const mode = modes[source]
    if (mode === 'offline') {
      res.writeHead(503)
      res.end()
      return
    }
    if (mode === 'bad-signature' && file.endsWith('.sig')) {
      res.end('invalid')
      return
    }
    const oldBlockmap = file === installerName(oldVersion) + '.blockmap'
    if (oldBlockmap && modes.oldBlockmap === 'missing') {
      res.writeHead(404)
      res.end()
      return
    }
    const sourcePath = path.join(oldBlockmap ? oldOutput : published, file)
    try {
      const stat = await fs.stat(sourcePath)
      const match = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/)
      const start = match ? Number(match[1]) : 0,
        end = match && match[2] ? Number(match[2]) : stat.size - 1
      if (start > end || end >= stat.size) {
        res.writeHead(416)
        res.end()
        return
      }
      const headers: Record<string, string | number> = {
        'Content-Length': end - start + 1,
        'Accept-Ranges': 'bytes'
      }
      if (match) headers['Content-Range'] = `bytes ${start}-${end}/${stat.size}`
      res.writeHead(match ? 206 : 200, headers)
      if (req.method === 'HEAD') {
        res.end()
        return
      }
      const stream = createReadStream(sourcePath, { start, end })
      stream.on('error', () => res.destroy())
      res.on('close', () => stream.destroy())
      stream.pipe(res)
    } catch {
      res.writeHead(404)
      res.end()
    }
  }
)
await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
const base = `https://127.0.0.1:${(server.address() as { port: number }).port}`
const keys = crypto.generateKeyPairSync('ed25519')
const privateKey = keys.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
const publicKey = keys.publicKey.export({ type: 'spki', format: 'pem' }).toString()

try {
  await fs.writeFile(
    configPath,
    JSON.stringify({
      root: sandbox,
      fingerprint: new crypto.X509Certificate(cert).fingerprint256,
      update: {
        publicKey,
        github: {
          repository: 'qa/release',
          mirrorPrefixes: [base + '/primary/', base + '/backup/']
        },
        manifestUrls: [base + '/zos/latest.yml']
      }
    })
  )
  // Bundle only test startup plus production updater modules. Native updater stays a real dependency.
  await bundle({
    entryPoints: [path.join(root, 'scripts/installer-fixture-main.ts')],
    outfile: entry,
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'cjs',
    packages: 'external'
  })
  await fs.mkdir(project)
  await fs.copyFile(entry, path.join(project, 'main.cjs'))
  // A separate project prevents production file/extraResources arrays being merged into the fixture.
  const pkg = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
  const copied = new Map<string, string>()
  async function copyDependency(dependency: string, from: string) {
    const manifest = require.resolve(dependency + '/package.json', { paths: [from] })
    const metadata = JSON.parse(await fs.readFile(manifest, 'utf8'))
    if (copied.has(dependency)) {
      assert.equal(copied.get(dependency), metadata.version)
      return
    }
    copied.set(dependency, metadata.version)
    const source = path.dirname(manifest)
    await fs.cp(source, path.join(project, 'node_modules', dependency), {
      recursive: true,
      filter: (file) => path.basename(file) !== 'node_modules'
    })
    for (const child of Object.keys(metadata.dependencies || {}))
      await copyDependency(child, source)
  }
  for (const dependency of ['electron-updater', 'builder-util-runtime', 'js-yaml'])
    await copyDependency(dependency, root)
  for (const [version, output] of [
    [oldVersion, oldOutput],
    [newVersion, newOutput]
  ]) {
    console.log(`Building isolated NSIS fixture ${version}`)
    await fs.writeFile(
      path.join(project, 'package.json'),
      JSON.stringify({
        name,
        version,
        main: 'main.cjs',
        description: 'Isolated updater verification',
        author: 'QA',
        dependencies: Object.fromEntries(
          ['electron-updater', 'builder-util-runtime', 'js-yaml'].map((dep) => [
            dep,
            pkg.dependencies[dep]
          ])
        ),
        build: {
          appId,
          productName: name,
          directories: { output },
          electronVersion: require('electron/package.json').version,
          artifactName: 'POE-Price-Patch-${version}-x64-Setup.${ext}',
          files: ['main.cjs', 'package.json'],
          extraResources: [{ from: configPath, to: 'qa-config.json' }],
          win: { executableName, icon: path.join(root, 'resources/icon.png'), target: ['nsis'] },
          publish: { provider: 'generic', url: base + '/zos/' },
          nsis: {
            oneClick: false,
            perMachine: false,
            allowToChangeInstallationDirectory: true,
            createDesktopShortcut: false,
            createStartMenuShortcut: false,
            runAfterFinish: false,
            deleteAppDataOnUninstall: false
          }
        }
      })
    )
    await pack({
      projectDir: project,
      targets: Platform.WINDOWS.createTarget(['nsis'], Arch.x64),
      publish: 'never'
    })
    const bundled = JSON.parse(
      asar
        .extractFile(path.join(output, 'win-unpacked/resources/app.asar'), 'package.json')
        .toString()
    )
    assert.equal(bundled.name, name)
    assert.equal(bundled.version, version)
    assert.equal(bundled.main, 'main.cjs')
  }
  await buildRelease({
    directory: newOutput,
    output: published,
    privateKey,
    publicKey,
    notes: { version: newVersion, notes: ['隔离验证跨版本安装'] }
  })
  await fs.mkdir(path.join(sandbox, 'userdata'), { recursive: true })
  const settings = path.join(sandbox, 'userdata/desktop-settings.json')
  await fs.writeFile(
    settings,
    JSON.stringify({ theme: 'dark', league: 'fixed', autoUpdate: true, history: ['preserve'] })
  )
  const beforeSettings = await fs.readFile(settings)
  await run(path.join(oldOutput, installerName(oldVersion)), ['/S', '/D=' + installed])
  await until(async () => readVersion() === oldVersion, 'initial NSIS install', 90000)
  checks.push('真实 NSIS 首次安装成功，使用独立应用 ID 和中文安装路径')

  // No old package or blockmap: every mirror fails and ZOS serves one complete target.
  await fs.unlink(path.join(cache, 'installer.exe')).catch(() => {})
  await fs.unlink(path.join(cache, 'current.blockmap')).catch(() => {})
  modes.primary = modes.backup = 'offline'
  modes.oldBlockmap = 'missing'
  await launch()
  assert.equal((await command('check')).status, 'available')
  assert.equal((await command('download')).status, 'ready')
  assert.ok(
    requests.some((r) => r.source === 'zos' && r.file === installerName(newVersion) && !r.range)
  )
  checks.push('1.0.0 无基线直接下载 2.4.0；国内源失败后使用 ZOS，旧 blockmap 缺失回退全量')
  await close()
  assert.equal(readVersion(), oldVersion)
  checks.push('下载后普通退出不触发自动安装')

  // With a matching cached installer, native blockmap/range download is exercised.
  await clearPending()
  await fs.mkdir(cache, { recursive: true })
  await fs.copyFile(
    path.join(oldOutput, installerName(oldVersion)),
    path.join(cache, 'installer.exe')
  )
  await fs.unlink(path.join(cache, 'current.blockmap')).catch(() => {})
  delete modes.backup
  delete modes.oldBlockmap
  modes.primary = 'bad-signature'
  const beforeRequests = requests.length
  await launch()
  assert.equal((await command('check')).status, 'available')
  assert.equal((await command('download')).status, 'ready')
  assert.ok(
    requests.slice(beforeRequests).some((r) => r.range),
    'Native differential download must issue Range requests'
  )
  assert.ok(
    !requests.slice(beforeRequests).some((r) => r.file === installerName(newVersion) && !r.range),
    'Native differential download must finish without a full-file fallback'
  )
  const downloadPath = await application!.evaluate(
    () => (globalThis as any).qaDriver.updater.installerPath
  )
  assert.equal(
    await hashFile(downloadPath),
    await hashFile(path.join(published, installerName(newVersion)))
  )
  checks.push('签名异常切换备用元数据源；真实 electron-updater 差分下载结果与完整安装包一致')

  const exit = application!.waitForEvent('close')
  await command('install').catch(() => {})
  await exit
  application = undefined
  await until(
    async () => {
      const boot = JSON.parse(
        await fs.readFile(path.join(sandbox, `boot-${newVersion}.json`), 'utf8')
      )
      bootPid = boot.pid
      return (
        boot.version === newVersion &&
        path.resolve(boot.executable) ===
          path.resolve(path.join(installed, executableName + '.exe'))
      )
    },
    'NSIS upgrade and target restart',
    120000
  )
  assert.equal(readVersion(), newVersion)
  assert.deepEqual(await fs.readFile(settings), beforeSettings)
  const receipt = JSON.parse(
    await fs.readFile(path.join(sandbox, 'userdata/software-updates/installer-result.json'), 'utf8')
  )
  assert.equal(receipt.status, 'completed')
  checks.push('真实 NSIS 从 1.0.0 跨版本安装 2.4.0 并重启，设置逐字节保留，目标启动回执完成')
  console.log(JSON.stringify({ sandbox, checks }, null, 2))
} finally {
  await close().catch(() => {})
  if (bootPid) await run('taskkill.exe', ['/PID', String(bootPid), '/T', '/F']).catch(() => {})
  const uninstaller = path.join(installed, `Uninstall ${executableName}.exe`)
  if (await fs.stat(uninstaller).catch(() => null)) await run(uninstaller, ['/S']).catch(() => {})
  server.closeAllConnections()
  server.close()
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, 'test-results/software-updates.json'),
    JSON.stringify({ sandbox, appId, cache, checks, requests }, null, 2)
  )
}
