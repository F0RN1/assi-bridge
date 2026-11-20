"""Assi Tray — иконка в трее Windows: отправить файл с компьютера на телефон.

Запуск:  pythonw phone_tray.py        (без окна)
Токен и порт берёт из bridge.json рядом со скриптом (у второго экземпляра — bridge-friend.json).
"""

import json
import sys
from pathlib import Path

import httpx
import pystray
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
ICON = ROOT / "static" / "icon-192.png"
LAST = {"name": "—"}


def state_file() -> Path:
    for name in sys.argv[1:]:
        p = Path(name)
        if p.is_file():
            return p
    for name in ("bridge.json", "bridge-friend.json"):
        p = ROOT / name
        if p.is_file():
            return p
    raise SystemExit("не нашёл bridge.json рядом со скриптом")


STATE = state_file()
CFG = json.loads(STATE.read_text("utf-8"))
BASE = f"http://127.0.0.1:{CFG.get('port', 8787)}"
TOKEN = CFG["token"]


def pick_file() -> str:
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(title="Отправить на телефон")
    root.destroy()
    return path or ""


def send(path: str) -> dict:
    with open(path, "rb") as fh:
        r = httpx.post(
            f"{BASE}/api/share",
            headers={"X-Bridge-Token": TOKEN},
            files={"file": (Path(path).name, fh)},
            timeout=300,
        )
    r.raise_for_status()
    return r.json()


def on_send(icon, item):
    path = pick_file()
    if not path:
        return
    try:
        data = send(path)
        LAST["name"] = data["name"]
        icon.notify(f"Отправлено: {data['name']}", "Assi")
    except Exception as exc:  # мост выключен, файл занят и т.п.
        icon.notify(f"Не вышло: {exc}", "Assi")
    icon.update_menu()


def on_quit(icon, item):
    icon.stop()


def make_icon() -> Image.Image:
    if ICON.exists():
        return Image.open(ICON).resize((64, 64))
    img = Image.new("RGBA", (64, 64), (10, 10, 12, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(187, 243, 81, 255))
    d.line([(32, 46), (32, 20)], fill=(10, 10, 12, 255), width=6)
    d.line([(22, 30), (32, 20), (42, 30)], fill=(10, 10, 12, 255), width=6)
    return img


def main() -> None:
    menu = pystray.Menu(
        pystray.MenuItem("Отправить файл на телефон…", on_send, default=True),
        pystray.MenuItem(lambda i: "последнее: " + LAST["name"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", on_quit),
    )
    pystray.Icon("assi-tray", make_icon(), "Assi — отправка на телефон", menu).run()


if __name__ == "__main__":
    main()
