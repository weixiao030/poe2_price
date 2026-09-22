import crypto from 'node:crypto'
import { createReadStream } from 'node:fs'
import fs from 'node:fs/promises'
import { load } from 'js-yaml'
import type { UpdateInfo } from 'builder-util-runtime'
import type { SoftwareRelease } from '../shared/software-update'

export const APP_ID = 'com.poepricepatch.desktop'
export const MANIFEST_NAME = 'latest.yml'
export const MANIFEST_LIMIT = 128 * 1024

export function versionParts(value: string): number[] {
  if (
    typeof value !== 'string' ||
    !/^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$/.test(value)
  )
    throw new Error('更新版本号无效')
  return value.split('.').map(Number)
}

export function newerVersion(next: string, current: string): boolean {
  const a = versionParts(next),
    b = versionParts(current)
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i]
  return false
}

export function installerName(version: string): string {
  versionParts(version)
  return `POE-Price-Patch-${version}-x64-Setup.exe`
}

export function updateUrl(value: string, allowLocalhost = false): string {
  const url = new URL(value)
  const local =
    allowLocalhost && url.protocol === 'http:' && ['127.0.0.1', '[::1]'].includes(url.hostname)
  if ((!local && url.protocol !== 'https:') || url.username || url.password || url.hash)
    throw new Error('更新地址必须使用 HTTPS')
  return url.href
}

export async function hashFile(
  file: string,
  algorithm: 'sha256' | 'sha512' = 'sha256'
): Promise<string> {
  const hash = crypto.createHash(algorithm)
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest(algorithm === 'sha512' ? 'base64' : 'hex')
}

export function verifyRelease(
  bytes: Buffer,
  signature: string,
  publicKey: string
): SoftwareRelease {
  if (
    !bytes.length ||
    bytes.length > MANIFEST_LIMIT ||
    !/^[A-Za-z0-9+/]{86}==$/.test(signature.trim())
  )
    throw new Error('安装更新清单格式无效')
  const key = crypto.createPublicKey(publicKey)
  if (
    key.asymmetricKeyType !== 'ed25519' ||
    !crypto.verify(null, bytes, key, Buffer.from(signature.trim(), 'base64'))
  )
    throw new Error('更新说明签名校验失败')
  const info = load(bytes.toString('utf8')) as UpdateInfo & { packages?: unknown }
  versionParts(info?.version)
  if (
    !Array.isArray(info.files) ||
    info.files.length !== 1 ||
    info.packages ||
    info.stagingPercentage !== undefined ||
    typeof info.releaseDate !== 'string' ||
    !Number.isFinite(Date.parse(info.releaseDate)) ||
    (info.releaseNotes !== undefined && typeof info.releaseNotes !== 'string')
  )
    throw new Error('更新说明内容无效')
  const file = info.files[0],
    name = installerName(info.version)
  if (
    !file ||
    file.url !== name ||
    !Number.isSafeInteger(file.size) ||
    file.size! <= 0 ||
    file.size! > 2_000_000_000 ||
    !/^[A-Za-z0-9+/]{86}==$/.test(file.sha512) ||
    (info.path !== undefined && info.path !== name) ||
    (info.sha512 !== undefined && info.sha512 !== file.sha512)
  )
    throw new Error('安装包信息无效')
  const notes = ((info.releaseNotes || '') as string)
    .split(/\r?\n/)
    .map((note) => note.replace(/^[-*]\s+/, '').trim())
    .filter(Boolean)
  if (notes.length > 40 || notes.some((note) => note.length > 2000)) throw new Error('版本说明过长')
  return {
    version: info.version,
    publishedAt: info.releaseDate,
    notes,
    installer: { name, size: file.size!, sha512: file.sha512 },
    info
  }
}

export function signManifest(bytes: Buffer, privateKey: string): string {
  return crypto.sign(null, bytes, privateKey).toString('base64')
}

export async function verifyInstaller(file: string, release: SoftwareRelease) {
  const stat = await fs.lstat(file)
  if (
    !stat.isFile() ||
    stat.isSymbolicLink() ||
    stat.size !== release.installer.size ||
    (await hashFile(file, 'sha512')) !== release.installer.sha512
  )
    throw new Error('安装包校验失败，请重新下载')
}
