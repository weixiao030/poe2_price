import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const original = path.resolve(process.argv[2])
assert.notEqual(original, root)
const output = path.join(root, 'verification')
fs.mkdirSync(output, { recursive: true })
const ledger = path.join(output, 'VERIFICATION.txt')
if (fs.existsSync(ledger))
  fs.renameSync(ledger, path.join(output, `VERIFICATION.previous-${Date.now()}.txt`))
fs.writeFileSync(
  ledger,
  `TARGET_COPY=${root}\nPRISTINE_SOURCE=${original}\nCHANGED=worldMap module; overlayDefaults.names/connections=true; runOperation/schedule independent of map; persistent map session; settings links/cleanup\n`
)
process.on('uncaughtExceptionMonitor', (error) =>
  fs.appendFileSync(ledger, `\nTRANSACTION_ERROR=${error.stack}\nTRANSACTION_EXIT_STATUS=1\n`)
)
function run(label, command, args, cwd = root, allowed = [0]) {
  const result = spawnSync(command, args, {
    cwd,
    encoding: 'utf8',
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024
  })
  fs.appendFileSync(
    ledger,
    `\n[${label}]\nCWD=${cwd}\nCOMMAND=${JSON.stringify([command, ...args])}\nSTDOUT_BEGIN\n${result.stdout || ''}\nSTDOUT_END\nSTDERR_BEGIN\n${result.stderr || result.error || ''}\nSTDERR_END\nEXIT_STATUS=${result.status}\n`
  )
  assert.ok(allowed.includes(result.status), `${label}: ${result.stderr || result.error}`)
  return result.stdout
}
const hash = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files = (directory) =>
  [
    ...new Set(
      run(
        'source inventory',
        'git',
        ['ls-files', '-z', '--cached', '--others', '--exclude-standard'],
        directory
      )
        .split('\0')
        .filter(Boolean)
    )
  ].sort()
const beforeFiles = files(original),
  afterFiles = files(root)
const manifest = (directory, paths) =>
  Object.fromEntries(paths.map((p) => [p, hash(path.join(directory, p))]))
const before = manifest(original, beforeFiles),
  after = manifest(root, afterFiles)
fs.writeFileSync(path.join(output, 'baseline-files.json'), JSON.stringify(before, null, 2))
fs.writeFileSync(path.join(output, 'modified-files.json'), JSON.stringify(after, null, 2))
const baseline = path.join(output, 'BASELINE.tar'),
  modified = path.join(output, 'MODIFIED_FILE.tar')
