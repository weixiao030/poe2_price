import { test } from 'node:test'
import type { TestContext } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import http from 'node:http'
import { dump } from 'js-yaml'
import { buildRelease } from '../scripts/build-software-update'
import { verifyChannel } from '../scripts/verify-update-release'
import {
  hashFile,
  installerName,
  newerVersion,
  signManifest,
  updateUrl,
  verifyRelease
} from '../src/main/software-update-protocol'
import { SoftwareUpdater } from '../src/main/software-update'
import type { UpdateDriver } from '../src/main/software-update'
import {
  GITHUB_MIRROR_PREFIXES,
  installerSources,
  manifestSources
} from '../src/main/software-update-sources'
import type { SoftwareUpdateState } from '../src/shared/software-update'

const keys = crypto.generateKeyPairSync('ed25519')
const privateKey = keys.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
const publicKey = keys.publicKey.export({ type: 'spki', format: 'pem' }).toString()
const payload = Buffer.from('complete installer payload shared by every old version')
function metadata(version = '2.4.0', extra: Record<string, unknown> = {}) {
  return Buffer.from(
    dump({
      version,
      releaseDate: '2026-09-22T00:00:00.000Z',
      releaseNotes: '保留现有功能\n跨版本直升',
      files: [
        {
          url: installerName(version),
          size: payload.length,
          sha512: crypto.createHash('sha512').update(payload).digest('base64')
        }
      ],
      ...extra
    })
  )
}
function verified(version = '2.4.0') {
  const bytes = metadata(version)
  return verifyRelease(bytes, signManifest(bytes, privateKey), publicKey)
}

test('publication rejects downgrades, changed same-version metadata and invalid channel signatures', () => {
  const bytes = metadata(),
    signature = signManifest(bytes, privateKey)
  const hash = crypto.createHash('sha256').update(bytes).digest('hex')
  assert.equal(verifyChannel(bytes, signature, publicKey, '3.0.0', 'next-hash'), '2.4.0')
  assert.equal(verifyChannel(bytes, signature, publicKey, '2.4.0', hash), '2.4.0')
  assert.throws(() => verifyChannel(bytes, signature, publicKey, '2.3.9', hash), /旧版本/)
  assert.throws(() => verifyChannel(bytes, signature, publicKey, '2.4.0', 'changed'), /元数据/)
  assert.throws(
    () =>
      verifyChannel(Buffer.concat([bytes, Buffer.from('x')]), signature, publicKey, '3.0.0', hash),
    /签名/
  )
})

test('standard signed YAML rejects tampering, foreign keys, paths, web packages and wrong platform assets', () => {
  const bytes = metadata(),
    signature = signManifest(bytes, privateKey)
  assert.equal(verifyRelease(bytes, signature, publicKey).version, '2.4.0')
  assert.throws(
    () => verifyRelease(Buffer.concat([bytes, Buffer.from('x')]), signature, publicKey),
    /签名/
  )
  const foreign = crypto
    .generateKeyPairSync('ed25519')
    .publicKey.export({ type: 'spki', format: 'pem' })
    .toString()
  assert.throws(() => verifyRelease(bytes, signature, foreign), /签名/)
  for (const extra of [
    { files: [{ url: '../bad.exe', size: 10, sha512: 'a'.repeat(86) + '==' }] },
    { files: [{ url: 'https://other.test/install.exe', size: 10, sha512: 'a'.repeat(86) + '==' }] },
    { packages: { x64: { path: 'payload.7z' } } },
    { files: [] },
    { version: '3.0.0-beta.1' },
    { stagingPercentage: 10 }
  ]) {
    const bad = metadata('2.4.0', extra)
    assert.throws(() => verifyRelease(bad, signManifest(bad, privateKey), publicKey))
  }
  assert.throws(() => updateUrl('http://example.test/latest.yml'))
  assert.throws(() => updateUrl('https://user:password@example.test/latest.yml'))
  assert.throws(() => updateUrl('https://example.test/latest.yml#fragment'))
  assert.equal(newerVersion('2.0.0', '1.99.99'), true)
})

