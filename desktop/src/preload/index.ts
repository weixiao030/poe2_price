import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopApi, ProgressEvent, AppSnapshot } from '../shared/types'
function subscribe<T>(channel: string, callback: (event: T) => void) {
  const listener = (_event: Electron.IpcRendererEvent, value: T) => callback(value)
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}
const api: DesktopApi = {
  getMapStatus: () => ipcRenderer.invoke('map:status'),
  setMapDirectory: (directory) => ipcRenderer.invoke('map:directory', directory),
  setMapEnabled: (enabled) => ipcRenderer.invoke('map:enabled', enabled),
  confirmMapConsent: (token) => ipcRenderer.invoke('map:consent', token),
  readMap: (reset) => ipcRenderer.invoke('map:read', reset ?? false),
  searchMap: (query) => ipcRenderer.invoke('map:search', query),
  planMapRoute: (request) => ipcRenderer.invoke('map:route', request),
  clearMapRoute: () => ipcRenderer.invoke('map:route-clear'),
  setMapOverlay: (options) => ipcRenderer.invoke('map:overlay-options', options),
  setMapPlanning: (state) => ipcRenderer.invoke('map:planning', state),
  setMapPicking: (enabled) => ipcRenderer.invoke('map:picking', enabled),
  onMapSelection: (callback) => subscribe('map:selection', callback),
  onMapPicking: (callback) => subscribe('map:picking', callback),
  cleanupFiles: (kind, remove) => ipcRenderer.invoke('app:cleanup', kind, remove),
  openCommunity: (kind) => ipcRenderer.invoke('app:community', kind),
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
