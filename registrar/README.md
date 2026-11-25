# Registrar — постоянные адреса `<имя>.assi.pro`

Cloudflare Worker, который по пригласительному коду создаёт туннель и DNS-запись:
человек получает `https://<имя>.assi.pro` и токен туннеля, и его мост живёт на
постоянном адресе без `trycloudflare.com` и без запущенного `cloudflared` на ПК
(токен запускает туннель сам).

Всё делается руками в панели Cloudflare — сборка не нужна, `worker.js` — один файл.

## 1. Создать Worker

1. Открыть [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → **Worker**.
2. Имя: `assi-registrar`. **Deploy**.
3. **Edit code** → вставить целиком содержимое `worker.js` → **Deploy**.

## 2. Привязать KV для лимитов

1. **Storage & Databases** → **KV** → **Create namespace** → имя `assi-limits`.
2. Вернуться в Worker → **Settings** → **Bindings** → **Add** → **KV namespace**:
   - Variable name: `LIMITS`
   - KV namespace: `assi-limits`

Без этого `/register` ответит «KV-пространство LIMITS не привязано».

## 3. Секреты

**Settings** → **Variables and Secrets** → **Add** (тип **Secret**):

| Имя | Что это |
| --- | --- |
| `CF_API_TOKEN` | API-токен Cloudflare (см. ниже) |
| `CF_ACCOUNT_ID` | ID аккаунта (правый сайдбар панели, или из URL `dash.cloudflare.com/<ID>`) |
| `CF_ZONE_ID` | ID зоны `assi.pro`: **Overview** зоны → правый сайдбар → **Zone ID** |
| `INVITE_CODES` | пригласительные коды через запятую, например `forni-2026,slava-4417` |
| `ADMIN_KEY` | необязательный ключ владельца: с ним `/release` работает без пригласительного кода. Придумай длинную случайную строку |

### Токен Cloudflare

**My Profile** → **API Tokens** → **Create Token** → **Custom token**:

- **Account** → *Cloudflare Tunnel* → **Edit**
- **Zone** → *DNS* → **Edit** — зона `assi.pro`
- (опционально) ограничить по IP/сроку

Скопировать токен сразу — второй раз он не показывается. Секреты в репозиторий
не попадают: они живут только в панели Cloudflare.

## 4. Проверить

```powershell
curl.exe https://assi-registrar.<твой-поддомен>.workers.dev/health
# {"ok":true,"service":"assi-registrar"}

curl.exe -X POST https://assi-registrar.<...>.workers.dev/register `
  -H "content-type: application/json" `
  -d '{"name":"test1","invite":"forni-2026"}'
# {"ok":true,"url":"https://test1.assi.pro","token":"..."}
```

Потом этот же `token` вставляется в `bridge.json` как `tunnel_token`, либо
`setup.ps1` делает это сам (пункт «постоянный адрес»), если вверху скрипта
заполнено `$RegistrarUrl`.

## API

| Метод | Путь | Тело | Ответ |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{"ok":true}` |
| `POST` | `/register` | `{"name","invite"}` | `{"ok":true,"url","token"}` |
| `POST` | `/release` | `{"name","invite"}` или `{"name"}` + заголовок `X-Admin-Key` | `{"ok":true,"released"}` |

Правила:

- имя — 2–8 символов, `[a-z0-9]`; зарезервированы `assi`, `friend`, `slava`,
  `www`, `api`, `mail`, `registrar`, `admin`, `root`;
- без пригласительного кода — `403` (кроме `/release` с верным `X-Admin-Key`);
- занятое имя (или уже выданное) — `409` / повторная выдача того же токена;
- не больше 5 регистраций с одного IP в сутки и 25 адресов всего — `429`;
- ingress туннеля всегда указывает на `http://localhost:8787`, менять его снаружи
  нельзя: адрес — это только вход, а мост на машине пользователя.

## Убрать адрес без кода приглашения

Если завёл секрет `ADMIN_KEY`, `/release` можно звать без `invite`:

```powershell
curl.exe -X POST https://assi-registrar.<...>.workers.dev/release `
  -H "content-type: application/json" -H "X-Admin-Key: <ключ>" `
  -d "{\"name\":\"slava\"}"
```

Из репозитория то же самое делает `release.ps1`:

```powershell
.\release.ps1 -Name slava -AdminKey <ключ>
# или положить ключ в окружение и не указывать вовсе:
$env:ASSI_ADMIN_KEY = '<ключ>'; .\release.ps1 -Name slava
```

Без `ADMIN_KEY` всё работает по-старому: нужен любой действующий код из
`INVITE_CODES`.

## Ограничения

- Cloudflare разрешает **25 туннелей на аккаунт** (free) — отсюда `TOTAL_LIMIT`.
  Менять лимиты — в `worker.js`, константы `DAILY_PER_IP` и `TOTAL_LIMIT`.
- Пригласительные коды общие: один код можно дать нескольким людям. Если нужен
  код «на одного» — удалять его из `INVITE_CODES` после выдачи.
- `/release` удаляет DNS и туннель, но счётчик `total` уменьшает на единицу —
  этого достаточно для лимита.
