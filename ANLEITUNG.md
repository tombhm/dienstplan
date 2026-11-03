# Dienstplan RW 18: automatisch aktualisieren

So funktioniert es: GitHub startet alle 2 Stunden (ca. 5–23 Uhr) ein Skript. Das loggt sich bei
dienstplan.drk-dortmund.de ein, klickt sich wie du zum Abteilungsplan (RW 18, alle anzeigen),
lädt das PDF, wertet es aus und veröffentlicht die Website **verschlüsselt** neu. Dein iPhone muss
dafür nichts tun. Das alles ist kostenlos.

Zeitaufwand für die Einrichtung: ca. 15 Minuten, am besten am Computer.

---

## 1. GitHub-Konto anlegen
Auf https://github.com/signup registrieren (falls du noch kein Konto hast).

## 2. Repository anlegen und Dateien hochladen
1. Oben rechts auf **+** und dann auf **New repository**.
2. Name: `dienstplan`, Sichtbarkeit: **Public** (kostenlose Websites gibt es nur für öffentliche
   Repositories). Im Repository liegt **nur der Programmcode**, keine Namen und kein Dienstplan.
3. **Create repository** anklicken, danach auf den Link **uploading an existing file**.
4. Diese Dateien aus dem ZIP hineinziehen:
   `fetch_pdf.py`, `parse_dienstplan.py`, `build_site.py`, `template.html`, `requirements.txt`,
   `.gitignore`, `ANLEITUNG.md`. Dann **Commit changes** anklicken.
5. Die Zeitplan-Datei legst du von Hand an, weil der Ordner `.github` auf dem Mac versteckt ist:
   **Add file**, dann **Create new file**. Als Dateinamen genau das eintippen:
   `.github/workflows/dienstplan.yml`
   Den Inhalt der Datei `dienstplan.yml` aus dem ZIP hineinkopieren und **Commit changes** anklicken.

## 3. Passwörter als Secrets hinterlegen
Im Repository unter **Settings**, dann **Secrets and variables**, dann **Actions** dreimal
**New repository secret** anklicken:

| Name               | Inhalt                                                        |
|--------------------|---------------------------------------------------------------|
| `CAREMAN_USER`     | dein Benutzername für dienstplan.drk-dortmund.de              |
| `CAREMAN_PASSWORD` | dein CareMan-Passwort                                         |
| `SITE_PASSWORD`    | ein **neues** Passwort für deine Website (lang, nicht dein CareMan-Passwort!) |

Secrets sind verschlüsselt gespeichert. Niemand kann sie lesen, auch du selbst nicht mehr.

## 4. Website einschalten
**Settings**, dann **Pages**, dann bei *Source* **GitHub Actions** auswählen.

## 5. Erster Testlauf
1. Den Reiter **Actions** öffnen, links auf **Dienstplan aktualisieren**, dann rechts auf **Run workflow**.
2. Für den ersten Lauf das Häkchen **Fehlersuche** setzen und starten.
3. Nach ca. 2 Minuten:
   - **Grüner Haken:** Unter *deploy* steht der Link zu deiner Seite, etwa
     `https://DEINNAME.github.io/dienstplan/`.
   - **Rotes X:** Den Lauf anklicken, dann den Schritt *Dienstplan bei CareMan abholen*. Dort steht,
     welcher Klick nicht geklappt hat. Unten bei *Artifacts* liegen Screenshots der einzelnen
     Schritte. Schick mir die Fehlermeldung und die Screenshots, dann passe ich das Skript an.
     (Die Screenshots zeigen nur das Menü, nie den fertigen Plan, und werden nach einem Tag gelöscht.)

## 6. Aufs iPhone holen
Die Seite in Safari öffnen, auf **Teilen** tippen und **Zum Home-Bildschirm** wählen. Dann
sieht sie aus wie eine App. Einmal das Website-Passwort eingeben, „angemeldet bleiben“ ist schon
angehakt.

## 7. (Optional) Kurzbefehl „Jetzt aktualisieren“
Damit kannst du außerhalb der 2-Stunden-Takte sofort aktualisieren.

1. Auf GitHub: Profilbild, dann **Settings**, dann **Developer settings**, dann
   **Personal access tokens**, dann **Fine-grained tokens** und **Generate new token**.
   - *Repository access:* **Only select repositories**, dann `dienstplan` wählen.
   - *Permissions*, dann *Repository permissions*, dann **Actions: Read and write**.
   - Den Token kopieren (er beginnt mit `github_pat_…`).
2. In der Kurzbefehle-App einen neuen Kurzbefehl anlegen und die Aktion
   **Inhalte von URL abrufen** hinzufügen:
   - URL: `https://api.github.com/repos/DEINNAME/dienstplan/actions/workflows/dienstplan.yml/dispatches`
   - Methode: **POST**
   - Header: `Authorization` = `Bearer github_pat_…` und `Accept` = `application/vnd.github+json`
   - Hauptteil anfordern: **JSON**, Feld `ref` (Text) = `main`
3. Danach die Aktion **Mitteilung anzeigen** mit dem Text „Dienstplan wird aktualisiert (ca. 2 Min.)“ hinzufügen.

---

### Gut zu wissen
- **Zeitplan ändern:** In `dienstplan.yml` die Zeile `cron:` anpassen (Zeiten sind in UTC, also
  1 Stunde früher als bei uns im Winter). GitHub startet Zeitpläne manchmal ein paar Minuten später.
- **Passwort bei CareMan geändert?** Unter Settings, dann Secrets das Secret `CAREMAN_PASSWORD` aktualisieren.
- **Website-Passwort ändern:** `SITE_PASSWORD` ändern und einmal *Run workflow* ausführen.
- **Datenschutz:** Die Website enthält nur verschlüsselte Daten. Ohne Website-Passwort sind sie
  nicht lesbar. Gib das Passwort nur an Kollegen weiter, die den Plan ohnehin sehen dürfen, und
  kläre das Ganze am besten kurz mit der Wachenleitung ab.
