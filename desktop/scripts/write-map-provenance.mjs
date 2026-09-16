import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const upstream = path.resolve(process.argv[2])
const commit = execFileSync('git', ['rev-parse', 'HEAD'], {
  cwd: upstream,
  encoding: 'utf8'
}).trim()
assert.equal(commit, '7dde80bf90d38eae5773c82de4797999c1008cf1')
const files = execFileSync('git', ['ls-files', '-z'], { cwd: upstream, encoding: 'utf8' })
  .split('\0')
  .filter(Boolean)
const destinations = []
function walk(dir) {
  for (const item of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
    const file = `${dir}/${item.name}`
    if (item.isDirectory()) walk(file)
    else destinations.push(file)
  }
}
walk('world-map/Upstream')
destinations.push(
  'world-map/licenses/POE2GPS-MIT.txt',
  'desktop/src/renderer/public/world-map/AtlasIconContentMapBoss.png'
)
const sha256 = (buffer) => crypto.createHash('sha256').update(buffer).digest('hex')
const result = destinations.map((destination) => {
  const matching = files.filter((file) => file.endsWith('/' + path.basename(destination)))
  assert.equal(matching.length, 1, destination)
  const original = execFileSync('git', ['show', `${commit}:${matching[0]}`], {
    cwd: upstream,
    maxBuffer: 10 * 1024 * 1024
  })
  const modified = fs.readFileSync(path.join(root, destination))
  return {
    source: matching[0],
    destination,
    upstreamSha256: sha256(original),
    localSha256: sha256(modified),
    byteIdentical: original.equals(modified)
  }
})
fs.writeFileSync(
  path.join(root, 'docs/world-map-provenance.json'),
  JSON.stringify(
    { repository: 'https://github.com/weixiao030/poe_Plugin', commit, files: result },
    null,
    2
  ) + '\n'
)
console.log(`Verified upstream commit and ${result.length} selected source/resource records`)
