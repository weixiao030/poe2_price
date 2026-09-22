import { updateFs as fs } from './software-update-fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawn } from 'node:child_process'
import type {
  SoftwareUpdateState,
  UpdateConfig,
  UpdatePackage,
  UpdateFile
} from '../shared/software-update'
import {
  hashFile,
  newerVersion,
  safeFile,
  selectAsset,
  unpackUpdate,
  updateUrl,
  verifyInventory,
  verifyRelease
} from './software-update-protocol'

export interface UpdateOptions {
  version: string
  notes: string[]
  config: UpdateConfig
  appRoot: string
  transactionRoot: string
  helperSource: string
  packaged: boolean
  canInstall: () => boolean
  changed: (state: SoftwareUpdateState) => void
  quit: () => void
  allowLocalhost?: boolean
}
export class SoftwareUpdater {
  private state: SoftwareUpdateState
  private abort?: AbortController
  private staged?: { dir: string; manifest: UpdatePackage }
  constructor(private options: UpdateOptions) {
    const configured = options.config.manifestUrls.length > 0 && !!options.config.publicKey
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
  private async response(url: string, signal: AbortSignal): Promise<Response> {
    for (let redirect = 0; redirect <= 4; redirect++) {
      url = updateUrl(url, this.options.allowLocalhost)
      const response = await fetch(url, {
        redirect: 'manual',
        signal,
        headers: {
          'Cache-Control': 'no-cache',
          'User-Agent': 'POE-Price-Patch/' + this.options.version
        }
      })
      if (response.status >= 300 && response.status < 400) {
        const next = response.headers.get('location')
        await response.body?.cancel()
        if (!next) throw new Error('更新服务器重定向无效')
        url = new URL(next, url).href
      } else {
        if (!response.ok || !response.body) {
          await response.body?.cancel()
          throw new Error(`更新服务器返回 ${response.status}`)
        }
        return response
      }
    }
    throw new Error('更新服务器重定向过多')
  }
  async check(): Promise<SoftwareUpdateState> {
    if (['checking', 'downloading', 'installing', 'ready'].includes(this.state.status))
      return this.snapshot
    if (!this.options.config.manifestUrls.length || !this.options.config.publicKey)
      return this.snapshot
    this.set({ status: 'checking', message: '正在检查新版本…', release: undefined })
    let lastError: unknown
    for (const url of this.options.config.manifestUrls) {
      try {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 20_000)
        let release
        try {
          const response = await this.response(url, controller.signal)
          const chunks: Uint8Array[] = []
          let length = 0
          for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
            length += chunk.length
            if (length > 1_100_000) {
              controller.abort()
              throw new Error('更新说明大小超限')
            }
            chunks.push(chunk)
          }
          release = verifyRelease(
            JSON.parse(Buffer.concat(chunks).toString('utf8')),
            this.options.config.publicKey,
            this.options.allowLocalhost
          )
        } finally {
          clearTimeout(timeout)
        }
        const available = newerVersion(release.version, this.options.version)
        const asset = available ? selectAsset(release, this.options.version) : undefined
        this.set({
          status: available ? 'available' : 'current',
          release,
          checkedAt: new Date().toISOString(),
          packageKind: asset?.kind,
          totalBytes: asset?.size || 0,
          downloadedBytes: 0,
          message: available ? `发现新版本 v${release.version}` : '当前已是最新版本'
        })
        return this.snapshot
      } catch (error) {
        lastError = error
      }
    }
    this.fail(lastError)
    return this.snapshot
  }
  cancel() {
    if (this.state.status === 'downloading') this.abort?.abort()
  }
  async download(): Promise<SoftwareUpdateState> {
    if (this.state.status !== 'available' || !this.state.release)
      throw new Error('请先检查可用的软件更新')
    const release = this.state.release
    const asset = selectAsset(release, this.options.version)
    this.abort = new AbortController()
    const token = crypto.randomUUID()
    const dir = path.join(this.options.transactionRoot, token)
    const archive = path.join(dir, 'update.zip')
    this.set({
      status: 'downloading',
      downloadedBytes: 0,
      totalBytes: asset.size,
      message: '正在下载更新包…'
    })
    const timeout = setTimeout(
      () => this.abort?.abort(new Error('下载更新包超时，请重试')),
      15 * 60_000
    )
    try {
      await fs.mkdir(dir, { recursive: true })
      const response = await this.response(asset.url, this.abort.signal)
      const output = await fs.open(archive, 'wx')
      const hash = crypto.createHash('sha256')
      let size = 0
      let lastSent = 0
      try {
        for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
          size += chunk.length
          if (size > asset.size) throw new Error('更新包大小超过发布清单')
          hash.update(chunk)
          await output.writeFile(chunk)
          if (Date.now() - lastSent > 100) {
            this.set({ downloadedBytes: size })
            lastSent = Date.now()
          }
        }
      } finally {
        await output.close()
      }
      if (size !== asset.size || hash.digest('hex') !== asset.sha256)
        throw new Error('更新包校验失败，请重新下载')
      if (this.abort.signal.aborted) throw new Error('下载已取消')
      this.set({ downloadedBytes: size, message: '正在校验更新文件…' })
      const manifest = await unpackUpdate(archive, path.join(dir, 'files'), asset, release)
      if (this.abort.signal.aborted) throw new Error('下载已取消')
      if (asset.kind === 'delta') await verifyInventory(this.options.appRoot, manifest.baseFiles)
      this.staged = { dir, manifest }
      this.set({ status: 'ready', message: '更新包已就绪，安装时软件将自动重启。' })
    } catch (error) {
      // Keep bounded evidence for diagnosis; no application file has been changed.
      await fs.rm(archive, { force: true }).catch(() => {})
      if (this.abort.signal.aborted && !this.abort.signal.reason?.message?.includes('超时'))
        this.set({ status: 'available', downloadedBytes: 0, message: '下载已取消，可以重新开始。' })
      else this.fail(error)
    } finally {
      clearTimeout(timeout)
      this.abort = undefined
    }
    return this.snapshot
  }
  async install(): Promise<SoftwareUpdateState> {
    if (this.state.status !== 'ready' || !this.staged) throw new Error('更新包尚未准备完成')
    if (!this.options.packaged) throw new Error('开发模式不替换程序文件，请使用发行版验证安装')
    if (!this.options.canInstall()) throw new Error('请等待物价补丁和后台查询完成后再安装')
    this.set({ status: 'installing', message: '正在准备重启并安装…' })
    const { dir, manifest } = this.staged
    try {
      if (manifest.kind === 'delta') await verifyInventory(this.options.appRoot, manifest.baseFiles)
      await verifyInventory(path.join(dir, 'files'), manifest.files)
      const probe = path.join(this.options.appRoot, '.poe-update-write-' + crypto.randomUUID())
      await fs.writeFile(probe, '', { flag: 'wx' })
      await fs.unlink(probe)
      const target = new Set(manifest.targetFiles.map((file) => file.path))
      const removeFiles = manifest.baseFiles.filter((file) => !target.has(file.path))
      const beforeFiles: (UpdateFile & { exists: boolean })[] = []
      for (const file of [...manifest.files, ...removeFiles]) {
        const current = await safeFile(this.options.appRoot, file.path)
        const stat = await fs.stat(current).catch((e) => {
          if (e.code === 'ENOENT') return null
          throw e
        })
        beforeFiles.push({
          path: file.path,
          size: stat?.size || 0,
          sha256: stat ? await hashFile(current) : '',
          exists: !!stat
        })
      }
      const token = path.basename(dir)
      const plan = {
        schema: 1,
        token,
        version: manifest.version,
        parentPid: process.pid,
        appRoot: this.options.appRoot,
        stageRoot: path.join(dir, 'files'),
        backupRoot: path.join(dir, 'backup'),
        executable: manifest.executable,
        restart: true,
        files: manifest.files,
        removeFiles,
        beforeFiles,
        baseFiles: manifest.baseFiles,
        targetFiles: manifest.targetFiles
      }
      await fs.writeFile(path.join(dir, 'plan.json'), JSON.stringify(plan))
      const helper = path.join(dir, 'install.ps1')
      await fs.copyFile(this.options.helperSource, helper)
      await fs.writeFile(
        path.join(dir, 'recover.ps1'),
        '\ufeff& (Join-Path $PSScriptRoot "install.ps1") -PlanPath (Join-Path $PSScriptRoot "plan.json") -Recover\n'
      )
      await fs.writeFile(
        path.join(this.options.transactionRoot, 'last-update.json'),
        JSON.stringify({ token })
      )
      const powershell = path.join(
        process.env.SystemRoot || 'C:/Windows',
        'System32/WindowsPowerShell/v1.0/powershell.exe'
      )
      const helperLog = await fs.open(path.join(dir, 'installer.log'), 'a')
      const child = spawn(
        powershell,
        [
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          helper,
          '-PlanPath',
          path.join(dir, 'plan.json'),
          '-Launch'
        ],
        // The bootstrap opens an independent hidden console; wait for the real
        // helper's handshake before exiting, even if the bootstrap has returned.
        { windowsHide: true, stdio: ['ignore', helperLog.fd, helperLog.fd] }
      )
      let spawnError: Error | undefined
      child.on('error', (error) => {
        spawnError = error
      })
      await helperLog.close()
      let ready = false
      for (let attempt = 0; attempt < 100; attempt++) {
        if (spawnError) throw spawnError
        const result = await fs
          .readFile(path.join(dir, 'helper-ready.json'), 'utf8')
          .catch(() => '')
        if (result && JSON.parse(result).token === token) {
          ready = true
          break
        }
        if (child.exitCode !== null && child.exitCode !== 0)
          throw new Error(
            `更新安装程序未能启动（${child.exitCode}），详情见 ${path.join(dir, 'installer.log')}`
          )
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
      if (!ready) throw new Error('更新安装程序准备超时，软件尚未退出')
      child.unref()
      this.options.quit()
    } catch (error) {
      await fs.writeFile(path.join(dir, 'abort'), 'cancelled').catch(() => {})
      this.staged = undefined
      this.set({
        status: 'error',
        message: `尚未安装：${error instanceof Error ? error.message : String(error)}`
      })
    }
    return this.snapshot
  }
  async previousResult() {
    try {
      const { token } = JSON.parse(
        await fs.readFile(path.join(this.options.transactionRoot, 'last-update.json'), 'utf8')
      )
      if (!/^[a-f0-9-]{36}$/.test(token)) return
      const result = JSON.parse(
        await fs.readFile(path.join(this.options.transactionRoot, token, 'result.json'), 'utf8')
      )
      if (result.status !== 'completed')
        this.set({ message: `上次更新未完成：${result.message}`, status: 'error' })
    } catch {
      /* No prior update result. */
    }
  }
}
