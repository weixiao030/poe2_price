import { app } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import path from 'node:path'
import crypto from 'node:crypto'
import { mapDirectory } from './world-map-policy'

export class WorldMapWorker {
  private child: ChildProcessWithoutNullStreams | null = null
  private pending: {
    id: string
    resolve: (value: any) => void
    reject: (error: Error) => void
    timer: NodeJS.Timeout
  } | null = null
  private output = ''
  private stderr = ''
  private queue: Promise<unknown> = Promise.resolve()
  private queued = 0
  get enabled() {
    return this.child !== null
  }
  get busy() {
    return this.queued > 0
  }

  start(directory: string) {
    if (this.child) throw new Error('地图读取已开启')
    const executable = app.isPackaged
      ? path.join(process.resourcesPath, 'world-map/PoeWorldMap.exe')
      : path.join(app.getAppPath(), '.world-map/PoeWorldMap.exe')
    const child = spawn(executable, ['--directory', mapDirectory(directory)], {
      windowsHide: true,
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        DOTNET_ROOT: app.isPackaged
          ? path.join(process.resourcesPath, 'engine/tools/dotnet-runtime')
          : path.join(app.getAppPath(), '.runtime/tools/dotnet-runtime'),
        DOTNET_ROOT_X64: app.isPackaged
          ? path.join(process.resourcesPath, 'engine/tools/dotnet-runtime')
          : path.join(app.getAppPath(), '.runtime/tools/dotnet-runtime'),
        DOTNET_MULTILEVEL_LOOKUP: '0'
      }
    })
    this.child = child
    this.output = this.stderr = ''
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => {
      if (this.child !== child) return
      this.output += chunk
      if (Buffer.byteLength(this.output, 'utf8') > 24 * 1024 * 1024) {
        this.stop(new Error('地图读取输出超限'))
        return
      }
      let end: number
      while ((end = this.output.indexOf('\n')) >= 0) {
        const line = this.output.slice(0, end)
        this.output = this.output.slice(end + 1)
        try {
          const response = JSON.parse(line)
          if (this.pending?.id !== response.id) continue
          const pending = this.pending!
          clearTimeout(pending.timer)
          this.pending = null
          if (response.error) pending.reject(new Error(String(response.error)))
          else pending.resolve(response.result)
        } catch {
          this.stop(new Error('地图读取返回了无效数据'))
        }
      }
    })
    child.stderr.on('data', (chunk: string) => {
      if (this.child === child) this.stderr = (this.stderr + chunk).slice(-4000)
    })
    child.stdin.on('error', (error) => {
      if (this.child === child) this.stop(error)
    })
    child.once('error', (error) => {
      if (this.child === child) this.stop(error)
    })
    child.once('exit', (code) => {
      if (this.child === child) this.stop(new Error(`地图读取进程已退出 (${code}) ${this.stderr}`))
    })
  }

  request<T>(action: string, fields: Record<string, unknown> = {}): Promise<T> {
    const child = this.child
    if (!child) return Promise.reject(new Error('世界地图规划尚未开启'))
    if (this.queued >= 8) return Promise.reject(new Error('地图查询过于频繁，请稍后重试'))
    this.queued++
    const next = this.queue.then(() => {
      if (this.child !== child) throw new Error('地图读取已停止')
      return this.perform<T>(action, fields)
    })
    this.queue = next.catch(() => {})
    return next.finally(() => {
      this.queued--
    })
  }

  private perform<T>(action: string, fields: Record<string, unknown>): Promise<T> {
    if (!this.child) return Promise.reject(new Error('世界地图规划尚未开启'))
    if (this.pending) return Promise.reject(new Error('地图正在读取，请稍后重试'))
    const child = this.child
    const id = crypto.randomUUID()
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => this.stop(new Error('地图读取超时，已停止读取')), 20_000)
      this.pending = { id, resolve, reject, timer }
      child.stdin.write(JSON.stringify({ ...fields, action, id }) + '\n')
    })
  }

  stop(error = new Error('地图读取已停止')) {
    const child = this.child
    this.child = null
    if (this.pending) {
      clearTimeout(this.pending.timer)
      this.pending.reject(error)
      this.pending = null
    }
    child?.kill()
    this.output = ''
  }
}
