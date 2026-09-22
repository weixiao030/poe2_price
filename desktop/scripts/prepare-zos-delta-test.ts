import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { buildPackage, signRelease } from './build-software-update'
import { APP_ID, hashFile, verifyRelease } from '../src/main/software-update-protocol'

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.dirname(desktop)
const option = (name: string, fallback: string) => {
  const index = process.argv.indexOf(name)
  return index < 0 ? fallback : path.resolve(process.argv[index + 1])
}
const baseline = option('--baseline', path.join(root, 'release-desktop/baselines/0.9.2/win-unpacked'))
const config = JSON.parse(await fs.readFile(path.join(baseline, 'resources/update-config.json'), 'utf8'))
assert.equal(config.manifestUrls.length, 1, '测试基线必须配置单个公开更新清单地址')
const baseUrl = new URL('.', config.manifestUrls[0]).href
const staging = option('--staging', path.join(root, 'release-desktop/zos-0.9.3-light-test'))
const target = path.join(staging, 'win-unpacked')
const output = path.join(staging, 'poe-updates')
await fs.mkdir(staging, { recursive: true })
try { await fs.access(target); throw new Error('测试目标已存在，请保留现有证据') }
catch (error: any) { if (error.code !== 'ENOENT') throw error }
await fs.cp(baseline, target, { recursive: true, force: false, errorOnExist: true })
const asar = createRequire(import.meta.url)('@electron/asar')
const source = path.join(staging, 'asar-source')
asar.extractAll(path.join(target, 'resources/app.asar'), source)
const packagePath = path.join(source, 'package.json')
const pkg = JSON.parse(await fs.readFile(packagePath, 'utf8'))
assert.equal(pkg.version, '0.9.2')
pkg.version = '0.9.3'
await fs.writeFile(packagePath, JSON.stringify(pkg, null, 2) + '\n')
await asar.createPackage(source, path.join(target, 'resources/app.asar'))
const notes = ['ZOS 轻量增量升级测试：应用版本从 0.9.2 升至 0.9.3。', '仅更新应用版本号和本段测试说明；物价功能、程序外壳和引擎保持 0.9.2。']
await fs.writeFile(path.join(target, 'resources/current-release.json'), JSON.stringify({ version: pkg.version, notes }, null, 2) + '\n')
assert.equal(await hashFile(path.join(target, '物价补丁.exe')), await hashFile(path.join(baseline, '物价补丁.exe')))
const asset = await buildPackage({
  from: baseline, fromVersion: '0.9.2', to: target, version: '0.9.3', output,
  baseUrl
})
const release = { appId: APP_ID, version: '0.9.3', notes, publishedAt: new Date().toISOString(), packages: [asset] }
const privateKey = await fs.readFile(path.join(desktop, '.release-keys/update-private.pem'), 'utf8')
const envelope = signRelease(release, privateKey)
assert.deepEqual(verifyRelease(envelope, config.publicKey), release)
await fs.writeFile(path.join(output, 'latest.json'), JSON.stringify(envelope, null, 2) + '\n')
await fs.writeFile(path.join(staging, 'release-info.json'), JSON.stringify(release, null, 2) + '\n')
console.log(JSON.stringify({ from: '0.9.2', version: '0.9.3', scope: 'test only', asset }, null, 2))
