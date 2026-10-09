"""基于已创建的合成验收库启动一组新端口，用于加载最新代码。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import argparse

from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from app.core.config import settings

parser = argparse.ArgumentParser()
parser.add_argument('--backend-port', type=int, default=8003)
parser.add_argument('--frontend-port', type=int, default=5178)
parser.add_argument('--keepalive', action='store_true')
parser.add_argument('--backend-only', action='store_true')
ports = parser.parse_args()

state = json.loads((ROOT/'.codex/agent-acceptance/session.json').read_text(encoding='utf-8'))
target_url = make_url(settings.database_url).set(database=state['database'])
env = dict(os.environ, DATABASE_URL=target_url.render_as_string(hide_password=False),
           DEFAULT_SCHOOL_CODE='accept_admin', SCHEMA_SYNC_DROP='false',
           APP_NAME='轻课堂 · 合成验收', PYTHONUTF8='1')
private = ROOT/'.codex/agent-acceptance'
backend_log = open(private/f'backend-{ports.backend_port}.log', 'w', encoding='utf-8')
backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host',
    '127.0.0.1', '--port', str(ports.backend_port)], cwd=BACKEND, env=env, stdout=backend_log,
    stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
if ports.backend_only:
    print(json.dumps({'backend_port': ports.backend_port, 'backend_pid': backend.pid}), flush=True)
    if ports.keepalive:
        backend.wait()
    sys.exit(0)
node = r'C:\Program Files\AutoClaw\resources\node\node.exe'
frontend_log = open(private/f'frontend-{ports.frontend_port}.log', 'w', encoding='utf-8')
frontend = subprocess.Popen([node, 'node_modules/vite/bin/vite.js', '--host',
    '127.0.0.1', '--port', str(ports.frontend_port), '--strictPort'], cwd=ROOT/'frontend-react',
    env=dict(os.environ, VITE_DEV_PROXY=f'http://127.0.0.1:{ports.backend_port}'), stdout=frontend_log,
    stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'backend_port': ports.backend_port, 'frontend_port': ports.frontend_port,
                  'backend_pid': backend.pid, 'frontend_pid': frontend.pid}), flush=True)
if ports.keepalive:
    frontend.wait()
