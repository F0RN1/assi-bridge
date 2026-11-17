# Асси Bridge

Мост между телефоном и ПК: PWA-чат, который ходит в headless-сервер OpenCode
через HTTP API. Файлы с телефона складываются в `Inbox`, голос распознаётся
локально (faster-whisper), ответы приходят потоком по SSE.

## Что внутри

| Файл | Назначение |
|---|---|
| `app.py` | FastAPI: поднимает `opencode serve`, проксирует чат/историю/SSE, принимает файлы и голос |
| `static/index.html` | SPA-чат: инкрементальный рендер, markdown, стриминг, запись с микрофона |
| `static/sw.js` | service worker: оболочка из кэша, `/api/*` всегда из сети |
| `static/manifest.webmanifest` | манифест PWA («Асси», standalone) |
| `make_icons.py` | генерация иконок приложения на Pillow |
| `probe.py` | диагностический стенд для API OpenCode |
| `peek.py` | снимок состояния сессии (сообщения, время, ошибки) |

## Запуск

```powershell
cd $env:USERPROFILE\tools\mobile-bridge
$env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe app.py
```

Мост слушает `0.0.0.0:8787`, сам поднимает `opencode serve` на `127.0.0.1:8790`
и печатает в лог адреса для телефона и токен доступа.

Токен и пароль сервера лежат в `bridge.json` (в репозиторий не попадает).

## Стек

Python 3.12, FastAPI, uvicorn, httpx, faster-whisper (`small`, cpu, int8),
PyAV 13 (более новые ломают декодирование в faster-whisper 1.2.1).
