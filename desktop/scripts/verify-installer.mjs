import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const { getPath7za } = createRequire(import.meta.url)('app-builder-lib/out/toolsets/7zip')
const { version } = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
const arg = process.argv.indexOf('--release-dir')
const release = arg < 0 ? path.join(root, 'dist') : path.resolve(process.argv[arg + 1])
const installer = path.join(release, `POE-Price-Patch-${version}-x64-Setup.exe`)
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-installer-payload-'))
const outer = path.join(sandbox, 'archive'),
  appDirectory = path.join(sandbox, '安装载荷 中文路径')
function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
    timeout: 240000,
    maxBuffer: 8 * 1024 * 1024
  })
  assert.equal(result.status, 0, result.error?.message || result.stderr || result.stdout)
  return result.stdout
}
async function inventory(dir) {
  const result = {}
  for (const entry of await fs.readdir(dir, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile()) continue
    const file = path.join(entry.parentPath, entry.name)
    result[path.relative(dir, file).replaceAll('\\', '/')] = createHash('sha256')
      .update(await fs.readFile(file))
      .digest('hex')
  }
  return result
}
const seven = await getPath7za()
run(seven, ['x', installer, '-o' + outer, '-y'])
const archives = (await fs.readdir(outer, { recursive: true })).filter((name) =>
  /app-64\.7z$/.test(name)
)
if (archives.length === 1)
  run(seven, ['x', path.join(outer, archives[0]), '-o' + appDirectory, '-y'])
else {
  // Current 7-Zip recognizes the embedded archive directly in this NSIS build.
  await fs.access(path.join(outer, 'resources/app.asar'))
  await fs.cp(outer, appDirectory, { recursive: true })
}
const extracted = await inventory(appDirectory)
assert.deepEqual(extracted, await inventory(path.join(release, 'win-unpacked')))
run(process.execPath, [
  path.join(root, 'scripts/verify-package.mjs'),
  '--ci',
  '--app-dir',
  appDirectory
])
run(process.execPath, [
  path.join(root, 'scripts/verify-startup.mjs'),
  '--packaged',
  '--app-dir',
  appDirectory
])
assert.deepEqual(await inventory(appDirectory), extracted)
await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
const evidence = {
  installer,
  appDirectory,
  files: Object.keys(extracted).length,
  checks: [
    '完整 NSIS 载荷逐文件哈希与构建目录一致',
    '安装载荷在中文路径启动、引擎及设置保留通过',
    '启动和使用不改写程序目录'
  ]
}
await fs.writeFile(
  path.join(root, 'test-results/installer-evidence.json'),
  JSON.stringify(evidence, null, 2)
)
console.log(JSON.stringify(evidence, null, 2))
