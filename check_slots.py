#!/usr/bin/env python3
"""
Passbevakare – Norges ambassad i Stockholm (ventus.enalog.se)

Går igenom bokningsflödet precis som i webbläsaren:
  1. Startsida: Sakstype = Pass/Personnummer -> "Booke ny tid"
  2. "Jeg godtar avtalen" + Antall personer = 1 -> "Neste"
  3. "Pass for voksen" -> "Neste"
  4. "Jeg bekrefter å ha med all nødvendig dokumentasjon" -> "Neste"
  5. "Første ledige tidspunkt"
och skickar ett mejl om det finns lediga tider.

Inställningar via miljövariabler:
  SMTP_HOST      (default smtp.gmail.com)
  SMTP_PORT      (default 465, SSL)
  SMTP_USER      avsändarkonto, t.ex. dittkonto@gmail.com
  SMTP_PASSWORD  app-lösenord (inte vanliga lösenordet)
  MAIL_TO        mottagare, kommaseparerat (t.ex. pappa@x.se,du@y.se)
  STATE_FILE     fil som minns senast notifierade tider (default state.json)

Flaggor:
  --dry-run      kolla men skicka inget mejl
  --test-email   skicka ett testmejl och avsluta

Exit-koder: 0 = ok (med eller utan tider), 1 = flödet gick inte igenom
(t.ex. sidan har ändrats) – då mejlar GitHub dig om misslyckad körning.
"""

import json
import os
import re
import smtplib
import sys
from email.message import EmailMessage

import requests
from bs4 import BeautifulSoup

BASE = "https://ventus.enalog.se/Booking/Booking/"
SITE = "RNEStockholm"
INDEX_URL = f"{BASE}Index/{SITE}"
NEXT_URL = f"{BASE}Next/{SITE}"
RESTART_URL = f"{BASE}Restart/{SITE}"

SERVICE_GROUP_PASS = "504"    # Pass/Personnummer
CATEGORY_ADULT_PASS = "490"   # Pass for voksen
NO_SLOTS_TEXT = "Ingen ledige datoer funnet"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (passbevakare; checks every ~10 min)",
    "Accept-Language": "nb-NO,nb;q=0.9,sv;q=0.8,en;q=0.7",
}


class FlowError(Exception):
    pass


