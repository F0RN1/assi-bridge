import json, time, httpx

st = json.load(open('bridge.json', encoding='utf-8'))
pw, sid = st['password'], st['session_id']
c = httpx.Client(base_url='http://127.0.0.1:8790', auth=('opencode', pw), timeout=30)
msgs = c.get(f'/api/session/{sid}/message', params={'order': 'asc'}).json()['data']
print('session', sid, 'total', len(msgs))
now = int(time.time() * 1000)
for m in msgs[-5:]:
    t = m.get('type')
    tm = m.get('time') or {}
    created = tm.get('created')
    age = round((now - created) / 1000, 1) if created else None
    if t == 'assistant':
        txt = ''.join(p.get('text', '') for p in (m.get('content') or []))
        err = m.get('error') or {}
        print(f"assistant  age={age}s len={len(txt)} finish={m.get('finish')} completed={tm.get('completed')} err={str(err.get('message'))[:150]}")
    elif t == 'user':
        print(f"user       age={age}s len={len(m.get('text') or '')} :: {(m.get('text') or '')[:60]!r}")
    elif t == 'idle':
        err = m.get('error') or {}
        print(f"idle       age={age}s outcome={m.get('outcome')} err={str(err.get('message'))[:150]}")
    else:
        print(f"{t}  age={age}s")
print('active?', c.get('/api/session/active').status_code)
