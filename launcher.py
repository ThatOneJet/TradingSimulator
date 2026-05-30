import subprocess
import threading
import time
import sys
import os
import urllib.request

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
BACKEND_FILE = os.path.join(BASE_DIR, 'backend', 'app.py')
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')
DIST_DIR     = os.path.join(FRONTEND_DIR, 'dist')
FLASK_PORT   = 8765


# ── Kill any existing process on the Flask port ──────────────────────────────

def kill_port(port):
    """Kill any process currently holding port (Windows only)."""
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr :{port}', shell=True, encoding='utf-8', stderr=subprocess.DEVNULL
        )
        pids = set()
        for line in out.splitlines():
            if 'LISTENING' in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            try:
                subprocess.run(f'taskkill /F /T /PID {pid}', shell=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f'[TradeSimulator] Killed old backend process (PID {pid}).')
            except Exception:
                pass
    except Exception:
        pass

kill_port(FLASK_PORT)


# ── Build frontend if dist/ is missing ───────────────────────────────────────

def build_frontend():
    print('[TradeSimulator] Building frontend...')
    result = subprocess.run(
        ['npm', 'run', 'build'],
        cwd=FRONTEND_DIR,
        shell=True,
    )
    if result.returncode != 0:
        print('[TradeSimulator] Frontend build failed. Run `npm install` in frontend/ first.')
        sys.exit(1)
    print('[TradeSimulator] Frontend built.')


if not os.path.isdir(DIST_DIR):
    build_frontend()


# ── Window API (exposed to JS via window.pywebview.api) ──────────────────────

class WindowApi:
    def __init__(self):
        self._win  = None
        self._prev = None

    def set_window(self, win):
        self._win = win

    def minimize_window(self):
        if self._win: self._win.minimize()
        return True

    def maximize_window(self):
        if self._win:
            self._prev = (self._win.x, self._win.y, self._win.width, self._win.height)
            self._win.maximize()
        return True

    def restore_window(self):
        if self._win:
            if self._prev:
                x, y, w, h = self._prev
                self._win.restore()
                self._win.resize(w, h)
                self._win.move(x, y)
                self._prev = None
            else:
                self._win.restore()
        return True

    def close_window(self):
        if self._win: self._win.destroy()
        return True

    def move_window(self, x, y):
        if self._win: self._win.move(int(x), int(y))
        return True


# ── Start Flask backend ───────────────────────────────────────────────────────

def run_flask():
    subprocess.run([sys.executable, BACKEND_FILE], cwd=os.path.join(BASE_DIR, 'backend'))


print('[TradeSimulator] Starting backend...')
threading.Thread(target=run_flask, daemon=True).start()

for _ in range(40):
    try:
        urllib.request.urlopen(f'http://localhost:{FLASK_PORT}/health', timeout=1)
        print('[TradeSimulator] Backend ready.')
        break
    except Exception:
        time.sleep(0.5)
else:
    print('[TradeSimulator] Backend did not start in time — continuing anyway.')


# ── Open window ───────────────────────────────────────────────────────────────

import webview

api = WindowApi()

print('[TradeSimulator] Opening window...')
win = webview.create_window(
    'TradeSimulator',
    f'http://localhost:{FLASK_PORT}',
    width=1400,
    height=880,
    min_size=(1100, 700),
    frameless=True,
    easy_drag=False,
    js_api=api,
)
api.set_window(win)

webview.start(
    private_mode=False,
    storage_path=os.path.join(BASE_DIR, '.webview_data'),
)
