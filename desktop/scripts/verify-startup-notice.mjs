// Real production Electron main/preload/renderer with a signed, isolated update feed.
import { _electron as electron } from 'playwright'
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dump } from 'js-yaml'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const { version } = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-startup-notice-'))
const profile = path.join(sandbox, 'profile')
const evidence = path.resolve(root, '../verification/desktop-v' + version + '/startup-notice')
await fs.mkdir(evidence, { recursive: true })
await fs.mkdir(path.join(sandbox, 'resources'))
await fs.copyFile(path.join(root, 'resources/icon.png'), path.join(sandbox, 'resources/icon.png'))
await fs.copyFile(
  path.join(root, 'resources/current-release.json'),
  path.join(sandbox, 'resources/current-release.json')
)
const keys = crypto.generateKeyPairSync('ed25519')
await fs.writeFile(
  path.join(sandbox, 'resources/update-config.json'),
  JSON.stringify({
    publicKey: keys.publicKey.export({ type: 'spki', format: 'pem' }),
    manifestUrls: ['https://updates.example.test/latest.yml']
  })
)
await fs.writeFile(
  path.join(sandbox, 'package.json'),
  JSON.stringify({ name: 'poe-notice-qa', version, main: 'bootstrap.cjs' })
)
await fs.writeFile(
  path.join(sandbox, 'bootstrap.cjs'),
  `
const fs = require('node:fs');
const feed = JSON.parse(fs.readFileSync(${JSON.stringify(path.join(sandbox, 'feed.json'))}, 'utf8'));
globalThis.noticeRequests = [];
globalThis.fetch = async url => {
  globalThis.noticeRequests.push(String(url));
  if (feed.offline) return new Response('', {status:503});
  if (!String(url).endsWith('.yml') && !String(url).endsWith('.yml.sig')) throw new Error('Unexpected automatic download');
  return new Response(String(url).endsWith('.sig') ? feed.signature : feed.manifest);
};
import(${JSON.stringify(pathToFileURL(path.join(root, 'out/main/index.js')).href)});
`
)
async function feed(release, offline = false) {
  const manifest = dump({
    version: release,
    releaseDate: new Date().toISOString(),
    releaseNotes: '验证用更新',
    files: [
      {
        url: `POE-Price-Patch-${release}-x64-Setup.exe`,
        size: 123,
        sha512: crypto.createHash('sha512').update('isolated fixture').digest('base64')
      }
    ]
  })
  await fs.writeFile(
    path.join(sandbox, 'feed.json'),
    JSON.stringify({
      manifest,
      signature: crypto.sign(null, Buffer.from(manifest), keys.privateKey).toString('base64'),
      offline
    })
  )
}
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const checks = [],
  errors = []
let app, page
async function launch(hidden = false) {
  app = await electron.launch({
    args: [sandbox, ...(hidden ? ['--hidden'] : [])],
    env,
    timeout: 30000
  })
  if (!hidden) await ready()
}
async function ready() {
  page = await app.firstWindow()
  page.on('pageerror', (error) => errors.push(error.message))
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.waitForFunction(async () =>
    ['available', 'current', 'error'].includes((await window.desktop.getSoftwareUpdate()).status)
  )
}
async function close() {
  const requests = await app.evaluate(() => globalThis.noticeRequests)
  assert.equal(requests.length, 2, 'Each process checks exactly one manifest and signature')
  assert.ok(
    requests.every((url) => /\.yml(?:\.sig)?$/.test(url)),
    'No automatic package downloads'
  )
  await app.close()
  app = undefined
}
try {
  await feed('1.0.2')
  await launch()
  const notice = page.getByRole('complementary', { name: '发现软件更新' })
  await notice.waitFor()
  await page.mouse.move(0, 0)
  await notice.waitFor({ state: 'hidden', timeout: 5500 })
  assert.equal(await page.getByRole('heading', { name: '物价补丁', exact: true }).count(), 1)
  checks.push('Startup checks without navigation; notice disappears after approximately 3 seconds')
  await close()

  await launch()
  await page.getByRole('complementary', { name: '发现软件更新' }).hover()
  await page.waitForTimeout(3300)
  assert.equal(await page.getByRole('button', { name: '本次更新不再提醒' }).count(), 1)
  await page.screenshot({ path: path.join(evidence, 'notice-light.png') })
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'dark' }))
  await page.screenshot({ path: path.join(evidence, 'notice-dark.png') })
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(960, 680))
  await page.screenshot({ path: path.join(evidence, 'notice-compact.png') })
  const bounds = await page.getByRole('complementary', { name: '发现软件更新' }).boundingBox()
  assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 960)
  await page.getByRole('button', { name: '本次更新不再提醒' }).click()
  assert.equal(
    JSON.parse(await fs.readFile(path.join(profile, 'software-updates/notice.json'), 'utf8'))
      .ignoredVersion,
    '1.0.2'
  )
  checks.push('Hover keeps actions available; light/dark/compact layouts; ignored version saved')
  await close()

  await launch()
  assert.equal(await page.getByRole('complementary', { name: '发现软件更新' }).count(), 0)
  await page.getByRole('button', { name: '检查更新', exact: true }).click()
  await page.getByRole('heading', { name: '新版本 v1.0.2', exact: true }).waitFor()
  checks.push('Ignored release stays quiet after restart, remains visible in manual updates')
  await close()

  await feed('1.0.3')
  await launch(true)
  await app.evaluate(async () => {
    for (let n = 0; n < 100 && globalThis.noticeRequests.length < 2; n++)
      await new Promise((resolve) => setTimeout(resolve, 50))
  })
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 0)
  await app.evaluate(({ app }) => app.emit('activate'))
  await ready()
  await page.getByRole('button', { name: '查看更新', exact: true }).click()
  await page.getByRole('heading', { name: '检查更新', exact: true }).waitFor()
  checks.push(
    'New version reminds again; hidden startup stays windowless; View updates does not install'
  )
  await close()

  await feed(version)
  await launch()
  assert.equal(await page.getByRole('complementary', { name: '发现软件更新' }).count(), 0)
  await close()
  await feed('1.0.3', true)
  await launch()
  assert.equal(await page.getByRole('complementary', { name: '发现软件更新' }).count(), 0)
  assert.equal(await page.getByRole('heading', { name: '物价补丁', exact: true }).count(), 1)
  await close()
  checks.push('Current version and network errors remain quiet')
  assert.deepEqual(errors, [])
  await fs.writeFile(
    path.join(evidence, 'result.json'),
    JSON.stringify({ checks, errors, sandbox }, null, 2)
  )
  console.log(JSON.stringify({ checks, errors, evidence }))
} finally {
  if (app) await app.close()
}
