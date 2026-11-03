#!/usr/bin/env python3
"""Loggt sich bei CareMan Dienstplan (Web) ein und lädt den Abteilungsplan als PDF.

Klickweg: ☰ → Berichte → Abteilungsplan → Planungsgruppe wählen → "alle anzeigen" → Abteilungsplan

Umgebungsvariablen:
  CAREMAN_USER, CAREMAN_PASSWORD   Zugangsdaten (als GitHub-Secret hinterlegen!)
  CAREMAN_URL                      Standard: https://dienstplan.drk-dortmund.de
  PLANUNGSGRUPPE                   Standard: RW 18
  DEBUG=1                          speichert Screenshots der Zwischenschritte in debug/

Aufruf:  python3 fetch_pdf.py dienstplan.pdf
"""
import base64, os, re, sys, time
from playwright.sync_api import sync_playwright

URL = os.environ.get("CAREMAN_URL", "https://dienstplan.drk-dortmund.de")
USER = os.environ.get("CAREMAN_USER", "")
PASS = os.environ.get("CAREMAN_PASSWORD", "")
GROUP = os.environ.get("PLANUNGSGRUPPE", "RW 18")
DEBUG = os.environ.get("DEBUG") == "1"
step_no = 0


def log(msg):
    print(f"[dienstplan] {msg}", flush=True)


def shot(page, name):
    """Screenshot nur bis vor dem Erzeugen des Plans – danach stehen Namen drauf."""
    global step_no
    step_no += 1
    if DEBUG:
        os.makedirs("debug", exist_ok=True)
        page.screenshot(path=f"debug/{step_no:02d}_{name}.png", full_page=True)


def visible(loc):
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def click_first(page, what, candidates, timeout=20):
    """Klickt das erste sichtbare Element aus einer Liste von Locator-Fabriken."""
    end = time.time() + timeout
    while time.time() < end:
        for make in candidates:
            try:
                loc = make()
                n = loc.count()
            except Exception:
                continue
            for i in range(n):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        el.click()
                        log(f"geklickt: {what}")
                        page.wait_for_timeout(800)
                        return True
                except Exception:
                    pass
        page.wait_for_timeout(500)
    dump_clickables(page)
    raise SystemExit(f"Nicht gefunden: {what}")


def dump_clickables(page):
    """Hilft beim Anpassen: listet anklickbare Elemente (ohne Inhalte des Dienstplans)."""
    try:
        items = page.evaluate("""() => [...document.querySelectorAll('body *')]
            .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0
                && getComputedStyle(e).visibility !== 'hidden'
                && ([...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
                    || /^(BUTTON|A|INPUT|SELECT|MAT-SELECT|MAT-CHECKBOX)$/.test(e.tagName)
                    || /button|menuitem|option|checkbox|combobox|switch|radio|tab/.test(e.getAttribute('role') || '')); })
            .slice(0, 150)
            .map(e => `${e.tagName.toLowerCase()} class="${(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) || ''}" `
                    + `role="${e.getAttribute('role') || ''}" aria="${e.getAttribute('aria-label') || ''}" `
                    + `text="${(e.innerText || e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 50)}"`)""")
        items = [re.sub(r"[A-ZÄÖÜ][\wäöüß-]+, ?[A-ZÄÖÜ][\wäöüß-]+", "[Name]", i) for i in items]
        log("Sichtbare Elemente auf der Seite:\n  " + "\n  ".join(items))
    except Exception as e:
        log(f"(Elementliste nicht möglich: {e})")
    shot(page, "fehler")


def text_re(t):
    """Passt auf 't' – auch wenn davor ein Material-Icon-Wort steht (z. B. 'apps Menü')."""
    return re.compile(r"(^|\s)" + re.escape(t) + r"\s*$", re.I)


def by_text(page, t, roles=("menuitem", "link", "button", "tab", "treeitem", "option")):
    """Kandidaten für ein Element mit der Beschriftung t, vom genauesten zum ungenauesten."""
    lit = t.replace("'", "")
    c = [lambda r=r: page.get_by_role(r, name=text_re(t)) for r in roles]
    c += [
        lambda: page.locator(f"xpath=//*[normalize-space(text())='{lit}']"),
        lambda: page.get_by_text(t, exact=True),
        lambda: page.get_by_text(text_re(t)),
        lambda: page.get_by_text(re.compile(r"\b" + re.escape(t) + r"\b", re.I)),
    ]
    return c


def any_visible(cands):
    for make in cands:
        try:
            loc = make()
            for i in range(min(loc.count(), 10)):
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            pass
    return False


SPINNER = ("mat-spinner, mat-progress-spinner, .mat-mdc-progress-spinner, .mdc-circular-progress, "
           "[role=progressbar], .spinner, .loading, .loader")


