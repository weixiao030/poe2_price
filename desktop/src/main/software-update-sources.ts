import type { SoftwareRelease, UpdateConfig } from '../shared/software-update'
import { installerName, MANIFEST_NAME, updateUrl } from './software-update-protocol'

export const GITHUB_MIRROR_PREFIXES = [
  'https://ghfast.top/',
  'https://gh-proxy.com/',
  'https://ghproxy.it/',
  'https://gh-proxy.org/',
  'https://ghproxy.net/'
]
// These relays return a valid multipart/byteranges response. The remaining
// relays and ZOS are intentionally kept on the compatibility path because
// they either reject multipart ranges or silently return the full file.
const MULTI_RANGE_MIRRORS = new Set(['gh-proxy.com', 'gh-proxy.org'])
export interface UpdateSource {
  name: string
  url: string
}
export interface InstallerSource extends UpdateSource {
  kind: 'mirror' | 'direct'
  oldBlockmapUrl(version: string): string
  useMultipleRangeRequest: boolean
}

function githubSources(
  config: UpdateConfig,
  suffix: string,
  allowLocalhost: boolean
): UpdateSource[] {
  if (!config.github) return []
  const { repository, mirrorPrefixes = GITHUB_MIRROR_PREFIXES } = config.github
  if (!/^[A-Za-z0-9_-][A-Za-z0-9_.-]*\/[A-Za-z0-9_-][A-Za-z0-9_.-]*$/.test(repository))
    throw new Error('GitHub 更新仓库配置无效')
  if (!Array.isArray(mirrorPrefixes) || !mirrorPrefixes.length || mirrorPrefixes.length > 12)
    throw new Error('GitHub 国内源配置无效')
  return mirrorPrefixes.map((prefix, index) => {
    const url = new URL(updateUrl(prefix, allowLocalhost))
    if (url.search || !url.pathname.endsWith('/')) throw new Error('GitHub 国内源前缀无效')
    return {
      name: `${index ? '国内备用源' : '国内主源'} ${url.hostname}`,
      url: url.href + `https://github.com/${repository}/releases/${suffix}`
    }
  })
}

export function manifestSources(config: UpdateConfig, allowLocalhost = false): UpdateSource[] {
  return [
    ...githubSources(config, `latest/download/${MANIFEST_NAME}`, allowLocalhost),
    ...config.manifestUrls.map((url) => ({
      name: 'ZOS 备用源',
      url: updateUrl(url, allowLocalhost)
    }))
  ]
}

export function installerSources(
  config: UpdateConfig,
  release: SoftwareRelease,
  allowLocalhost = false
): InstallerSource[] {
  const suffix = `download/v${release.version}/${release.installer.name}`
  const mirrors = githubSources(config, suffix, allowLocalhost)
  const installerMirrors = mirrors.map((source, index) => ({
    ...source,
    kind: 'mirror' as const,
    oldBlockmapUrl: (version: string) =>
      githubSources(
        config,
        `download/v${version}/${installerName(version)}.blockmap`,
        allowLocalhost
      )[index].url,
    useMultipleRangeRequest: MULTI_RANGE_MIRRORS.has(new URL(source.url).hostname.toLowerCase())
  }))
  // Prefer relays that can carry the differential ranges in two requests;
  // unsupported relays remain available as safe fallbacks.
  installerMirrors.sort(
    (a, b) => Number(b.useMultipleRangeRequest) - Number(a.useMultipleRangeRequest)
  )
  return [
    ...installerMirrors,
    ...config.manifestUrls.map((manifest) => {
      const base = new URL('.', updateUrl(manifest, allowLocalhost))
      return {
        name: 'ZOS 备用源',
        kind: 'direct' as const,
        url: new URL(release.installer.name, base).href,
        oldBlockmapUrl: (version: string) =>
          new URL(installerName(version) + '.blockmap', base).href,
        useMultipleRangeRequest: false
      }
    })
  ]
}

export type DownloadMode = 'differential' | 'full'
export class DifferentialUnavailableError extends Error {}

/** Try efficient differential relays before a full download from the direct store. */
export function installerAttempts(sources: InstallerSource[]) {
  const multipart = sources.filter((source) => source.useMultipleRangeRequest)
  const differential = multipart.length ? multipart : sources.filter((s) => s.kind === 'mirror')
  const full = [...sources].sort(
    (a, b) => Number(b.kind === 'direct') - Number(a.kind === 'direct')
  )
  return [
    ...differential.map((source) => ({ source, mode: 'differential' as DownloadMode })),
    ...full.map((source) => ({ source, mode: 'full' as DownloadMode }))
  ]
}
