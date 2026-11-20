# Assi Bridge

Мост между телефоном и компьютером: телефон становится пультом для [OpenCode](https://opencode.ai) — чат с агентом, файлы и фото, голосовой ввод, управление питанием ПК.

<p align="center"><img src="docs/hub.png" alt="Assi Hub — страница /local" width="820"></p>

## Что умеет

- **Чат** с агентом OpenCode из браузера или приложения (SSE-стриминг ответа, markdown, история сессий, переключение и создание чатов).
- **Файлы в обе стороны** — отправка с телефона агенту и **скачивание с ПК**: проводник по дискам прямо в приложении, а любой путь в ответе агента превращается в ссылку «скачать на телефон». Файл с телефона можно положить **прямо в любую папку ПК** (кнопка загрузки в проводнике), без участия агента.
- **Трей на ПК** — `phone_tray.py`: правый клик по иконке → «Отправить файл на телефон», файл сам приезжает в «Загрузки» телефона.
- **Голос** — запись в браузере, расшифровка локально через `faster-whisper` (без внешних сервисов).
- **Питание ПК** — сон, блокировка, перезагрузка, выключение, а также **Wake-on-LAN** (шлёт само приложение, когда сервер спит).
- **Сторож связи** — приложение пингует `/api/ping`; если ноут уснул, показывает «Разбудить ноут» вместо ошибки Cloudflare.
- **Хаб `/local`** — локальная страница со всеми мостами: адрес, токен, статус, QR-код, кнопка скачать APK.
- **Несколько экземпляров** — каждый со своим портом, токеном, доменом и историей (переменные окружения).

## Быстрый старт

```powershell
git clone https://github.com/F0RN1/assi-bridge.git
cd assi-bridge
powershell -ExecutionPolicy Bypass -File install-assi.ps1
```

Скрипт проверит Python (нет — поставит через winget), создаст `.venv`, поставит зависимости, запустит мост и откроет `http://127.0.0.1:8787/local` с адресом и токеном.

Флаг `-Autostart` добавит ярлык в автозагрузку.

Требуется установленный и авторизованный **OpenCode** — мост поднимает `opencode serve` сам.

## Доступ снаружи

Мост слушает `127.0.0.1`-порты и наружу сам не смотрит. Для интернета — туннель Cloudflare:

```yaml
# %USERPROFILE%\.cloudflared\config.yml
tunnel: <tunnel-id>
credentials-file: C:\Users\<user>\.cloudflared\<tunnel-id>.json
protocol: http2
edge-ip-version: "4"

ingress:
  - hostname: assi.example.com
    service: http://127.0.0.1:8787
  - service: http_status:404
```

`protocol: http2` + IPv4 — не Cosmetic: на QUIC (UDP) туннель у части провайдеров рвётся и запросы висят по 30 секунд.

## Второй экземпляр (для друга, теста)

```powershell
powershell -ExecutionPolicy Bypass -File start-friend.ps1
```

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `ASSI_INSTANCE` | `assi` | имя экземпляра: `bridge-<имя>.json`, `client-<имя>.log`, `~/Inbox/<имя>` |
| `ASSI_PORT` | `8787` | порт HTTP |
| `ASSI_OPENCODE_PORT` | `8790` | порт `opencode serve` для этого экземпляра |
| `ASSI_PUBLIC_URL` | `https://assi.assi.pro` | адрес, который показывается на `/local` |

У каждого экземпляра свой токен, своя сессия и своя папка входящих — чаты не пересекаются.

## API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/ping` | проверка живости (без токена) |
| `GET` | `/api/history` | история текущей сессии |
| `POST` | `/api/chat` | отправить сообщение агенту |
| `GET` | `/api/stream?t=<token>` | SSE: дельты текста и завершение |
| `GET` | `/api/sessions` | список сессий, `POST /api/session/new`, `/api/session/select` |
| `POST` | `/api/upload` | файл с телефона → локальный путь |
| `GET` | `/api/fs/list?path=` | проводник: диски, папки, файлы с размерами |
| `GET` | `/api/fs/download?path=&t=` | отдать файл с ПК на телефон |
| `POST` | `/api/fs/upload?path=` | положить файл с телефона в выбранную папку ПК |
| `POST` | `/api/share` | очередь «ПК → телефон» (файл кладёт трей) |
| `GET` | `/api/share`, `/api/share/{id}`, `POST /api/share/{id}/ack` | забрать и подтвердить файл из очереди |
| `POST` | `/api/transcribe` | аудио → текст (faster-whisper) |
| `POST` | `/api/power` | `lock` / `sleep` / `reboot` / `shutdown` |
| `GET` | `/api/wol-info` | MAC и broadcast-адреса для Wake-on-LAN |
| `GET` | `/apk` | свежий APK приложения |
| `GET` | `/local` | хаб с токенами — **только с localhost** |

Авторизация — заголовок `X-Bridge-Token` (или `?t=` для SSE).

## Безопасность

- Токен — единственный ключ ко всему: файлы, сессии, память агента, питание ПК. Никому не передавайте.
- `/local` отдаётся только на `127.0.0.1` — снаружи 404.
- `bridge.json`, `bridge-friend.json`, логи и `.venv` в `.gitignore`.

## Структура

```
app.py                  FastAPI: OpenCode, чат, SSE, загрузки, питание, WOL, /local
static/index.html       интерфейс чата (терминальная тема)
static/sw.js            service worker: оболочка из кэша, /api — всегда в сеть
static/manifest.webmanifest  PWA-манифест
install-assi.ps1        установка в один запуск
start-assi.ps1          запуск основного моста + туннеля
start-friend.ps1        второй экземпляр (8788)
start-tray.ps1          иконка в трее: отправить файл на телефон
phone_tray.py           сам трей (pystray, requirements-tray.txt)
requirements.txt        зависимости
```

Приложение: [F0RN1/assi-app](https://github.com/F0RN1/assi-app).

## Лицензия

MIT
