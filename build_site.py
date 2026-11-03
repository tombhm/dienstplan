#!/usr/bin/env python3
"""Baut die Website aus data.json:

  index.html            verschlüsselte Seite (Passwort = SITE_PASSWORD)
  stand.json            nur Versionskennung + Zeitstempel (für "neuer Stand verfügbar")
  cal/<token>.ics       je Person ein geheimer Kalender zum Abonnieren (Apple/Google Kalender)
  icon-*.png, manifest  App-Symbol für den Home-Bildschirm

Aufruf:  SITE_PASSWORD=… python3 build_site.py data.json site/index.html
Optional: DISPATCH_TOKEN (für den Aktualisieren-Knopf), ICS_SECRET (sonst SITE_PASSWORD),
          GITHUB_REPOSITORY / GITHUB_REF_NAME (setzt GitHub automatisch)
"""
import base64, hashlib, hmac, json, os, re, shutil, sys
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 250_000
HERE = os.path.dirname(os.path.abspath(__file__))
OTHER = {"BFRA": "Berufsschule", "KLA": "Klinikum", "FOB": "Fortbildung", "IN8": "Innendienst",
         "ZF": "Zertifizierung", "TP": "Praktikum"}
SHIFTNAME = {"Früh": "Frühdienst", "Tag": "Tagdienst", "Spät": "Spätdienst", "Nacht": "Nachtdienst"}
EMOJI = {"RTW": "🚑", "NEF": "🚨", "Kinder-NEF": "🧸", "KTW": "🚐", "Springer": "🔁"}


# ---------- Schicht-Logik (identisch zur Website) ----------
def shift_of(base):
    if re.match(r"^F", base): return "Früh"
    if re.match(r"^S\d", base): return "Spät"
    if re.match(r"^N\d", base) or base.endswith("N"): return "Nacht"
    return "Tag"


def info(data, code):
    P = code.endswith("P") and len(code) > 2
    base = code[:-1] if P and code != "TP" else code
    unit = next((u for u in data["einheiten"] if base in u["codes"]), None)
    lg = data["legende"].get(base) or data["legende"].get(code) or {}
    return {"code": code, "base": base, "P": P, "unit": unit,
            "shift": shift_of(base) if unit else None,
            "von": lg.get("von", ""), "bis": lg.get("bis", ""),
            "label": unit["name"] if unit else OTHER.get(base, lg.get("name") or code),
            "legname": lg.get("name", "")}


def pretty(n):
    parts = n.split(", ")
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else n


# ---------- Kalender (.ics) ----------
VTZ = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def ics_esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out, b = [], line.encode()
    while len(b) > 75:
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80:  # nicht mitten im UTF-8-Zeichen trennen
            cut -= 1
        out.append(b[:cut].decode()); b = b[cut:]
    out.append(b.decode())
    return "\r\n ".join(out)


