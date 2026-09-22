import electronUpdater from 'electron-updater'
import { CancellationToken } from 'builder-util-runtime'
import type { CustomPublishOptions, ProgressInfo, UpdateInfo } from 'builder-util-runtime'
import type { AppAdapter } from 'electron-updater/out/AppAdapter'
import type { ProviderRuntimeOptions } from 'electron-updater/out/providers/Provider'
import type { SoftwareRelease } from '../shared/software-update'
import type { InstallerSource } from './software-update-sources'
import type { UpdateDriver } from './software-update'

const { NsisUpdater, Provider } = electronUpdater
interface VerifiedOptions extends CustomPublishOptions {
  release: SoftwareRelease
  source: InstallerSource
}

/** Only transport routing is custom. NSIS owns download, cache, diff and install. */
export class VerifiedReleaseProvider extends Provider<UpdateInfo> {
  private options: VerifiedOptions
  constructor(options: CustomPublishOptions, _updater: unknown, runtime: ProviderRuntimeOptions) {
    super({ ...runtime, isUseMultipleRangeRequest: false })
    this.options = options as VerifiedOptions
    if (!this.options.release || !this.options.source) throw new Error('缺少已验证的更新来源')
  }
  async getLatestVersion() {
    return structuredClone(this.options.release.info)
  }
  resolveFiles() {
    return [{ url: new URL(this.options.source.url), info: this.options.release.info.files[0] }]
  }
  getBlockMapFiles(_url: URL, oldVersion: string) {
    return [
      new URL(this.options.source.oldBlockmapUrl(oldVersion)),
      new URL(this.options.source.url + '.blockmap')
    ]
  }
}

export class NsisUpdateDriver implements UpdateDriver {
  readonly updater: InstanceType<typeof NsisUpdater>
  private installingError?: (error: Error) => void
  constructor(
    logger: NonNullable<InstanceType<typeof NsisUpdater>['logger']>,
    adapter?: AppAdapter
  ) {
    this.updater = new NsisUpdater(undefined, adapter)
    this.updater.logger = logger
    this.updater.autoDownload = false
    this.updater.autoInstallOnAppQuit = false
    this.updater.allowDowngrade = false
    this.updater.allowPrerelease = false
    this.updater.disableWebInstaller = true
    this.updater.on('error', (error) => {
      logger.error(error)
      this.installingError?.(error)
    })
  }
  async download(
    release: SoftwareRelease,
    source: InstallerSource,
    signal: AbortSignal,
    progress: (transferred: number, total: number) => void
  ): Promise<string> {
    signal.throwIfAborted()
    const options: VerifiedOptions = {
      provider: 'custom',
      updateProvider: VerifiedReleaseProvider,
      release,
      source
    }
    this.updater.setFeedURL(options)
    const result = await this.updater.checkForUpdates()
    if (!result || result.updateInfo.version !== release.version)
      throw new Error('更新器未确认目标版本')
    const token = new CancellationToken()
    const cancel = () => token.cancel()
    const onProgress = (event: ProgressInfo) => progress(event.transferred, event.total)
    signal.addEventListener('abort', cancel, { once: true })
    this.updater.on('download-progress', onProgress)
    try {
      signal.throwIfAborted()
      const files = await this.updater.downloadUpdate(token)
      signal.throwIfAborted()
      if (files.length !== 1) throw new Error('更新器未返回完整安装包')
      return files[0]
    } finally {
      signal.removeEventListener('abort', cancel)
      this.updater.removeListener('download-progress', onProgress)
    }
  }
  install(onError: (error: Error) => void) {
    this.installingError = onError
    this.updater.quitAndInstall(true, true)
  }
}
