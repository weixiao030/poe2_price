import fs from 'node:fs/promises'
import path from 'node:path'
import type { SoftwareRelease, SoftwareUpdateState, UpdateConfig } from '../shared/software-update'
import {
  MANIFEST_LIMIT,
  newerVersion,
  updateUrl,
  verifyInstaller,
  verifyRelease
} from './software-update-protocol'
import { installerSources, manifestSources } from './software-update-sources'
import type { InstallerSource } from './software-update-sources'

export interface UpdateDriver {
  download(
    release: SoftwareRelease,
    source: InstallerSource,
    signal: AbortSignal,
    progress: (transferred: number, total: number) => void
  ): Promise<string>
  install(onError: (error: Error) => void): void
}
export interface UpdateOptions {
  version: string
  notes: string[]
  config: UpdateConfig
  stateRoot: string
  packaged: boolean
  driver: UpdateDriver
  canInstall: () => boolean
  changed: (state: SoftwareUpdateState) => void
  allowLocalhost?: boolean
  manifestTimeoutMs?: number
  sourceIdleTimeoutMs?: number
  sourceTimeoutMs?: number
}

export class SoftwareUpdater {
  private state: SoftwareUpdateState
  private abort?: AbortController
  private downloaded?: string
  private startupCheckStarted = false
  private readonly receiptPath: string
  constructor(private options: UpdateOptions) {
    const configured =
      (options.config.manifestUrls.length > 0 || !!options.config.github) &&
      !!options.config.publicKey
    this.receiptPath = path.join(options.stateRoot, 'installer-result.json')
    this.state = {
      status: configured ? 'idle' : 'unconfigured',
      currentVersion: options.version,
      currentNotes: options.notes,
      downloadedBytes: 0,
      totalBytes: 0,
      message: configured ? '检查是否有新的软件版本' : '更新服务准备中，当前版本可正常使用。'
    }
  }
  get snapshot() {
    return structuredClone(this.state)
  }
  get installing() {
    return this.state.status === 'installing'
  }
  private set(patch: Partial<SoftwareUpdateState>) {
    Object.assign(this.state, patch)
    this.options.changed(this.snapshot)
  }
  private fail(error: unknown) {
    this.set({ status: 'error', message: error instanceof Error ? error.message : String(error) })
  }
  async checkAtStartup() {
    if (this.startupCheckStarted) return
    this.startupCheckStarted = true
    let ignoredVersion: unknown
    try {
      ignoredVersion = JSON.parse(
        await fs.readFile(path.join(this.options.stateRoot, 'notice.json'), 'utf8')
      ).ignoredVersion
    } catch {
      /* Missing or damaged preferences must not prevent checking. */
    }
    const result = await this.check()
    if (result.status === 'available' && result.release?.version !== ignoredVersion)
      this.set({ startupNotificationVersion: result.release!.version })
  }
  async dismissNotice(version: string, ignore: boolean) {
    if (version !== this.state.startupNotificationVersion) return
    if (ignore) {
      await fs.mkdir(this.options.stateRoot, { recursive: true })
      const destination = path.join(this.options.stateRoot, 'notice.json')
      await fs.writeFile(destination + '.new', JSON.stringify({ ignoredVersion: version }), 'utf8')
      await fs.rename(destination + '.new', destination)
    }
    this.set({ startupNotificationVersion: undefined })
  }
  private async fetchBytes(url: string, limit: number, signal: AbortSignal): Promise<Buffer> {
    for (let redirect = 0; redirect <= 4; redirect++) {
      const response = await fetch(updateUrl(url, this.options.allowLocalhost), {
        redirect: 'manual',
        signal,
        headers: {
          'Cache-Control': 'no-cache',
          'User-Agent': 'POE-Price-Patch/' + this.options.version
        }
      })
      if (response.status >= 300 && response.status < 400) {
        await response.body?.cancel()
        const next = response.headers.get('location')
        if (!next) throw new Error('更新服务器重定向无效')
        url = new URL(next, url).href
        continue
      }
      if (!response.ok || !response.body) {
        await response.body?.cancel()
        throw new Error(`更新服务器返回 ${response.status}`)
      }
      const chunks: Uint8Array[] = []
      let size = 0
      for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
        size += chunk.length
        if (size > limit) throw new Error('更新说明超过大小限制')
        chunks.push(chunk)
      }
      return Buffer.concat(chunks)
    }
    throw new Error('更新服务器重定向过多')
  }
  async check(): Promise<SoftwareUpdateState> {
    if (
      ['unconfigured', 'checking', 'downloading', 'ready', 'installing'].includes(this.state.status)
    )
      return this.snapshot
    this.downloaded = undefined
    this.set({
      status: 'checking',
      release: undefined,
      downloadedBytes: 0,
      totalBytes: 0,
      message: '正在检查新版本…'
    })
    let lastError: unknown = new Error('更新源不可用')
    let hasOlderRelease = false
    try {
      for (const source of manifestSources(this.options.config, this.options.allowLocalhost)) {
        this.set({ message: `正在通过${source.name}检查新版本…` })
        const controller = new AbortController()
        const timeout = setTimeout(
          () => controller.abort(new Error('检查更新超时')),
          this.options.manifestTimeoutMs ?? 20_000
        )
        try {
          const [manifest, signature] = await Promise.all([
            this.fetchBytes(source.url, MANIFEST_LIMIT, controller.signal),
            this.fetchBytes(source.url + '.sig', 1024, controller.signal)
          ])
          const release = verifyRelease(
            manifest,
            signature.toString('utf8'),
            this.options.config.publicKey
          )
          // A lagging mirror must not offer a downgrade or hide a newer fallback.
          if (newerVersion(this.options.version, release.version)) {
            hasOlderRelease = true
            continue
          }
          const available = newerVersion(release.version, this.options.version)
          this.set({
            status: available ? 'available' : 'current',
            release,
            checkedAt: new Date().toISOString(),
            totalBytes: available ? release.installer.size : 0,
            message: available ? `发现新版本 v${release.version}` : '当前已是最新版本'
          })
          return this.snapshot
        } catch (error) {
          lastError = new Error(
            `${source.name}：${error instanceof Error ? error.message : String(error)}`
          )
        } finally {
          clearTimeout(timeout)
          controller.abort()
        }
      }
      if (hasOlderRelease)
        this.set({
          status: 'current',
          checkedAt: new Date().toISOString(),
          message: '当前版本高于更新源中的版本，无需降级。'
        })
      else this.fail(lastError)
    } catch (error) {
      this.fail(error)
    }
    return this.snapshot
  }
  cancel() {
    if (this.state.status === 'downloading') this.abort?.abort(new Error('用户取消下载'))
  }
  async download(): Promise<SoftwareUpdateState> {
    if (this.state.status !== 'available' || !this.state.release)
      throw new Error('请先检查可用的软件更新')
    const release = structuredClone(this.state.release)
    const controller = new AbortController()
    this.abort = controller
    this.set({
      status: 'downloading',
      downloadedBytes: 0,
      totalBytes: release.installer.size,
      message: '正在下载安装包…'
    })
    try {
      let lastError: unknown = new Error('所有更新下载源均不可用')
      for (const source of installerSources(
        this.options.config,
        release,
        this.options.allowLocalhost
      )) {
        controller.signal.throwIfAborted()
        this.set({
          downloadedBytes: 0,
          totalBytes: release.installer.size,
          message: `正在通过${source.name}下载更新…`
        })
        const attempt = new AbortController()
        const signal = AbortSignal.any([controller.signal, attempt.signal])
        const deadline = setTimeout(
          () => attempt.abort(new Error('当前下载源超时')),
          this.options.sourceTimeoutMs ?? 30 * 60_000
        )
        let idle: ReturnType<typeof setTimeout>
        const touch = () => {
          clearTimeout(idle)
          idle = setTimeout(
            () => attempt.abort(new Error('当前下载源长时间无响应')),
            this.options.sourceIdleTimeoutMs ?? 60_000
          )
        }
        touch()
        try {
          const file = await this.options.driver.download(
            release,
            source,
            signal,
            (transferred, total) => {
              if (signal.aborted) return
              touch()
              this.set({ downloadedBytes: transferred, totalBytes: total })
            }
          )
          signal.throwIfAborted()
          try {
            await verifyInstaller(file, release)
          } catch (error) {
            await fs.unlink(file).catch(() => {})
            throw error
          }
          signal.throwIfAborted()
          this.downloaded = file
          this.set({
            status: 'ready',
            downloadedBytes: release.installer.size,
            totalBytes: release.installer.size,
            message: '安装包已就绪，重启后完成软件更新。'
          })
          return this.snapshot
        } catch (error) {
          controller.signal.throwIfAborted()
          lastError = new Error(
            `${source.name}：${attempt.signal.reason?.message || (error instanceof Error ? error.message : String(error))}`
          )
        } finally {
          clearTimeout(deadline)
          clearTimeout(idle!)
          attempt.abort()
        }
      }
      throw lastError
    } catch (error) {
      if (controller.signal.aborted)
        this.set({
          status: 'available',
          downloadedBytes: 0,
          totalBytes: release.installer.size,
          message: '下载已取消，可以重新开始。'
        })
      else this.fail(error)
    } finally {
      this.abort = undefined
    }
    return this.snapshot
  }
  private async receipt(value: Record<string, unknown>) {
    await fs.mkdir(this.options.stateRoot, { recursive: true })
    const temp = this.receiptPath + '.new'
    await fs.writeFile(temp, JSON.stringify(value), 'utf8')
    await fs.rename(temp, this.receiptPath)
  }
  async install(): Promise<SoftwareUpdateState> {
    if (this.state.status !== 'ready' || !this.downloaded || !this.state.release)
      throw new Error('安装包尚未准备完成')
    if (!this.options.packaged) throw new Error('开发模式不安装软件更新，请使用安装版验证')
    if (!this.options.canInstall()) throw new Error('请等待物价补丁和后台查询完成后再安装')
    // Acquire the application-wide task guard before any await.
    this.set({ status: 'installing', message: '正在准备重启并安装…' })
    try {
      await verifyInstaller(this.downloaded, this.state.release)
      if (!this.options.canInstall()) throw new Error('请等待后台任务结束后安装')
      await this.receipt({
        status: 'installing',
        from: this.options.version,
        version: this.state.release.version,
        at: new Date().toISOString()
      })
      this.options.driver.install((error) => {
        if (this.installing) this.fail(error)
      })
    } catch (error) {
      // electron-updater reuses a same-process cache by existence; remove a
      // failed cache so a retry downloads and verifies the installer again.
      if (this.downloaded) await fs.unlink(this.downloaded).catch(() => {})
      this.downloaded = undefined
      this.fail(error)
    }
    return this.snapshot
  }
  async previousResult() {
    try {
      const result = JSON.parse(await fs.readFile(this.receiptPath, 'utf8'))
      if (result.status === 'installing' && result.version !== this.options.version)
        this.set({
          message: '上次安装未完成，可重新检查更新或使用完整安装包修复。',
          status: 'error'
        })
    } catch {
      /* No previous installation receipt. */
    }
  }
  async uiReady() {
    try {
      const result = JSON.parse(await fs.readFile(this.receiptPath, 'utf8'))
      if (result.status === 'installing' && result.version === this.options.version)
        await this.receipt({
          ...result,
          status: 'completed',
          completedAt: new Date().toISOString()
        })
    } catch {
      /* A receipt is diagnostic, never a prerequisite for normal startup. */
    }
  }
}
