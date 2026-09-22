import { updateFs as fs, rawFs } from './software-update-fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import yauzl from 'yauzl'
import type {
  SoftwareRelease,
  UpdateAsset,
  UpdateFile,
  UpdatePackage
} from '../shared/software-update'

export const APP_ID = 'com.poepricepatch.desktop'
const { createReadStream, createWriteStream } = rawFs
const HASH = /^[a-f0-9]{64}$/
export function versionParts(value: string): number[] {
  if (!/^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(value)) throw new Error('更新版本号无效')
  return value.split('.').map(Number)
}
export function newerVersion(next: string, current: string): boolean {
  const a = versionParts(next),
    b = versionParts(current)
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i]
  return false
}
export function updateUrl(value: string, allowLocalhost = false): string {
  const url = new URL(value)
  const local =
    allowLocalhost && url.protocol === 'http:' && ['127.0.0.1', '[::1]'].includes(url.hostname)
  if ((!local && url.protocol !== 'https:') || url.username || url.password || url.hash)
    throw new Error('更新地址必须使用 HTTPS')
  return url.href
}
export function relativeFile(value: string): string {
  if (
    typeof value !== 'string' ||
    value.length > 230 ||
    !value ||
    value.includes('\\') ||
    value
      .split('/')
      .some(
        (part) =>
          !part ||
          part === '.' ||
          part === '..' ||
          /[<>:"|?*\x00-\x1f]/.test(part) ||
          /[. ]$/.test(part) ||
          /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part)
      )
  )
    throw new Error('更新包文件路径无效')
  return value
}
export async function safeFile(root: string, relative: string): Promise<string> {
  const parts = relativeFile(relative).split('/')
  let cursor = path.resolve(root)
  const rootStat = await fs.lstat(cursor)
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) throw new Error('更新目录不能是链接')
  for (let i = 0; i < parts.length; i++) {
    cursor = path.join(cursor, parts[i])
    const stat = await fs.lstat(cursor).catch((e) => {
      if (e.code === 'ENOENT') return null
      throw e
    })
    if (
      stat &&
      (stat.isSymbolicLink() || (i < parts.length - 1 ? !stat.isDirectory() : !stat.isFile()))
    )
      throw new Error('更新路径包含链接或类型冲突')
  }
  return cursor
}
export async function hashFile(file: string): Promise<string> {
  const hash = crypto.createHash('sha256')
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest('hex')
}
export function verifyRelease(
  envelope: unknown,
  publicKey: string,
  allowLocalhost = false
): SoftwareRelease {
  const value = envelope as { schema?: number; payload?: string; signature?: string }
  if (
    value?.schema !== 1 ||
    typeof value.payload !== 'string' ||
    typeof value.signature !== 'string' ||
    value.payload.length > 1_000_000 ||
    !publicKey
  )
    throw new Error('更新说明格式或签名配置无效')
  const bytes = Buffer.from(value.payload, 'base64')
  if (!crypto.verify(null, bytes, publicKey, Buffer.from(value.signature, 'base64')))
    throw new Error('更新说明签名校验失败')
  const release = JSON.parse(bytes.toString('utf8')) as SoftwareRelease
  versionParts(release.version)
  if (
    release.appId !== APP_ID ||
    !Number.isFinite(Date.parse(release.publishedAt)) ||
    !Array.isArray(release.notes) ||
    release.notes.length > 40 ||
    release.notes.some((note) => typeof note !== 'string' || note.length > 2000) ||
    !Array.isArray(release.packages) ||
    !release.packages.length ||
    release.packages.length > 100
  )
    throw new Error('更新说明内容无效')
  for (const asset of release.packages) {
    updateUrl(asset.url, allowLocalhost)
    if (
      !['delta', 'full'].includes(asset.kind) ||
      !HASH.test(asset.sha256) ||
      !Number.isSafeInteger(asset.size) ||
      asset.size <= 0 ||
      asset.size > 2_000_000_000
    )
      throw new Error('更新包信息无效')
    if (asset.kind === 'delta') {
      versionParts(asset.fromVersion || '')
      if (!newerVersion(release.version, asset.fromVersion!))
        throw new Error('增量更新版本范围无效')
    } else if (asset.fromVersion !== undefined) throw new Error('完整包不能限定起始版本')
  }
  return release
}
export function selectAsset(release: SoftwareRelease, current: string): UpdateAsset {
  if (!newerVersion(release.version, current)) throw new Error('没有可安装的新版本')
  const candidates = release.packages.filter(
    (asset) => asset.kind === 'full' || asset.fromVersion === current
  )
  candidates.sort(
    (a, b) => Number(a.kind === 'full') - Number(b.kind === 'full') || a.size - b.size
  )
  if (!candidates[0]) throw new Error('暂无适用于当前版本的更新包')
  return candidates[0]
}
function fileList(input: unknown): UpdateFile[] {
  if (!Array.isArray(input) || input.length > 30_000) throw new Error('更新文件清单无效')
  const seen = new Set<string>()
  for (const file of input as UpdateFile[]) {
    const key = relativeFile(file.path).toLowerCase()
    if (
      seen.has(key) ||
      !HASH.test(file.sha256) ||
      !Number.isSafeInteger(file.size) ||
      file.size < 0 ||
      file.size > 2_000_000_000
    )
      throw new Error('更新清单包含重复或无效文件')
    seen.add(key)
  }
  for (const file of input as UpdateFile[])
    if (
      file.path
        .split('/')
        .slice(0, -1)
        .some((_part, i, parts) =>
          seen.has(
            parts
              .slice(0, i + 1)
              .join('/')
              .toLowerCase()
          )
        )
    )
      throw new Error('更新清单文件与目录冲突')
  return input
}
export function verifyPackage(
  input: unknown,
  asset: UpdateAsset,
  release: SoftwareRelease
): UpdatePackage {
  const value = input as UpdatePackage
  if (
    value?.schema !== 1 ||
    value.appId !== APP_ID ||
    value.version !== release.version ||
    value.kind !== asset.kind ||
    value.fromVersion !== asset.fromVersion ||
    value.executable !== '物价补丁.exe'
  )
    throw new Error('更新包与发布版本不对应')
  value.files = fileList(value.files)
  value.baseFiles = fileList(value.baseFiles)
  value.targetFiles = fileList(value.targetFiles)
  const target = new Map(value.targetFiles.map((file) => [file.path, file]))
  const base = new Map(value.baseFiles.map((file) => [file.path, file]))
  const baseNames = new Map(value.baseFiles.map((file) => [file.path.toLowerCase(), file.path]))
  for (const file of value.targetFiles)
    if (
      baseNames.has(file.path.toLowerCase()) &&
      baseNames.get(file.path.toLowerCase()) !== file.path
    )
      throw new Error('更新包不能仅通过大小写重命名 Windows 文件')
  if (!target.has(value.executable) || !target.has('resources/app.asar'))
    throw new Error('更新包缺少应用入口')
  for (const file of value.files)
    if (target.get(file.path)?.sha256 !== file.sha256 || target.get(file.path)?.size !== file.size)
      throw new Error('更新文件不属于目标清单')
  const changed = new Set(value.files.map((file) => file.path))
  for (const file of value.targetFiles)
    if (
      !changed.has(file.path) &&
      (value.kind === 'full' ||
        base.get(file.path)?.sha256 !== file.sha256 ||
        base.get(file.path)?.size !== file.size)
    )
      throw new Error('更新包缺少变更文件')
  if (value.kind === 'full' && value.baseFiles.length) throw new Error('完整更新包的基线无效')
  if (value.targetFiles.reduce((sum, file) => sum + file.size, 0) > 4_000_000_000)
    throw new Error('更新包解压大小超限')
  return value
}
export async function verifyInventory(root: string, files: UpdateFile[]): Promise<void> {
  for (const file of files) {
    const target = await safeFile(root, file.path)
    const stat = await fs.stat(target).catch(() => null)
    if (!stat || stat.size !== file.size || (await hashFile(target)) !== file.sha256)
      throw new Error(`本地文件与更新基线不一致：${file.path}`)
  }
}
export async function unpackUpdate(
  zipPath: string,
  destination: string,
  asset: UpdateAsset,
  release: SoftwareRelease
): Promise<UpdatePackage> {
  await fs.mkdir(destination, { recursive: true })
  let manifest: UpdatePackage | undefined
  const seen = new Set<string>()
  const zip = await new Promise<yauzl.ZipFile>((resolve, reject) =>
    yauzl.open(
      zipPath,
      { lazyEntries: true, validateEntrySizes: true, strictFileNames: true },
      (error, file) => (error ? reject(error) : resolve(file!))
    )
  )
  try {
    await new Promise<void>((resolve, reject) => {
      zip.on('error', reject)
      zip.on('end', resolve)
      zip.on('entry', (entry: yauzl.Entry) => {
        void (async () => {
          const name = relativeFile(entry.fileName)
          const mode = (entry.externalFileAttributes >>> 16) & 0xf000
          if (mode === 0xa000 || entry.generalPurposeBitFlag & 1 || seen.has(name.toLowerCase()))
            throw new Error('更新包包含重复、加密或链接文件')
          seen.add(name.toLowerCase())
          const stream = await new Promise<NodeJS.ReadableStream>((yes, no) =>
            zip.openReadStream(entry, (error, source) => (error ? no(error) : yes(source!)))
          )
          if (name === 'update.json') {
            if (manifest || seen.size !== 1 || entry.uncompressedSize > 8_000_000)
              throw new Error('更新清单位置或大小无效')
            const chunks: Buffer[] = []
            let bytes = 0
            for await (const chunk of stream as AsyncIterable<Buffer>) {
              bytes += chunk.length
              if (bytes > 8_000_000) throw new Error('更新清单过大')
              chunks.push(chunk)
            }
            manifest = verifyPackage(
              JSON.parse(Buffer.concat(chunks).toString('utf8')),
              asset,
              release
            )
          } else {
            const file = manifest?.files.find((item) => 'files/' + item.path === name)
            if (!file || file.size !== entry.uncompressedSize)
              throw new Error('更新包包含未声明的文件')
            const target = await safeFile(destination, file.path)
            await fs.mkdir(path.dirname(target), { recursive: true })
            let bytes = 0
            const limit = new Transform({
              transform(chunk, _encoding, done) {
                bytes += chunk.length
                done(bytes > file.size ? new Error('更新文件大小超限') : null, chunk)
              }
            })
            await pipeline(stream, limit, createWriteStream(target, { flags: 'wx' }))
            if (bytes !== file.size || (await hashFile(target)) !== file.sha256)
              throw new Error('更新文件校验失败')
          }
          zip.readEntry()
        })().catch(reject)
      })
      zip.readEntry()
    })
    if (!manifest || seen.size !== manifest.files.length + 1) throw new Error('更新包文件不完整')
    return manifest
  } finally {
    zip.close()
  }
}
