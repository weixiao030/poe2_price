import { contextBridge, ipcRenderer } from 'electron'
import type { OverlayFrame } from '../shared/world-map'
contextBridge.exposeInMainWorld('atlasOverlay', {
  onFrame(callback: (frame: OverlayFrame) => void) {
    const listener = (_event: Electron.IpcRendererEvent, frame: OverlayFrame) => callback(frame)
    ipcRenderer.on('map:overlay-frame', listener)
    return () => ipcRenderer.removeListener('map:overlay-frame', listener)
  }
})
