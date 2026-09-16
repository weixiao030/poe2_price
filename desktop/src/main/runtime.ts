import { app } from 'electron'
import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'

let preparing: Promise<string> | undefined
export const dataRoot = () => path.join(app.getPath('userData'), 'engine')
export function prepareRuntime(): Promise<string> {
  preparing ??= stage().catch((error) => {
    preparing = undefined
    throw error
  })
  return preparing
}
async function stage(): Promise<string> {
  const source = app.isPackaged
    ? path.join(process.resourcesPath, 'engine')
    : path.join(app.getAppPath(), '.runtime')
  const manifest = JSON.parse(await fs.readFile(path.join(source, 'manifest.json'), 'utf8')) as {
    id: string
    files: Record<string, string>
  }
  const destination = dataRoot()
  await fs.mkdir(destination, { recursive: true })
  let current = ''
  try {
    current = await fs.readFile(path.join(destination, '.ready'), 'utf8')
  } catch {
    /* First use. */
  }
  if (current === manifest.id) {
    try {
      await Promise.all(
        [
          'worker.ps1',
          'tools/python/poe_python.exe',
          'tools/python/python313.zip',
          'tools/dotnet-runtime/dotnet.exe',
          'tools/BundleExtractor/BundleExtractor.exe'
        ].map((file) => fs.access(path.join(destination, file)))
      )
      return destination
    } catch {
      /* Restore a partially removed runtime from bundled resources. */
    }
  }
  for (const [relative, hash] of Object.entries(manifest.files)) {
    const to = path.resolve(destination, relative)
    if (!to.startsWith(destination + path.sep)) throw new Error('内置引擎清单路径无效')
    const data = await fs.readFile(path.join(source, relative))
    if (crypto.createHash('sha256').update(data).digest('hex') !== hash)
      throw new Error(`内置引擎校验失败：${relative}`)
    await fs.mkdir(path.dirname(to), { recursive: true })
    const temp = to + '.new'
    await fs.writeFile(temp, data)
    await fs.rename(temp, to)
  }
  await fs.writeFile(path.join(destination, '.ready'), manifest.id)
  return destination
}