def _token(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.find("input", {"name": "__RequestVerificationToken"})
    return el["value"] if el and el.has_attr("value") else ""


def _post(session, url, prev_html, data):
    payload = dict(data)
    tok = _token(prev_html)
    if tok:
        payload["__RequestVerificationToken"] = tok
    r = session.post(url, data=payload, timeout=30)
    r.raise_for_status()
    return r.text


def _expect(html, marker, step):
    if marker not in html:
        raise FlowError(f"Steg '{step}' misslyckades – hittade inte '{marker}' på sidan.")


def fetch_timetable_html() -> str:
    s = requests.Session()
    s.headers.update(HEADERS)

    r = s.get(INDEX_URL, timeout=30)
    r.raise_for_status()
    html = r.text
    if "ServiceGroupId" not in html:
        # Sessionen hamnade på felsidan – tryck "Tilbake til start"
        html = _post(s, RESTART_URL, html, {"NextButtonID1": "Tilbake til start"})
    _expect(html, "ServiceGroupId", "startsida")

    html = _post(s, NEXT_URL, html, {
        "FormId": "1",
        "ServiceGroupId": SERVICE_GROUP_PASS,
        "StartNextButton": "Booke ny tid",
    })
    _expect(html, "AcceptInformationStorage", "avtale")

    html = _post(s, NEXT_URL, html, {
        "AcceptInformationStorage": "true",
        "NumberOfPeople": "1",
        "Next": "Neste",
    })
    _expect(html, "ServiceCategoryCustomers", "tjenestekategorier")

    html = _post(s, NEXT_URL, html, {
        "ServiceCategoryCustomers[0].CustomerIndex": "0",
        "ServiceCategoryCustomers[0].ServiceCategoryId": CATEGORY_ADULT_PASS,
        "Next": "Neste",
    })
    _expect(html, "AcceptConditionalAgreement", "dokumentasjonskrav")

    html = _post(s, NEXT_URL, html, {
        "AcceptConditionalAgreement": "true",
        "Next": "Neste",
    })
    _expect(html, "TimeSearchFirstAvailableButton", "velg tidspunkt")

    soup = BeautifulSoup(html, "html.parser")

    def val(name, default=""):
        el = soup.find(attrs={"name": name})
        if el is None:
            return default
        if el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            return opt["value"] if opt else default
        return el.get("value", default)

    html = _post(s, NEXT_URL, html, {
        "FormId": "1",
        "RegionId": val("RegionId", "0"),
        "SectionId": val("SectionId"),
        "ServiceTypeId": val("ServiceTypeId"),
        "FromDateString": val("FromDateString"),
        "TimeSearchFirstAvailableButton": "Første ledige tidspunkt",
    })
    if "timetable" not in html and NO_SLOTS_TEXT not in html:
        raise FlowError("Resultatsidan saknar både tidtabell och 'Ingen ledige datoer'.")
    return html


def parse_slots(html: str):
    """Returnerar (har_tider, lista med beskrivningar av tider)."""
    if NO_SLOTS_TEXT in html:
        return False, []

    soup = BeautifulSoup(html, "html.parser")
    slots = []

    # Vanliga markeringar för en bokningsbar tid i Ventus/Nemo-Q
    for el in soup.select("[data-fromdatetime]"):
        slots.append(el["data-fromdatetime"])
    if not slots:
        for el in soup.select("table.timetable input[type=radio]"):
            v = el.get("value") or el.get("id") or ""
            slots.append(v)
    if not slots:
        # Generiskt: innehåll i dagkolumnerna = tider
        for td in soup.select("td.timetable-cells"):
            day = td.get("headers", [""])
            day = day[0] if isinstance(day, list) and day else str(day)
            for cell in td.select(".cellcontainer > *"):
                txt = " ".join(cell.get_text(" ", strip=True).split())
                title = cell.get("title", "")
                slots.append(f"{day} {title or txt}".strip())

    slots = sorted({s for s in slots if s})
    # Saknas "Ingen ledige"-texten räknar vi det som att tider finns,
    # även om vi inte lyckas tolka exakt vilka.
    return True, slots


def send_email(subject: str, body: str):
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    user = os.environ["SMTP_USER"]
    pwd = os.environ["SMTP_PASSWORD"]
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to)
    msg.set_content(body)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
            smtp.send_message(msg)


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def main():
    dry = "--dry-run" in sys.argv
    state_path = os.environ.get("STATE_FILE", "state.json")

    if "--test-email" in sys.argv:
        send_email("Passbevakaren: testmejl",
                   "Det här är ett testmejl. Om du ser det fungerar notifieringen.\n")
        print("Testmejl skickat.")
        return 0

    try:
        html = fetch_timetable_html()
    except (FlowError, requests.RequestException) as e:
        print(f"FEL: {e}", file=sys.stderr)
        return 1

    has_slots, slots = parse_slots(html)
    state = load_state(state_path)

    if not has_slots:
        print("Inga lediga tider.")
        state["notified_slots"] = []   # nollställ så nästa fynd notifieras
        save_state(state_path, state)
        return 0

    print(f"LEDIGA TIDER: {slots or '(kunde inte tolka exakt tid)'}")
    key = slots or ["unknown"]
    if key == state.get("notified_slots"):
        print("Samma tider som redan notifierats – skickar inget nytt mejl.")
        return 0

    body = (
        "Hej!\n\n"
        "Det finns nu lediga tider för passförnyelse (Pass for voksen) "
        "på Norges ambassad i Stockholm.\n\n"
        + ("Tider:\n" + "\n".join(f"  - {s}" for s in slots) + "\n\n" if slots else "")
        + "Boka snabbt här (gå igenom stegen och välj 'Første ledige tidspunkt'):\n"
        f"{INDEX_URL}\n\n"
        "Kom ihåg utskrift av personbevis från Skatteverket.\n\n"
        "/Passbevakaren\n"
    )
    if dry:
        print("--dry-run: skulle ha skickat:\n" + body)
    else:
        send_email("Ledig passtid på norska ambassaden!", body)
        print("Mejl skickat.")
        state["notified_slots"] = key
        save_state(state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
