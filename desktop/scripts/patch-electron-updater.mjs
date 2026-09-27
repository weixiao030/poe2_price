import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const packagePath = path.join(root, 'node_modules/electron-updater/package.json')
const sourcePath = path.join(root, 'node_modules/electron-updater/out/differentialDownloader/multipleRangeDownloader.js')
const packageInfo = JSON.parse(await fs.readFile(packagePath, 'utf8'))
if (packageInfo.version !== '6.8.9') throw new Error(`Unsupported electron-updater version: ${packageInfo.version}`)
const marker = 'const nextOffset = taskOffset + 1000;'
const patched = 'const nextOffset = taskOffset + 200;'
const source = await fs.readFile(sourcePath, 'utf8')
if (source.includes(patched)) {
  console.log('electron-updater multipart range batch already capped at 200')
} else {
  if (!source.includes(marker)) throw new Error('electron-updater multipart range batch marker not found')
  await fs.writeFile(sourcePath, source.replace(marker, patched), 'utf8')
  console.log('Capped electron-updater multipart range batches at 200 ranges')
}
