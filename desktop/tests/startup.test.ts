import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reconcileAutoStart, shouldShowSecondInstance } from '../src/main/startup'

test('startup registration is written with hidden argument and read back', () => {
  let state = { openAtLogin: false, executableWillLaunchAtLogin: false }
  let written: unknown
  const api = {
    getLoginItemSettings: () => state,
    setLoginItemSettings: (value: { openAtLogin: boolean; path: string; args: string[] }) => {
      written = value
      state = { openAtLogin: value.openAtLogin, executableWillLaunchAtLogin: value.openAtLogin }
    }
  }
  assert.match(reconcileAutoStart(api, 'C:\\App\\物价补丁.exe', true), /已核对/)
  assert.deepEqual(written, {
    openAtLogin: true,
    path: 'C:\\App\\物价补丁.exe',
    args: ['--hidden']
  })
})

test('reports a startup item disabled by Windows StartupApproved', () => {
  const api = {
    getLoginItemSettings: () => ({ openAtLogin: true, executableWillLaunchAtLogin: false }),
    setLoginItemSettings: () => assert.fail('existing registration should not be rewritten')
  }
  assert.match(reconcileAutoStart(api, 'C:\\App\\物价补丁.exe', true), /Windows 禁用/)
})

test('rejects a registration that cannot be persisted', () => {
  const api = {
    getLoginItemSettings: () => ({ openAtLogin: false, executableWillLaunchAtLogin: false }),
    setLoginItemSettings() {}
  }
  assert.throws(() => reconcileAutoStart(api, 'C:\\App\\物价补丁.exe', true), /未成功保存/)
})

test('disabling removes a stale registration after moving the portable folder', () => {
  let staleRegistration = true
  const api = {
    getLoginItemSettings: () => ({ openAtLogin: false, executableWillLaunchAtLogin: false }),
    setLoginItemSettings: (value: { openAtLogin: boolean }) => {
      assert.equal(value.openAtLogin, false)
      staleRegistration = false
    }
  }
  reconcileAutoStart(api, 'D:\\Moved\\物价补丁.exe', false)
  assert.equal(staleRegistration, false)
})

test('another enabled launch entry cannot hide Windows disabling the hidden entry', () => {
  const executable = 'C:\\App\\物价补丁.exe'
  const api = {
    getLoginItemSettings: () => ({
      openAtLogin: true,
      executableWillLaunchAtLogin: true,
      launchItems: [
        { path: executable, args: ['--hidden'], enabled: false },
        { path: executable, args: [], enabled: true }
      ]
    }),
    setLoginItemSettings: () => assert.fail('do not rewrite Windows preferences')
  }
  assert.match(reconcileAutoStart(api, executable, true), /Windows 禁用/)
})

test('a hidden second instance keeps the tray hidden; a user launch opens it', () => {
  assert.equal(shouldShowSecondInstance(['app.exe', '--hidden']), false)
  assert.equal(shouldShowSecondInstance(['app.exe']), true)
})
