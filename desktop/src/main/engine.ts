import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { StringDecoder } from 'node:string_decoder'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { appendTail } from './policy'
import { prepareRuntime } from './runtime'
import { OperationOutput } from './operation-output'
import type { TabletLayerStatus } from '../shared/operation-outcome'

export interface WorkerResult {
  stdout: string
  stderr: string
  exitCode: number
  tabletAffixes?: TabletLayerStatus
}
export const workers = new Set<ChildProcessWithoutNullStreams>()
export async function stopTree(child: ChildProcessWithoutNullStreams): Promise<boolean> {
  if (!child.pid || child.exitCode !== null) return false
  return new Promise((resolve) => {
    const killer = spawn(
      path.join(process.env.SystemRoot || 'C:\\Windows', 'System32/taskkill.exe'),
      ['/PID', String(child.pid), '/T', '/F'],
      { windowsHide: true }
    )
    killer.once('error', () => resolve(false))
    killer.once('close', (code) => resolve(code === 0))
  })
}
export async function worker(
  payload: Record<string, unknown>,
  onData: (stream: 'stdout' | 'stderr', message: string) => void = () => {},
  onSpawn: (child: ChildProcessWithoutNullStreams) => void = () => {},
  timeout = 120_000
): Promise<WorkerResult> {
  const root = await prepareRuntime()
  const requestPath = path.join(os.tmpdir(), `poe-${crypto.randomUUID()}.json`)
  await fs.writeFile(requestPath, JSON.stringify(payload), { mode: 0o600 })
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn(
        path.join(
          process.env.SystemRoot || 'C:\\Windows',
          'System32/WindowsPowerShell/v1.0/powershell.exe'
        ),
        [
          '-NoLogo',
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          path.join(root, 'worker.ps1'),
          '-RequestPath',
          requestPath
        ],
        {
          cwd: root,
          windowsHide: true,
          env: { ...process.env, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' }
        }
      )
      workers.add(child)
      onSpawn(child)
      let stdout = '',
        stderr = '',
        timedOut = false
      const decoders = { stdout: new StringDecoder('utf8'), stderr: new StringDecoder('utf8') }
      const operationOutput = new OperationOutput()
      const send = (stream: 'stdout' | 'stderr', data: string) => {
        if (stream === 'stdout') operationOutput.write(data)
        if (stream === 'stdout') stdout = appendTail(stdout, data)
        else stderr = appendTail(stderr, data)
        onData(stream, data)
      }
      child.stdout.on('data', (chunk) => send('stdout', decoders.stdout.write(chunk)))
      child.stderr.on('data', (chunk) => send('stderr', decoders.stderr.write(chunk)))
      const timer = setTimeout(() => {
        timedOut = true
        void stopTree(child)
      }, timeout)
      child.once('error', (error) => {
        workers.delete(child)
        clearTimeout(timer)
        reject(error)
      })
      child.once('close', (code) => {
        clearTimeout(timer)
        workers.delete(child)
        send('stdout', decoders.stdout.end())
        send('stderr', decoders.stderr.end())
        if (timedOut) stderr = appendTail(stderr, '\n后台任务超时，已请求终止子进程树。')
        operationOutput.end()
        resolve({
          stdout,
          stderr,
          exitCode: timedOut ? 124 : (code ?? 1),
          tabletAffixes: operationOutput.tabletAffixes
        })
      })
    })
  } finally {
    await fs.unlink(requestPath).catch(() => {})
  }
}
export async function query<T>(payload: Record<string, unknown>): Promise<T> {
  const result = await worker(payload)
  if (result.exitCode !== 0)
    throw new Error(result.stderr || result.stdout || `后台退出码 ${result.exitCode}`)
  const line = result.stdout.split(/\r?\n/).find((line) => line.startsWith('__POE_RESULT__'))
  if (!line) throw new Error('后台没有返回有效数据')
  return JSON.parse(line.slice('__POE_RESULT__'.length)) as T
}
