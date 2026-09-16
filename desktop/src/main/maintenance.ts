import fs from 'node:fs/promises'
import path from 'node:path'

export type CleanupKind = 'cache' | 'logs'
export interface CleanupResult {
  files: number
  bytes: number
  skipped: number
  olderThanDays: number
}
export const OLD_DAYS = 7
// Never traverse game installations, engine binaries, configuration or restore outputs.
const CACHE_DIRECTORIES = [
  'price_patch_cache',
  'poe1_price_patch_cache',
  'dat_files_latest',
  'poe2_price_patch_latest'
]
export async function cleanupOldFiles(
  userData: string,
  logs: string,
  kind: CleanupKind,
  activeLog: string,
  remove: boolean,
  now = Date.now()
): Promise<CleanupResult> {
  const root = path.resolve(userData)
  const result: CleanupResult = { files: 0, bytes: 0, skipped: 0, olderThanDays: OLD_DAYS }
  const cutoff = now - OLD_DAYS * 86400_000
  const roots =
    kind === 'logs'
      ? [path.resolve(logs)]
      : CACHE_DIRECTORIES.map((p) => path.join(root, 'engine/output', p))
  const allowed = (p: string) => p.startsWith(root + path.sep)
  async function safe(p: string) {
    if (!allowed(p)) return false
    for (let at = p; ; at = path.dirname(at)) {
      const stat = await fs.lstat(at)
      if (stat.isSymbolicLink()) return false
      if (at === root) break
    }
    return (await fs.realpath(p)).startsWith((await fs.realpath(root)) + path.sep)
  }
  let visited = 0
  async function visit(directory: string, depth = 0) {
    if (depth > 12 || visited > 100000) {
      result.skipped++
      return
    }
    try {
      if (!(await safe(directory))) {
        result.skipped++
        return
      }
      for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
        if (++visited > 100000) {
          result.skipped++
          return
        }
        const file = path.join(directory, entry.name)
        if (entry.isSymbolicLink()) {
          result.skipped++
          continue
        }
        if (entry.isDirectory()) {
          await visit(file, depth + 1)
          continue
        }
        if (
          !entry.isFile() ||
          path.resolve(file).toLowerCase() === path.resolve(activeLog).toLowerCase()
        )
          continue
        if (kind === 'logs' && !/\.(log|old|txt)(\.\d+)?$/i.test(entry.name)) continue
        try {
          const before = await fs.lstat(file)
          if (before.mtimeMs >= cutoff || before.nlink > 1 || !(await safe(file))) continue
          if (remove) {
            const current = await fs.lstat(file)
            if (
              current.isSymbolicLink() ||
              current.ino !== before.ino ||
              current.mtimeMs !== before.mtimeMs
            ) {
              result.skipped++
              continue
            }
            await fs.unlink(file)
          }
          result.files++
          result.bytes += before.size
        } catch {
          result.skipped++
        }
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') result.skipped++
    }
  }
  for (const directory of roots) await visit(directory)
  return result
}
