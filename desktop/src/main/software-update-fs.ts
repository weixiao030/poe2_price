import fs from 'node:fs'
import { createRequire } from 'node:module'

// Electron's regular fs treats *.asar as virtual directories. Updates must
// hash, extract and replace the actual archive bytes, including in staging.
export const rawFs: typeof fs = process.versions.electron
  ? createRequire(import.meta.url)('original-fs')
  : fs
export const updateFs = rawFs.promises
