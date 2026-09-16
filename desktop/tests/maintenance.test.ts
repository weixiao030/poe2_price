import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { cleanupOldFiles } from '../src/main/maintenance'

test('cleanup only deletes old allowlisted cache and logs; restores, active logs, links and recent files survive', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-maintenance-'))
  const external = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-protected-'))
  const logs = path.join(root, 'logs'),
    cache = path.join(root, 'engine/output/price_patch_cache')
  const old = new Date(Date.now() - 10 * 86400_000)
  async function file(relative: string, aged = true) {
    const name = path.join(root, relative)
    await fs.mkdir(path.dirname(name), { recursive: true })
    await fs.writeFile(name, 'fixture')
    if (aged) await fs.utimes(name, old, old)
    return name
  }
  const stale = await file('engine/output/price_patch_cache/old.zip')
  const recent = await file('engine/output/price_patch_cache/recent.zip', false)
  const restore = await file('engine/output/restore/backup.zip')
  const config = await file('desktop-settings.json')
  const active = await file('logs/main.log')
  const oldLog = await file('logs/main.old.log')
  const newLog = await file('logs/recent.log', false)
  const foreign = path.join(external, 'keep.zip')
  await fs.writeFile(foreign, 'protected')
  await fs.utimes(foreign, old, old)
  await fs.symlink(external, path.join(cache, 'linked'), 'junction')
  const dry = await cleanupOldFiles(root, logs, 'cache', active, false)
  assert.equal(dry.files, 1)
  assert.equal(dry.bytes, 7)
  assert.equal(await fs.readFile(stale, 'utf8'), 'fixture')
  const applied = await cleanupOldFiles(root, logs, 'cache', active, true)
  assert.equal(applied.files, 1)
  await assert.rejects(fs.access(stale))
  const cleared = await cleanupOldFiles(root, logs, 'logs', active, true)
  assert.equal(cleared.files, 1)
  await assert.rejects(fs.access(oldLog))
  for (const keep of [recent, restore, config, active, newLog, foreign]) await fs.access(keep)
  assert.equal((await cleanupOldFiles(root, external, 'logs', active, true)).files, 0)
  await fs.unlink(path.join(cache, 'linked'))
  await fs.rm(root, { recursive: true })
  await fs.rm(external, { recursive: true })
})
