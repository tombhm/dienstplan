#!/usr/bin/env python3
"""Schickt data.json an den Dienstplan-Server (Cloudflare Worker).

Aufruf:  APP_SECRET=… python3 upload_plan.py data.json https://dienstplan-rw18.xyz.workers.dev
Der Upload-Schlüssel wird aus APP_SECRET abgeleitet – derselbe Weg wie im Server.
"""
import base64, hashlib, hmac, json, os, sys, urllib.request

src, target = sys.argv[1], sys.argv[2].rstrip("/")
secret = os.environ.get("APP_SECRET")
if not secret:
    sys.exit("APP_SECRET fehlt")
if not target:
    sys.exit("Keine Zieladresse: Bitte über den Knopf „Aktualisieren“ auf der Website starten "
             "oder in GitHub das Secret WORKER_URL (z. B. https://dienstplan-rw18.NAME.workers.dev) anlegen.")
from urllib.parse import urlparse
host = urlparse(target).hostname or ""
allowed = os.environ.get("WORKER_URL", "").rstrip("/")
if not ((allowed and target == allowed) or (target.startswith("https://") and host.endswith(".workers.dev")) or host == "localhost"):
    sys.exit(f"Zieladresse nicht erlaubt: {target}")
token = base64.urlsafe_b64encode(hmac.new(secret.encode(), b"ingest", hashlib.sha256).digest()).rstrip(b"=").decode()
body = open(src, "rb").read()
req = urllib.request.Request(target + "/api/ingest", data=body, method="PUT",
                             headers={"authorization": "Bearer " + token, "content-type": "application/json",
                                      "user-agent": "dienstplan-rw18-upload"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read())
except urllib.error.HTTPError as e:
    sys.exit(f"Upload fehlgeschlagen: HTTP {e.code} {e.read()[:200]!r}")
print(f"Dienstplan hochgeladen ({res.get('personen')} Personen).")