test('all configured GitHub mirrors precede ZOS and package URLs pin the verified release', () => {
  const config = {
    github: { repository: 'weixiao030/poe2_price' },
    manifestUrls: ['https://example.zos.ctyun.cn/installer/latest.yml'],
    publicKey
  }
  const manifests = manifestSources(config),
    sources = installerSources(config, verified())
  assert.equal(manifests.length, 9)
  for (let i = 0; i < 8; i++) {
    assert.ok(manifests[i].url.startsWith(GITHUB_MIRROR_PREFIXES[i] + 'https://github.com/'))
    assert.ok(
      sources[i].url.includes('/releases/download/v2.4.0/POE-Price-Patch-2.4.0-x64-Setup.exe')
    )
    assert.ok(
      sources[i]
        .oldBlockmapUrl('1.0.0')
        .includes('/releases/download/v1.0.0/POE-Price-Patch-1.0.0-x64-Setup.exe.blockmap')
    )
  }
  assert.equal(
    sources[8].url,
    'https://example.zos.ctyun.cn/installer/POE-Price-Patch-2.4.0-x64-Setup.exe'
  )
  assert.ok(!manifests.some((source) => source.url.startsWith('https://github.com/')))
  assert.throws(() => manifestSources({ ...config, github: { repository: '../other' } }))
})

