// Run production scheduling/operation code with a virtual clock and an inert engine.
// root may point to an archived source tree to reproduce the same scenarios before a fix.
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import crypto from 'node:crypto'
import ts from 'typescript'

export const request = {
  operation: 'update',
  gameVersion: 'poe2',
  gameDirectory: 'C:\\Fixture\\POE2',
  patchScope: 'all',
  languageMode: 'auto',
  league: 'Fixture',
  poeNinjaLeague: 'Fixture',
  poeCurrencySeason: '',
  leagueIsCurrent: true,
  islandRumourHints: true
}

export function createHarness(root, initial = {}) {
  let now = initial.now ?? Date.UTC(2026, 8, 17)
  let state = structuredClone(
    initial.state ?? {
      settings: {
        autoUpdate: true,
        gameVersion: 'poe2',
        directories: { poe2: request.gameDirectory }
      },
      history: [],
      confirmed: null
    }
  )
  let engineExit = 0,
    calls = 0,
    queries = 0,
    engineWait = null,
    failWrites = false
  const timers = new Set()
  const store = {
    get: (key) => structuredClone(state[key]),
    set(key, value) {
      if (failWrites) throw new Error('fixture: disk full')
      state[key] = structuredClone(value)
    },
    get store() {
      return structuredClone(state)
    },
    set store(value) {
      if (failWrites) throw new Error('fixture: disk full')
      state = structuredClone(value)
    }
  }
  const context = vm.createContext({
    store,
    path,
    crypto,
    maintenanceRunning: false,
    softwareUpdater: { installing: false },
    quitting: false,
    Date: class extends Date {
      constructor(...args) {
        super(...(args.length ? args : [now]))
      }
      static now() {
        return now
      }
    },
    setTimeout(callback, delay) {
      const timer = { callback, delay, at: now + delay, unref() {} }
      timers.add(timer)
      return timer
    },
    clearTimeout(timer) {
      timers.delete(timer)
    },
    refresh() {},
    send() {},
    log: { info() {}, error() {} },
    queryOnce: async () => {
      queries++
      return {
        installKind: 'Fixture',
        displayName: 'Fixture',
        path: request.gameDirectory,
        isChina: false
      }
    },
    worker: async () => {
      calls++
      if (engineWait) await engineWait
      return { exitCode: engineExit, stdout: 'fixture', stderr: '', tabletAffixes: 'applied' }
    },
    stopTree: async () => true
  })
  function source(file, names) {
    const full = path.join(root, file)
    if (!fs.existsSync(full)) return ''
    const ast = ts.createSourceFile(
      file,
      fs.readFileSync(full, 'utf8'),
      ts.ScriptTarget.Latest,
      true
    )
    return ast.statements
      .filter((node) =>
        names
          ? ts.isFunctionDeclaration(node) && names.includes(node.name?.text)
          : !ts.isImportDeclaration(node)
      )
      .map((node) => node.getText(ast).replace(/^export /, ''))
      .join('\n')
  }
  const code = `let active = null, processChild = null, cancellationRequested = false, timer, nextUpdate = null, scheduleGeneration = 0, autoUpdatePausedReason = '';
    ${source('src/main/policy.ts')}
    ${source('src/shared/operation-outcome.ts')}
    ${source('src/main/auto-update.ts')}
    ${source('src/main/index.ts', ['runOperation', 'schedule', 'cancelSchedule', 'autoUpdateStatus', 'saveAutoUpdateSchedule'])}
    globalThis.probe = { runOperation, schedule, deadline: () => nextUpdate,
      setActive: (value) => { active = value }, cancel: () => { cancellationRequested = true } };`
  vm.runInContext(ts.transpile(code, { target: ts.ScriptTarget.ES2022 }), context)
  async function advance(ms) {
    const target = now + ms
    let iterations = 0
    while (true) {
      const timer = [...timers].sort((a, b) => a.at - b.at)[0]
      if (!timer || timer.at > target) break
      if (++iterations > 10000) throw new Error('Unbounded timer loop')
      now = timer.at
      timers.delete(timer)
      await timer.callback()
    }
    now = target
  }
  return {
    ...context.probe,
    advance,
    store,
    get state() {
      return structuredClone(state)
    },
    get now() {
      return now
    },
    get calls() {
      return calls
    },
    get queries() {
      return queries
    },
    get timer() {
      return [...timers].sort((a, b) => a.at - b.at)[0]
    },
    set exit(value) {
      engineExit = value
    },
    set engineWait(value) {
      engineWait = value
    },
    set failWrites(value) {
      failWrites = value
    },
    set maintenance(value) {
      context.maintenanceRunning = value
    },
    set softwareInstalling(value) {
      context.softwareUpdater.installing = value
    },
    jump(ms) {
      now += ms
    },
    restart() {
      return createHarness(root, { now, state })
    }
  }
}
