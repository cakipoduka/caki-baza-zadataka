"""
CAKI Matematika - pipeline.py

Jezgra pipelinea (Mathpix OCR, Claude strukturiranje, Google Sheets upis s
detekcijom duplikata, upload slika na Drive). Logika je identična onoj u
Colab notebooku (Koraci 1-4) - jedina razlika je autentifikacija: umjesto
interaktivne Google prijave (google.colab.auth), ovdje se koristi Google
Service Account, jer server (Streamlit) nema interaktivnu sesiju.
"""
import os
import re
import io
import json
import time
import difflib
import requests
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ZADACI_HEADERS = [
    "id", "izvor_tip", "izvor_naziv", "godina", "broj_pdf_ulaza",
    "razina", "razred", "kategorija", "cjelina", "kljucne_rijeci",
    "tekst_zadatka_latex", "tekst_zadatka_mathjax",
    "rjesenje", "rjesenje_status", "tip_rjesenja_izvor",
    "slika_putanja", "video_url",
    "vizualni_potencijal", "geogebra_komande", "geogebra_material_id",
    "tezina", "max_bodovi", "slicni_zadaci",
    "status_provjere", "skenirano", "pretext_permalink",
    "tip_zadatka", "slika_zadana",
]

EXTRACTION_SYSTEM_PROMPT = """Ti si asistent koji strukturira zadatke iz hrvatske državne mature i drugih matematičkih materijala.
Dobit ćeš OCR tekst (Mathpix Markdown) ispita, i po mogućnosti tekst s rješenjima/bodovanjem.

Tvoj zadatak:
1. Razdvoji ispit na pojedinačne zadatke (zadrži izvorni redni broj u polju privremeni_broj).
2. Za svaki zadatak izvuci čist tekst u polje tekst_zadatka_latex (LaTeX matematika unutar $...$, retci unutar zadatka odvojeni s \\\\ kao LaTeX prijelom retka, bez naredbi za formatiranje cijelog dokumenta).
3. Ako je u ovoj poruci dan odjeljak 'TEKST RJEŠENJA/BODOVANJA', pronađi odgovarajuće rješenje za svaki zadatak po broju i uključi puni postupak ako postoji, inače samo finalni rezultat. AKO TAJ ODJELJAK NIJE DAN, OBAVEZNO ostavi polje rjesenje prazno ("") - NE smiješ sam rješavati zadatak niti nagađati odgovor, čak i ako znaš rješenje.
4. Dodijeli TOČNO JEDNU kategoriju i cjelinu IZ DANOG ŠIFRARNIKA — ne izmišljaj nove nazive, koristi postojeće doslovno.
5. Procijeni težinu: "lako", "srednje" ili "tesko".
6. Predloži 3-6 ključnih riječi/pojmova (kljucne_rijeci, odvojene zarezom).
7. vizualni_potencijal: "da" SAMO ako zadatak NEMA zadanu sliku ali bi GeoGebra vizualizacija pomogla razumijevanju (npr. tekstualni zadatak o funkciji bez priloženog grafa), inače "ne".
8. Ako pronađeš broj bodova za zadatak u tekstu bodovanja, upiši u max_bodovi (samo broj), inače ostavi prazno.
9. tip_rjesenja_izvor: "puni_postupak" ako rješenje sadrži korake, "samo_rezultat" ako je samo finalni odgovor, inače prazno.
10. Ako nisi siguran u OCR neke formule/rješenja, kratko napomeni u status_provjere (npr. "OCR nesiguran kod zadatka 5, provjeriti simbol"), inače ostavi prazno.
11. tip_zadatka: "visestruki_izbor" (ima ponuđene odgovore A/B/C/D), "kratki_odgovor" (traži se kratak numerički/simbolički odgovor, npr. "Odgovor: ____"), ili "prosireni_odgovor" (traži se prikaz cijelog postupka rješavanja).
12. slika_zadana: "da" ako je u tekstu ispita (Mathpix Markdown) uz ovaj zadatak priložena slika/graf/dijagram koji je DIO zadatka (student mora pročitati podatke sa slike da riješi zadatak) - PREPOZNAJ TO PO MARKDOWN REFERENCI NA SLIKU (oblika ![](url) ili slično) koja se nalazi neposredno uz tekst tog zadatka. Ako je slika_zadana="da", OBAVEZNO u polje slika_url upiši TOČAN URL te slike, prekopiran iz Mathpix Markdown teksta (ne izmišljaj URL). Ako nema takve slike, slika_zadana="ne" i slika_url prazan.
VAŽNO: slika_zadana i vizualni_potencijal se međusobno isključuju - zadatak sa zadanom slikom NIKAD ne dobiva vizualni_potencijal="da" (ne rekonstruiramo zadanu sliku preko GeoGebre, samo je izrežemo iz originala).

VAŽNO: Odgovori ISKLJUČIVO JSON listom objekata, bez ikakvog teksta prije/poslije, bez markdown ograda (bez ```). Svaki objekt neka ima točno ova polja:
privremeni_broj, tekst_zadatka_latex, kategorija, cjelina, kljucne_rijeci, tezina, vizualni_potencijal, rjesenje, tip_rjesenja_izvor, max_bodovi, status_provjere, tip_zadatka, slika_zadana, slika_url
"""