def wait_loaded(page, timeout=90):
    """Wartet, bis kein Ladekreis mehr zu sehen ist (CareMan lädt nach dem Login eine Weile)."""
    end = time.time() + timeout
    page.wait_for_timeout(1000)
    while time.time() < end:
        try:
            spinning = page.locator(SPINNER).evaluate_all(
                "els => els.some(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })")
        except Exception:
            spinning = False
        if not spinning:
            page.wait_for_timeout(1500)
            return
        page.wait_for_timeout(1000)
    log("Hinweis: Ladekreis nach 90 s immer noch sichtbar – mache trotzdem weiter")


def login(page):
    page.goto(URL, wait_until="networkidle")
    shot(page, "start")
    pw = page.locator("input[type=password]")
    pw.first.wait_for(state="visible", timeout=30000)
    user = page.locator("input:not([type=password]):not([type=hidden]):not([type=checkbox])"
                        ":not([type=radio]):not([type=submit]):not([type=button])")
    user.first.fill(USER)
    pw.first.fill(PASS)
    btn = page.get_by_role("button", name=re.compile(r"anmeld|login|einlog|weiter|ok", re.I))
    if visible(btn):
        btn.first.click()
    else:
        pw.first.press("Enter")
    # warten, bis das Passwortfeld verschwunden ist
    try:
        page.wait_for_function("() => ![...document.querySelectorAll('input[type=password]')].some(e => e.offsetParent)",
                               timeout=30000)
    except Exception:
        shot(page, "login_fehlgeschlagen")
        raise SystemExit("Login fehlgeschlagen – Benutzername/Passwort prüfen (oder Zusatzcode/Captcha?).")
    page.wait_for_load_state("networkidle")
    wait_loaded(page)
    log("eingeloggt")
    shot(page, "eingeloggt")


def open_menu(page):
    """Öffnet das Hauptmenü. Probiert mehrere Knöpfe, bis 'Berichte' sichtbar ist."""
    target = by_text(page, "Berichte")
    if any_visible(target):
        return
    menu_buttons = [
        ("Knopf 'Menü'", lambda: page.get_by_role("button", name=re.compile(r"(^|\s)men[uü]\s*$", re.I))),
        ("Icon 'menu'", lambda: page.locator("button:has(mat-icon:text-is('menu')), a:has(mat-icon:text-is('menu'))")),
        ("Icon 'menu' (ohne Knopf)", lambda: page.locator("mat-icon:text-is('menu'), span.material-icons:text-is('menu')")),
        ("Hamburger-Klasse", lambda: page.locator("[class*=hamburger],[class*=burger],[class*=menu-toggle],[class*=navbar-toggle],"
                                                  "[class*=sidenav-toggle],[class*=nav-toggle],[class*=fa-bars],.pi-bars")),
        ("aria Menü/Navigation", lambda: page.get_by_role("button", name=re.compile(r"men[uü]|navigation|toggle", re.I))),
        ("Icon 'apps'", lambda: page.locator("button:has(mat-icon:text-is('apps'))")),
    ]
    end = time.time() + 60
    tried = set()
    while time.time() < end:
        wait_loaded(page, timeout=30)
        if any_visible(target):
            return
        if try_menu_buttons(page, menu_buttons, target, tried):
            return
        page.wait_for_timeout(2000)
    shot(page, "menue_nicht_gefunden")
    dump_clickables(page)
    raise SystemExit("Menü mit 'Berichte' nicht gefunden.")


def try_menu_buttons(page, menu_buttons, target, tried):
    for name, make in menu_buttons:
        try:
            loc = make()
            n = loc.count()
        except Exception:
            continue
        for i in range(min(n, 3)):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                el.click()
            except Exception:
                continue
            for _ in range(6):          # bis zu 3 s auf das aufklappende Menü warten
                page.wait_for_timeout(500)
                if any_visible(target):
                    log(f"Menü geöffnet über: {name}")
                    shot(page, "menue_offen")
                    return True
            if name not in tried:
                log(f"Menü-Versuch ohne Erfolg: {name}")
                tried.add(name)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    return False


def choose_group(page):
    # 1) echtes <select> mit passender Option
    for i in range(page.locator("select").count()):
        sel = page.locator("select").nth(i)
        opts = sel.locator("option").all_inner_texts()
        if any(o.strip() == GROUP for o in opts):
            sel.select_option(label=next(o for o in opts if o.strip() == GROUP))
            log(f"Planungsgruppe gewählt: {GROUP}")
            return
    # 2) eigene Dropdown-Komponente: Feld "Planungsgruppe" anklicken, dann Option
    click_first(page, "Filter Planungsgruppe", [
        lambda: page.get_by_role("combobox", name=re.compile("Planungsgruppe", re.I)),
        lambda: page.locator("mat-form-field:has(mat-label:text-matches('Planungsgruppe','i')) mat-select"),
        lambda: page.get_by_label(re.compile("Planungsgruppe", re.I)),
        lambda: page.get_by_role("combobox", name=re.compile("Planungsgruppe", re.I)),
        lambda: page.locator("*:has(> :text-is('Planungsgruppe')) >> [role=combobox], *:has(> :text-is('Planungsgruppe')) >> input"),
        lambda: page.get_by_text(re.compile(r"^\s*Planungsgruppe", re.I)),
    ])
    click_first(page, f"Planungsgruppe {GROUP}",
                by_text(page, GROUP, roles=("option", "checkbox", "menuitem", "radio", "treeitem")))
    page.keyboard.press("Escape")


