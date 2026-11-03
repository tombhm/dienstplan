// Dienstplan RW 18 – Server (Cloudflare Worker + Durable Object mit SQLite)
//
// Aufgaben:
//  * liefert die Website aus (index.html, Icons)
//  * Benutzerkonten: Registrierung -> Freigabe durch Admin per E-Mail -> Anmeldung
//  * gibt den Dienstplan nur an angemeldete, freigegebene Benutzer heraus
//  * nimmt den neuen Dienstplan von GitHub entgegen (/api/ingest)
//  * startet auf Knopfdruck das Abholen bei CareMan (GitHub Actions)
//
// Secrets (werden automatisch aus GitHub gesetzt):
//  APP_SECRET      langer Zufallswert (signiert Freigabe-Links, Schlüssel für Upload)
//  RESEND_API_KEY  zum Versenden der Freigabe-Mails
//  ADMIN_EMAIL     an diese Adresse gehen die Freigabe-Mails
//  ADMIN_USERNAME  dieser Benutzername ist Admin und wird automatisch freigegeben
//  GH_TOKEN        GitHub-Token (Actions: Read and write) für den Aktualisieren-Knopf
//  GH_REPO         z. B. tombhm/dienstplan (setzt GitHub automatisch)

import HTML from "./index.html";
import ICON180 from "./icon-180.png";
import ICON512 from "./icon-512.png";
import { DurableObject } from "cloudflare:workers";