run('archive original bytes', 'tar', ['-cf', baseline, '-C', original, '--', ...beforeFiles])
run('archive modified bytes', 'tar', ['-cf', modified, '-C', root, '--', ...afterFiles])
const baselineHash = hash(baseline)
fs.appendFileSync(
  ledger,
  `BASELINE_ARCHIVE_SHA256=${baselineHash}\nBASELINE_FILE_COUNT=${beforeFiles.length}\nMODIFIED_FILE_COUNT=${afterFiles.length}\n`
)
const transaction = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-source-transaction-'))
run('extract baseline', 'tar', ['-xf', baseline, '-C', transaction])
run('patch staging init', 'git', ['init', '--quiet'], transaction)
fs.writeFileSync(path.join(transaction, '.git/info/attributes'), '* -text\n')
run('patch byte mode', 'git', ['config', 'core.autocrlf', 'false'], transaction)
run('patch baseline index', 'git', ['add', '--all'], transaction)
for (const file of afterFiles) {
  const destination = path.join(transaction, file)
  fs.mkdirSync(path.dirname(destination), { recursive: true })
  fs.copyFileSync(path.join(root, file), destination)
}
for (const file of beforeFiles.filter((p) => !afterFiles.includes(p))) {
  const destination = path.resolve(transaction, file)
  assert.ok(destination.startsWith(transaction + path.sep))
  fs.unlinkSync(destination)
}
run('include new source', 'git', ['add', '--intent-to-add', '.'], transaction)
const diff = path.join(output, 'DIFF_FILE.patch')
const patch = spawnSync('git', ['diff', '--binary', '--full-index', '--no-ext-diff'], {
  cwd: transaction,
  windowsHide: true,
  maxBuffer: 64 * 1024 * 1024
})
assert.equal(patch.status, 0)
fs.writeFileSync(diff, patch.stdout)
fs.appendFileSync(
  ledger,
  `PATCH_COMMAND=git diff --binary --full-index --no-ext-diff\nPATCH_EXIT_STATUS=${patch.status}\nPATCH_STDERR=${patch.stderr}\n`
)
const rollback = path.join(output, 'ROLLBACK.sh')
fs.writeFileSync(
  rollback,
  `#!/bin/sh\nset -eu\nhere=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n[ "$#" -eq 1 ] || { echo 'Usage: ROLLBACK.sh <source-archive-copy>' >&2; exit 2; }\n[ -f "$1" ] || { echo 'Target copy must exist' >&2; exit 2; }\n[ ! "$1" -ef "$here/BASELINE.tar" ] || { echo 'Refusing baseline itself' >&2; exit 2; }\nexpected='${baselineHash}'\nactual=$(sha256sum "$here/BASELINE.tar" | cut -d ' ' -f 1)\n[ "$actual" = "$expected" ] || { echo 'Baseline hash mismatch' >&2; exit 1; }\ncp -- "$here/BASELINE.tar" "$1"\necho 'ROLLBACK restored pristine source archive'\nsha256sum "$1"\n`,
  { mode: 0o755 }
)
const probe = path.join(root, 'desktop/scripts/probe-source-transaction.mjs')
const b = run('BASELINE', process.execPath, [probe, baseline])
const m = run('MODIFIED', process.execPath, [probe, modified])
const restored = path.join(output, 'rollback-test-copy.tar')
fs.copyFileSync(modified, restored)
run('EXECUTE_ROLLBACK', 'C:/Program Files/Git/bin/bash.exe', [
  rollback.replaceAll('\\', '/'),
  restored.replaceAll('\\', '/')
])
assert.equal(hash(restored), baselineHash)
const r = run('ROLLBACK', process.execPath, [probe, restored])
assert.deepEqual(JSON.parse(r), JSON.parse(b))
const reapply = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-source-reapply-'))
run('reapply extract', 'tar', ['-xf', restored, '-C', reapply])
run('reapply init', 'git', ['init', '--quiet'], reapply)
fs.writeFileSync(path.join(reapply, '.git/info/attributes'), '* -text\n')
run('reapply byte mode', 'git', ['config', 'core.autocrlf', 'false'], reapply)
run('reapply GOAL', 'git', ['apply', '--binary', '--whitespace=nowarn', diff], reapply)
assert.deepEqual(manifest(reapply, afterFiles), after)
run('reapply archive to MODIFIED_FILE', 'tar', [
  '-cf',
  modified,
  '-C',
  reapply,
  '--',
  ...afterFiles
])
assert.deepEqual(
  JSON.parse(run('REAPPLIED_MODIFIED', process.execPath, [probe, modified])),
  JSON.parse(m)
)
assert.deepEqual(manifest(original, beforeFiles), before)
fs.appendFileSync(
  ledger,
  `\nRESTORED_SHA256=${hash(restored)}\nORIGINAL_SOURCE_UNCHANGED=true\nPATCH_RECONSTRUCTS_MODIFIED_BYTES=true\n`
)
for (const role of [modified, diff, rollback])
  fs.appendFileSync(ledger, `ROLE=${role}\nSHA256=${hash(role)}\n`)
run('REOPEN_MODIFIED_FILE', 'tar', ['-tf', modified])
for (const role of [diff, ledger, rollback]) assert.ok(fs.readFileSync(role).length > 0)
console.log(
  JSON.stringify(
    {
      originalUnchanged: true,
      baseline: JSON.parse(b),
      modified: JSON.parse(m),
      rollback: JSON.parse(r),
      roles: [modified, diff, ledger, rollback]
    },
    null,
    2
  )
)
