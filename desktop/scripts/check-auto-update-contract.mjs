// Execute the production operation/scheduler functions with a virtual clock and inert engine.
// The same probe accepts the previous source archive and the current checkout.
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import crypto from 'node:crypto'
import ts from 'typescript'

const root = path.resolve(process.argv[2])
function functions(file, names) {
  const source = ts.createSourceFile(file, fs.readFileSync(path.join(root, file), 'utf8'), ts.ScriptTarget.Latest, true)
  return source.statements.filter(n => ts.isFunctionDeclaration(n) && (!names || names.includes(n.name?.text)))
    .map(n => n.getText(source).replace(/^export /, '')).join('\n')
}
let state = { settings: { autoUpdate: true, gameVersion: 'poe2', directories: { poe2: 'C:\\Fixture\\POE2' } }, history: [], confirmed: null }
let now = Date.UTC(2026, 8, 16), engineExit = 0, calls = 0
const store = {
  get: key => structuredClone(state[key]),
  get store() { return structuredClone(state) },
  set store(value) { state = structuredClone(value) }
}
const context = vm.createContext({
  store, path, crypto,
  Date: class extends Date { static now() { return now } },
  setTimeout: (callback, delay) => ({ callback, delay, unref() {} }), clearTimeout() {},
  refresh() {}, send() {}, log: { info() {}, error(error) { throw error } },
  queryOnce: async () => ({ installKind: 'Fixture', displayName: 'Fixture', path: 'C:\\Fixture\\POE2', isChina: false }),
  worker: async () => { calls++; return { exitCode: engineExit, stdout: 'fixture', stderr: '' } },
  stopTree: async () => true
})
const code = `let active = null, processChild = null, cancellationRequested = false, timer, nextUpdate = null;
${functions('src/main/policy.ts')}
${functions('src/main/index.ts', ['runOperation', 'schedule'])}
globalThis.probe = { runOperation, schedule, deadline: () => nextUpdate, tick: () => timer.callback() };`
vm.runInContext(ts.transpile(code, { target: ts.ScriptTarget.ES2022 }), context)
const { probe } = context
const request = { operation: 'update', gameVersion: 'poe2', gameDirectory: 'C:\\Fixture\\POE2', patchScope: 'all',
  languageMode: 'auto', league: 'Fixture', poeNinjaLeague: 'Fixture', poeCurrencySeason: '', leagueIsCurrent: true, islandRumourHints: true }
const status = () => ({ enabled: state.settings.autoUpdate, confirmed: !!state.confirmed, scheduled: !!probe.deadline() })
probe.schedule()
const beforeFirstUpdate = status()
await probe.runOperation(request)
const enabledAfterSuccess = status()
const deadline = probe.deadline()
now += 10_000
probe.schedule()
const unrelatedSettingsKeepDeadline = probe.deadline() === deadline
await probe.runOperation({ ...request, operation: 'restore' })
const afterRestore = status()
// Re-enable explicitly so the failure/skip scenarios remain identical for both revisions.
state.settings.autoUpdate = true
await probe.runOperation(request)
engineExit = 1
await probe.tick()
const afterFailedHour = status()
engineExit = 2
await probe.tick()
const afterSkippedHour = status()
const expiredTimer = vm.runInContext('timer.callback', context)
state.settings.autoUpdate = false
probe.schedule()
const afterManualOff = status()
const callsBefore = calls
await expiredTimer()
const disabledQueuedCallbackRuns = calls - callsBefore
console.log(JSON.stringify({ beforeFirstUpdate, enabledAfterSuccess, unrelatedSettingsKeepDeadline,
  afterRestore, afterFailedHour, afterSkippedHour, afterManualOff, disabledQueuedCallbackRuns }, null, 2))
