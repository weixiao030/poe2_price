import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopApi, ProgressEvent, AppSnapshot } from '../shared/types'
function subscribe<T>(channel: string, callback: (event: T) => void) {
  const listener = (_event: Electron.IpcRendererEvent, value: T) => callback(value)
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}
const api: DesktopApi = {
  getSnapshot: () => ipcRenderer.invoke('app:snapshot'),
  saveSettings: (patch) => ipcRenderer.invoke('settings:save', patch),
  pickGameDirectory: () => ipcRenderer.invoke('game:pick'),
  discoverGames: (version) => ipcRenderer.invoke('game:discover', version),
  inspectGame: (version, directory, language) =>
    ipcRenderer.invoke('game:inspect', version, directory, language),
  getLeagues: (version, china) => ipcRenderer.invoke('game:leagues', version, china),
  runOperation: (request) => ipcRenderer.invoke('patch:run', request),
  cancelOperation: (id) => ipcRenderer.invoke('patch:cancel', id),
  openFolder: (kind) => ipcRenderer.invoke('app:folder', kind),
  exportLog: (text) => ipcRenderer.invoke('app:export', text),
  getBackground: () => ipcRenderer.invoke('background:get'),
  chooseBackground: () => ipcRenderer.invoke('background:choose'),
  clearBackground: () => ipcRenderer.invoke('background:clear'),
  onProgress: (callback) => subscribe<ProgressEvent>('patch:progress', callback),
  onSnapshot: (callback) => subscribe<AppSnapshot>('app:snapshot', callback)
}
contextBridge.exposeInMainWorld('desktop', api)
