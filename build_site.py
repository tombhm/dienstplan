#!/usr/bin/env python3
"""Baut die Website aus data.json.

Datenschutz: Es wird NUR verschlüsselt veröffentlicht. Auf dem Server liegt kein
lesbarer Dienstplan, keine Kalenderdatei und kein Name im Klartext.

  index.html            Seite, Dienstplan darin AES-256-verschlüsselt (Passwort = SITE_PASSWORD)
  stand.json            nur eine Versionskennung (zufällig aussehender Code, kein Inhalt)
  icon-*.png, manifest  App-Symbol für den Home-Bildschirm

Aufruf:  SITE_PASSWORD=… python3 build_site.py data.json site/index.html
Optional: DISPATCH_TOKEN (für den Aktualisieren-Knopf),
          GITHUB_REPOSITORY / GITHUB_REF_NAME (setzt GitHub automatisch)
"""
import base64, hashlib, json, os, shutil, sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 250_000
HERE = os.path.dirname(os.path.abspath(__file__))


def main(src, dst):
    pw = os.environ.get("SITE_PASSWORD")
    if not pw:
        sys.exit("SITE_PASSWORD fehlt")
    if len(pw) < 12:
        print("WARNUNG: SITE_PASSWORD ist kürzer als 12 Zeichen – bitte ein längeres Passwort wählen.")
    out = dst if not dst.endswith(".html") else (os.path.dirname(dst) or ".")
    os.makedirs(out, exist_ok=True)
    old_cal = os.path.join(out, "cal")
    if os.path.isdir(old_cal):
        shutil.rmtree(old_cal)

    data = json.load(open(src, encoding="utf-8"))
    payload = dict(data)
    payload["repo"] = os.environ.get("GITHUB_REPOSITORY", "")
    payload["branch"] = os.environ.get("GITHUB_REF_NAME", "main")
    payload["dispatch"] = os.environ.get("DISPATCH_TOKEN", "")
    raw = json.dumps(payload, ensure_ascii=False).encode()

    salt, iv = os.urandom(16), os.urandom(12)
    k = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(pw.encode())
    ct = AESGCM(k).encrypt(iv, raw, None)
    enc = {n: base64.b64encode(v).decode() for n, v in {"salt": salt, "iv": iv, "ct": ct}.items()}
    enc["iter"] = ITER
    enc["v"] = hashlib.sha256(ct).hexdigest()[:12]

    html = open(os.path.join(HERE, "template.html"), encoding="utf-8").read().replace("/*__ENC__*/null", json.dumps(enc))
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(html)
    json.dump({"v": enc["v"]}, open(os.path.join(out, "stand.json"), "w"))
    for f in ("icon-180.png", "icon-512.png"):
        if os.path.exists(os.path.join(HERE, f)):
            shutil.copy(os.path.join(HERE, f), os.path.join(out, f))
    json.dump({"name": "Dienstplan RW 18", "short_name": "Dienstplan", "start_url": "./", "display": "standalone",
               "background_color": "#101828", "theme_color": "#101828",
               "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                         {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]},
              open(os.path.join(out, "manifest.webmanifest"), "w"), ensure_ascii=False)
    # Für Hosting bei Netlify: nicht indexieren, nicht zwischenspeichern (GitHub Pages ignoriert die Datei)
    open(os.path.join(out, "_headers"), "w").write("/*\n  X-Robots-Tag: noindex, nofollow\n  Cache-Control: no-cache\n")
    print(f"Website gebaut (nur verschlüsselt). Aktualisieren-Knopf {'an' if payload['dispatch'] else 'aus'}.")


if __name__ == "__main__":
    main(*sys.argv[1:3])
