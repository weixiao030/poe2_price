import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.dirname(desktop)
const provenance = JSON.parse(await fs.readFile(path.join(root, 'docs/core-provenance.json'), 'utf8'))
for (const record of provenance.files) {
  const source = await fs.readFile(path.join(root, record.path))
  const normalized = /\.(ps1|py|json)$/.test(record.path)
    ? Buffer.from(source.toString('utf8').replace(/^\ufeff/, '').replaceAll('\r\n', '\n')) : source
  assert.equal(crypto.createHash('sha256').update(normalized).digest('hex'), record.normalized_sha256, record.path)
  const bundled = await fs.readFile(path.join(desktop, '.runtime', record.path.replace(/^物价补丁\//, '')))
  assert.deepEqual(bundled, source, `Packaged core differs: ${record.path}`)
}
for (const seed of ['国服还原包.zip', '国际服还原补丁.zip'])
  assert.deepEqual(await fs.readFile(path.join(root, 'restore-seeds', seed)), await fs.readFile(path.join(desktop, '.runtime', seed)))
for (const record of provenance.native_tools) {
  const source = await fs.readFile(path.join(root, record.path))
  const canonical = /\.(cs|csproj|md|json)$/.test(record.path)
    ? Buffer.from(source.toString('utf8').replace(/^\ufeff/, '').replaceAll('\r\n', '\n')) : source
  assert.equal(crypto.createHash('sha256').update(canonical).digest('hex'), record.sha256, record.path)
  if (record.path.startsWith('物价补丁/'))
    assert.deepEqual(await fs.readFile(path.join(desktop, '.runtime', record.path.replace(/^物价补丁\//, ''))), source)
}
for (const obsolete of ['price_patch_gui.ps1', 'auto_update_worker.ps1'])
  await assert.rejects(fs.access(path.join(desktop, '.runtime/tools', obsolete)))
console.log(JSON.stringify({ upstream: provenance.upstream, commit: provenance.commit,
  unchangedCoreFiles: provenance.files.length, unchangedNativeToolsAndSeeds: provenance.native_tools.length, restoreSeeds: 2, obsoleteEntrypoints: 0 }))
