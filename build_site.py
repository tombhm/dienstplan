#!/usr/bin/env python3
"""Verschlüsselt data.json mit einem Passwort und baut daraus index.html.

Aufruf:  SITE_PASSWORD=geheim python3 build_site.py data.json index.html
"""
import base64, json, os, sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 250_000


def main(src, dst):
    pw = os.environ.get("SITE_PASSWORD")
    if not pw:
        sys.exit("SITE_PASSWORD fehlt")
    data = open(src, "rb").read()
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(pw.encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    enc = {k: base64.b64encode(v).decode() for k, v in {"salt": salt, "iv": iv, "ct": ct}.items()}
    enc["iter"] = ITER
    here = os.path.dirname(os.path.abspath(__file__))
    html = open(os.path.join(here, "template.html"), encoding="utf-8").read()
    html = html.replace("/*__ENC__*/null", json.dumps(enc))
    open(dst, "w", encoding="utf-8").write(html)
    print(f"{dst} geschrieben ({len(html)//1024} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
