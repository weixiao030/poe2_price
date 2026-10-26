/** Read-only live audit. No downloaded executable is ever run. */
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gunzipSync } from 'node:zlib'
import {
  manifestSources,
  installerSources,
  GITHUB_MIRROR_PREFIXES
} from '../src/main/software-update-sources'
import { verifyRelease, newerVersion } from '../src/main/software-update-protocol'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const outputIndex = process.argv.indexOf('--output')
const output =
  outputIndex < 0
    ? path.join(root, 'test-results/download-source-audit.json')
    : path.resolve(process.argv[outputIndex + 1])
const full = process.argv.includes('--full')
const config = JSON.parse(
  await fs.readFile(path.join(root, 'resources/update-config.json'), 'utf8')
)
const report: any = {
  checkedAt: new Date().toISOString(),
  readOnly: true,
  full,
  manifests: [],
  installers: [],
  localization: [],
  runtimes: []
}

async function request(url: string, limit: number, range?: string, timeout = 20000) {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(timeout),
    headers: {
      'User-Agent': 'poe-price-patch-source-audit',
      'Accept-Encoding': 'identity',
      ...(range ? { Range: range } : {})
    }
  })
  const reader = response.body!.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.length
      if (size > limit) throw new Error(`响应超过 ${limit} 字节（Range 可能未生效）`)
      chunks.push(value)
    }
  } finally {
    await reader.cancel().catch(() => {})
  }
  return { response, bytes: Buffer.concat(chunks) }
}

async function check(rows: any[], name: string, url: string, fn: () => Promise<object>) {
  const started = Date.now()
  const row: any = { name, url }
  try {
    Object.assign(row, await fn(), { ok: true })
  } catch (error) {
    Object.assign(row, {
      ok: false,
      error: String(error),
      cause: String((error as Error)?.cause || '')
    })
  }
  row.durationMs = Date.now() - started
  rows.push(row)
  console.log(JSON.stringify(row))
  await fs.mkdir(path.dirname(output), { recursive: true })
  await fs.writeFile(output, JSON.stringify(report, null, 2) + '\n')
  return row
}

async function parallel<T>(items: T[], fn: (item: T) => Promise<unknown>) {
  let next = 0
  await Promise.all(
    Array.from({ length: Math.min(3, items.length) }, async () => {
      while (next < items.length) await fn(items[next++])
    })
  )
}

let selected: ReturnType<typeof verifyRelease> | undefined
await parallel(manifestSources(config), async (source) => {
  await check(report.manifests, source.name, source.url, async () => {
    const { bytes } = await request(source.url, 128 * 1024)
    const signature = await request(source.url + '.sig', 1024)
    const release = verifyRelease(bytes, signature.bytes.toString('utf8'), config.publicKey)
    if (!selected || newerVersion(release.version, selected.version)) selected = release
    return {
      version: release.version,
      manifestSha256: crypto.createHash('sha256').update(bytes).digest('hex')
    }
  })
})

if (selected) {
  const release = selected
  report.release = release
  await parallel(installerSources(config, release), async (source) => {
    await check(report.installers, source.name, source.url, async () => {
      const head = await request(source.url, 4096, 'bytes=0-1023')
      assert.equal(head.response.status, 206)
      assert.equal(
        head.response.headers.get('content-range'),
        `bytes 0-1023/${release.installer.size}`
      )
      assert.equal(head.bytes.length, 1024)
      assert.equal(head.bytes.subarray(0, 2).toString(), 'MZ')
      const blockmap = await request(source.url + '.blockmap', 4 * 1024 * 1024)
      const decoded = JSON.parse(
        gunzipSync(blockmap.bytes, { maxOutputLength: 16 * 1024 * 1024 }).toString()
      )
      assert.ok(decoded.files?.length)
      let multiRange: boolean | string = false
      if (source.useMultipleRangeRequest) {
        try {
          const multi = await request(source.url, 8192, 'bytes=0-15,32-47')
          assert.equal(multi.response.status, 206)
          assert.match(multi.response.headers.get('content-type') || '', /^multipart\/byteranges;/i)
          const body = multi.bytes.toString('latin1')
          for (const [start, end] of [
            [0, 15],
            [32, 47]
          ]) {
            const marker = new RegExp(
              `Content-Range: bytes ${start}-${end}/${release.installer.size}\\r\\n(?:[^\\r]+\\r\\n)*\\r\\n`,
              'i'
            ).exec(body)
            assert.ok(marker, `缺少 Range ${start}-${end}`)
            assert.ok(
              multi.bytes
                .subarray(marker.index + marker[0].length, marker.index + marker[0].length + 16)
                .equals(head.bytes.subarray(start, end + 1))
            )
          }
          multiRange = true
        } catch (error) {
          multiRange = String(error)
        }
      }
      return { size: release.installer.size, blockmapFiles: decoded.files.length, multiRange }
    })
  })
  if (full) {
    const source = installerSources(config, release).at(-1)!
    report.fullInstaller = await check([], source.name, source.url, async () => {
      const { bytes } = await request(source.url, release.installer.size, undefined, 180000)
      assert.equal(bytes.length, release.installer.size)
      assert.equal(
        crypto.createHash('sha512').update(bytes).digest('base64'),
        release.installer.sha512
      )
      return { size: bytes.length, sha512Verified: true }
    })
  }
}

