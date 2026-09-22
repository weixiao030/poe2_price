import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dump, load } from 'js-yaml'
import {
  hashFile,
  installerName,
  MANIFEST_NAME,
  signManifest,
  verifyRelease
} from '../src/main/software-update-protocol'

/** Sign the final, standard NSIS metadata. No old release is an input. */
export async function buildRelease(options: {
  directory: string
  output: string
  privateKey: string
  publicKey: string
  notes: { version: string; notes: string[] }
}) {
  const { directory, output, notes } = options
  const signingKey = crypto.createPrivateKey(options.privateKey)
  const bundledKey = crypto.createPublicKey(options.publicKey)
  if (
    signingKey.asymmetricKeyType !== 'ed25519' ||
    !crypto
      .createPublicKey(signingKey)
      .export({ type: 'spki', format: 'der' })
      .equals(bundledKey.export({ type: 'spki', format: 'der' }))
  )
    throw new Error('签名私钥与客户端公钥不对应')
  const info = load(await fs.readFile(path.join(directory, MANIFEST_NAME), 'utf8')) as Record<
    string,
    unknown
  >
  if (info.version !== notes.version || !Array.isArray(notes.notes))
    throw new Error('发行版本与更新说明不一致')
  const name = installerName(notes.version)
  const installer = path.join(directory, name),
    blockmap = installer + '.blockmap'
  const file = (info.files as { url: string; size: number; sha512: string }[])?.[0]
  if (
    !file ||
    file.url !== name ||
    file.size !== (await fs.stat(installer)).size ||
    file.sha512 !== (await hashFile(installer, 'sha512'))
  )
    throw new Error('安装包与 builder 元数据不一致')
  const blockmapBytes = (await fs.stat(blockmap)).size
  if (!blockmapBytes || blockmapBytes > 16 * 1024 * 1024) throw new Error('缺少有效的 blockmap')
  info.releaseNotes = notes.notes.join('\n')
  const bytes = Buffer.from(dump(info, { lineWidth: -1 }), 'utf8')
  const signature = signManifest(bytes, options.privateKey)
  const release = verifyRelease(bytes, signature, options.publicKey)
  // Never silently replace a previously prepared release with different bytes.
  await fs.mkdir(output, { recursive: true })
  async function writeImmutable(name: string, contents: Buffer) {
    const destination = path.join(output, name)
    try {
      await fs.writeFile(destination, contents, { flag: 'wx' })
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
      if (!(await fs.readFile(destination)).equals(contents))
        throw new Error(`拒绝覆盖已有发行文件：${name}`)
    }
  }
  await writeImmutable(name, await fs.readFile(installer))
  await writeImmutable(name + '.blockmap', await fs.readFile(blockmap))
  await writeImmutable(MANIFEST_NAME, bytes)
  await writeImmutable(MANIFEST_NAME + '.sig', Buffer.from(signature + '\n'))
  const names = [name, name + '.blockmap', MANIFEST_NAME, MANIFEST_NAME + '.sig']
  const hashes = await Promise.all(
    names.map(async (name) => `${await hashFile(path.join(output, name))}  ${name}`)
  )
  await writeImmutable('SHA256SUMS.txt', Buffer.from(hashes.join('\n') + '\n'))
  return {
    version: release.version,
    output,
    files: [...names, 'SHA256SUMS.txt'],
    installerBytes: release.installer.size
  }
}

async function main() {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const args = process.argv.slice(2)
  const option = (name: string) => {
    const i = args.indexOf('--' + name)
    return i < 0 ? undefined : args[i + 1]
  }
  if (args.some((arg) => ['--from', '--to', '--delta-only', '--base-url'].includes(arg)))
    throw new Error('1.0.0 使用完整安装包和 blockmap；无需旧版基线。使用 --directory 和 --out。')
  const directory = path.resolve(option('directory') || path.join(root, 'dist'))
  const output = path.resolve(option('out') || path.join(directory, 'update-publish'))
  if (directory === output) throw new Error('签名发行输出目录必须独立于构建目录')
  const config = JSON.parse(
    await fs.readFile(option('config') || path.join(root, 'resources/update-config.json'), 'utf8')
  )
  const notes = JSON.parse(
    await fs.readFile(option('notes') || path.join(root, 'resources/current-release.json'), 'utf8')
  )
  const privateKey = await fs.readFile(
    option('key') || path.join(root, '.release-keys/update-private.pem'),
    'utf8'
  )
  console.log(
    JSON.stringify(
      await buildRelease({ directory, output, privateKey, publicKey: config.publicKey, notes }),
      null,
      2
    )
  )
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
