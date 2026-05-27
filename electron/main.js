const { app, BrowserWindow, ipcMain } = require('electron')
const path  = require('path')
const fs    = require('fs')
const http  = require('http')
const { spawn } = require('child_process')

app.setName('TradeSimulator')

const FLASK_PORT   = 8765
const PROJECT_ROOT = path.join(__dirname, '..')
const IS_DEV       = process.env.TRADESIM_DEV === '1'

let mainWindow   = null
let flaskProcess = null

function findPython() {
  const venvCandidates = [
    path.join(PROJECT_ROOT, 'venv',  'Scripts', 'python.exe'),
    path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(PROJECT_ROOT, 'venv',  'bin', 'python'),
    path.join(PROJECT_ROOT, '.venv', 'bin', 'python'),
  ]
  for (const p of venvCandidates) {
    if (fs.existsSync(p)) return p
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

function startFlask() {
  const python = findPython()
  const script = path.join(PROJECT_ROOT, 'backend', 'app.py')
  const cwd    = path.join(PROJECT_ROOT, 'backend')

  console.log(`[TradeSimulator] Starting Flask: ${python} ${script}`)

  flaskProcess = spawn(python, [script], {
    cwd,
    env:   { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  flaskProcess.stdout.on('data', d => process.stdout.write(`[Flask] ${d}`))
  flaskProcess.stderr.on('data', d => process.stderr.write(`[Flask] ${d}`))
  flaskProcess.on('error', err => console.error('[Flask] spawn error:', err.message))
}

function waitForFlask(retries = 40, delayMs = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0
    function tryOnce() {
      const req = http.get(`http://127.0.0.1:${FLASK_PORT}/health`, (res) => {
        res.resume(); resolve()
      })
      req.setTimeout(delayMs, () => req.destroy())
      req.on('error', () => {
        if (++attempts >= retries) reject(new Error('Flask backend did not start in time'))
        else setTimeout(tryOnce, delayMs)
      })
    }
    tryOnce()
  })
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width:     1400,
    height:    880,
    minWidth:  1100,
    minHeight: 700,
    frame:     false,
    show:      false,
    backgroundColor: '#0d1119',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  })

  mainWindow.on('maximize',   () => mainWindow.webContents.send('win:maximized', true))
  mainWindow.on('unmaximize', () => mainWindow.webContents.send('win:maximized', false))

  try {
    console.log('[TradeSimulator] Waiting for Flask...')
    await waitForFlask()
    console.log('[TradeSimulator] Flask ready.')
  } catch (err) {
    console.error('[TradeSimulator]', err.message)
  }

  const url = IS_DEV ? 'http://127.0.0.1:5173' : `http://127.0.0.1:${FLASK_PORT}`
  await mainWindow.loadURL(url)
  mainWindow.once('ready-to-show', () => mainWindow.show())
}

function registerIPC() {
  ipcMain.on('win:minimize', ()      => mainWindow?.minimize())
  ipcMain.on('win:maximize', ()      => mainWindow?.maximize())
  ipcMain.on('win:restore',  ()      => mainWindow?.unmaximize())
  ipcMain.on('win:close',    ()      => mainWindow?.close())
  ipcMain.on('win:move', (_, x, y)  => {
    if (mainWindow && !mainWindow.isMaximized()) mainWindow.setPosition(x, y)
  })
}

app.whenReady().then(() => {
  registerIPC()
  startFlask()
  createWindow()
})

app.on('window-all-closed', () => {
  if (flaskProcess) { flaskProcess.kill(); flaskProcess = null }
  app.quit()
})

app.on('before-quit', () => {
  if (flaskProcess) { flaskProcess.kill(); flaskProcess = null }
})
