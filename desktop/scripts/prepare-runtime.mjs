import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
const require = createRequire(import.meta.url)
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repo = path.dirname(root)
const runtime = path.resolve(root, '.runtime')
// Build from declared inputs in a fresh directory; stale local files must never ship.
const target = await fs.mkdtemp(path.join(root, '.runtime-stage-'))
await fs.mkdir(target, { recursive: true })
await fs.copyFile(path.join(repo, '使用许可.md'), path.join(target, '使用许可.md'))
await fs.copyFile(path.join(repo, 'docs/第三方工具说明.md'), path.join(target, '第三方工具说明.md'))
const filter = (p) =>
  !/(?:^|[\\/])(?:__pycache__|downloads)(?:[\\/]|$)/.test(p) && !/\.(?:pyc|pdb)$/i.test(p) &&
  !['price_patch_gui.ps1', 'auto_update_worker.ps1'].includes(path.basename(p))
await fs.cp(path.join(repo, '物价补丁/tools'), path.join(target, 'tools'), {
  recursive: true,
  filter
})
await fs.cp(
  path.join(repo, '物价补丁/一键安装特殊补丁工具'),
  path.join(target, '一键安装特殊补丁工具'),
  { recursive: true, filter }
)
for (const obsolete of ['price_patch_gui.ps1', 'auto_update_worker.ps1'])
  await fs.rm(path.join(target, 'tools', obsolete), { force: true })
const runtimeBuild = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
  path.join(repo, 'build/prepare_runtime.ps1'), '-Destination', path.join(target, 'tools')],
  { windowsHide: true, stdio: 'inherit' })
if (runtimeBuild.status !== 0) throw new Error('Failed to prepare verified standalone runtimes')
for (const seed of ['国服还原包.zip', '国际服还原补丁.zip'])
  await fs.copyFile(path.join(repo, 'restore-seeds', seed), path.join(target, seed))
// Windows PowerShell 5.1 needs BOM for Chinese source literals; JSON stays UTF-8.
await fs.writeFile(
  path.join(target, 'worker.ps1'),
  '\ufeff' +
    (await fs.readFile(path.join(root, 'resources/worker.ps1'), 'utf8')).replace(/^\ufeff/, '')
)
for (const name of [
  'tools/python/poe_python.exe',
  'tools/python/python313.zip',
  'tools/dotnet-runtime/dotnet.exe',
  'tools/BundleExtractor/BundleExtractor.exe',
  '一键安装特殊补丁工具/PatchBundle3.exe'
])
  await fs.access(path.join(target, name))
const files = {}
async function walk(dir) {
  for (const item of (await fs.readdir(dir, { withFileTypes: true })).sort((a, b) =>
    a.name.localeCompare(b.name)
  )) {
    const p = path.join(dir, item.name)
    if (item.isDirectory()) await walk(p)
    else if (item.name !== 'manifest.json')
      files[path.relative(target, p).split(path.sep).join('/')] = crypto
        .createHash('sha256')
        .update(await fs.readFile(p))
        .digest('hex')
  }
}
await walk(target)
const id = crypto.createHash('sha256').update(JSON.stringify(files)).digest('hex')
await fs.writeFile(path.join(target, 'manifest.json'), JSON.stringify({ id, files }, null, 2))
const icon = require('@iconify-json/ph/icons.json').icons['stack-fill']
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><rect width="256" height="256" rx="48" fill="#176b55"/><g transform="translate(38,38) scale(.7)" fill="#fff">${icon.body.replaceAll('currentColor', '#fff')}</g></svg>`
await sharp(Buffer.from(svg)).png().toFile(path.join(root, 'resources/icon.png'))
await fs.mkdir(path.join(root, 'src/renderer/public'), { recursive: true })
await fs.copyFile(
  path.join(root, 'resources/icon.png'),
  path.join(root, 'src/renderer/public/icon.png')
)
await fs.copyFile(path.join(root, 'resources/icon.png'), path.join(root, 'src/renderer/icon.png'))
if (path.dirname(runtime) !== root || path.basename(runtime) !== '.runtime')
  throw new Error('Unexpected generated runtime path')
const previous = await fs.lstat(runtime).catch((error) => {
  if (error.code === 'ENOENT') return null
  throw error
})
if (previous?.isSymbolicLink()) throw new Error('Runtime output cannot be a link')
await fs.rm(runtime, { recursive: true, force: true })
await fs.rename(target, runtime)
console.log(JSON.stringify({ runtime, fileCount: Object.keys(files).length, sha256: id }))
