const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
  minimize:   ()       => ipcRenderer.send('win:minimize'),
  maximize:   ()       => ipcRenderer.send('win:maximize'),
  restore:    ()       => ipcRenderer.send('win:restore'),
  close:      ()       => ipcRenderer.send('win:close'),
  move:       (x, y)   => ipcRenderer.send('win:move', Math.round(x), Math.round(y)),
  onMaximize: (cb)     => { ipcRenderer.on('win:maximized', (_, val) => cb(val)) },
})
