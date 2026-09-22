import type { SoftwareRelease, UpdateConfig } from '../shared/software-update'
import { installerName, MANIFEST_NAME, updateUrl } from './software-update-protocol'

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
export interface InstallerSource extends UpdateSource {
  oldBlockmapUrl(version: string): string
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
  return [
    ...mirrors.map((source, index) => ({
      ...source,
      oldBlockmapUrl: (version: string) =>
        githubSources(
          config,
          `download/v${version}/${installerName(version)}.blockmap`,
          allowLocalhost
        )[index].url
    })),
    ...config.manifestUrls.map((manifest) => {
      const base = new URL('.', updateUrl(manifest, allowLocalhost))
      return {
        name: 'ZOS 备用源',
        url: new URL(release.installer.name, base).href,
        oldBlockmapUrl: (version: string) =>
          new URL(installerName(version) + '.blockmap', base).href
      }
    })
  ]
}
