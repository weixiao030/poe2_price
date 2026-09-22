export interface UpdateAsset {
  kind: 'delta' | 'full'
  fromVersion?: string
  url: string
  size: number
  sha256: string
}
export interface SoftwareRelease {
  appId: 'com.poepricepatch.desktop'
  version: string
  publishedAt: string
  notes: string[]
  packages: UpdateAsset[]
}
export interface UpdateConfig {
  manifestUrls: string[]
  publicKey: string
  github?: {
    repository: string
    mirrorPrefixes?: string[]
  }
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
  downloadedBytes: number
  totalBytes: number
  message: string
  packageKind?: 'delta' | 'full'
}
export interface UpdateFile {
  path: string
  size: number
  sha256: string
}
export interface UpdatePackage {
  schema: 1
  appId: 'com.poepricepatch.desktop'
  version: string
  fromVersion?: string
  kind: 'delta' | 'full'
  executable: string
  files: UpdateFile[]
  // Exact publisher inventory. Local user files outside it are left alone.
  baseFiles: UpdateFile[]
  targetFiles: UpdateFile[]
}
