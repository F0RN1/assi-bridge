"""Мост телефон <-> OpenCode. FastAPI + PWA + faster-whisper."""
import asyncio, base64, json, os, re, secrets, shutil, socket, subprocess, sys, tempfile, time, uuid, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
# Экземпляр можно запускать по несколько: параметры через переменные окружения.
INSTANCE = os.environ.get("ASSI_INSTANCE", "assi")
STATE = ROOT / f"bridge{'' if INSTANCE == 'assi' else '-' + INSTANCE}.json"
INBOX = Path.home() / "Inbox" if INSTANCE == "assi" else Path.home() / "Inbox" / INSTANCE
OPENCODE_PORT = int(os.environ.get("ASSI_OPENCODE_PORT", 8790))
BIND = ("0.0.0.0", int(os.environ.get("ASSI_PORT", 8787)))
PUBLIC_URL = os.environ.get("ASSI_PUBLIC_URL", "https://assi.assi.pro")
# Владелец машины — только основной экземпляр "assi".
# Гостевые экземпляры (friend, slava) получают лишь чат: без проводника, питания и очереди файлов.
OWNER = INSTANCE == "assi"
MODEL = {"providerID": "opencode", "id": "deepseek-v4.1-flash-free"}
AGENT = "build"
WORKDIR = str(Path.home())
# Какие кнопки питания реально включены на этом сервере.
# shutdown/reboot — только когда на машине заведомо работают права и политика; по умолчанию выключены.
POWER_ACTIONS = [a.strip() for a in
                 os.environ.get("ASSI_POWER_ACTIONS", "wake,sleep,lock").split(",") if a.strip()]

state = json.loads(STATE.read_text("utf-8")) if STATE.exists() else {}


def save_state():
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


if "token" not in state:
    state["token"] = secrets.token_urlsafe(18)
    save_state()

TOKEN = state["token"]
if "public_url" not in state:
    state["public_url"] = PUBLIC_URL
    save_state()
if state.get("port") != BIND[1] or state.get("instance") != INSTANCE:
    state["port"] = BIND[1]
    state["instance"] = INSTANCE
    save_state()
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


def owner_only() -> None:
    """Всё, что трогает компьютер владельца, — только для экземпляра "assi"."""
    if not OWNER:
        raise HTTPException(403, "гостевой режим: доступ к компьютеру закрыт")


@app.get("/api/ping")
async def ping():
    return {"ok": True, "owner": OWNER, "instance": INSTANCE}


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


