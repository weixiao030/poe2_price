import { test } from 'node:test'
import assert from 'node:assert/strict'
import { appendTail, argsFor, settingsPatch, scriptFor, validateRequest } from '../src/main/policy'
import type { PatchRequest } from '../src/shared/types'
const request: PatchRequest = {
  operation: 'update',
  gameVersion: 'poe2',
  gameDirectory: 'D:\\游戏\\POE2',
  languageMode: 'auto',
  patchScope: 'all',
  league: 'test',
  poeNinjaLeague: 'Test League',
  poeCurrencySeason: '0.5',
  leagueIsCurrent: false,
  islandRumourHints: true
}
test('POE1 never receives unsupported POE2 parameters', () => {
  const r = validateRequest({ ...request, gameVersion: 'poe1' })
  const args = argsFor(r)
  assert.equal(args.Poe1Dir, request.gameDirectory)
  assert.equal(args.Poe1LanguageMode, 'auto')
  assert.equal('IslandRumourHints' in args, false)
  assert.equal('PoeNinjaLeague' in args, false)
  assert.equal(scriptFor(r), 'update_poe1_price_patch.ps1')
})
test('preserves historical league boolean, CN season and scout/ninja identities', () => {
  const args = argsFor(request)
  assert.equal(args.LeagueIsCurrent, false)
  assert.equal(args.PoeCurrencySeason, '0.5')
  assert.equal(args.PoeNinjaLeague, 'Test League')
  assert.equal(args.League, 'test')
  assert.equal(args.IslandRumourHints, true)
})
test('restore/localize only receive supported arguments', () => {
  assert.deepEqual(argsFor({ ...request, operation: 'restore' }), {
    Poe2Dir: request.gameDirectory
  })
  assert.deepEqual(argsFor({ ...request, gameVersion: 'poe1', operation: 'localize' }), {
    Poe1Dir: request.gameDirectory
  })
  assert.equal(
    scriptFor({ ...request, gameVersion: 'poe1', operation: 'localize' }),
    'localize_poe1.ps1'
  )
})
test('rejects malformed renderer requests before spawning a worker', () => {
  for (const patch of [
    { operation: 'arbitrary' },
    { gameDirectory: '' },
    { gameDirectory: '..\\game' },
    { gameDirectory: '\\\\server\\game' },
    { languageMode: 'en' },
    { league: 'x\nWrite-Host injected' },
    { operation: 'localize' },
    { leagueIsCurrent: 'false' }
  ])
    assert.throws(() => validateRequest({ ...request, ...patch }))
})
test('JSON preserves Chinese paths and literal metacharacters without interpolation', () => {
  const r = validateRequest({
    ...request,
    gameDirectory: "D:\\游戏 $目录\\O'Brien (1)",
    league: 'League $x ` literal'
  })
  assert.deepEqual(JSON.parse(JSON.stringify(argsFor(r))), argsFor(r))
})
test('settings reject unknown fields and do not mix client paths', () => {
  assert.throws(() => settingsPatch({ executable: 'cmd.exe' }))
  assert.throws(() => settingsPatch({ autoUpdate: 'true' }))
  assert.deepEqual(settingsPatch({ directories: { poe1: 'D:\\Poe1', poe2: 'E:\\Poe2' } }), {
    directories: { poe1: 'D:\\Poe1', poe2: 'E:\\Poe2' }
  })
})
test('keeps newest bounded log output under a sustained output stream', () => {
  let output = ''
  for (let i = 0; i < 5000; i++) output = appendTail(output, `中文阶段 ${i}\n`, 1000)
  assert.ok(output.length <= 1000)
  assert.ok(output.endsWith('中文阶段 4999\n'))
  assert.ok(!output.includes('阶段 1\n'))
})
