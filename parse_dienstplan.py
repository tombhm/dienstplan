#!/usr/bin/env python3
"""Liest einen CareMan-Abteilungsdienstplan (PDF-Export) und schreibt data.json.

Aufruf:  python3 parse_dienstplan.py dienstplan.pdf data.json
"""
import json, re, sys
from datetime import datetime
import pdfplumber

NAME_X_MAX = 140          # alles links davon ist Namensspalte
LINE_TOL = 3              # Toleranz beim Zusammenfassen von Textzeilen

# Fahrzeug-Zuordnung der Kürzel (RW 18). Unbekannte Kürzel landen in "Sonstiges".
# soll  = benötigte Besatzung pro Schicht (ohne Praktikanten)
# pflicht = an welchen Wochentagen eine Schicht besetzt sein MUSS (0=So, 1=Mo … 6=Sa).
#           Schichten, die nicht drinstehen, werden nur geprüft, wenn jemand eingeteilt ist.
ALLE, MO_FR, MO_SA, WE = [0, 1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6], [0, 6]
UNITS = [
    {"name": "18-RTW-1", "typ": "RTW", "codes": ["81T", "81N"], "soll": 2, "pflicht": {"Tag": ALLE, "Nacht": ALLE}},
    {"name": "18-RTW-2", "typ": "RTW", "codes": ["82T"], "soll": 2, "pflicht": {"Tag": MO_SA}},
    {"name": "18-RTW-3", "typ": "RTW", "codes": ["83T", "83N"], "soll": 2, "pflicht": {"Tag": ALLE, "Nacht": ALLE}},
    {"name": "11-NEF-1", "typ": "NEF", "codes": ["1NT", "1NN"], "soll": 1, "pflicht": {"Tag": ALLE, "Nacht": ALLE}},
    {"name": "00-KIND-NEF-01", "typ": "Kinder-NEF", "codes": ["0NT", "0NN"], "soll": 1, "pflicht": {"Tag": ALLE, "Nacht": ALLE}},
    {"name": "18-KTW-1", "typ": "KTW", "codes": ["F81", "S81", "N81"], "soll": 2,
     "pflicht": {"Früh": MO_FR, "Spät": MO_FR, "Nacht": WE}},
    {"name": "Springer", "typ": "Springer", "codes": ["SPT", "SPN"], "soll": 0, "pflicht": {}},
]


def group_lines(words):
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1]["top"] - w["top"]) <= LINE_TOL:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    return lines


def parse_grid(pdf):
    meta, people = {}, []
    for page in pdf.pages:
        words = page.extract_words()
        lines = group_lines(words)
        # Kopfzeile mit den Tagesnummern 1..n finden
        header = next((l for l in lines
                       if len(l["words"]) >= 28
                       and [w["text"] for w in l["words"]] == [str(i) for i in range(1, len(l["words"]) + 1)]), None)
        if header is None:
            continue
        cols = {int(w["text"]): (w["x0"] + w["x1"]) / 2 for w in header["words"]}
        for l in lines:
            txt = " ".join(w["text"] for w in l["words"])
            m = re.search(r"Abteilungsdienstplan (.+?) (\d\d\.\d\d\.\d{4}) - (\d\d\.\d\d\.\d{4}), (.+)$", txt)
            if m:
                meta.update(abteilung=m.group(1), von=m.group(2), bis=m.group(3), ersteller=m.group(4))
        current = None
        for l in lines:
            if l["top"] <= header["top"] + 1:
                continue
            first = l["words"][0]
            txt = " ".join(w["text"] for w in l["words"])
            if txt.startswith("Legende"):
                break
            if re.match(r"\d\d\.\d\d\.\d{4} / CareMan", txt):  # Fußzeile
                current = None
                continue
            name_words = [w for w in l["words"] if w["x1"] < NAME_X_MAX]
            cell_words = [w for w in l["words"] if w["x0"] >= NAME_X_MAX]
            if name_words:
                nm = " ".join(w["text"] for w in name_words)
                if "," in nm or current is None:
                    current = {"name": nm, "cells": {}}
                    people.append(current)
                else:  # umgebrochener Vorname
                    current["name"] += " " + nm
            if current is None:
                continue
            for w in cell_words:
                cx = (w["x0"] + w["x1"]) / 2
                day = min(cols, key=lambda d: abs(cols[d] - cx))
                current["cells"].setdefault(day, []).append(w["text"])
    for p in people:
        p["tage"] = {}
        for day, parts in sorted(p.pop("cells").items()):
            codes = [c for c in "".join(parts).split(",") if c]
            p["tage"][str(day)] = codes
    return meta, people


LEG_RE = re.compile(
    r"^\s*([0-9A-Z]{2,5})\s+(?:(.+?)\s+)?(\w+dienst|Ausbildung)\s+(?:1\s+)?(\d\d\.\d\d)\s+(\d\d\.\d\d)")


def parse_legend(pdf):
    legend = {}
    for page in pdf.pages:
        text = page.extract_text(layout=True) or ""
        for line in text.splitlines():
            m = LEG_RE.match(line)
            if m:
                code, name, typ, von, bis = m.groups()
                legend[code] = {"name": (name or "").strip(), "typ": typ,
                                "von": von.replace(".", ":"), "bis": bis.replace(".", ":")}
    if "FOB" in legend and not legend["FOB"]["name"]:
        legend["FOB"]["name"] = "Fortbildung"
    return legend


def main(src, dst):
    with pdfplumber.open(src) as pdf:
        meta, people = parse_grid(pdf)
        legend = parse_legend(pdf)
    meta["stand"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    unknown = sorted({c for p in people for cs in p["tage"].values() for c in cs} - set(legend))
    data = {"meta": meta, "legende": legend,
            "einheiten": UNITS,
            "personen": people, "unbekannt": unknown}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(people)} Personen, {len(legend)} Kürzel, unbekannt: {unknown}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