const enc = new TextEncoder();
const DAY = 86400000;
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const rnd = n => b64u(crypto.getRandomValues(new Uint8Array(n)));
async function hmac(key, msg) {
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(await crypto.subtle.sign("HMAC", k, enc.encode(msg)));
}
const sha = async s => b64u(await crypto.subtle.digest("SHA-256", enc.encode(s)));
function same(a, b) { // Vergleich in konstanter Zeit
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let d = 0; for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i); return d === 0;
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SEC = {
  "x-robots-tag": "noindex, nofollow", "referrer-policy": "no-referrer", "x-content-type-options": "nosniff",
  "x-frame-options": "DENY", "strict-transport-security": "max-age=31536000", "permissions-policy": "camera=(), microphone=(), geolocation=()",
};
const CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...SEC } });
const page = (title, body, status = 200) => new Response(`<!DOCTYPE html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><style>body{font:16px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:#f2f2f7;margin:0;padding:24px;color:#111}
.c{max-width:440px;margin:40px auto;background:#fff;border-radius:16px;padding:24px}h1{font-size:21px;margin:0 0 10px}p{color:#3c3c43}
button{font:inherit;font-weight:600;border:0;border-radius:11px;padding:12px 16px;width:100%;margin-top:8px;cursor:pointer}
.ok{background:#34c759;color:#fff}.no{background:#ff3b30;color:#fff}.m{color:#8e8e93;font-size:14px}</style></head><body><div class="c">${body}</div></body></html>`,
  { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'", ...SEC } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    if (p === "/" || p === "/index.html")
      return new Response(HTML, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-cache", "content-security-policy": CSP, ...SEC } });
    if (p === "/icon-180.png" || p === "/icon-512.png")
      return new Response(p.includes("180") ? ICON180 : ICON512, { headers: { "content-type": "image/png", "cache-control": "public, max-age=86400" } });
    if (p === "/manifest.webmanifest")
      return new Response(JSON.stringify({
        name: "Dienstplan RW 18", short_name: "Dienstplan", start_url: "./", display: "standalone",
        background_color: "#101828", theme_color: "#101828",
        icons: [{ src: "icon-180.png", sizes: "180x180", type: "image/png" }, { src: "icon-512.png", sizes: "512x512", type: "image/png" }]
      }), { headers: { "content-type": "application/manifest+json" } });
    if (p.startsWith("/api/")) {
      if (!env.APP_SECRET) return json({ error: "Server noch nicht eingerichtet (APP_SECRET fehlt)." }, 500);
      const stub = env.STORE.get(env.STORE.idFromName("main"));
      return stub.fetch(request);
    }
    return new Response("Nicht gefunden", { status: 404 });
  },
};

export class Store extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.env = env;
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS users (u TEXT PRIMARY KEY, name TEXT, hash TEXT, salt TEXT, status TEXT,
      created INTEGER, decided INTEGER, fails INTEGER DEFAULT 0, locked INTEGER DEFAULT 0, last_login INTEGER);
      CREATE TABLE IF NOT EXISTS sessions (t TEXT PRIMARY KEY, u TEXT, exp INTEGER);
      CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);`);
  }
  one(q, ...a) { const r = this.sql.exec(q, ...a).toArray(); return r[0] || null; }
  all(q, ...a) { return this.sql.exec(q, ...a).toArray(); }
  get(k) { const r = this.one("SELECT v FROM kv WHERE k=?", k); return r ? r.v : null; }
  set(k, v) { this.sql.exec("INSERT INTO kv (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", k, v); }
  isAdmin(u) { return !!this.env.ADMIN_USERNAME && u === this.env.ADMIN_USERNAME.trim().toLowerCase(); }

  async auth(request) {
    const h = request.headers.get("authorization") || "";
    const t = h.startsWith("Bearer ") ? h.slice(7) : "";
    if (!t) return null;
    const s = this.one("SELECT u, exp FROM sessions WHERE t=?", await sha(t));
    if (!s || s.exp < Date.now()) return null;
    const user = this.one("SELECT u, name, status FROM users WHERE u=?", s.u);
    if (!user || user.status !== "active") return null;
    return { ...user, admin: this.isAdmin(user.u), tokenHash: await sha(t) };
  }

  async mail(subject, html) {
    if (!this.env.RESEND_API_KEY || !this.env.ADMIN_EMAIL) return false;
    try {
      const r = await fetch("https://api.resend.com/emails", {
        method: "POST", headers: { authorization: `Bearer ${this.env.RESEND_API_KEY}`, "content-type": "application/json" },
        body: JSON.stringify({ from: "Dienstplan RW 18 <onboarding@resend.dev>", to: [this.env.ADMIN_EMAIL], subject, html }),
      });
      return r.ok;
    } catch (e) { return false; }
  }

  async github(path, init = {}) {
    return fetch(`https://api.github.com/repos/${this.env.GH_REPO}/actions${path}`, {
      ...init, headers: { authorization: `Bearer ${this.env.GH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "dienstplan-rw18", ...(init.headers || {}) },
    });
  }

  async fetch(request) {
    const url = new URL(request.url), p = url.pathname, m = request.method, now = Date.now();
    const body = async () => { try { return await request.json(); } catch (e) { return {}; } };
    this.sql.exec("DELETE FROM sessions WHERE exp < ?", now);

    // ---------- Registrieren ----------
    if (p === "/api/register" && m === "POST") {
      const b = await body();
      const u = String(b.u || "").trim().toLowerCase(), name = String(b.name || "").trim().slice(0, 80), pw = String(b.pw || "");
      if (!/^[a-z0-9._-]{3,30}$/.test(u)) return json({ error: "Benutzername: 3–30 Zeichen, nur Buchstaben, Zahlen, Punkt, Minus, Unterstrich." }, 400);
      if (name.length < 3) return json({ error: "Bitte Vor- und Nachname angeben." }, 400);
      if (!/^[A-Za-z0-9_-]{43}$/.test(pw)) return json({ error: "Ungültige Anfrage." }, 400);
      if (this.one("SELECT u FROM users WHERE u=?", u)) return json({ error: "Dieser Benutzername ist schon vergeben." }, 409);
      const pending = this.one("SELECT COUNT(*) AS n FROM users WHERE status='pending'").n;
      if (pending >= 25) return json({ error: "Zu viele offene Anfragen. Bitte später erneut versuchen." }, 429);
      const salt = rnd(16), admin = this.isAdmin(u);
      this.sql.exec("INSERT INTO users (u,name,hash,salt,status,created,decided) VALUES (?,?,?,?,?,?,?)",
        u, name, await sha(salt + pw), salt, admin ? "active" : "pending", now, admin ? now : null);
      if (admin) return json({ ok: true, status: "active" });
      const s = await hmac(this.env.APP_SECRET, `decide|${u}|${now}`);
      const link = `${url.origin}/api/decide?u=${encodeURIComponent(u)}&s=${s}`;
      const sent = await this.mail(`Neue Anmeldung: ${name} (${u})`,
        `<p>Neue Registrierung für den <b>Dienstplan RW 18</b>:</p>
         <p><b>Name:</b> ${esc(name)}<br><b>Benutzername:</b> ${esc(u)}<br><b>Zeit:</b> ${new Date(now).toLocaleString("de-DE", { timeZone: "Europe/Berlin" })}</p>
         <p><a href="${link}" style="display:inline-block;background:#ff3b30;color:#fff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:600">Anfrage ansehen &amp; freigeben</a></p>
         <p style="color:#888;font-size:13px">Kennst du die Person nicht, lehne die Anfrage ab.</p>`);
      return json({ ok: true, status: "pending", mail: sent });
    }

    // ---------- Freigabe-Link aus der E-Mail ----------
    if (p === "/api/decide") {
      const f = m === "POST" ? Object.fromEntries(await request.formData()) : Object.fromEntries(url.searchParams);
      const user = this.one("SELECT * FROM users WHERE u=?", String(f.u || ""));
      if (!user || !same(String(f.s || ""), await hmac(this.env.APP_SECRET, `decide|${user.u}|${user.created}`)))
        return page("Ungültig", "<h1>Link ungültig</h1><p>Die Anfrage existiert nicht mehr oder der Link ist falsch.</p>", 404);
      if (m === "POST") {
        const a = f.a === "approve" ? "active" : "rejected";
        if (a === "rejected") this.sql.exec("DELETE FROM users WHERE u=?", user.u);
        else this.sql.exec("UPDATE users SET status='active', decided=? WHERE u=?", now, user.u);
        return page("Erledigt", a === "active"
          ? `<h1>✅ Freigegeben</h1><p><b>${esc(user.name)}</b> (${esc(user.u)}) kann sich jetzt anmelden.</p>`
          : `<h1>❌ Abgelehnt</h1><p>Die Anfrage von <b>${esc(user.name)}</b> wurde gelöscht.</p>`);
      }
      const state = user.status === "active" ? "<p class='m'>Bereits freigegeben.</p>" : user.status === "blocked" ? "<p class='m'>Derzeit gesperrt.</p>" : "";
      return page("Anfrage prüfen", `<h1>Zugang zum Dienstplan</h1>
        <p><b>Name:</b> ${esc(user.name)}<br><b>Benutzername:</b> ${esc(user.u)}<br>
        <b>Angefragt:</b> ${new Date(user.created).toLocaleString("de-DE", { timeZone: "Europe/Berlin" })}</p>${state}
        <form method="post"><input type="hidden" name="u" value="${esc(user.u)}"><input type="hidden" name="s" value="${esc(f.s)}">
        <button class="ok" name="a" value="approve">Freigeben</button><button class="no" name="a" value="reject">Ablehnen &amp; löschen</button></form>`);
    }

    // ---------- Anmelden ----------
    if (p === "/api/login" && m === "POST") {
      const b = await body();
      const u = String(b.u || "").trim().toLowerCase(), pw = String(b.pw || "");
      const user = this.one("SELECT * FROM users WHERE u=?", u);
      const fail = msg => json({ error: msg || "Benutzername oder Passwort falsch." }, 401);
      if (!user) { await sha(rnd(8)); return fail(); }
      if (user.locked > now) return json({ error: `Zu viele Fehlversuche. Bitte in ${Math.ceil((user.locked - now) / 60000)} Min. erneut versuchen.` }, 429);
      if (!same(await sha(user.salt + pw), user.hash)) {
        const fails = user.fails + 1;
        this.sql.exec("UPDATE users SET fails=?, locked=? WHERE u=?", fails >= 8 ? 0 : fails, fails >= 8 ? now + 15 * 60000 : 0, u);
        return fail();
      }
      this.sql.exec("UPDATE users SET fails=0, locked=0 WHERE u=?", u);
      if (user.status === "pending") return json({ error: "Dein Zugang wurde noch nicht freigegeben. Bitte warte auf die Freigabe.", status: "pending" }, 403);
      if (user.status !== "active") return json({ error: "Dein Zugang ist gesperrt. Bitte wende dich an die Wachenleitung.", status: "blocked" }, 403);
      const t = rnd(32);
      this.sql.exec("INSERT INTO sessions (t,u,exp) VALUES (?,?,?)", await sha(t), u, now + (b.keep ? 30 * DAY : DAY / 2));
      this.sql.exec("UPDATE users SET last_login=? WHERE u=?", now, u);
      return json({ ok: true, token: t });
    }

    // ---------- Upload des Dienstplans durch GitHub ----------
    if (p === "/api/ingest" && m === "PUT") {
      const t = (request.headers.get("authorization") || "").replace(/^Bearer /, "");
      if (!same(t, await hmac(this.env.APP_SECRET, "ingest"))) return json({ error: "nicht erlaubt" }, 403);
      const txt = await request.text();
      let plan; try { plan = JSON.parse(txt); } catch (e) { return json({ error: "kein JSON" }, 400); }
      if (!plan.personen || !plan.meta) return json({ error: "unerwartetes Format" }, 400);
      this.set("plan", txt); this.set("plan_updated", String(now));
      return json({ ok: true, personen: plan.personen.length });
    }

    // ---------- ab hier nur angemeldet ----------
    const me = await this.auth(request);
    if (!me) return json({ error: "Bitte anmelden." }, 401);

    if (p === "/api/plan" && m === "GET") {
      const plan = this.get("plan");
      return json({ plan: plan ? JSON.parse(plan) : null, updated: +(this.get("plan_updated") || 0), user: { u: me.u, name: me.name, admin: me.admin } });
    }
    if (p === "/api/logout" && m === "POST") {
      this.sql.exec("DELETE FROM sessions WHERE t=?", me.tokenHash);
      return json({ ok: true });
    }
    if (p === "/api/password" && m === "POST") {
      const b = await body(), user = this.one("SELECT * FROM users WHERE u=?", me.u);
      if (!same(await sha(user.salt + String(b.old || "")), user.hash)) return json({ error: "Altes Passwort ist falsch." }, 400);
      if (!/^[A-Za-z0-9_-]{43}$/.test(String(b.pw || ""))) return json({ error: "Ungültige Anfrage." }, 400);
      const salt = rnd(16);
      this.sql.exec("UPDATE users SET hash=?, salt=? WHERE u=?", await sha(salt + b.pw), salt, me.u);
      this.sql.exec("DELETE FROM sessions WHERE u=? AND t<>?", me.u, me.tokenHash);
      return json({ ok: true });
    }
    if (p === "/api/refresh" && m === "POST") {
      if (!this.env.GH_TOKEN || !this.env.GH_REPO) return json({ error: "Aktualisieren ist auf dem Server nicht eingerichtet (GH_TOKEN fehlt)." }, 500);
      const last = +(this.get("refresh_at") || 0);
      if (now - last < 5 * 60000) return json({ error: `Wird gerade aktualisiert – bitte ${Math.ceil((5 * 60000 - (now - last)) / 60000)} Min. warten.`, since: last }, 429);
      let r = null;
      for (const ref of ["main", "master"]) {
        r = await this.github("/workflows/dienstplan.yml/dispatches", { method: "POST", body: JSON.stringify({ ref, inputs: { ziel: url.origin } }) });
        if (r.status === 204) break;
      }
      if (!r || r.status !== 204) return json({ error: `GitHub hat den Start abgelehnt (${r && r.status}).` }, 502);
      this.set("refresh_at", String(now));
      return json({ ok: true, since: now });
    }
    if (p === "/api/status" && m === "GET") {
      const since = +(url.searchParams.get("since") || 0), updated = +(this.get("plan_updated") || 0);
      let run = null;
      try {
        const r = await this.github("/runs?event=workflow_dispatch&per_page=1");
        const x = ((await r.json()).workflow_runs || [])[0];
        if (x && new Date(x.created_at).getTime() > since - 60000) run = { status: x.status, conclusion: x.conclusion };
      } catch (e) { }
      return json({ updated, run });
    }

    // ---------- Admin ----------
    if (p.startsWith("/api/admin/")) {
      if (!me.admin) return json({ error: "Nur für Admin." }, 403);
      if (p === "/api/admin/users" && m === "GET")
        return json({ users: this.all("SELECT u, name, status, created, decided, last_login FROM users ORDER BY status='pending' DESC, name") });
      if (p === "/api/admin/user" && m === "POST") {
        const b = await body(), u = String(b.u || "");
        if (u === me.u) return json({ error: "Den eigenen Zugang kannst du hier nicht ändern." }, 400);
        if (!this.one("SELECT u FROM users WHERE u=?", u)) return json({ error: "Unbekannter Benutzer." }, 404);
        if (b.action === "approve") this.sql.exec("UPDATE users SET status='active', decided=? WHERE u=?", now, u);
        else if (b.action === "block") { this.sql.exec("UPDATE users SET status='blocked' WHERE u=?", u); this.sql.exec("DELETE FROM sessions WHERE u=?", u); }
        else if (b.action === "delete") { this.sql.exec("DELETE FROM users WHERE u=?", u); this.sql.exec("DELETE FROM sessions WHERE u=?", u); }
        else return json({ error: "Unbekannte Aktion." }, 400);
        return json({ ok: true });
      }
    }
    return json({ error: "Nicht gefunden." }, 404);
  }
}