@app.get("/api/wol-info")
async def wol_info(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """MAC ноута и broadcast-адреса — приложение шлёт magic packet само, когда сервер спит."""
    auth(request, token)
    owner_only()
    bcasts = ["255.255.255.255"]
    try:
        for ip in lan_ips():
            if ip.startswith(("127.", "169.254.")):
                continue
            bcasts.append(ip.rsplit(".", 1)[0] + ".255")
    except Exception:
        pass
    return {"mac": WOL_MAC, "broadcasts": ",".join(dict.fromkeys(bcasts)),
            "actions": POWER_ACTIONS}


@app.post("/api/power")
async def power(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Действия: shutdown / reboot / sleep / lock / wake (magic packet)."""
    auth(request, token)
    owner_only()
    body = await request.json()
    action = body.get("action")
    if action not in POWER_ACTIONS:
        raise HTTPException(403, "action disabled")
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



CLIENT_LOG = ROOT / (f"client{'' if INSTANCE == 'assi' else '-' + INSTANCE}.log")
SHARE_DIR = ROOT / ("shared" if INSTANCE == "assi" else f"shared-{INSTANCE}")


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
            text = "".join(parts)
            # шаг агента без текста (вызов инструментов) в ленте не показываем:
            # иначе на телефоне висит пустой пузырь с точками
            if not text.strip() and not (m.get("error") or {}).get("message"):
                continue
            out.append({"role": "assistant", "text": text, "time": m["time"]["created"],
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
                    yield 'data: ' + json.dumps({"type": "bridge.error", "data": {"message": f"upstream {r.status_code}"}}, ensure_ascii=False) + "\n\n"
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


# ---------- файлы ПК -> телефон ----------

def _human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.0f}"


def _fs_guard(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise HTTPException(400, "нужен абсолютный путь")
    rp = p.resolve()
    if os.name == "nt":
        blocked = [Path(f"{d}:\\{s}") for d in "CDEFGHIJ" for s in ("Windows", "$Recycle.Bin", "System Volume Information")]
        for b in blocked:
            try:
                rp.relative_to(b)
                raise HTTPException(403, "системная папка")
            except ValueError:
                pass
    return rp


@app.get("/api/fs/list")
async def fs_list(request: Request, path: str = "",
                  token: str | None = Header(default=None, alias="X-Bridge-Token"),
                  t: str | None = None):
    """Проводник по компьютеру: без path — список дисков и быстрых папок."""
    auth(request, token or t)
    owner_only()
    if not path.strip():
        entries = []
        if os.name == "nt":
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                d = Path(f"{letter}:\\")
                if d.exists():
                    entries.append({"name": f"Локальный диск ({letter}:)", "path": str(d), "dir": True})
        home = Path.home()
        for label, sub in (("Загрузки", "Downloads"), ("Изображения", "Pictures"),
                           ("Документы", "Documents"), ("Рабочий стол", "Desktop")):
            d = home / sub
            if d.is_dir():
                entries.append({"name": label, "path": str(d), "dir": True, "quick": True})
        entries.append({"name": "Домашняя папка", "path": str(home), "dir": True, "quick": True})
        return {"path": "", "parent": None, "entries": entries}

    p = _fs_guard(path)
    if not p.is_dir():
        raise HTTPException(404, "нет такой папки")
    entries = []
    try:
        for it in p.iterdir():
            try:
                st = it.stat()
                is_dir = it.is_dir()
                if it.name in ("$Recycle.Bin", "System Volume Information"):
                    continue
                entries.append({
                    "name": it.name,
                    "path": str(it),
                    "dir": is_dir,
                    "size": 0 if is_dir else st.st_size,
                    "size_text": "" if is_dir else _human_size(st.st_size),
                    "mtime": int(st.st_mtime),
                    "ext": "" if is_dir else it.suffix.lower().lstrip("."),
                })
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(403, "нет доступа")
    entries.sort(key=lambda e: (not e["dir"], e["name"].casefold()))
    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "entries": entries[:800]}


@app.get("/api/fs/download")
async def fs_download(request: Request, path: str, t: str | None = None,
                      token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Отдаёт файл с ПК на телефон (токен можно ?t= — так скачивает DownloadManager в приложении)."""
    auth(request, token or t)
    owner_only()
    p = _fs_guard(path)
    if not p.is_file():
        raise HTTPException(404, "нет файла")
    return FileResponse(p, media_type=MEDIA.get(p.suffix.lower()),
                        filename=p.name, headers={"X-Content-Type-Options": "nosniff"})


@app.post("/api/fs/upload")
async def fs_upload(request: Request, path: str, file: UploadFile = File(...),
                    t: str | None = None, token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Кладёт файл с телефона прямо в выбранную папку компьютера — без участия агента."""
    auth(request, token or t)
    owner_only()
    dest = _fs_guard(path)
    if not dest.is_dir():
        raise HTTPException(404, "нет такой папки")
    name = Path(file.filename or "file").name
    target = dest / name
    i = 1
    while target.exists():
        target = dest / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    try:
        with target.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except PermissionError:
        raise HTTPException(403, "нет доступа к папке")
    return {"ok": True, "name": target.name, "path": str(target),
            "size": target.stat().st_size, "size_text": _human_size(target.stat().st_size)}


@app.post("/api/share")
async def share_add(request: Request, file: UploadFile = File(...),
                    token: str | None = Header(default=None, alias="X-Bridge-Token")):
    """Компьютер → телефон: файл кладётся в очередь, приложение забирает его само."""
    auth(request, token)
    owner_only()
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    name = Path(file.filename or "file").name
    target = SHARE_DIR / f"{sid}__{name}"
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    item = {"id": sid, "name": name, "size": target.stat().st_size,
            "size_text": _human_size(target.stat().st_size), "ts": int(time.time())}
    state.setdefault("share", []).append(item)
    save_state()
    return {"ok": True, **item}


@app.get("/api/share")
async def share_list(request: Request, token: str | None = Header(default=None, alias="X-Bridge-Token"),
                     t: str | None = None):
    auth(request, token or t)
    owner_only()
    items = [it for it in state.get("share", []) if (SHARE_DIR / f"{it['id']}__{it['name']}").exists()]
    return {"items": items}


@app.get("/api/share/{sid}")
async def share_get(sid: str, request: Request, t: str | None = None,
                    token: str | None = Header(default=None, alias="X-Bridge-Token")):
    auth(request, token or t)
    owner_only()
    for it in state.get("share", []):
        if it["id"] == sid:
            p = SHARE_DIR / f"{sid}__{it['name']}"
            if p.is_file():
                return FileResponse(p, filename=it["name"],
                                    headers={"X-Content-Type-Options": "nosniff"})
    raise HTTPException(404, "нет файла")


@app.post("/api/share/{sid}/ack")
async def share_ack(sid: str, request: Request,
                    token: str | None = Header(default=None, alias="X-Bridge-Token")):
    auth(request, token)
    owner_only()
    kept = []
    for it in state.get("share", []):
        if it["id"] == sid:
            try:
                (SHARE_DIR / f"{sid}__{it['name']}").unlink(missing_ok=True)
            except OSError:
                pass
            continue
        kept.append(it)
    state["share"] = kept
    save_state()
    return {"ok": True}


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
    # имя файла санитизируем (без .name путь с ..\ выносит запись вне каталога) + uuid от коллизий
    tmp = Path(tempfile.gettempdir()) / f"voice-{uuid.uuid4().hex}-{Path(file.filename or 'a.webm').name}"
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
    # HTML не кэшируем: интерфейс обновляется с сервера, а WebView любит держать старую копию
    return FileResponse(ROOT / "static" / "index.html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


APK_PATHS = [
    Path.home() / "tools" / "apk-webview" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk",
    Path.home() / "tools" / "apk-build" / "app-release-signed.apk",
]
APK_PATH = next((p for p in APK_PATHS if p.exists()), APK_PATHS[-1])


@app.get("/apk")
async def apk():
    """Свежий APK — чтобы ставить приложение на телефон без кабеля."""
    if not APK_PATH.exists():
        raise HTTPException(404, "apk not built")
    return FileResponse(APK_PATH, filename="assi.apk", media_type="application/vnd.android.package-archive")


HUB_CSS = """
:root{
  --bg:#0a0a0c; --surface:#101216; --surface-2:#15181e; --line:rgba(255,255,255,.08);
  --text:#e8edf5; --muted:#7c8798; --lime:#bbf351; --cyan:#00bcff; --red:#ff5f57;
  --mono:"Cascadia Mono","Source Code Pro",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:"Inter",-apple-system,"Segoe UI",Roboto,ui-sans-serif,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 500px at 50% -180px,#151a14,transparent 70%),var(--bg);
  color:var(--text);font:400 15px/1.55 var(--sans);-webkit-font-smoothing:antialiased;padding:28px 20px 56px}
.wrap{max-width:900px;margin:0 auto}
header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:26px;flex-wrap:wrap}
h1{margin:0;font:600 26px/1.15 var(--mono);letter-spacing:-.02em}
h1 .dot{color:var(--lime)}
.sub{margin:6px 0 0;color:var(--muted);font:12px/1.4 var(--mono);letter-spacing:.06em;text-transform:uppercase}
.btn{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:0 16px;border-radius:10px;
  border:1px solid var(--line);background:var(--surface);color:var(--text);font:500 13px/1 var(--mono);
  text-decoration:none;cursor:pointer;transition:background .16s ease,border-color .16s ease,transform .16s ease}
.btn:hover{background:var(--surface-2);border-color:rgba(255,255,255,.16)}
.btn:active{transform:translateY(1px)}
.btn:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
.btn.primary{background:var(--lime);border-color:var(--lime);color:#0a0a0c;font-weight:600}
.btn.primary:hover{filter:brightness(1.06);background:var(--lime)}
.btn svg{width:16px;height:16px;flex:none}
.grid{display:grid;gap:14px;grid-template-columns:1fr}
@media(min-width:780px){.grid{grid-template-columns:1fr 1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px;
  display:flex;flex-direction:column;gap:14px}
.card .top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.name{font:600 14px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border-radius:999px;
  font:500 11px/1 var(--mono);letter-spacing:.04em;border:1px solid transparent}
.pill i{width:6px;height:6px;border-radius:50%;background:currentColor;display:block}
.pill.ok{color:var(--lime);background:rgba(187,243,81,.1);border-color:rgba(187,243,81,.25)}
.pill.bad{color:var(--red);background:rgba(255,95,87,.1);border-color:rgba(255,95,87,.25)}
.port{margin-left:auto;color:var(--muted);font:12px/1 var(--mono)}
.field{display:flex;flex-direction:column;gap:5px}
.k{color:var(--muted);font:11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase}
.val{font:13px/1.5 var(--mono);word-break:break-all;color:var(--cyan)}
.mask{color:var(--muted);letter-spacing:.12em}
.acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.mini{min-height:32px;padding:0 10px;font-size:12px;border-radius:8px}
.qr{display:none;align-items:center;gap:14px;padding:12px;background:#fff;border-radius:12px;color:#0a0a0c}
.qr.on{display:flex}
.qr svg{width:132px;height:132px;display:block}
.qr .cap{font:12px/1.45 var(--mono);color:#0a0a0c}
footer{margin-top:26px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font:12px/1.7 var(--mono)}
footer b{color:var(--text);font-weight:500}
.toast{position:fixed;left:50%;bottom:24px;transform:translate(-50%,16px);opacity:0;pointer-events:none;
  background:var(--lime);color:#0a0a0c;font:600 12px/1 var(--mono);padding:10px 16px;border-radius:999px;
  transition:opacity .18s ease,transform .18s ease}
.toast.on{opacity:1;transform:translate(-50%,0)}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

HUB_JS = """
const toast=(t)=>{const el=document.getElementById('toast');el.textContent=t;el.classList.add('on');
  clearTimeout(window._tt);window._tt=setTimeout(()=>el.classList.remove('on'),1400)};
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',async()=>{
  const v=b.getAttribute('data-copy');
  try{await navigator.clipboard.writeText(v);}catch(_){
    const ta=document.createElement('textarea');ta.value=v;document.body.appendChild(ta);
    ta.select();document.execCommand('copy');ta.remove();
  }
  toast('скопировано');
}));
document.querySelectorAll('[data-reveal]').forEach(b=>b.addEventListener('click',()=>{
  const el=document.getElementById(b.getAttribute('data-reveal'));
  const full=el.getAttribute('data-token')||'';
  const hide=!el.classList.contains('mask');
  el.textContent = hide ? '•'.repeat(Math.min(full.length,20)) : full;
  el.classList.toggle('mask', hide);
  b.textContent = hide ? 'показать' : 'скрыть';
}));
document.querySelectorAll('[data-qr]').forEach(b=>b.addEventListener('click',()=>{
  const el=document.getElementById(b.getAttribute('data-qr'));el.classList.toggle('on');
}));
"""

COPY_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
             'stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/>'
             '<path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>')
OPEN_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4 10 14"/>'
             '<path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/></svg>')
APK_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/>'
            '<path d="M5 21h14"/></svg>')


def qr_svg(data: str) -> str:
    """QR-код локально, без обращения к внешним сервисам (токен никуда не уходит)."""
    try:
        import segno
        return segno.make(data, error="m").svg_inline(scale=4, border=2,
                                                      dark="#0a0a0c", light="#ffffff")
    except Exception:
        return ""


def hub_instances() -> list[dict]:
    found = []
    for p in sorted(ROOT.glob("bridge*.json")):
        try:
            st = json.loads(p.read_text("utf-8"))
        except Exception:
            continue
        name = "assi" if p.name == "bridge.json" else p.stem.split("-", 1)[1]
        found.append({"name": name, "st": st})
    found.sort(key=lambda x: (x["name"] != INSTANCE, x["name"]))
    return found


@app.get("/local")
async def local_info(request: Request):
    """Хаб: все мосты на этом компьютере — адреса, токены, состояние. Только с localhost."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(404, "not found")

    from html import escape
    cards = []
    for item in hub_instances():
        st = item["st"]
        name = escape(item["name"])
        pub = (st.get("public_url") or "").rstrip("/")
        port = st.get("port") or (8787 if item["name"] == "assi" else "")
        tok = st.get("token") or ""
        link = f"{pub}/?token={tok}" if pub and tok else ""
        alive = False
        if port:
            try:
                async with httpx.AsyncClient(timeout=2) as hc:
                    r = await hc.get(f"http://127.0.0.1:{port}/api/ping")
                    alive = r.status_code == 200 and '"ok"' in r.text
            except Exception:
                alive = False
        pill = ('<span class="pill ok"><i></i>отвечает</span>' if alive
                else '<span class="pill bad"><i></i>не отвечает</span>')
        qr_id = "qr-" + item["name"]
        cards.append(f"""
        <article class="card">
          <div class="top">
            <span class="name">{name}</span>{pill}
            <span class="port">{'порт ' + str(port) if port else ''}</span>
          </div>
          <div class="field"><span class="k">адрес сервера</span>
            <span class="val">{escape(pub or '—')}</span></div>
          <div class="field"><span class="k">токен</span>
            <span class="val"><span id="tok-{name}" class="mask" data-token="{escape(tok)}">{'•' * 14}</span></span></div>
          <div class="acts">
            <button class="btn mini" data-reveal="tok-{name}" type="button">показать</button>
            <button class="btn mini" data-copy="{escape(tok)}" type="button">{COPY_ICON}копировать</button>
            {f'<a class="btn mini primary" href="{escape(link)}" target="_blank" rel="noopener">{OPEN_ICON}открыть чат</a>' if link else ''}
            {f'<button class="btn mini" data-qr="{qr_id}" type="button">QR</button>' if link else ''}
          </div>
          {f'<div class="qr" id="{qr_id}">{qr_svg(link)}<div class="cap">наведи камеру телефона —<br>страница откроется с токеном</div></div>' if link else ''}
        </article>""")

    apk_note = ""
    if APK_PATH.exists():
        kb = APK_PATH.stat().st_size // 1024
        when = datetime.datetime.fromtimestamp(APK_PATH.stat().st_mtime).strftime("%d.%m %H:%M")
        apk_note = f"{kb} КБ · собран {when}"

    lan = ""
    ips = lan_ips()
    for pref in ("192.168.", "10.", "172."):
        hit = next((ip for ip in ips if ip.startswith(pref)), None)
        if hit:
            lan = hit
            break
    html_page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Assi Hub — мосты на этом компьютере</title>
<style>{HUB_CSS}</style></head>
<body><div class="wrap">
<header>
  <div>
    <h1><span class="dot">◆</span> Assi Hub</h1>
    <p class="sub">мосты и токены · только этот компьютер</p>
  </div>
  <a class="btn primary" href="/apk">{APK_ICON}скачать APK</a>
</header>
<div class="grid">{''.join(cards)}</div>
<footer>
  <b>Приложение:</b> адрес — строка «адрес сервера», токен — кнопкой «копировать». {apk_note}<br>
  <b>Та же сеть без туннеля:</b> {f'http://{escape(lan)}:{BIND[1]} — если телефон в одном Wi-Fi с ноутом.' if lan else 'нет сетевого адреса.'}<br>
  <b>Наружу:</b> через cloudflared-туннель, домены вида https://assi.assi.pro.
</footer>
</div><div id="toast" class="toast"></div>
<script>{HUB_JS}</script></body></html>"""
    return HTMLResponse(html_page)


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
