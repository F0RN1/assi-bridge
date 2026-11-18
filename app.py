"""Мост телефон <-> OpenCode. FastAPI + PWA + faster-whisper."""
import asyncio, base64, json, os, re, secrets, shutil, socket, subprocess, sys, time, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
STATE = ROOT / "bridge.json"
INBOX = Path.home() / "Inbox"
OPENCODE_PORT = 8790
BIND = ("0.0.0.0", 8787)
MODEL = {"providerID": "opencode", "id": "deepseek-v4.1-flash-free"}
AGENT = "build"
WORKDIR = str(Path.home())

state = json.loads(STATE.read_text("utf-8")) if STATE.exists() else {}


def save_state():
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


if "token" not in state:
    state["token"] = secrets.token_urlsafe(18)
    save_state()

TOKEN = state["token"]
api = httpx.AsyncClient(base_url=f"http://127.0.0.1:{OPENCODE_PORT}", timeout=180)
_server: subprocess.Popen | None = None


async def ensure_server() -> None:
    """Поднять `opencode serve` и получить пароль из его stdout."""
    global _server
    if state.get("password"):
        api.auth = ("opencode", state["password"])
        try:
            (await api.get("/api/info")).raise_for_status()
            return
        except Exception:
            pass
    if _server is None:
        exe = shutil.which("opencode.exe") or os.path.expandvars(
            r"%APPDATA%\npm\node_modules\@opencode\cli\bin\opencode.exe")
        _server = subprocess.Popen(
            [exe, "serve", "--port", str(OPENCODE_PORT), "--hostname", "127.0.0.1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
        )
    for _ in range(120):
        line = _server.stdout.readline()
        m = re.search(r"server password (\S+)", line or "")
        if m:
            state["password"] = m.group(1)
            save_state()
            api.auth = ("opencode", m.group(1))
            await asyncio.sleep(1.5)
            return
    raise RuntimeError("не удалось получить пароль opencode serve")


async def ensure_session() -> str:
    await ensure_server()
    sid = state.get("session_id")
    if sid:
        r = await api.get(f"/api/session/{sid}")
        if r.status_code == 200:
            return sid
    r = await api.post("/api/session", json={
        "title": "Телефон", "agent": AGENT, "model": MODEL,
        "location": {"directory": WORKDIR},
    })
    r.raise_for_status()
    state["session_id"] = r.json()["data"]["id"]
    save_state()
    return state["session_id"]


app = FastAPI(title="Bridge")


def auth(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")) -> None:
    t = (token or request.query_params.get("token") or "").strip()
    if "token=" in t:
        t = t[t.index("token=") + 6:].split("&")[0]
    t = t.strip(" \t\r\n\"'`«»")
    if t != TOKEN:
        ua = request.headers.get("user-agent", "")[:60]
        got = (t or "")[:6] + "…" if t else "пусто"
        logc_local(f"401 {request.url.path} ip={request.client.host if request.client else '?'} ua={ua} token={got} len={len(t or '')}")
        raise HTTPException(401, "bad token")


@app.get("/api/ping")
async def ping():
    return {"ok": True}


# --- Управление питанием -------------------------------------------------
# WOL: Magic Packet на MAC Wi-Fi адаптера, чтобы разбудить уснувший ноут с телефона.
WOL_MAC = "30-E3-A4-D4-DD-2A"


def send_wol(mac: str = WOL_MAC) -> bool:
    """Шлёт magic packet (6x FF + MAC, повторённый 16 раз) на broadcast:9."""
    try:
        import socket
        addr = mac.replace("-", ":").replace(":", "")
        if len(addr) != 12:
            return False
        payload = b"\xff" * 6 + bytes.fromhex(addr) * 16
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            s.sendto(payload, ("255.255.255.255", 9))
        s.close()
        return True
    except Exception:
        return False


@app.post("/api/power")
async def power(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Действия: shutdown / reboot / sleep / lock / wake (magic packet)."""
    auth(request, token)
    body = await request.json()
    action = body.get("action")
    cmds = {
        "shutdown": ["shutdown.exe", "/s", "/t", "5", "/c", "Выключение с телефона"],
        "reboot": ["shutdown.exe", "/r", "/t", "5", "/c", "Перезагрузка с телефона"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    }
    if action == "wake":
        ok = send_wol()
        return {"ok": ok, "action": action}
    if action not in cmds:
        raise HTTPException(400, "unknown action")
    subprocess.Popen(cmds[action], creationflags=subprocess.CREATE_NO_WINDOW)
    return {"ok": True, "action": action}


ASSETLINKS = [{
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
        "namespace": "android_app",
        "package_name": "ru.f0rn1.assibridge",
        "sha256_cert_fingerprints": [
            "03:59:D5:37:50:9A:E7:D5:0F:91:50:09:2D:D9:91:8C:23:10:BC:E0:D2:5D:EB:59:02:0E:C6:40:26:41:37:3D",
        ],
    },
}]


@app.get("/.well-known/assetlinks.json")
async def assetlinks():
    """Digital Asset Links: без этого Chrome не считает приложение доверенным и падает в Custom Tab."""
    return JSONResponse(ASSETLINKS)



CLIENT_LOG = ROOT / "client.log"


@app.post("/api/clientlog")
async def clientlog(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Копилка сообщений с телефона — чтобы отлаживать, не подключаясь к консоли."""
    auth(request, token)
    body = await request.json()
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {body.get('msg', '')[:800]}\n"
    with CLIENT_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    return {"ok": True}


@app.get("/api/clientlog")
async def clientlog_read(token: str | None = Header(default=None, alias="X-Bridge-Token")):
    return {"log": CLIENT_LOG.read_text(encoding="utf-8")[-4000:] if CLIENT_LOG.exists() else ""}


@app.post("/api/chat")
async def chat(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    auth(request, token)
    body = await request.json()
    text = (body.get("text") or "").strip()
    files = body.get("files") or []
    if files:
        text += "\n\nФайлы (пользователь прислал с телефона, пути локальные):\n" + "\n".join(f"- {f}" for f in files)
    if not text:
        raise HTTPException(400, "empty")
    sid = await ensure_session()
    # Асинхронно: не ждём постановку промпта, чтобы телефон не держал долгий запрос
    # (мобильные сети режут длинные соединения — отсюда Failed to fetch).
    async def _send():
        try:
            r = await api.post(f"/api/session/{sid}/prompt", json={"text": text})
            if r.status_code >= 400:
                logc_local(f"prompt error: {r.status_code} {r.text[:200]}")
        except Exception as e:
            logc_local(f"prompt exception: {e}")
    asyncio.create_task(_send())
    return {"ok": True}


def logc_local(msg: str) -> None:
    """Пишем ошибки отправки в client.log, чтобы видеть проблемы с телефона."""
    try:
        with CLIENT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} bridge: {msg}\n")
    except Exception:
        pass


FILE_BLOCK = "\n\nФайлы (пользователь прислал с телефона, пути локальные):\n"


def split_files(text: str) -> tuple[str, list[str]]:
    """Отделяет служебный блок с путями от текста сообщения."""
    if FILE_BLOCK not in text:
        return text, []
    head, _, tail = text.partition(FILE_BLOCK)
    files = [line.strip()[2:].strip() for line in tail.splitlines() if line.strip().startswith("- ")]
    return head.strip(), [f for f in files if f]


def render(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["type"] == "user":
            text, files = split_files(m.get("text", ""))
            out.append({"role": "user", "text": text, "time": m["time"]["created"], "files": files})
        elif m["type"] == "assistant":
            parts = [c.get("text", "") for c in m.get("content") or [] if c.get("type") == "text"]
            out.append({"role": "assistant", "text": "".join(parts), "time": m["time"]["created"],
                        "done": bool(m["time"].get("completed")),
                        "error": (m.get("error") or {}).get("message")})
    return out


STREAM_EVENTS = [
    "session.text.started", "session.text.delta", "session.text.ended",
    "session.execution.succeeded", "session.execution.failed",
    "session.execution.interrupted",
]


@app.get("/api/stream")
async def stream(request: Request, t: str | None = None):
    """Прокси SSE от OpenCode: телефон видит ответ по мере генерации."""
    if t != TOKEN:
        raise HTTPException(401, "bad token")
    sid = await ensure_session()

    async def gen():
        params = [("types", e) for e in STREAM_EVENTS]
        c = httpx.AsyncClient(base_url=f"http://127.0.0.1:{OPENCODE_PORT}", timeout=None,
                              auth=("opencode", state.get("password")))
        try:
            async with c.stream("GET", "/api/event", params=params) as r:
                if r.status_code != 200:
                    yield 'data: {"type":"bridge.error","data":{"message":"upstream "}}' + "\n\n"
                    return
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    data = ev.get("data") or {}
                    if data.get("sessionID") not in (None, sid):
                        continue
                    yield "data: " + json.dumps({"type": ev.get("type"), "data": data}, ensure_ascii=False) + "\n\n"
                    if await request.is_disconnected():
                        break
        except Exception as e:
            yield 'data: ' + json.dumps({"type": "bridge.error", "data": {"message": str(e)}}, ensure_ascii=False) + "\n\n"
        finally:
            await c.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history")
async def history(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    auth(request, token)
    sid = await ensure_session()
    r = await api.get(f"/api/session/{sid}/message", params={"order": "asc"})
    r.raise_for_status()
    info = await api.get(f"/api/session/{sid}")
    title = (info.json().get("data") or {}).get("title") if info.status_code == 200 else None
    return {"messages": render(r.json()["data"]), "session": sid, "title": title}


@app.get("/api/sessions")
async def sessions(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Список чатов в OpenCode: свежие сверху."""
    auth(request, token)
    await ensure_session()
    r = await api.get("/api/session")
    r.raise_for_status()
    items = r.json()
    items = items.get("data") if isinstance(items, dict) else items
    out = []
    for s in items or []:
        t = (s.get("time") or {})
        out.append({
            "id": s.get("id"),
            "title": s.get("title") or "без названия",
            "updated": t.get("updated") or t.get("created") or 0,
            "busy": bool(t.get("busy")),
            "agent": s.get("agent"),
        })
    out.sort(key=lambda s: s["updated"], reverse=True)
    return {"sessions": out[:60], "current": state.get("session_id")}


@app.post("/api/session/new")
async def session_new(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Новый чат."""
    auth(request, token)
    await ensure_server()
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    title = (body.get("title") or "").strip() or "Телефон " + datetime.datetime.now().strftime("%d.%m %H:%M")
    r = await api.post("/api/session", json={
        "title": title, "agent": AGENT, "model": MODEL,
        "location": {"directory": WORKDIR},
    })
    if r.status_code >= 400:
        raise HTTPException(502, r.text[:300])
    state["session_id"] = r.json()["data"]["id"]
    save_state()
    return {"ok": True, "session": state["session_id"], "title": title}


@app.post("/api/session/select")
async def session_select(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Переключиться на существующий чат."""
    auth(request, token)
    body = await request.json()
    sid = body.get("id") or ""
    if not sid.startswith("ses_"):
        raise HTTPException(400, "bad session id")
    await ensure_server()
    r = await api.get(f"/api/session/{sid}")
    if r.status_code != 200:
        raise HTTPException(404, "нет такого чата")
    state["session_id"] = sid
    save_state()
    return {"ok": True, "session": sid}


MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".gif": "image/gif", ".heic": "image/heic", ".mp4": "video/mp4", ".webm": "video/webm",
         ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".mp3": "audio/mpeg",
         ".ogg": "audio/ogg", ".m4a": "audio/mp4"}


@app.get("/api/file")
async def get_file(request: Request, path: str, t: str | None = None, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Отдаёт присланный с телефона файл (только из Inbox). Токен можно передать ?t= для <img>."""
    auth(request, token or t)
    p = Path(path).resolve()
    try:
        p.relative_to(INBOX.resolve())
    except ValueError:
        raise HTTPException(403, "вне Inbox")
    if not p.is_file():
        raise HTTPException(404, "нет файла")
    return FileResponse(p, media_type=MEDIA.get(p.suffix.lower()))


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), token: str | None = Header(default=None, alias="X-Bridge-Token")):
    auth(request, token)
    day = INBOX / datetime.date.today().isoformat()
    day.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "file").name
    dst = day / name
    i = 1
    while dst.exists():
        dst = day / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dst), "name": dst.name, "size": dst.stat().st_size,
            "media": MEDIA.get(dst.suffix.lower())}


_whisper = None


@app.post("/api/transcribe")
async def transcribe(request: Request, file: UploadFile = File(...), seconds: str | None = Form(default=None),
                     token: str | None = Header(default=None, alias="X-Bridge-Token")):
    auth(request, token)
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    tmp = Path(os.environ["TEMP"]) / f"voice-{int(time.time())}-{file.filename or 'a.webm'}"
    with tmp.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        segments, info = _whisper.transcribe(str(tmp), language="ru", vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        line = (f"{datetime.datetime.now().isoformat(timespec='seconds')} voice: client={seconds}s "
                f"audio={getattr(info, 'duration', 0):.1f}s vad={getattr(info, 'duration_after_vad', 0):.1f}s "
                f"bytes={tmp.stat().st_size} chars={len(text)}\n")
        with CLIENT_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    finally:
        tmp.unlink(missing_ok=True)
    return {"text": text}


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


APK_PATH = Path.home() / "tools" / "apk-build" / "app-release-signed.apk"


@app.get("/apk")
async def apk():
    """Свежий APK — чтобы ставить приложение на телефон без кабеля."""
    if not APK_PATH.exists():
        raise HTTPException(404, "apk not built")
    return FileResponse(APK_PATH, filename="assi.apk", media_type="application/vnd.android.package-archive")


app.mount("/", StaticFiles(directory=ROOT / "static"), name="static")


def lan_ips() -> list[str]:
    """Все IPv4 адреса машины во всех сетях (Wi-Fi, хотспот, Ethernet)."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    # адрес основного маршрута (UDP-соединение ничего не отправляет)
    for probe in ("8.8.8.8", "10.255.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))
                ips.add(s.getsockname()[0])
        except OSError:
            pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


if __name__ == "__main__":
    import uvicorn

    print(f"token: {TOKEN}", flush=True)
    print("адреса для телефона:", flush=True)
    for ip in lan_ips():
        print(f"  http://{ip}:{BIND[1]}/", flush=True)
    uvicorn.run(app, host=BIND[0], port=BIND[1], log_level="info")
