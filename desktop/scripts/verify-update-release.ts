import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import crypto from 'node:crypto'
import {
  hashFile,
  MANIFEST_NAME,
  newerVersion,
  verifyInstaller,
  verifyRelease
} from '../src/main/software-update-protocol'

/** Channel updates move forward; retrying the exact same release is safe. */
export function verifyChannel(
  manifest: Buffer,
  signature: string,
  publicKey: string,
  nextVersion: string,
  nextHash: string
) {
  const current = verifyRelease(manifest, signature, publicKey)
  if (newerVersion(current.version, nextVersion)) throw new Error('拒绝用旧版本覆盖最新发布')
  if (
    current.version === nextVersion &&
    crypto.createHash('sha256').update(manifest).digest('hex') !== nextHash
  )
    throw new Error('拒绝修改已发布版本的元数据')
  return current.version
}

export async function inspectRelease(directory: string, publicKey: string) {
  const bytes = await fs.readFile(path.join(directory, MANIFEST_NAME))
  const signature = await fs.readFile(path.join(directory, MANIFEST_NAME + '.sig'), 'utf8')
  const release = verifyRelease(bytes, signature, publicKey)
  await verifyInstaller(path.join(directory, release.installer.name), release)
  const names = [
    release.installer.name,
    release.installer.name + '.blockmap',
    MANIFEST_NAME,
    MANIFEST_NAME + '.sig'
  ]
  const files = await Promise.all(
    names.map(async (name) => {
      const file = path.join(directory, name),
        stat = await fs.lstat(file)
      if (!stat.isFile() || stat.isSymbolicLink() || !stat.size)
        throw new Error(`发行文件无效：${name}`)
      return {
        name,
        size: stat.size,
        sha256: await hashFile(file),
        contentType: name.endsWith('.exe')
          ? 'application/vnd.microsoft.portable-executable'
          : name.endsWith('.yml')
            ? 'text/yaml; charset=utf-8'
            : 'application/octet-stream'
      }
    })
  )
  const sums = files.map((file) => `${file.sha256}  ${file.name}`).join('\n') + '\n'
  if ((await fs.readFile(path.join(directory, 'SHA256SUMS.txt'), 'utf8')) !== sums)
    throw new Error('发行校验清单不一致')
  return {
    version: release.version,
    files,
    manifestSha256: files.find((file) => file.name === MANIFEST_NAME)!.sha256
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const configPath =
    process.argv[3] || fileURLToPath(new URL('../resources/update-config.json', import.meta.url))
  const config = JSON.parse(await fs.readFile(configPath, 'utf8'))
  if (process.argv[2] === '--channel') {
    const chunks: Buffer[] = []
    let size = 0
    for await (const chunk of process.stdin) {
      size += chunk.length
      if (size > 256 * 1024) throw new Error('通道检查输入过大')
      chunks.push(chunk)
    }
    const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    console.log(
      JSON.stringify({
        previousVersion: verifyChannel(
          Buffer.from(input.manifest, 'base64'),
          input.signature,
          config.publicKey,
          input.version,
          input.manifestSha256
        )
      })
    )
  } else
    console.log(
      JSON.stringify(await inspectRelease(path.resolve(process.argv[2]), config.publicKey))
    )
}