try {
  const api = 'https://api.github.com/repos/aianlinb/LibGGPK3/releases/latest'
  const { bytes } = await request(api, 4 * 1024 * 1024)
  const metadata = JSON.parse(bytes.toString('utf8'))
  const asset = metadata.assets.find((item: any) => item.name === 'PoeChinese3_win-x64.exe')
  assert.ok(asset && /^sha256:[a-f0-9]{64}$/.test(asset.digest))
  report.localizationRelease = {
    tag: metadata.tag_name,
    url: asset.browser_download_url,
    size: asset.size,
    digest: asset.digest
  }
  await parallel([...GITHUB_MIRROR_PREFIXES, ''], async (prefix) => {
    const url = prefix + asset.browser_download_url
    await check(report.localization, prefix || 'GitHub 官方源', url, async () => {
      const { bytes, response } = await request(
        url,
        full ? asset.size : 4096,
        full ? undefined : 'bytes=0-1023',
        full ? 60000 : 20000
      )
      assert.equal(bytes.subarray(0, 2).toString(), 'MZ')
      if (full) {
        assert.equal(bytes.length, asset.size)
        assert.equal(
          'sha256:' + crypto.createHash('sha256').update(bytes).digest('hex'),
          asset.digest
        )
      } else {
        assert.equal(response.status, 206)
        assert.equal(response.headers.get('content-range'), `bytes 0-1023/${asset.size}`)
      }
      return { size: asset.size, sha256Verified: full }
    })
  })
} catch (error) {
  report.localizationError = String(error)
}

// Discover the build-time runtime URLs and hashes from their actual source.
const runtimeScript = await fs.readFile(path.resolve(root, '../build/prepare_runtime.ps1'), 'utf8')
const archives = [
  ...runtimeScript.matchAll(
    /\$(Python|Dotnet)Name = '([^']+)'\s+Install-Archive \$\1Name '([a-f0-9]{64})' @\(([\s\S]*?)\)/g
  )
]
assert.equal(archives.length, 2, '无法识别固定的 Python/.NET 下载配置')
await parallel(
  archives.flatMap((match) =>
    [...match[4].matchAll(/"(https:[^"]+)"/g)].map((url) => ({
      url: url[1].replace(`$${match[1]}Name`, match[2]),
      name: match[2],
      sha256: match[3]
    }))
  ),
  async (archive) => {
    await check(report.runtimes, archive.name, archive.url, async () => {
      const { bytes, response } = await request(
        archive.url,
        full ? 128 * 1024 * 1024 : 4096,
        full ? undefined : 'bytes=0-1023',
        full ? 90000 : 20000
      )
      assert.equal(bytes.subarray(0, 2).toString(), 'PK')
      if (full)
        assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), archive.sha256)
      else assert.equal(response.status, 206)
      return { size: full ? bytes.length : null, sha256Verified: full }
    })
  }
)

const versions = new Map<string, string>()
report.manifestAgreement = report.manifests
  .filter((row: any) => row.ok)
  .every((row: any) => {
    const previous = versions.get(row.version)
    versions.set(row.version, row.manifestSha256)
    return !previous || previous === row.manifestSha256
  })
await fs.writeFile(output, JSON.stringify(report, null, 2) + '\n')
console.log(`报告：${output}`)
if (
  !selected ||
  !report.manifestAgreement ||
  !report.installers.some((row: any) => row.ok) ||
  !report.localization.some((row: any) => row.ok) ||
  (full && !report.fullInstaller?.ok) ||
  archives.some((match) => !report.runtimes.some((row: any) => row.name === match[2] && row.ok))
)
  process.exitCode = 1
