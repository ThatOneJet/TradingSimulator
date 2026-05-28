const { app, BrowserWindow, ipcMain } = require('electron')
const path   = require('path')
const fs     = require('fs')
const http   = require('http')
const { spawn, execSync } = require('child_process')

app.setName('TradeSimulator')

const FLASK_PORT   = 8765
const PROJECT_ROOT = path.join(__dirname, '..')
const IS_DEV       = process.env.TRADESIM_DEV === '1'

let mainWindow   = null
let flaskProcess = null
let isQuitting   = false

// ── Kill anything currently occupying the port ────────────────────────────────
function killPort(port) {
  try {
    if (process.platform === 'win32') {
      const out = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' })
      const pids = new Set()
      for (const line of out.split('\n')) {
        const m = line.match(/LISTENING\s+(\d+)/)
        if (m) pids.add(m[1])
      }
      for (const pid of pids) {
        try { execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' }) } catch {}
      }
    } else {
      execSync(`lsof -ti:${port} | xargs kill -9`, { stdio: 'ignore', shell: true })
    }
  } catch {
    // port was already free — that's fine
  }
}

// ── Kill the Flask child and its entire OS process tree ───────────────────────
function killFlask() {
  if (!flaskProcess) return
  const pid = flaskProcess.pid
  flaskProcess.removeAllListeners()
  try { flaskProcess.kill('SIGTERM') } catch {}
  flaskProcess = null
  if (!pid) return

  // Small window for graceful shutdown, then force-kill the tree
  setTimeout(() => {
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' })
      } else {
        process.kill(-pid, 'SIGKILL')   // negative = entire process group
      }
    } catch {}
  }, 300)
}

// ── Python / Flask startup ────────────────────────────────────────────────────
function findPython() {
  const candidates = [
    path.join(PROJECT_ROOT, 'venv',  'Scripts', 'python.exe'),
    path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(PROJECT_ROOT, 'venv',  'bin', 'python'),
    path.join(PROJECT_ROOT, '.venv', 'bin', 'python'),
  ]
  for (const p of candidates) {
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
    env:      { ...process.env },
    stdio:    ['ignore', 'pipe', 'pipe'],
    // On Unix, own process group so kill(-pid) reaches all children
    detached: process.platform !== 'win32',
  })

  flaskProcess.stdout.on('data', d => process.stdout.write(`[Flask] ${d}`))
  flaskProcess.stderr.on('data', d => process.stderr.write(`[Flask] ${d}`))
  flaskProcess.on('error', err => console.error('[Flask] spawn error:', err.message))
  flaskProcess.on('exit', (code, signal) => {
    if (!isQuitting) console.log(`[Flask] exited (code=${code}, signal=${signal})`)
    flaskProcess = null
  })
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

// ── Window ────────────────────────────────────────────────────────────────────
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
  ipcMain.on('win:minimize', ()     => mainWindow?.minimize())
  ipcMain.on('win:maximize', ()     => mainWindow?.maximize())
  ipcMain.on('win:restore',  ()     => mainWindow?.unmaximize())
  ipcMain.on('win:close',    ()     => mainWindow?.close())
  ipcMain.on('win:move', (_, x, y) => {
    if (mainWindow && !mainWindow.isMaximized()) mainWindow.setPosition(x, y)
  })
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  registerIPC()
  killPort(FLASK_PORT)   // clean up any stale occupant from a previous crash
  startFlask()
  createWindow()
})

app.on('before-quit', () => {
  isQuitting = true
  killFlask()
})

app.on('window-all-closed', () => {
  isQuitting = true
  killFlask()
  app.quit()
})

// Belt-and-suspenders: catch process signals (e.g. kill from terminal)
process.on('SIGTERM', () => { killFlask(); process.exit(0) })
process.on('SIGINT',  () => { killFlask(); process.exit(0) })