async function fixture(t: TestContext, current = '1.0.0') {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-installer-test-'))
  t.after(() => fs.rm(dir, { recursive: true, force: true }))
  const requests: string[] = [],
    modes: Record<string, string> = {}
  const bytes = metadata(),
    signature = signManifest(bytes, privateKey)
  const server = http.createServer((req, res) => {
    const source = req.url!.split('/')[1]
    const kind = req.url!.endsWith('.sig')
      ? 'signature'
      : req.url!.endsWith('.yml')
        ? 'manifest'
        : 'installer'
    requests.push(`${source}:${kind}`)
    const mode = modes[source + ':' + kind] || modes[source]
    if (mode === 'offline') {
      res.writeHead(503)
      res.end()
      return
    }
    if (mode === 'hang') return
    const content =
      mode === 'corrupt'
        ? Buffer.from('tampered')
        : kind === 'signature'
          ? Buffer.from(signature)
          : kind === 'manifest'
            ? bytes
            : payload
    res.writeHead(200, { 'Content-Length': content.length })
    res.end(content)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  t.after(() => {
    server.closeAllConnections()
    server.close()
  })
  const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`
  let installs = 0,
    busy = false,
    installationError: Error | undefined
  const downloaded = path.join(dir, 'pending.exe')
  const driver: UpdateDriver = {
    async download(_release, source, signal, progress) {
      const response = await fetch(source.url, { signal })
      if (!response.ok) throw new Error('download ' + response.status)
      const content = Buffer.from(await response.arrayBuffer())
      await fs.writeFile(downloaded, content)
      progress(content.length, content.length)
      return downloaded
    },
    install(onError) {
      installs++
      if (installationError) onError(installationError)
    }
  }
  const changes: SoftwareUpdateState[] = []
  const options = {
    version: current,
    notes: [],
    config: {
      publicKey,
      github: { repository: 'owner/repo', mirrorPrefixes: [base + '/primary/', base + '/backup/'] },
      manifestUrls: [base + '/zos/latest.yml']
    },
    stateRoot: path.join(dir, 'state'),
    packaged: true,
    driver,
    canInstall: () => !busy,
    changed: (s: SoftwareUpdateState) => changes.push(s),
    allowLocalhost: true,
    sourceIdleTimeoutMs: 150,
    manifestTimeoutMs: 500
  }
  const updater = new SoftwareUpdater(options)
  return {
    dir,
    requests,
    modes,
    updater,
    options,
    driver,
    changes,
    downloaded,
    installs: () => installs,
    busy: (value: boolean) => {
      busy = value
    },
    installationError: (error: Error) => {
      installationError = error
    }
  }
}

test('startup checks once, never downloads, and persists only the ignored release across restarts', async (t) => {
  const f = await fixture(t)
  await f.updater.checkAtStartup()
  assert.equal(f.updater.snapshot.startupNotificationVersion, '2.4.0')
  const requests = f.requests.length
  await f.updater.checkAtStartup()
  assert.equal(f.requests.length, requests)
  assert.ok(f.requests.every(r => !r.endsWith(':installer')))
  assert.equal(f.installs(), 0)
  await f.updater.dismissNotice('2.4.0', true)
  assert.equal(f.updater.snapshot.startupNotificationVersion, undefined)
  const restarted = new SoftwareUpdater(f.options)
  await restarted.checkAtStartup()
  assert.equal(restarted.snapshot.status, 'available')
  assert.equal(restarted.snapshot.startupNotificationVersion, undefined)
  assert.equal((await restarted.check()).release?.version, '2.4.0')
  await fs.writeFile(path.join(f.options.stateRoot, 'notice.json'), JSON.stringify({ ignoredVersion: '2.3.9' }))
  const next = new SoftwareUpdater(f.options)
  await next.checkAtStartup()
  assert.equal(next.snapshot.startupNotificationVersion, '2.4.0')
  await next.dismissNotice('2.4.0', false)
  const nextRestart = new SoftwareUpdater(f.options)
  await nextRestart.checkAtStartup()
  assert.equal(nextRestart.snapshot.startupNotificationVersion, '2.4.0')
})

test('startup check failure and current releases do not create a notice', async (t) => {
  const f = await fixture(t, '2.4.0')
  await f.updater.checkAtStartup()
  assert.equal(f.updater.snapshot.startupNotificationVersion, undefined)
  for (const source of ['primary', 'backup', 'zos']) f.modes[source] = 'offline'
  const offline = new SoftwareUpdater(f.options)
  await offline.checkAtStartup()
  assert.equal(offline.snapshot.status, 'error')
  assert.equal(offline.snapshot.startupNotificationVersion, undefined)
})

for (const current of ['1.0.0', '1.0.7', '1.9.0', '2.0.0']) {
  test(`${current} downloads the same complete 2.4.0 without intermediate releases or inventories`, async (t) => {
    const f = await fixture(t, current)
    assert.equal((await f.updater.check()).status, 'available')
    assert.equal((await f.updater.download()).status, 'ready')
    assert.deepEqual(await fs.readFile(f.downloaded), payload)
    assert.deepEqual(
      f.requests.filter((x) => x.endsWith(':installer')),
      ['primary:installer']
    )
  })
}

test('invalid primary signature uses the backup; corrupt installer retries backup with the same signed target', async (t) => {
  const f = await fixture(t)
  f.modes['primary:signature'] = 'corrupt'
  assert.equal((await f.updater.check()).status, 'available')
  f.modes['primary:installer'] = 'corrupt'
  assert.equal((await f.updater.download()).status, 'ready')
  assert.deepEqual(
    f.requests.filter((x) => x.endsWith(':installer')),
    ['primary:installer', 'backup:installer']
  )
  assert.ok(!f.requests.some((x) => x.startsWith('zos:')))
})

test('ZOS is used only after every mirror fails for each operation', async (t) => {
  const f = await fixture(t)
  f.modes.primary = f.modes.backup = 'offline'
  assert.equal((await f.updater.check()).status, 'available')
  assert.equal((await f.updater.download()).status, 'ready')
  assert.deepEqual(
    f.requests.filter((x) => x.endsWith(':installer')),
    ['primary:installer', 'backup:installer', 'zos:installer']
  )
  assert.deepEqual(
    f.requests.filter((x) => x.endsWith(':manifest')),
    ['primary:manifest', 'backup:manifest', 'zos:manifest']
  )
})

test('stalled download advances to the next mirror', async (t) => {
  const f = await fixture(t)
  await f.updater.check()
  f.modes['primary:installer'] = 'hang'
  assert.equal((await f.updater.download()).status, 'ready')
  assert.deepEqual(
    f.requests.filter((x) => x.endsWith(':installer')),
    ['primary:installer', 'backup:installer']
  )
})

test('cancel stops all fallback attempts and permits retry; concurrent requests do not launch another download', async (t) => {
  const f = await fixture(t)
  await f.updater.check()
  f.modes['primary:installer'] = 'hang'
  const downloading = f.updater.download()
  await assert.rejects(f.updater.download(), /先检查/)
  while (!f.requests.includes('primary:installer'))
    await new Promise((resolve) => setTimeout(resolve, 5))
  f.updater.cancel()
  assert.equal((await downloading).status, 'available')
  assert.ok(!f.requests.includes('backup:installer'))
  delete f.modes['primary:installer']
  assert.equal((await f.updater.download()).status, 'ready')
})

test('installation is blocked while busy, takes the guard immediately and never installs a changed cache', async (t) => {
  const f = await fixture(t)
  await f.updater.check()
  await f.updater.download()
  f.busy(true)
  await assert.rejects(f.updater.install(), /等待/)
  assert.equal(f.installs(), 0)
  f.busy(false)
  await fs.writeFile(f.downloaded, 'modified after download')
  const installing = f.updater.install()
  assert.equal(f.updater.installing, true)
  assert.equal((await installing).status, 'error')
  assert.equal(f.installs(), 0)
  await assert.rejects(fs.access(f.downloaded))
  await f.updater.check()
  await f.updater.download()
  assert.equal((await f.updater.install()).status, 'installing')
  assert.equal(f.installs(), 1)
  await assert.rejects(f.updater.install(), /尚未准备/)
})

test('installer errors are reported, receipts survive restart and only the target UI marks completion', async (t) => {
  const f = await fixture(t)
  await f.updater.check()
  await f.updater.download()
  f.installationError(new Error('安装器无法启动'))
  assert.equal((await f.updater.install()).status, 'error')
  assert.match(f.updater.snapshot.message, /无法启动/)
  const old = new SoftwareUpdater(f.options)
  await old.previousResult()
  assert.equal(old.snapshot.status, 'error')
  const target = new SoftwareUpdater({ ...f.options, version: '2.4.0' })
  await target.uiReady()
  assert.equal(
    JSON.parse(await fs.readFile(path.join(f.options.stateRoot, 'installer-result.json'), 'utf8'))
      .status,
    'completed'
  )
})

test('publisher signs a standard release without a baseline and refuses altered or overwritten installers', async (t) => {
  const f = await fixture(t)
  const directory = path.join(f.dir, 'build'),
    output = path.join(f.dir, 'publish')
  await fs.mkdir(directory)
  await fs.writeFile(path.join(directory, installerName('2.4.0')), payload)
  await fs.writeFile(path.join(directory, installerName('2.4.0') + '.blockmap'), 'blockmap')
  await fs.writeFile(path.join(directory, 'latest.yml'), metadata())
  const options = {
    directory,
    output,
    privateKey,
    publicKey,
    notes: { version: '2.4.0', notes: ['跨版本更新'] }
  }
  const result = await buildRelease(options)
  assert.equal(result.files.filter((name) => name.endsWith('.exe')).length, 1)
  assert.ok(!result.files.some((name) => name.endsWith('.zip')))
  assert.equal(
    await hashFile(path.join(output, installerName('2.4.0'))),
    await hashFile(path.join(directory, installerName('2.4.0')))
  )
  const release = verifyRelease(
    await fs.readFile(path.join(output, 'latest.yml')),
    await fs.readFile(path.join(output, 'latest.yml.sig'), 'utf8'),
    publicKey
  )
  assert.equal(release.version, '2.4.0')
  await buildRelease(options)
  await assert.rejects(
    buildRelease({ ...options, notes: { version: '2.4.0', notes: ['changed'] } }),
    /覆盖/
  )
  await fs.writeFile(path.join(directory, installerName('2.4.0')), 'changed binary')
  await assert.rejects(buildRelease(options), /不一致/)
})