# --- Google auth (Service Account) ---

def get_credentials(service_account_info: dict):
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


def get_gspread_client(service_account_info: dict):
    return gspread.authorize(get_credentials(service_account_info))


def get_drive_service(service_account_info: dict):
    return build("drive", "v3", credentials=get_credentials(service_account_info))


# --- Mathpix ---

def mathpix_process_pdf(pdf_bytes: bytes, filename: str, app_id: str, app_key: str) -> str:
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.post(
        "https://api.mathpix.com/v3/pdf",
        headers=headers,
        files={"file": (filename, pdf_bytes)},
        data={"options_json": '{"conversion_formats": {"md": true}}'},
    )
    response.raise_for_status()
    return response.json()["pdf_id"]


def mathpix_check_status(pdf_id: str, app_id: str, app_key: str) -> dict:
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.get(f"https://api.mathpix.com/v3/pdf/{pdf_id}", headers=headers)
    response.raise_for_status()
    return response.json()


def mathpix_get_markdown(pdf_id: str, app_id: str, app_key: str) -> str:
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.get(f"https://api.mathpix.com/v3/pdf/{pdf_id}.md", headers=headers)
    response.raise_for_status()
    return response.text


def mathpix_wait_and_get(pdf_id, app_id, app_key, poll_seconds=3, timeout_seconds=300, log=None) -> str:
    waited = 0
    while waited < timeout_seconds:
        status = mathpix_check_status(pdf_id, app_id, app_key)
        state = status.get("status")
        if log:
            log(f"⏳ Status: {state} ({waited}s)")
        if state == "completed":
            return mathpix_get_markdown(pdf_id, app_id, app_key)
        if state == "error":
            raise RuntimeError(f"Mathpix greška: {status}")
        time.sleep(poll_seconds)
        waited += poll_seconds
    raise TimeoutError("Mathpix obrada nije završila u zadanom vremenu.")


# --- Šifrarnik ---

def build_sifrarnik_text(sheet) -> str:
    ws = sheet.worksheet("Sifrarnik_cjelina")
    rows = ws.get_all_values()[1:]
    return "\n".join(f"- Kategorija: {r[0]} | Cjelina: {r[1]}" for r in rows if len(r) >= 2 and r[0])


# --- Claude extrakcija (s automatskim dijeljenjem ako se odgovor odreže) ---

