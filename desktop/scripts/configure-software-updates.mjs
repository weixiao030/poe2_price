import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
const target = path.join(root, 'resources/update-config.json')
const existing = JSON.parse(
  await fs.readFile(target, 'utf8').catch((error) => {
    if (error.code !== 'ENOENT') throw error
    return '{}'
  })
)
const i = args.indexOf('--base-url')
const baseUrl = i >= 0 ? args[i + 1] : ''
if (
  baseUrl &&
  (new URL(baseUrl).protocol !== 'https:' || new URL(baseUrl).username || new URL(baseUrl).password)
)
  throw new Error('请使用 ZOS 或自定义域名的公开 HTTPS 目录地址')
const keyDir = path.join(root, '.release-keys')
await fs.mkdir(keyDir, { recursive: true })
const privatePath = path.join(keyDir, 'update-private.pem')
let privateKey
try {
  privateKey = await fs.readFile(privatePath, 'utf8')
} catch (error) {
  if (error.code !== 'ENOENT') throw error
  privateKey = crypto
    .generateKeyPairSync('ed25519')
    .privateKey.export({ type: 'pkcs8', format: 'pem' })
  await fs.writeFile(privatePath, privateKey, { flag: 'wx', mode: 0o600 })
}
const publicKey = crypto.createPublicKey(privateKey).export({ type: 'spki', format: 'pem' })
const config = {
  github: existing.github || { repository: 'weixiao030/poe2_price' },
  manifestUrls: baseUrl
    ? [new URL('latest.yml', baseUrl.replace(/\/?$/, '/')).href]
    : existing.manifestUrls || [],
  publicKey
}
await fs.writeFile(target, JSON.stringify(config, null, 2) + '\n')
// Keep the installer cache metadata aligned with the public fallback location.
if (baseUrl) {
  const packagePath = path.join(root, 'package.json')
  const pkg = JSON.parse(await fs.readFile(packagePath, 'utf8'))
  pkg.build.publish = { provider: 'generic', url: new URL('.', config.manifestUrls[0]).href }
  await fs.writeFile(packagePath, JSON.stringify(pkg, null, 2) + '\n')
}
console.log(`发布配置：${target}\n签名私钥保存在 ${privatePath}，请独立备份，勿上传到下载目录。`)
