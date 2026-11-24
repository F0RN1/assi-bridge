/**
 * Assi Registrar — выдаёт постоянные адреса вида <имя>.assi.pro.
 *
 * Один файл, без сборки. Деплой: Cloudflare Dashboard → Workers & Pages →
 * Create Worker → вставить этот код → Deploy. Затем Secrets и KV (см. README.md).
 *
 * Секреты (Settings → Variables → Encrypt):
 *   CF_API_TOKEN   — API-токен Cloudflare: Account → Cloudflare Tunnel → Edit,
 *                    Zone → DNS → Edit (для зоны assi.pro)
 *   CF_ACCOUNT_ID  — ID аккаунта
 *   CF_ZONE_ID     — ID зоны assi.pro
 *   INVITE_CODES   — пригласительные коды через запятую
 *
 * KV-пространство LIMITS привязано как LIMITS (счётчики и реестр имён).
 *
 * Запросы: GET /health, POST /register {name, invite}, POST /release {name, invite}
 */

const API = "https://api.cloudflare.com/client/v4";
const RESERVED = ["assi", "friend", "slava", "www", "api", "mail", "registrar", "admin", "root"];
const NAME_RE = /^[a-z0-9]{2,8}$/;
const DAILY_PER_IP = 5;
const TOTAL_LIMIT = 25;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function bad(message, status = 400) {
  return json({ ok: false, error: message }, status);
}

async function cf(env, path, init = {}) {
  const r = await fetch(API + path, {
    ...init,
    headers: {
      authorization: "Bearer " + env.CF_API_TOKEN,
      "content-type": "application/json",
      ...(init.headers || {}),
    },
  });
  let body = {};
  try {
    body = await r.json();
  } catch (_) {}
  if (!r.ok || body.success === false) {
    const msg =
      (body.errors && body.errors[0] && body.errors[0].message) ||
      "Cloudflare ответил " + r.status;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return body.result;
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function checkInvite(env, invite) {
  const list = (env.INVITE_CODES || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return Boolean(invite) && list.includes(String(invite).trim());
}

function normalizeName(raw) {
  const name = String(raw || "").trim().toLowerCase();
  if (!NAME_RE.test(name)) {
    return { error: "имя: 2–8 символов, только латиница и цифры" };
  }
  if (RESERVED.includes(name)) {
    return { error: "это имя зарезервировано" };
  }
  return { name };
}

async function register(env, req) {
  let body = {};
  try {
    body = await req.json();
  } catch (_) {
    return bad("нужен JSON: {name, invite}");
  }
  if (!checkInvite(env, body.invite)) {
    return bad("пригласительный код не принят", 403);
  }
  const parsed = normalizeName(body.name);
  if (parsed.error) return bad(parsed.error);
  const name = parsed.name;

  if (!env.LIMITS) return bad("KV-пространство LIMITS не привязано", 500);

  // уже выданный адрес — просто отдаём его же (идемпотентно)
  const known = await env.LIMITS.get("name:" + name, "json");
  if (known && known.tunnelId) {
    const token = await env.LIMITS.get("token:" + name);
    if (token) return json({ ok: true, url: "https://" + name + ".assi.pro", token, reused: true });
  }

  const ip = req.headers.get("cf-connecting-ip") || "unknown";
  const ipKey = "ip:" + ip + ":" + today();
  const usedByIp = Number((await env.LIMITS.get(ipKey)) || 0);
  if (usedByIp >= DAILY_PER_IP) {
    return bad("слишком много регистраций с этого адреса за сутки", 429);
  }
  const total = Number((await env.LIMITS.get("total")) || 0);
  if (total >= TOTAL_LIMIT) {
    return bad("лимит адресов исчерпан", 429);
  }

  const host = name + ".assi.pro";
  let tunnelId = null;
  try {
    const tunnel = await cf(env, `/accounts/${env.CF_ACCOUNT_ID}/cfd_tunnel`, {
      method: "POST",
      body: JSON.stringify({ name: "assi-" + name, config_src: "cloudflare" }),
    });
    tunnelId = tunnel.id;

    await cf(env, `/accounts/${env.CF_ACCOUNT_ID}/cfd_tunnel/${tunnelId}/configurations`, {
      method: "PUT",
      body: JSON.stringify({
        config: {
          ingress: [
            { hostname: host, service: "http://localhost:8787" },
            { service: "http_status:404" },
          ],
        },
      }),
    });

    await cf(env, `/zones/${env.CF_ZONE_ID}/dns_records`, {
      method: "POST",
      body: JSON.stringify({
        type: "CNAME",
        name,
        content: tunnelId + ".cfargotunnel.com",
        proxied: true,
        comment: "assi bridge: " + name,
      }),
    });

    const token = await cf(env, `/accounts/${env.CF_ACCOUNT_ID}/cfd_tunnel/${tunnelId}/token`);
    if (!token) throw new Error("Cloudflare не выдал токен туннеля");

    await env.LIMITS.put("name:" + name, JSON.stringify({ tunnelId, ip, at: today() }));
    await env.LIMITS.put("token:" + name, token);
    await env.LIMITS.put(ipKey, String(usedByIp + 1), { expirationTtl: 60 * 60 * 48 });
    await env.LIMITS.put("total", String(total + 1));

    return json({ ok: true, url: "https://" + host, token });
  } catch (e) {
    // откатываем то, что успели создать
    if (tunnelId) {
      try {
        await cf(env, `/accounts/${env.CF_ACCOUNT_ID}/cfd_tunnel/${tunnelId}`, { method: "DELETE" });
      } catch (_) {}
    }
    const msg = String((e && e.message) || e);
    if (/already exists|duplicate|record with that host/i.test(msg)) {
      return bad("имя занято, попробуй другое", 409);
    }
    return bad("Cloudflare: " + msg, 502);
  }
}

async function release(env, req) {
  let body = {};
  try {
    body = await req.json();
  } catch (_) {
    return bad("нужен JSON: {name, invite}");
  }
  if (!checkInvite(env, body.invite)) {
    return bad("пригласительный код не принят", 403);
  }
  const parsed = normalizeName(body.name);
  if (parsed.error) return bad(parsed.error);
  const name = parsed.name;

  const known = await env.LIMITS.get("name:" + name, "json");
  if (!known || !known.tunnelId) return bad("такого адреса нет", 404);

  try {
    const dns = await cf(env, `/zones/${env.CF_ZONE_ID}/dns_records?name=${encodeURIComponent(name + ".assi.pro")}`);
    for (const rec of dns || []) {
      await cf(env, `/zones/${env.CF_ZONE_ID}/dns_records/${rec.id}`, { method: "DELETE" });
    }
    await cf(env, `/accounts/${env.CF_ACCOUNT_ID}/cfd_tunnel/${known.tunnelId}`, { method: "DELETE" });
  } catch (e) {
    return bad("Cloudflare: " + String((e && e.message) || e), 502);
  }

  await env.LIMITS.delete("name:" + name);
  await env.LIMITS.delete("token:" + name);
  const total = Number((await env.LIMITS.get("total")) || 0);
  await env.LIMITS.put("total", String(Math.max(0, total - 1)));
  return json({ ok: true, released: name });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    if (req.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "content-type",
          "access-control-allow-methods": "GET,POST,OPTIONS",
        },
      });
    }

    if (req.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "assi-registrar" });
    }
    if (req.method === "POST" && url.pathname === "/register") {
      return register(env, req);
    }
    if (req.method === "POST" && url.pathname === "/release") {
      return release(env, req);
    }
    return bad("нет такого метода", 404);
  },
};