def person_ics(data, person, year, month, stamp):
    by_day = {}
    for p in data["personen"]:
        for d, cs in p["tage"].items():
            for c in cs:
                by_day.setdefault(d, []).append((p, info(data, c)))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RW18 Dienstplan//DE", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:Dienst RW 18", "X-WR-TIMEZONE:Europe/Berlin",
             "X-APPLE-CALENDAR-COLOR:#FF3B30", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    lines += VTZ.split("\n")
    n = 0
    for d, cs in sorted(person["tage"].items(), key=lambda x: int(x[0])):
        for c in cs:
            i = info(data, c)
            if not i["von"]:
                continue
            day = datetime(year, month, int(d))
            h1, m1 = map(int, i["von"].split(":")); h2, m2 = map(int, i["bis"].split(":"))
            st = day.replace(hour=h1, minute=m1)
            en = day.replace(hour=h2, minute=m2)
            if en <= st:
                en += timedelta(days=1)
            u = i["unit"]
            summary = c                       # Titel = Kürzel aus dem Plan, z. B. 81T oder 83NP
            if u:
                mates = [(p, j) for p, j in by_day.get(d, []) if p is not person and j["unit"] is u and j["shift"] == i["shift"]]
                mate_txt = ", ".join(pretty(p["name"]) + (" (Prakt.)" if j["P"] else "") for p, j in mates) or "noch niemand"
                desc = f"Mitfahrer: {mate_txt}\nStand: {data['meta'].get('stand', '')}"
            else:
                desc = f"{i['legname'] or i['label']}\nStand: {data['meta'].get('stand', '')}"
            uid = hashlib.sha1(f"{person['name']}|{year}-{month:02d}-{int(d):02d}|{c}".encode()).hexdigest()[:20]
            lines += ["BEGIN:VEVENT", f"UID:{uid}@dienstplan-rw18", f"DTSTAMP:{stamp}",
                      f"DTSTART;TZID=Europe/Berlin:{st:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Berlin:{en:%Y%m%dT%H%M%S}",
                      f"SUMMARY:{ics_esc(summary)}", f"DESCRIPTION:{ics_esc(desc)}",
                      "LOCATION:Rettungswache 18", "TRANSP:OPAQUE", "END:VEVENT"]
            n += 1
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n", n


# ---------- Bauen ----------
def main(src, dst):
    pw = os.environ.get("SITE_PASSWORD")
    if not pw:
        sys.exit("SITE_PASSWORD fehlt")
    out = dst if not dst.endswith(".html") else (os.path.dirname(dst) or ".")
    os.makedirs(out, exist_ok=True)
    data = json.load(open(src, encoding="utf-8"))
    day, mon, year = map(int, data["meta"]["von"].split("."))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # geheime Kalender je Person
    key = (os.environ.get("ICS_SECRET") or pw).encode()
    if os.path.isdir(os.path.join(out, "cal")):
        shutil.rmtree(os.path.join(out, "cal"))
    os.makedirs(os.path.join(out, "cal"))
    kal = {}
    for p in data["personen"]:
        tok = hmac.new(key, p["name"].encode(), hashlib.sha256).hexdigest()[:24]
        text, n = person_ics(data, p, year, mon, stamp)
        if n:
            open(os.path.join(out, "cal", tok + ".ics"), "w", encoding="utf-8", newline="").write(text)
            kal[p["name"]] = tok

    payload = dict(data)
    payload["kal"] = kal
    payload["repo"] = os.environ.get("GITHUB_REPOSITORY", "")
    payload["branch"] = os.environ.get("GITHUB_REF_NAME", "main")
    payload["dispatch"] = os.environ.get("DISPATCH_TOKEN", "")
    raw = json.dumps(payload, ensure_ascii=False).encode()

    salt, iv = os.urandom(16), os.urandom(12)
    k = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(pw.encode())
    ct = AESGCM(k).encrypt(iv, raw, None)
    enc = {n: base64.b64encode(v).decode() for n, v in {"salt": salt, "iv": iv, "ct": ct}.items()}
    enc["iter"] = ITER
    enc["v"] = hashlib.sha256(raw).hexdigest()[:12]

    html = open(os.path.join(HERE, "template.html"), encoding="utf-8").read().replace("/*__ENC__*/null", json.dumps(enc))
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(html)
    json.dump({"v": enc["v"], "stand": data["meta"].get("stand", "")}, open(os.path.join(out, "stand.json"), "w"))
    for f in ("icon-180.png", "icon-512.png"):
        if os.path.exists(os.path.join(HERE, f)):
            shutil.copy(os.path.join(HERE, f), os.path.join(out, f))
    json.dump({"name": "Dienstplan RW 18", "short_name": "Dienstplan", "start_url": "./", "display": "standalone",
               "background_color": "#101828", "theme_color": "#101828",
               "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                         {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]},
              open(os.path.join(out, "manifest.webmanifest"), "w"), ensure_ascii=False)
    print(f"Website gebaut: {len(kal)} Kalender, Aktualisieren-Knopf {'an' if payload['dispatch'] else 'aus'}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