def extract_zadaci_with_claude(ispit_md, rjesenja_md, sifrarnik_text, anthropic_api_key,
                                model="claude-sonnet-5", _preostala_dubina=2, log=None):
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    user_content = f"""ŠIFRARNIK (koristi isključivo ove kategorije/cjeline, doslovno):
{sifrarnik_text}

=== TEKST ISPITA (Mathpix Markdown) ===
{ispit_md}
"""
    if rjesenja_md:
        user_content += f"\n=== TEKST RJEŠENJA/BODOVANJA (Mathpix Markdown) ===\n{rjesenja_md}\n"

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    if response.stop_reason == "max_tokens":
        if _preostala_dubina > 0 and len(ispit_md) > 1000:
            if log:
                log(f"⚠️ Odgovor odrezan (max_tokens) - dijelim ispit na dva dijela "
                    f"(preostalo dubina: {_preostala_dubina}) i ponovno pokušavam...")
            polovica = len(ispit_md) // 2
            prijelom = ispit_md.rfind("\n", 0, polovica)
            if prijelom == -1:
                prijelom = polovica
            dio1 = extract_zadaci_with_claude(ispit_md[:prijelom], rjesenja_md, sifrarnik_text,
                                               anthropic_api_key, model, _preostala_dubina - 1, log)
            dio2 = extract_zadaci_with_claude(ispit_md[prijelom:], rjesenja_md, sifrarnik_text,
                                               anthropic_api_key, model, _preostala_dubina - 1, log)
            return dio1 + dio2
        elif log:
            log("⚠️ UPOZORENJE: odgovor odrezan čak i nakon maksimalnog dijeljenja - rezultat je vjerojatno nepotpun.")

    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
    raw_text = re.sub(r"```$", "", raw_text).strip()
    zadaci = json.loads(raw_text, strict=False)

    for z in zadaci:
        latex_text = z.get("tekst_zadatka_latex", "")
        z["tekst_zadatka_mathjax"] = latex_text.replace("\\\\", "<br>")
    return zadaci


# --- Slike (preuzimanje s Mathpixa, upload na Drive) ---

def upload_image_to_drive(drive_service, folder_id: str, filename: str, image_bytes: bytes):
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/png", resumable=False)
    file_metadata = {"name": filename, "parents": [folder_id]}
    created = drive_service.files().create(
        body=file_metadata, media_body=media, fields="id,webViewLink", supportsAllDrives=True
    ).execute()
    return created.get("id"), created.get("webViewLink")


def preuzmi_i_spremi_slike(zadaci, izvor_naziv, mathpix_app_id, mathpix_app_key,
                            drive_service, slike_folder_id, log=None):
    broj_preuzetih = 0
    for z in zadaci:
        if z.get("slika_zadana") == "da" and z.get("slika_url"):
            try:
                headers = {"app_id": mathpix_app_id, "app_key": mathpix_app_key}
                resp = requests.get(z["slika_url"], headers=headers, timeout=30)
                resp.raise_for_status()
                naziv = f"{izvor_naziv}_zad{z.get('privremeni_broj', '0')}.png".replace(" ", "_")
                file_id, link = upload_image_to_drive(drive_service, slike_folder_id, naziv, resp.content)
                z["slika_putanja"] = link or file_id
                broj_preuzetih += 1
                if log:
                    log(f"🖼️ Slika spremljena za zadatak #{z.get('privremeni_broj')}: {naziv}")
            except Exception as e:
                if log:
                    log(f"⚠️ Neuspjelo preuzimanje slike za zadatak #{z.get('privremeni_broj')}: {e}")
                z["slika_putanja"] = ""
        else:
            z["slika_putanja"] = z.get("slika_putanja", "")
    return zadaci


# --- Upis u Sheet (s detekcijom duplikata po sličnosti teksta) ---

