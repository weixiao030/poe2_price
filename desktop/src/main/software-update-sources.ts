import type { UpdateAsset, UpdateConfig, SoftwareRelease } from '../shared/software-update'
import { updateUrl } from './software-update-protocol'

// Keep the order aligned with localize_poe1.ps1. ZOS replaces the direct-GitHub fallback.
export const GITHUB_MIRROR_PREFIXES = [
  'https://ghfast.top/',
  'https://gh-proxy.com/',
  'https://ghproxy.it/',
  'https://gh-proxy.org/',
  'https://ghproxy.net/',
  'https://gh.llkk.cc/',
  'https://ghproxy.imciel.com/',
  'https://ghfile.geekertao.top/'
]
export interface UpdateSource {
  name: string
  url: string
}

function githubSources(config: UpdateConfig, suffix: string, allowLocalhost: boolean): UpdateSource[] {
  if (!config.github) return []
  const { repository, mirrorPrefixes = GITHUB_MIRROR_PREFIXES } = config.github
  if (!/^[A-Za-z0-9_-][A-Za-z0-9_.-]*\/[A-Za-z0-9_-][A-Za-z0-9_.-]*$/.test(repository))
    throw new Error('GitHub 更新仓库配置无效')
  if (!Array.isArray(mirrorPrefixes) || !mirrorPrefixes.length || mirrorPrefixes.length > 12)
    throw new Error('GitHub 国内源配置无效')
  const official = `https://github.com/${repository}/releases/${suffix}`
  return mirrorPrefixes.map((prefix, index) => {
    const url = new URL(updateUrl(prefix, allowLocalhost))
    if (url.search || !url.pathname.endsWith('/')) throw new Error('GitHub 国内源前缀无效')
    return {
      name: `${index === 0 ? '国内主源' : '国内备用源'} ${url.hostname}`,
      url: url.href + official
    }
  })
}

function fallback(url: string, allowLocalhost: boolean): UpdateSource {
  const verified = updateUrl(url, allowLocalhost)
  const host = new URL(verified).hostname
  return { name: host.endsWith('.zos.ctyun.cn') ? 'ZOS 备用源' : host, url: verified }
}

export function manifestSources(config: UpdateConfig, allowLocalhost = false): UpdateSource[] {
  return [
    ...githubSources(config, 'latest/download/latest.json', allowLocalhost),
    ...config.manifestUrls.map((url) => fallback(url, allowLocalhost))
  ]
}

export function packageSources(
  config: UpdateConfig,
  release: SoftwareRelease,
  asset: UpdateAsset,
  allowLocalhost = false
): UpdateSource[] {
  const original = fallback(asset.url, allowLocalhost)
  const name = new URL(original.url).pathname.split('/').pop()!
  if (!name) throw new Error('更新包文件名无效')
  // All transports must deliver the same bytes described by the signed release.
  return [
    ...githubSources(config, `download/v${release.version}/${name}`, allowLocalhost),
    original
  ]
}
