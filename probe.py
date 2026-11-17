import json, os, re, sys, time
import httpx

LOG = os.path.join(os.environ["TEMP"], "opencode-serve-8790.log")
BASE = "http://127.0.0.1:8790"


def password() -> str:
    with open(LOG, "r", encoding="utf-16", errors="ignore") as f:
        m = re.search(r"server password (\S+)", f.read())
    if not m:
        sys.exit("password not found in log")
    return m.group(1)


def main():
    pw = password()
    c = httpx.Client(base_url=BASE, auth=("opencode", pw), timeout=120)
    model = {"providerID": "openai", "id": os.environ.get("PROBE_MODEL", "gpt-4o-mini")}
    r = c.post("/api/session", json={"title": "Bridge probe", "agent": "build",
                                     "model": model,
                                     "location": {"directory": "C:\\Users\\Forni"}})
    r.raise_for_status()
    sid = r.json()["data"]["id"]
    print("SID", sid, "model", model)

    r = c.post(f"/api/session/{sid}/prompt", json={"text": "Ответь одним словом: привет"})
    print("prompt", r.status_code, r.text[:200])

    deadline = time.time() + 90
    seen = None
    while time.time() < deadline:
        m = c.get(f"/api/session/{sid}/message", params={"order": "asc"}).json()["data"]
        kinds = [x["type"] for x in m]
        if "idle" in kinds:
            seen = m
            break
        time.sleep(2)
    m = seen or c.get(f"/api/session/{sid}/message", params={"order": "asc"}).json()["data"]
    print("types", [x["type"] for x in m])
    for x in m:
        if x["type"] in ("assistant", "idle"):
            print("----", x["type"])
            print(json.dumps(x, ensure_ascii=False)[:2500])
    with open(os.path.join(os.path.dirname(__file__), "probe_last.json"), "w", encoding="utf-8") as f:
        json.dump({"sid": sid, "messages": m}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
