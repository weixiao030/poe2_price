import fs from 'node:fs/promises'
import { createWriteStream } from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { pipeline } from 'node:stream/promises'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import yazl from 'yazl'
import {
  APP_ID,
  hashFile,
  relativeFile,
  versionParts,
  newerVersion,
  updateUrl
} from '../src/main/software-update-protocol'
import type {
  UpdateFile,
  UpdatePackage,
  UpdateAsset,
  SoftwareRelease
} from '../src/shared/software-update'

export async function inventory(root: string): Promise<UpdateFile[]> {
  const output: UpdateFile[] = []
  async function walk(dir: string) {
    for (const entry of (await fs.readdir(dir, { withFileTypes: true })).sort((a, b) =>
      a.name.localeCompare(b.name)
    )) {
      const file = path.join(dir, entry.name)
      // electron-builder adds this NSIS-only helper after creating NoInstall.zip.
      // Our updater never uses it; exclude it so both editions share one baseline.
      if (path.relative(root, file).split(path.sep).join('/').toLowerCase() === 'resources/elevate.exe') continue
      if (entry.isSymbolicLink()) throw new Error('发行目录不能包含符号链接')
      if (entry.isDirectory()) await walk(file)
      else if (entry.isFile())
        output.push({
          path: relativeFile(path.relative(root, file).split(path.sep).join('/')),
          size: (await fs.stat(file)).size,
          sha256: await hashFile(file)
        })
    }
  }
  await walk(root)
  for (const required of ['物价补丁.exe', 'resources/app.asar'])
    if (!output.some((file) => file.path === required)) throw new Error(`发行目录缺少 ${required}`)
  return output
}
export async function buildPackage(options: {
  to: string
  from?: string
  version: string
  fromVersion?: string
  output: string
  baseUrl: string
  allowLocalhost?: boolean
}): Promise<UpdateAsset> {
  versionParts(options.version)
  if (options.from) {
    versionParts(options.fromVersion || '')
    if (!newerVersion(options.version, options.fromVersion!))
      throw new Error('目标版本必须高于基线版本')
  }
  const targetFiles = await inventory(options.to)
  const baseFiles = options.from ? await inventory(options.from) : []
  const base = new Map(baseFiles.map((file) => [file.path, file]))
  const files = targetFiles.filter(
    (file) => file.sha256 !== base.get(file.path)?.sha256 || file.size !== base.get(file.path)?.size
  )
  const kind = options.from ? 'delta' : 'full'
  const manifest: UpdatePackage = {
    schema: 1,
    appId: APP_ID,
    version: options.version,
    kind,
    ...(options.from ? { fromVersion: options.fromVersion } : {}),
    executable: '物价补丁.exe',
    files,
    baseFiles,
    targetFiles
  }
  await fs.mkdir(options.output, { recursive: true })
  const name = `POE-Price-Patch-${options.fromVersion ? options.fromVersion + '-to-' : ''}${options.version}-${kind}.zip`
  const destination = path.join(options.output, name)
  const zip = new yazl.ZipFile()
  const writing = pipeline(zip.outputStream, createWriteStream(destination, { flags: 'wx' }))
  zip.addBuffer(Buffer.from(JSON.stringify(manifest)), 'update.json')
  for (const file of files) zip.addFile(path.join(options.to, file.path), 'files/' + file.path)
  zip.end()
  await writing
  const url = updateUrl(
    new URL(name, options.baseUrl.replace(/\/?$/, '/')).href,
    options.allowLocalhost
  )
  return {
    kind,
    ...(options.from ? { fromVersion: options.fromVersion } : {}),
    url,
    size: (await fs.stat(destination)).size,
    sha256: await hashFile(destination)
  }
}
export function signRelease(release: SoftwareRelease, privateKey: string) {
  const payload = Buffer.from(JSON.stringify(release))
  return {
    schema: 1,
    payload: payload.toString('base64'),
    signature: crypto.sign(null, payload, privateKey).toString('base64')
  }
}
async function main() {
  const args = process.argv.slice(2)
  const option = (name: string) => {
    const i = args.indexOf('--' + name)
    return i >= 0 ? args[i + 1] : undefined
  }
  const to = option('to'),
    output = option('out'),
    baseUrl = option('base-url'),
    key = option('key')
  if (!to || !output || !baseUrl || !key)
    throw new Error(
      '用法：--to win-unpacked --out 发布目录 --base-url HTTPS目录/ --key 私钥文件 [--from 旧版目录]'
    )
  const require = createRequire(import.meta.url)
  const asar = require('@electron/asar')
  const packagedVersion = (dir: string) =>
    JSON.parse(asar.extractFile(path.join(dir, 'resources/app.asar'), 'package.json').toString())
      .version as string
  const version = packagedVersion(to)
  const from = option('from')
  const deltaOnly = args.includes('--delta-only')
  if (deltaOnly && !from) throw new Error('--delta-only 必须提供 --from 旧版基线')
  const fromVersion = from ? packagedVersion(from) : undefined
  const notes = JSON.parse(
    await fs.readFile(option('notes') || path.resolve('resources/current-release.json'), 'utf8')
  )
  if (notes.version !== version || !Array.isArray(notes.notes))
    throw new Error('发布说明与目标应用版本不一致')
  const privateKey = await fs.readFile(key, 'utf8')
  const config = JSON.parse(await fs.readFile(path.join(to, 'resources/update-config.json'), 'utf8'))
  const signingPublic = crypto.createPublicKey(privateKey).export({ type: 'spki', format: 'der' })
  const bundledPublic = crypto.createPublicKey(config.publicKey).export({ type: 'spki', format: 'der' })
  if (!signingPublic.equals(bundledPublic)) throw new Error('签名私钥与目标发行版的更新公钥不对应')
  const packages: UpdateAsset[] = []
  if (from) packages.push(await buildPackage({ to, from, version, fromVersion, output, baseUrl }))
  if (!deltaOnly) packages.push(await buildPackage({ to, version, output, baseUrl }))
  const release: SoftwareRelease = {
    appId: APP_ID,
    version,
    notes: notes.notes,
    publishedAt: new Date().toISOString(),
    packages
  }
  const envelope = signRelease(release, privateKey)
  await fs.writeFile(path.join(output, 'latest.json'), JSON.stringify(envelope, null, 2))
  await fs.writeFile(path.join(output, 'release-info.json'), JSON.stringify(release, null, 2))
  console.log(JSON.stringify({ version, output, packages }, null, 2))
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
