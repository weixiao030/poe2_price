// Isolated QA application: bundles the production updater, never the production app identity.
import { app, BrowserWindow, session } from 'electron'
import fs from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { SoftwareUpdater } from '../src/main/software-update'
import { NsisUpdateDriver } from '../src/main/software-update-driver'

async function main() {
  // NSIS may restart through Explorer; inherited test environment is not guaranteed.
  const configPath =
    process.env.POE_INSTALLER_QA_CONFIG || path.join(process.resourcesPath, 'qa-config.json')
  if (!configPath) app.exit(2)
  else {
    const config = JSON.parse(readFileSync(configPath, 'utf8'))
    app.setPath('userData', path.join(config.root, 'userdata'))
    app.disableHardwareAcceleration()
    await app.whenReady()
    session
      .fromPartition('electron-updater', { cache: false })
      .setCertificateVerifyProc((request, callback) => {
        const fingerprint = new crypto.X509Certificate(request.certificate.data).fingerprint256
        callback(request.hostname === '127.0.0.1' && fingerprint === config.fingerprint ? 0 : -3)
      })
    const logger = Object.fromEntries(
      ['info', 'warn', 'error', 'debug'].map((level) => [
        level,
        (...values: unknown[]) => {
          void fs.appendFile(
            path.join(config.root, 'native-updater.log'),
            `${level}: ${values.map(String).join(' ')}\n`
          )
        }
      ])
    ) as Pick<Console, 'info' | 'warn' | 'error' | 'debug'>
    const driver = new NsisUpdateDriver(logger)
    const updater = new SoftwareUpdater({
      version: app.getVersion(),
      notes: [],
      config: config.update,
      stateRoot: path.join(app.getPath('userData'), 'software-updates'),
      packaged: true,
      driver,
      canInstall: () => true,
      changed: (state) => {
        void fs.writeFile(path.join(config.root, 'state.json'), JSON.stringify(state))
      },
      sourceIdleTimeoutMs: 4000
    })
    await updater.previousResult()
    await updater.uiReady()
    const window = new BrowserWindow({ show: false, webPreferences: { sandbox: true } })
    await window.loadURL('data:text/html,<title>Installer verification</title>')
    Object.assign(globalThis, { qaUpdater: updater, qaDriver: driver, qaReady: true })
    await fs.writeFile(
      path.join(config.root, `boot-${app.getVersion()}.json`),
      JSON.stringify({
        version: app.getVersion(),
        pid: process.pid,
        executable: app.getPath('exe')
      })
    )
  }
}
void main().catch((error) => {
  console.error(error)
  app.exit(1)
})
