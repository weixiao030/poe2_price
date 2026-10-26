import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import { finished } from 'node:stream/promises'
import { EventEmitter } from 'node:events'
import { CancellationToken } from 'builder-util-runtime'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const { DataSplitter } = createRequire(import.meta.url)(
  'electron-updater/out/differentialDownloader/DataSplitter'
)
const { executeTasksUsingMultipleRangeRequests } = createRequire(import.meta.url)(
  'electron-updater/out/differentialDownloader/multipleRangeDownloader'
)

test('postinstall remains byte-for-byte idempotent after all native patches', async () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const files = ['DataSplitter.js', 'multipleRangeDownloader.js'].map((name) =>
    path.join(root, 'node_modules/electron-updater/out/differentialDownloader', name))
  const before = await Promise.all(files.map((file) => fs.readFile(file)))
  for (let run = 0; run < 2; run++) execFileSync(process.execPath,
    [path.join(root, 'scripts/patch-electron-updater.mjs')], { stdio: 'pipe' })
  const after = await Promise.all(files.map((file) => fs.readFile(file)))
  assert.deepEqual(after, before)
})

for (const packetSize of [1, 2, 3, 5, 16, 64, 4096]) {
  test(`multipart download survives ${packetSize}-byte packets, EOF and epilogue`, async (t) => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-multipart-'))
    const old = path.join(dir, 'old.bin')
    await fs.writeFile(old, 'ABCDEFGHI')
    const handle = await fs.open(old, 'r')
    t.after(async () => {
      await handle.close()
      await fs.rm(dir, { recursive: true })
    })
    const data = [Buffer.from('alpha123'), Buffer.from('beta')]
    const tasks = [
      { kind: 0, start: 0, end: 3 },
      { kind: 1, start: 3, end: 11 },
      { kind: 0, start: 3, end: 6 },
      { kind: 1, start: 14, end: 18 },
      { kind: 0, start: 6, end: 9 }
    ]
    const out = new PassThrough()
    const output: Buffer[] = []
    out.on('data', (bytes) => output.push(bytes))
    let completions = 0
    const splitter = new DataSplitter(
      out,
      { tasks, start: 0, end: 5, oldFileFd: handle.fd },
      new Map([
        [0, 1],
        [1, 3]
      ]),
      'boundary',
      data.map((b) => b.length),
      () => completions++,
      12
    )
    const response = Buffer.concat([
      ...data.flatMap((body, i) => [
        Buffer.from(
          `--boundary\r\nContent-Type: application/octet-stream\r\nContent-Range: bytes ${tasks[i * 2 + 1].start}-${tasks[i * 2 + 1].end - 1}/21\r\n\r\n`
        ),
        body,
        Buffer.from('\r\n')
      ]),
      Buffer.from('--boundary--\r\n')
    ])
    const done = finished(splitter, { signal: AbortSignal.timeout(3000) })
    for (let at = 0; at < response.length; at += packetSize)
      await new Promise<void>((resolve, reject) =>
        splitter.write(response.subarray(at, at + packetSize), (error: Error | null) =>
          error ? reject(error) : resolve()
        )
      )
    // A separate epilogue packet must acknowledge its write callback too.
    await new Promise<void>((resolve, reject) =>
      splitter.write(Buffer.from('epilogue'), (error: Error | null) =>
        error ? reject(error) : resolve()
      )
    )
    splitter.end()
    await done
    assert.equal(completions, 1)
    assert.equal(Buffer.concat(output).toString(), 'ABCalpha123DEFbetaGHI')
    out.destroy()
  })
}

test('truncated multipart data fails instead of completing a corrupt installer', async (t) => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-multipart-'))
  const old = path.join(dir, 'old.bin')
  await fs.writeFile(old, 'ABC')
  const handle = await fs.open(old, 'r')
  t.after(async () => {
    await handle.close()
    await fs.rm(dir, { recursive: true })
  })
  const out = new PassThrough()
  out.resume()
  let completed = false
  const splitter = new DataSplitter(
    out,
    { tasks: [{ kind: 1, start: 0, end: 10 }], start: 0, end: 1, oldFileFd: handle.fd },
    new Map([[0, 0]]),
    'boundary',
    [10],
    () => {
      completed = true
    },
    10
  )
  const done = finished(splitter, { signal: AbortSignal.timeout(3000) })
  splitter.end('--boundary\r\nContent-Range: bytes 0-9/10\r\n\r\nshort')
  await assert.rejects(done, /Incomplete multipart/)
  assert.equal(completed, false)
  out.destroy()
})

test('cancellation stays attached after Electron closes the request side of a streaming response', async () => {
  const token = new CancellationToken()
  const response = Object.assign(new PassThrough(), {
    statusCode: 206,
    headers: { 'content-type': 'multipart/byteranges; boundary=boundary' }
  })
  let aborted = false
  const request = Object.assign(new EventEmitter(), {
    abort() {
      aborted = true
      request.emit('abort')
      response.destroy()
    },
    end() {
      request.emit('response', response)
      request.emit('close')
      response.write('--boundary\r\nContent-Range: bytes 0-9/20\r\n\r\nx')
    }
  })
  const out = new PassThrough()
  out.resume()
  const failed = new Promise<Error>((resolve) => {
    const worker = executeTasksUsingMultipleRangeRequests(
      {
        fileMetadataBuffer: null,
        options: { cancellationToken: token },
        createRequestOptions: () => ({ headers: {} }),
        httpExecutor: {
          createRequest(_options: unknown, callback: (...args: unknown[]) => void) {
            request.on('response', callback)
            return request
          },
          addErrorAndTimeoutHandlers() {}
        }
      },
      [
        { kind: 1, start: 0, end: 10 },
        { kind: 1, start: 10, end: 20 }
      ],
      out,
      0,
      resolve
    )
    worker(0)
  })
  token.cancel()
  const error = await failed
  assert.equal(error.message, 'cancelled')
  assert.equal(aborted, true)
  assert.equal(token.listenerCount('cancel'), 0)
  out.destroy()
})
