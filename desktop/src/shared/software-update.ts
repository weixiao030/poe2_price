import type { UpdateInfo } from 'builder-util-runtime'

/** A single immutable NSIS installer works for every supported older release. */
export interface SoftwareRelease {
  version: string
  publishedAt: string
  notes: string[]
  installer: { name: string; size: number; sha512: string }
  info: UpdateInfo
}

export interface UpdateConfig {
  manifestUrls: string[]
  publicKey: string
  github?: { repository: string; mirrorPrefixes?: string[] }
}

export interface SoftwareUpdateState {
  status:
    | 'unconfigured'
    | 'idle'
    | 'checking'
    | 'available'
    | 'current'
    | 'downloading'
    | 'ready'
    | 'installing'
    | 'error'
  currentVersion: string
  currentNotes: string[]
  release?: SoftwareRelease
  checkedAt?: string
  startupNotificationVersion?: string
  downloadedBytes: number
  totalBytes: number
  message: string
}
