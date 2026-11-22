"""Спящий сервер: держит порт, пока мост выключен.

Нужен для кнопки «включить сервер» с телефона: мост остановлен, но порт (и туннель)
живы, поэтому приложение достучится и сможет попросить поднять мост обратно.

Запуск:  python wake_gate.py          (порт и токен берутся из bridge.json)
"""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
INSTANCE = os.environ.get("ASSI_INSTANCE", "assi")
STATE = ROOT / ("bridge.json" if INSTANCE == "assi" else f"bridge-{INSTANCE}.json")

st = json.loads(STATE.read_text("utf-8-sig")) if STATE.exists() else {}
TOKEN = st.get("token", "")
PORT = int(os.environ.get("ASSI_PORT", st.get("port") or 8787))
NAME = st.get("name") or INSTANCE

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#08090b">
<title>Сервер выключен</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:grid; place-items:center; padding:24px;
         background:#08090b; color:#e8ecf1;
         font:15px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }
  .card { width:100%; max-width:380px; text-align:center; }
  .dot { width:56px; height:56px; margin:0 auto 18px; border-radius:18px;
         background:#bbf351; display:grid; place-items:center; }
  .dot svg { width:30px; height:30px; stroke:#08090b; }
  h1 { font-size:21px; margin:0 0 8px; font-weight:600; }
  p { margin:0 0 22px; color:#8b93a1; font-size:14px; }
  button { width:100%; padding:15px; border-radius:14px; border:0; cursor:pointer;
           background:#bbf351; color:#08090b; font:600 16px inherit; }
  button:disabled { opacity:.5; }
  input { width:100%; padding:14px; margin-bottom:10px; border-radius:12px;
          border:1px solid #262c36; background:#111318; color:#e8ecf1; font:15px inherit; }
  #msg { min-height:22px; margin-top:14px; font-size:13.5px; color:#8b93a1; }
  .ok { color:#bbf351; }
</style></head><body><div class="card">
<div class="dot"><svg viewBox="0 0 24 24" fill="none" stroke-width="2"
 stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v9"/><path d="M6.4 6.4a8 8 0 1011.2 0"/></svg></div>
<h1>Сервер выключен</h1>
<p>Компьютер на связи, но мост остановлен. Включить?</p>
<input id="tok" placeholder="токен" autocomplete="off">
<button id="go">Включить сервер</button>
<div id="msg"></div>
</div>
<script>
const q = new URLSearchParams(location.search);
let token = q.get('token') || q.get('t') || localStorage.getItem('token') || '';
const tok = document.getElementById('tok'), go = document.getElementById('go'), msg = document.getElementById('msg');
if (token) tok.value = token;
tok.addEventListener('change', () => { token = tok.value.trim(); localStorage.setItem('token', token); });
if (token) tok.type = 'password';
go.onclick = async () => {
  token = (tok.value || '').trim() || token;
  if (!token) { msg.textContent = 'нужен токен'; return; }
  go.disabled = true; msg.textContent = 'включаю…';
  try {
    const r = await fetch('/api/server', { method:'POST', headers:{ 'Content-Type':'application/json', 'X-Bridge-Token': token },
                                           body: JSON.stringify({ action:'resume' }) });
    if (r.status === 401) throw new Error('токен не подошёл');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    msg.className = 'ok'; msg.textContent = 'пошло, подожди ~15 секунд…';
    let n = 0;
    const t = setInterval(async () => {
      n++;
      try {
        const p = await fetch('/api/ping', { cache:'no-store' });
        const j = await p.json();
        if (j.ok) { clearInterval(t); location.href = '/?token=' + encodeURIComponent(token); }
      } catch (_) {}
      if (n > 30) { clearInterval(t); go.disabled = false; msg.textContent = 'долго… загляни на компьютер'; }
    }, 2000);
  } catch (e) {
    go.disabled = false; msg.className = ''; msg.textContent = String(e.message || e);
  }
};
</script></body></html>"""


def resume() -> None:
    """Запускает assi.ps1 resume отдельным процессом — этот скрипт должен умереть сам."""
    exe = ROOT / "assi.ps1"
    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                      "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    log = open(ROOT / "gate.log", "a", encoding="utf-8")
    try:
        subprocess.Popen(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(exe), "resume"],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=0x08000000 | 0x00000200,  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            close_fds=True,
        )
        log.write("resume: запустил assi.ps1 resume\n")
        log.flush()
    except Exception as exc:  # чтобы было видно в gate.log, а не молча
        log.write(f"resume error: {exc!r}\n")
        log.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = "AssiGate/1.0"

    def log_message(self, fmt, *args):  # не сорим в консоль
        pass

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self) -> bool:
        t = (self.headers.get("X-Bridge-Token") or "").strip()
        if not t:
            qs = parse_qs(urlparse(self.path).query)
            t = (qs.get("token") or qs.get("t") or [""])[0]
        return bool(TOKEN) and t.strip(" \t\r\n\"'`«»") == TOKEN

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/ping":
            # ok:false — мост выключен, но сервер на связи; приложение по этому флагу
            # не показывает «ноут не отвечает», а открывает страницу включения
            return self._json(200, {"ok": False, "wake": True, "owner": INSTANCE == "assi",
                                    "instance": INSTANCE, "name": NAME})
        if path in ("/", "/index.html"):
            return self._html(200, PAGE)
        return self._json(503, {"ok": False, "wake": True, "error": "сервер выключен"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/server":
            return self._json(404, {"ok": False})
        if INSTANCE != "assi":
            return self._json(403, {"ok": False, "error": "гостевой режим: сервером управляет только владелец"})
        if not self._token_ok():
            return self._json(401, {"ok": False, "error": "bad token"})
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            action = (json.loads(raw.decode("utf-8") or "{}") or {}).get("action", "resume")
        except Exception:
            action = "resume"
        if action not in ("resume", "start", "on"):
            return self._json(400, {"ok": False, "error": "неизвестное действие"})
        self._json(200, {"ok": True, "action": "resume"})
        threading.Thread(target=self._later, daemon=True).start()

    def _later(self):
        time.sleep(0.7)
        resume()
        time.sleep(1.0)
        os._exit(0)


def main() -> None:
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"wake gate on :{PORT}, instance={INSTANCE}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
