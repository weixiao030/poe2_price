import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import http from 'node:http'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { buildPackage, inventory, signRelease } from '../scripts/build-software-update'
import {
  APP_ID,
  newerVersion,
  relativeFile,
  selectAsset,
  unpackUpdate,
  updateUrl,
  verifyInventory,
  verifyRelease
} from '../src/main/software-update-protocol'
import { SoftwareUpdater } from '../src/main/software-update'
import type { SoftwareRelease } from '../src/shared/software-update'

const desktopRoot = fileURLToPath(new URL('../', import.meta.url))
const helper = path.join(desktopRoot, 'resources/install-software-update.ps1')
const keys = crypto.generateKeyPairSync('ed25519')
const privateKey = keys.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
const publicKey = keys.publicKey.export({ type: 'spki', format: 'pem' }).toString()
async function fixture() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-更新 $包-'))
  const old = path.join(root, 'old'),
    next = path.join(root, 'next'),
    out = path.join(root, 'published')
  for (const dir of [old, next]) {
    await fs.mkdir(path.join(dir, 'resources'), { recursive: true })
    await fs.writeFile(path.join(dir, '物价补丁.exe'), Buffer.alloc(100_000, 73))
  }
  await fs.writeFile(path.join(old, 'resources/app.asar'), 'old application')
  await fs.writeFile(path.join(old, 'resources/obsolete.dat'), 'old managed resource')
  await fs.writeFile(path.join(next, 'resources/app.asar'), 'new application')
  await fs.writeFile(path.join(next, 'resources/new.dat'), 'new managed resource')
  return { root, old, next, out }
}
async function makeRelease(
  f: Awaited<ReturnType<typeof fixture>>,
  baseUrl = 'https://download.example.test/'
) {
  const asset = await buildPackage({
    from: f.old,
    to: f.next,
    version: '0.9.1',
    fromVersion: '0.9.0',
    output: f.out,
    baseUrl,
    allowLocalhost: baseUrl.startsWith('http:')
  })
  const release: SoftwareRelease = {
    appId: APP_ID,
    version: '0.9.1',
    notes: ['真实更新测试'],
    publishedAt: new Date().toISOString(),
    packages: [asset]
  }
  return {
    asset,
    release,
    envelope: signRelease(release, privateKey),
    archive: path.join(f.out, new URL(asset.url).pathname.split('/').pop()!)
  }
}
test('software versions, paths, transport and publisher signature are enforced', () => {
  assert.equal(newerVersion('0.10.0', '0.9.9'), true)
  assert.equal(newerVersion('0.9.0', '0.9.0'), false)
  assert.throws(() => newerVersion('v0.9.0', '0.8.8'))
  for (const value of [
    '../outside',
    'C:/outside',
    'x\\y',
    '/absolute',
    'x/NUL.txt',
    'x.',
    'x/../y',
    'x//y'
  ])
    assert.throws(() => relativeFile(value))
  assert.throws(() => updateUrl('http://example.test/update.zip'))
  assert.throws(() => updateUrl('https://user:password@example.test/update.zip'))
  const release: SoftwareRelease = {
    appId: APP_ID,
    version: '0.9.1',
    publishedAt: new Date().toISOString(),
    notes: ['版本说明'],
    packages: [
      {
        kind: 'delta',
        fromVersion: '0.9.0',
        url: 'https://example.test/update.zip',
        size: 10,
        sha256: 'a'.repeat(64)
      }
    ]
  }
  const envelope = signRelease(release, privateKey)
  assert.equal(verifyRelease(envelope, publicKey).version, '0.9.1')
  assert.throws(() =>
    verifyRelease(
      {
        ...envelope,
        payload: Buffer.from(JSON.stringify({ ...release, version: '9.9.9' })).toString('base64')
      },
      publicKey
    )
  )
  assert.throws(() => selectAsset(release, '0.8.8'))
})
test('delta package contains only changed files, checks baseline, preserves unrelated files', async () => {
  const f = await fixture()
  await fs.writeFile(path.join(f.old, 'resources/elevate.exe'), 'NSIS-only helper')
  const { asset, release, archive } = await makeRelease(f)
  const stage = path.join(f.root, 'stage')
  const manifest = await unpackUpdate(archive, stage, asset, release)
  assert.deepEqual(manifest.files.map((file) => file.path).sort(), [
    'resources/app.asar',
    'resources/new.dat'
  ])
  assert.ok(asset.size < 10_000)
  await verifyInventory(f.old, manifest.baseFiles)
  assert.ok(!manifest.baseFiles.some(file => file.path === 'resources/elevate.exe'))
  await fs.unlink(path.join(f.old, 'resources/elevate.exe'))
  await verifyInventory(f.old, manifest.baseFiles)
  await fs.writeFile(path.join(f.old, 'personal-notes.txt'), 'keep me')
  await verifyInventory(f.old, manifest.baseFiles)
  await fs.writeFile(path.join(f.old, 'resources/app.asar'), 'modified locally')
  await assert.rejects(verifyInventory(f.old, manifest.baseFiles), /基线不一致/)
})
test('actual HTTP download verifies signed manifest and rejects tampered package', async (t) => {
  const f = await fixture()
  let manifestBody = '',
    archive = '',
    corrupted = false
  const server = http.createServer(async (req, res) => {
    if (req.url === '/latest.json') res.end(manifestBody)
    else {
      const bytes = await fs.readFile(archive)
      if (corrupted) bytes[bytes.length - 1] ^= 1
      res.end(bytes)
    }
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  t.after(() => {
    server.closeAllConnections()
    server.close()
  })
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/`
  const built = await makeRelease(f, baseUrl)
  archive = built.archive
  manifestBody = JSON.stringify(built.envelope)
  const create = () =>
    new SoftwareUpdater({
      version: '0.9.0',
      notes: [],
      config: { manifestUrls: [baseUrl + 'latest.json'], publicKey },
      appRoot: f.old,
      transactionRoot: path.join(f.root, 'transactions'),
      helperSource: helper,
      packaged: false,
      canInstall: () => false,
      changed: () => {},
      quit: () => {
        throw new Error('must not exit')
      },
      allowLocalhost: true
    })
  const updater = create()
  assert.equal((await updater.check()).status, 'available')
  assert.equal((await updater.download()).status, 'ready')
  await assert.rejects(updater.install(), /开发模式/)
  corrupted = true
  const other = create()
  await other.check()
  const failure = await other.download()
  assert.equal(failure.status, 'error')
  assert.match(failure.message, /校验失败/)
  assert.equal(await fs.readFile(path.join(f.old, 'resources/app.asar'), 'utf8'), 'old application')
})
async function applyFixture(f: Awaited<ReturnType<typeof fixture>>, corruptTarget = false) {
  const { asset, release, archive } = await makeRelease(f)
  const dir = path.join(f.root, crypto.randomUUID()),
    stage = path.join(dir, 'files')
  const manifest = await unpackUpdate(archive, stage, asset, release)
  const target = new Set(manifest.targetFiles.map((file) => file.path))
  const removeFiles = manifest.baseFiles.filter((file) => !target.has(file.path))
  const base = new Map(manifest.baseFiles.map((file) => [file.path, file]))
  const beforeFiles = [...manifest.files, ...removeFiles].map((file) => ({
    ...(base.get(file.path) || file),
    exists: base.has(file.path)
  }))
  const plan = {
    schema: 1,
    token: path.basename(dir),
    version: '0.9.1',
    parentPid: 0,
    appRoot: f.old,
    stageRoot: stage,
    backupRoot: path.join(dir, 'backup'),
    executable: '物价补丁.exe',
    restart: false,
    files: manifest.files,
    removeFiles,
    beforeFiles,
    baseFiles: manifest.baseFiles,
    targetFiles: manifest.targetFiles.map((file) =>
      corruptTarget && file.path === 'resources/app.asar'
        ? { ...file, sha256: '0'.repeat(64) }
        : file
    )
  }
  const planFile = path.join(dir, 'plan.json')
  await fs.writeFile(planFile, JSON.stringify(plan))
  await fs.writeFile(path.join(f.old, 'personal-notes.txt'), 'keep me')
  return { dir, planFile, manifest, plan }
}
async function runHelper(planFile: string, recover = false) {
  return new Promise<number | null>((resolve, reject) => {
    const child = spawn(
      'powershell.exe',
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        helper,
        '-PlanPath',
        planFile,
        ...(recover ? ['-Recover'] : [])
      ],
      { windowsHide: true, stdio: 'pipe' }
    )
    let errors = ''
    child.stderr.on('data', (chunk) => {
      errors += chunk.toString()
    })
    const timeout = setTimeout(() => {
      child.kill()
      reject(new Error('helper timeout: ' + errors))
    }, 30_000)
    child.on('error', reject)
    child.on('exit', (code) => {
      clearTimeout(timeout)
      resolve(code)
    })
  })
}
test(
  'real Windows helper applies changed files, removes managed obsolete file and keeps user file',
  { skip: process.platform !== 'win32' },
  async () => {
    const f = await fixture(),
      apply = await applyFixture(f)
    assert.equal(await runHelper(apply.planFile), 0)
    await verifyInventory(f.old, apply.manifest.targetFiles)
    assert.equal(await fs.readFile(path.join(f.old, 'personal-notes.txt'), 'utf8'), 'keep me')
    await assert.rejects(fs.access(path.join(f.old, 'resources/obsolete.dat')))
    assert.equal(
      JSON.parse(await fs.readFile(path.join(apply.dir, 'result.json'), 'utf8')).status,
      'completed'
    )
  }
)
test(
  'real Windows helper rolls back a failed post-write verification',
  { skip: process.platform !== 'win32' },
  async () => {
    const f = await fixture(),
      apply = await applyFixture(f, true)
    assert.equal(await runHelper(apply.planFile), 1)
    await verifyInventory(f.old, apply.manifest.baseFiles)
    await assert.rejects(fs.access(path.join(f.old, 'resources/new.dat')))
    assert.equal(
      JSON.parse(await fs.readFile(path.join(apply.dir, 'result.json'), 'utf8')).status,
      'rolled-back'
    )
  }
)
test(
  'interrupted commit can be recovered from the journal and verified backups',
  { skip: process.platform !== 'win32' },
  async () => {
    const f = await fixture(),
      apply = await applyFixture(f)
    for (const file of apply.plan.beforeFiles.filter((file) => file.exists)) {
      const destination = path.join(apply.plan.backupRoot, file.path)
      await fs.mkdir(path.dirname(destination), { recursive: true })
      await fs.copyFile(path.join(f.old, file.path), destination)
    }
    await fs.writeFile(path.join(apply.dir, 'journal.json'), JSON.stringify({ state: 'applying' }))
    await fs.writeFile(path.join(f.old, 'resources/app.asar'), 'interrupted update')
    assert.equal(await runHelper(apply.planFile, true), 0)
    await verifyInventory(f.old, apply.manifest.baseFiles)
  }
)
