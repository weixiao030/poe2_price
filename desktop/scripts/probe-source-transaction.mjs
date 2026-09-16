import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'
import { spawnSync } from 'node:child_process'
import ts from 'typescript'
import { fileURLToPath } from 'node:url'

const archive = path.resolve(process.argv[2])
const destination = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-source-probe-'))
const extract = spawnSync('tar', ['-xf', archive, '-C', destination], {
  encoding: 'utf8',
  windowsHide: true
})
if (extract.status !== 0) throw Error(extract.stderr)
const desktop = path.join(destination, 'desktop')
const shared = path.join(desktop, 'src/shared/world-map.ts')
let overlay = null
if (fs.existsSync(shared)) {
  const context = vm.createContext({ exports: {} })
  vm.runInContext(
    ts.transpile(fs.readFileSync(shared, 'utf8'), { module: ts.ModuleKind.CommonJS }),
    context
  )
  overlay = context.exports.overlayDefaults
}
const probe = spawnSync(
  process.execPath,
  [fileURLToPath(new URL('./check-auto-update-contract.mjs', import.meta.url)), desktop],
  { encoding: 'utf8', windowsHide: true }
)
if (probe.status !== 0) throw Error(probe.stderr)
const hourly = JSON.parse(probe.stdout)
let rememberedState = null
const policy = path.join(desktop, 'src/main/world-map-policy.ts')
if (fs.existsSync(policy)) {
  const context = vm.createContext({
    exports: {},
    require: (id) => (id === 'node:path' ? path : {})
  })
  vm.runInContext(
    ts.transpile(fs.readFileSync(policy, 'utf8'), { module: ts.ModuleKind.CommonJS }),
    context
  )
  const { shouldResumeMap, MAP_CONSENT_VERSION } = context.exports
  if (shouldResumeMap)
    rememberedState = {
      authorizedOn: shouldResumeMap({ enabled: true, consentVersion: MAP_CONSENT_VERSION }),
      authorizedOff: shouldResumeMap({ enabled: false, consentVersion: MAP_CONSENT_VERSION }),
      unauthorizedOn: shouldResumeMap({ enabled: true, consentVersion: 0 })
    }
}
console.log(
  JSON.stringify(
    {
      version: JSON.parse(fs.readFileSync(path.join(desktop, 'package.json'), 'utf8')).version,
      worldMapModule: fs.existsSync(path.join(destination, 'world-map/Program.cs')),
      overlay,
      rememberedState,
      hourlyWithMapAndRunningGame: hourly.mapRunningGameHour,
      hourlyWithMapAndNoGame: hourly.mapWaitingGameHour,
      manualOffStopsScheduler: hourly.disabledQueuedCallbackRuns === 0
    },
    null,
    2
  )
)
