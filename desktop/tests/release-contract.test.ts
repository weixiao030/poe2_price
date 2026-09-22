import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
test('release metadata agrees and only the price engine is packaged', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'))
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'))
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(root, 'resources/current-release.json'), 'utf8')).version,
    pkg.version
  )
  assert.equal(lock.version, pkg.version)
  assert.equal(lock.packages[''].version, pkg.version)
  assert.deepEqual(
    pkg.build.extraResources.map((entry: { to: string }) => entry.to),
    ['engine', 'icon.png', 'update-config.json', 'current-release.json']
  )
  assert.equal(pkg.scripts.build, 'npm run typecheck && electron-vite build')
  assert.deepEqual(pkg.build.win.target, [{ target: 'nsis', arch: ['x64'] }])
  assert.equal(pkg.build.win.executableName, '物价补丁')
  assert.equal(pkg.build.artifactName, 'POE-Price-Patch-${version}-${arch}-Setup.${ext}')
  assert.equal(pkg.build.portable, undefined)
})
