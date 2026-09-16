import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const { version } = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
const archive = path.join(root, `dist/POE-Price-Patch-${version}-x64-免安装版.zip`)
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-no-install-'))
const appDirectory = path.join(sandbox, '免安装版 中文路径')
await fs.mkdir(appDirectory)
const evidence = { archive, appDirectory, commands: [], checks: [] }
function run(command, args, extraEnv = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
    env: { ...process.env, ...extraEnv },
    timeout: 180000,
    maxBuffer: 8 * 1024 * 1024
  })
  evidence.commands.push({
    command: [command, ...args],
    stdout: result.stdout || '',
    stderr: result.stderr || '',
    exit: result.status,
    error: result.error?.message
  })
  process.stdout.write(result.stdout || '')
  process.stderr.write(result.stderr || '')
  assert.equal(result.status, 0, result.error?.message || `${command} failed`)
}
async function inventory(directory) {
  const entries = await fs.readdir(directory, { recursive: true, withFileTypes: true })
  const files = entries
    .filter((entry) => entry.isFile())
    .map((entry) => path.relative(directory, path.join(entry.parentPath, entry.name)))
    .sort()
  const hashes = {}
  for (const file of files)
    hashes[file] = createHash('sha256')
      .update(await fs.readFile(path.join(directory, file)))
      .digest('hex')
  return hashes
}
try {
  run(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      "$ErrorActionPreference = 'Stop'\nExpand-Archive -LiteralPath $env:POE_TEST_ARCHIVE -DestinationPath $env:POE_TEST_APP_DIR"
    ],
    { POE_TEST_ARCHIVE: archive, POE_TEST_APP_DIR: appDirectory }
  )
  const extracted = await inventory(appDirectory)
  const unpacked = await inventory(path.join(root, 'dist/win-unpacked'))
  // NSIS adds its elevation helper after the ZIP target; the app does not use it.
  const installerHelper = path.join('resources', 'elevate.exe')
  if (!extracted[installerHelper]) delete unpacked[installerHelper]
  assert.deepEqual(Object.keys(extracted).sort(), Object.keys(unpacked).sort())
  for (const [file, hash] of Object.entries(extracted)) assert.equal(hash, unpacked[file], file)
  assert.ok(extracted['物价补丁.exe'])
  assert.ok(extracted[path.join('resources', 'app.asar')])
  assert.ok(extracted[path.join('resources', 'engine', 'manifest.json')])
  evidence.fileCount = Object.keys(extracted).length
  evidence.checks.push(
    'ZIP 解压后全部应用文件哈希与打包目录一致；仅允许省略 NSIS 专用 elevate.exe，含物价补丁.exe 和完整运行资源'
  )
  run(process.execPath, [
    path.join(root, 'scripts/verify-package.mjs'),
    '--ci',
    '--app-dir',
    appDirectory
  ])
  evidence.startupMs = JSON.parse(
    await fs.readFile(path.join(root, 'test-results/package-evidence.json'), 'utf8')
  ).startupMs
  run(process.execPath, [
    path.join(root, 'scripts/verify-startup.mjs'),
    '--packaged',
    '--app-dir',
    appDirectory
  ])
  evidence.checks.push(
    '中文目录解压后无参数 EXE 启动、内置引擎、开机启动设置、后台驻留和托盘恢复通过'
  )
  assert.deepEqual(await inventory(appDirectory), extracted)
  evidence.checks.push('运行前后发行目录文件哈希不变，无自解包步骤')
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, 'test-results/no-install-evidence.json'),
    JSON.stringify(evidence, null, 2)
  )
}