def choose_all(page):
    loc = page.get_by_label(re.compile(r"alle anzeigen", re.I))
    if visible(loc):
        try:
            loc.first.check()
            log("'alle anzeigen' angehakt")
            return
        except Exception:
            pass
    for i in range(page.locator("select").count()):
        sel = page.locator("select").nth(i)
        opts = sel.locator("option").all_inner_texts()
        hit = [o for o in opts if re.search(r"alle anzeigen", o, re.I)]
        if hit:
            sel.select_option(label=hit[0])
            log("'alle anzeigen' gewählt")
            return
    click_first(page, "'alle anzeigen'", [
        lambda: page.get_by_role("option", name=re.compile(r"alle anzeigen", re.I)),
        lambda: page.get_by_role("radio", name=re.compile(r"alle anzeigen", re.I)),
        lambda: page.get_by_role("checkbox", name=re.compile(r"alle anzeigen", re.I)),
        lambda: page.get_by_role("switch", name=re.compile(r"alle anzeigen", re.I)),
        lambda: page.get_by_text(re.compile(r"alle anzeigen", re.I)),
    ])


def grab_pdf(page, context, trigger):
    """Klickt auf 'Abteilungsplan' und fängt das PDF ab – egal ob Download, neuer Tab oder Antwort."""
    found = {}

    def on_resp(r):
        try:
            if "pdf" in (r.headers.get("content-type") or "").lower() and "data" not in found:
                found["data"] = r.body()
        except Exception:
            pass

    downloads, pages = [], []
    context.on("response", on_resp)
    context.on("page", lambda p: pages.append(p))
    page.on("download", lambda d: downloads.append(d))
    for p in context.pages:
        p.on("download", lambda d: downloads.append(d))
    trigger()
    end = time.time() + 120
    while time.time() < end:
        if downloads:
            path = downloads[0].path()
            return open(path, "rb").read()
        if "data" in found and found["data"][:4] == b"%PDF":
            return found["data"]
        for p in pages:
            p.on("download", lambda d: downloads.append(d))
            u = p.url or ""
            if u.startswith("blob:"):
                b64 = p.evaluate("""async () => { const b = await (await fetch(location.href)).arrayBuffer();
                    let s = ''; const a = new Uint8Array(b); for (let i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
                    return btoa(s); }""")
                return base64.b64decode(b64)
        # Bericht evtl. als blob/iframe/embed in derselben Seite
        for sel in ("iframe[src^=blob]", "embed[src^=blob]", "object[data^=blob]"):
            el = page.locator(sel)
            if el.count():
                src = el.first.get_attribute("src") or el.first.get_attribute("data")
                b64 = page.evaluate("""async (u) => { const b = await (await fetch(u)).arrayBuffer();
                    let s = ''; const a = new Uint8Array(b); for (let i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
                    return btoa(s); }""", src)
                return base64.b64decode(b64)
        page.wait_for_timeout(500)
    dump_clickables(page)
    raise SystemExit("Kein PDF erhalten.")


def main(out):
    if not USER or not PASS:
        raise SystemExit("CAREMAN_USER / CAREMAN_PASSWORD fehlen.")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(accept_downloads=True, locale="de-DE", timezone_id="Europe/Berlin",
                                      viewport={"width": 1280, "height": 900})
        page = context.new_page()
        login(page)
        open_menu(page)
        click_first(page, "Berichte", by_text(page, "Berichte"))
        shot(page, "berichte")
        click_first(page, "Abteilungsplan (Menü)", by_text(page, "Abteilungsplan"))
        page.wait_for_load_state("networkidle")
        wait_loaded(page)
        shot(page, "berichtsseite")
        choose_group(page)
        shot(page, "gruppe_gewaehlt")
        choose_all(page)
        shot(page, "alle_anzeigen")

        def trigger():
            click_first(page, "Abteilungsplan erzeugen", [
                lambda: page.get_by_role("button", name=text_re("Abteilungsplan")),
                lambda: page.locator("input[type=submit][value='Abteilungsplan'],input[type=button][value='Abteilungsplan']"),
                lambda: page.get_by_role("button", name=re.compile("Abteilungsplan", re.I)),
                lambda: page.get_by_text(text_re("Abteilungsplan")).last,
            ])

        data = grab_pdf(page, context, trigger)
        if data[:4] != b"%PDF":
            raise SystemExit("Antwort ist kein PDF.")
        open(out, "wb").write(data)
        log(f"PDF gespeichert ({len(data)//1024} KB)")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dienstplan.pdf")
