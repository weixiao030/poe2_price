import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const directory = process.argv[2]
if (!directory) throw new Error('Pass the authorized POE2 international directory')
const child = spawn(path.join(root, '.world-map/PoeWorldMap.exe'), ['--directory', directory], {
  windowsHide: true,
  env: { ...process.env, DOTNET_ROOT_X64: path.join(root, '.runtime/tools/dotnet-runtime') }
})
let output = '',
  stderr = '',
  pending
child.stdout.setEncoding('utf8')
child.stderr.setEncoding('utf8')
child.stdout.on('data', (chunk) => {
  output += chunk
  let at
  while ((at = output.indexOf('\n')) >= 0) {
    const line = output.slice(0, at)
    output = output.slice(at + 1)
    const value = JSON.parse(line)
    if (pending && value.id === pending.id) {
      const p = pending
      pending = null
      value.error ? p.reject(Error(value.error)) : p.resolve(value.result)
    }
  }
})
child.stderr.on('data', (value) => {
  stderr += value
})
child.on('error', (error) => pending?.reject(error))
child.on('exit', (code) => pending?.reject(Error(`worker exited ${code}: ${stderr}`)))
let sequence = 0
const request = (action, extra = {}) =>
  new Promise((resolve, reject) => {
    const id = String(++sequence)
    pending = { id, resolve, reject }
    child.stdin.write(JSON.stringify({ id, action, ...extra }) + '\n')
  })
const timeout = setTimeout(() => {
  pending?.reject(Error('Live probe timed out'))
  child.kill()
}, 90_000)
const evidence = { directory, frames: [], stderr: '', route: null }
try {
  let snapshot
  for (let i = 0; i < 4; i++) {
    snapshot = await request('read')
    evidence.frames.push({
      available: snapshot.available,
      reason: snapshot.reason,
      nodes: snapshot.nodes.length,
      edges: snapshot.edges.length,
      unknownNames: snapshot.unknownNameCount,
      current: snapshot.currentNode,
      readMs: snapshot.readMilliseconds
    })
    console.log(JSON.stringify(evidence.frames.at(-1)))
    if (snapshot.available) {
      assert.ok(snapshot.nodes.length > 0)
      assert.equal(new Set(snapshot.nodes.map((n) => n.id)).size, snapshot.nodes.length)
      if (snapshot.currentNode)
        assert.ok(
          snapshot.nodes.some((n) => n.id === `${snapshot.currentNode.x},${snapshot.currentNode.y}`)
        )
    }
    await new Promise((resolve) => setTimeout(resolve, 1200))
  }
  assert.ok(snapshot.available, `Live atlas unavailable: ${snapshot.reason}`)
  const target = snapshot.nodes.find((n) => !n.canOpen && n.state !== 0) || snapshot.nodes[0]
  evidence.route = await request('route', { mode: 'accessible', target: target.grid })
  const matches = await request('search', { query: String(target.number) })
  assert.ok(matches.includes(target.id))
  console.log(JSON.stringify({ route: evidence.route, searchMatches: matches.length }))
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, 'test-results/world-map-live-snapshot.json'),
    JSON.stringify(snapshot)
  )
} finally {
  evidence.stderr = stderr
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, 'test-results/world-map-live.json'),
    JSON.stringify(evidence, null, 2)
  )
  clearTimeout(timeout)
  child.stdin.end()
  child.kill()
}