def _normalize_za_usporedbu(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def nadopuni_ili_dodaj_zadatke(ws_zadaci, zadaci, izvor_tip, izvor_naziv, godina, razina, broj_pdf_ulaza,
                                skenirano="ne", prag_slicnosti=0.85, prag_slicnosti_isti_naziv=0.75, log=None):
    all_values = ws_zadaci.get_all_values()
    data_rows = all_values[1:]

    existing_lookup = [
        (i + 2, row[2] if len(row) > 2 else "", row[10] if len(row) > 10 else "")
        for i, row in enumerate(data_rows)
    ]

    id_prefix = izvor_naziv.replace(" ", "_")
    existing_count = sum(1 for r in data_rows if r and r[0].startswith(id_prefix))

    novi_redovi = []
    broj_azuriranih = 0
    broj_dodanih = 0

    for z in zadaci:
        norm_novi = _normalize_za_usporedbu(z.get("tekst_zadatka_latex", ""))
        duljina_novi = len(norm_novi)
        najbolji_redak, najbolja_slicnost, najbolji_naziv = None, 0.0, None

        for row_number, existing_naziv, existing_latex in existing_lookup:
            norm_existing = _normalize_za_usporedbu(existing_latex)
            if duljina_novi and abs(len(norm_existing) - duljina_novi) / duljina_novi > 0.4:
                continue
            omjer = difflib.SequenceMatcher(None, norm_novi, norm_existing).ratio()
            if omjer > najbolja_slicnost:
                najbolja_slicnost, najbolji_redak, najbolji_naziv = omjer, row_number, existing_naziv

        isti_naziv = najbolji_redak and najbolji_naziv == izvor_naziv
        prag = prag_slicnosti_isti_naziv if isti_naziv else prag_slicnosti

        if najbolji_redak and najbolja_slicnost >= prag:
            rjesenje_novo = z.get("rjesenje", "")
            if rjesenje_novo:
                ws_zadaci.update(range_name=f"M{najbolji_redak}:O{najbolji_redak}", values=[[
                    rjesenje_novo, "sluzbeno", z.get("tip_rjesenja_izvor", ""),
                ]])
            if z.get("slika_putanja", ""):
                ws_zadaci.update(range_name=f"P{najbolji_redak}", values=[[z.get("slika_putanja", "")]])
            if z.get("max_bodovi", ""):
                ws_zadaci.update(range_name=f"V{najbolji_redak}", values=[[z.get("max_bodovi", "")]])
            if z.get("tip_zadatka", ""):
                ws_zadaci.update(range_name=f"AA{najbolji_redak}", values=[[z.get("tip_zadatka", "")]])
            if z.get("slika_zadana", ""):
                ws_zadaci.update(range_name=f"AB{najbolji_redak}", values=[[z.get("slika_zadana", "")]])
            if log:
                znak = "📄" if isti_naziv else "🔤"
                log(f"🔁 Zadatak #{z.get('privremeni_broj')} = duplikat retka {najbolji_redak} "
                    f"({znak}{najbolja_slicnost:.0%}, prag {prag:.0%}) - nadopunjen.")
            broj_azuriranih += 1
        else:
            zid = f"{id_prefix}_{existing_count + broj_dodanih + 1:03d}"
            row = [
                zid, izvor_tip, izvor_naziv, godina, broj_pdf_ulaza,
                razina, "",
                z.get("kategorija", ""), z.get("cjelina", ""), z.get("kljucne_rijeci", ""),
                z.get("tekst_zadatka_latex", ""), z.get("tekst_zadatka_mathjax", ""),
                z.get("rjesenje", ""),
                "sluzbeno" if z.get("rjesenje") else "nedostaje",
                z.get("tip_rjesenja_izvor", ""),
                z.get("slika_putanja", ""), "",
                z.get("vizualni_potencijal", ""),
                "", "",
                z.get("tezina", ""), z.get("max_bodovi", ""),
                "",
                z.get("status_provjere", ""), skenirano,
                "",
                z.get("tip_zadatka", ""), z.get("slika_zadana", ""),
            ]
            novi_redovi.append(row)
            broj_dodanih += 1

    if novi_redovi:
        ws_zadaci.append_rows(novi_redovi)

    return broj_dodanih, broj_azuriranih
