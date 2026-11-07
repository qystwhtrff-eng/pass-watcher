# Passbevakare – Norges ambassad i Stockholm

Kollar var 10:e minut om det finns en ledig tid för **Pass for voksen** på
https://ventus.enalog.se/Booking/Booking/Index/RNEStockholm och mejlar när
det dyker upp något.

Skriptet går igenom samma steg som du gör manuellt (Pass/Personnummer → godta
avtalet, 1 person → Pass for voksen → bekräfta dokumentation → "Første ledige
tidspunkt"), fast med vanliga HTTP-anrop i stället för en webbläsare. Det tar
några sekunder per körning.

- Om det finns lediga tider skickas **ett** mejl. Samma tider mejlas inte igen.
  När tiderna försvunnit och nya kommer skickas ett nytt mejl.
- Om flödet slutar fungera (t.ex. att sidan byggs om) misslyckas körningen, och
  GitHub mejlar dig som äger repot.

## Filer

| Fil | Vad |
|---|---|
| `check_slots.py` | Själva bevakaren |
| `requirements.txt` | Python-paket (`requests`, `beautifulsoup4`) |
| `.github/workflows/passbevakare.yml` | Schemat i GitHub Actions |

## Installation (cirka 10 minuter)

### 1. Skapa ett app-lösenord för Gmail (avsändaren)
Använd ett Gmail-konto som avsändare, gärna ditt eget.
1. Slå på tvåstegsverifiering på kontot om den inte redan är på.
2. Gå till https://myaccount.google.com/apppasswords och skapa ett app-lösenord,
   t.ex. med namnet "passbevakare".
3. Spara den 16 tecken långa koden. Det är den som är `SMTP_PASSWORD`.

(Om du använder Outlook/Hotmail i stället: `SMTP_HOST=smtp-mail.outlook.com`,
`SMTP_PORT=587`. Microsoft har dock stängt av lösenordsinloggning via SMTP för
många konton, så Gmail är enklast.)

### 2. Skapa ett GitHub-repo
1. Skapa ett nytt repo, t.ex. `passbevakare`.
   **Publikt repo rekommenderas**: Actions-minuter är då gratis och obegränsade.
   Ett privat repo har 2 000 gratisminuter/månad, och var 10:e minut ≈ 4 300
   minuter/månad (varje körning räknas som minst 1 minut). Koden innehåller
   inga hemligheter; lösenordet ligger krypterat i *Secrets*.
2. Ladda upp de tre filerna med samma mappstruktur (`.github/workflows/...`).

### 3. Lägg in secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Namn | Värde |
|---|---|
| `SMTP_USER` | avsändaradressen, t.ex. `dittkonto@gmail.com` |
| `SMTP_PASSWORD` | app-lösenordet från steg 1 |
| `MAIL_TO` | pappas mejl, gärna plus ditt: `pappa@exempel.se,du@exempel.se` |
| `SMTP_HOST` | *(valfri)* standard är `smtp.gmail.com` |
| `SMTP_PORT` | *(valfri)* standard är `465` |

### 4. Testa
1. Repo → **Actions** → *Passbevakare* → **Run workflow** och kryssa i
   *Skicka ett testmejl*. Kolla att mejlet kommer fram (titta även i skräpposten).
2. Kör en gång till utan krysset. Loggen ska visa `Inga lediga tider.` just nu.

Sedan går den av sig själv var 10:e minut.

## Bra att veta
- **GitHub pausar scheman efter 60 dagar** utan aktivitet i ett publikt repo.
  Då får du ett mejl från GitHub, och du kan slå på det igen med ett klick under
  Actions. Om det dröjer längre än så kan du göra en liten commit då och då.
- GitHubs cron är inte sekundexakt. Det kan bli 10–20 minuter mellan körningarna
  när GitHub har hög last. Enligt sidan släpps nya tider varje vecka, så det
  räcker gott. När ni ser vilken veckodag och tid de brukar släppas (syns i
  Actions-loggen) kan ni skärpa schemat runt just den tiden.
- Vill ni kolla en annan kategori, ändra `CATEGORY_ADULT_PASS` i skriptet:
  `490` = Pass for voksen, `491` = Pass for barn, `492` = Søknad om personnummer.
- Köra lokalt: `pip install -r requirements.txt` och sedan
  `python check_slots.py --dry-run`. Den varianten skickar inget mejl.
- Var snäll mot servern. Var 10:e minut är lågt. Gå inte ner till varje minut.
