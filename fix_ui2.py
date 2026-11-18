# -*- coding: utf-8 -*-
p = 'static/index.html'
h = open(p, encoding='utf-8').read()

old = """  try {
    await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify({ text, files: files.map(f => f.path) }) });
  } catch (e) {
    const err = makeNode({ role: 'assistant', error: e.message });
    paintNode(err, { role: 'assistant', error: e.message });
    nodes.push(err); log.appendChild(err);
    streaming = null; busy = false; setStat('ошибка', false);
  }
}"""
new = """  try {
    await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify({ text, files: files.map(f => f.path) }) });
  } catch (e) {
    // сеть моргнула: убираем черновик и повторяем отправку один раз через 3 с
    streaming = null;
    if (draft.parentNode) draft.parentNode.removeChild(draft);
    nodes.pop();
    setStat('сеть пропала, повторяю…', true);
    await new Promise(res => setTimeout(res, 3000));
    try {
      await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                               body: JSON.stringify({ text, files: files.map(f => f.path) }) });
      busy = true;
      const d2 = makeNode({ role: 'assistant', text: '', done: false });
      paintNode(d2, { role: 'assistant', text: '', done: false });
      nodes.push(d2); log.appendChild(d2);
      streaming = { node: d2, text: '', msg: null };
      streamSid = curSid;
      scrollDown(true);
      return;
    } catch (e2) {
      const err = makeNode({ role: 'assistant', error: 'не удалось отправить: ' + e2.message });
      paintNode(err, { role: 'assistant', error: err.error });
      nodes.push(err); log.appendChild(err);
      busy = false; setStat('ошибка', false);
    }
  }
}"""
assert old in h, 'send block not found'
h = h.replace(old, new)
open(p, 'w', encoding='utf-8', newline='').write(h)
print('ok', len(h))
