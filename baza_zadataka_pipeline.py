"""
CAKI Matematika - baza_zadataka_pipeline.py

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
    "razina", "razred", "kategorija", "cjelina", "potpoglavlje", "kljucne_rijeci",
    "tekst_zadatka_latex", "tekst_zadatka_mathjax",
    "rjesenje", "rjesenje_status", "tip_rjesenja_izvor",
    "slika_putanja", "video_url",
    "vizualni_potencijal", "geogebra_komande", "geogebra_material_id",
    "tezina", "max_bodovi", "slicni_zadaci",
    "status_provjere", "skenirano", "pretext_permalink",
    "tip_zadatka", "slika_zadana", "ponudjeni_odgovori", "konacan_odgovor",
    "uputa",
]


def _col_letter(field_name: str, headers=ZADACI_HEADERS) -> str:
    """Pretvori naziv polja u slovo(a) Sheet stupca (0-indeksirano -> A, B, ... Z, AA, AB, ...).
    Računa se dinamički iz ZADACI_HEADERS, umjesto hardkodiranih slova - tako da
    dodavanje/premještanje kolone (npr. `potpoglavlje`) ne pomakne sve nakon nje neopaženo."""
    idx = headers.index(field_name)
    letters = ""
    idx += 1  # 1-indeksirano za standardni algoritam pretvorbe
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters

EXTRACTION_SYSTEM_PROMPT = """Ti si asistent koji strukturira zadatke iz hrvatske državne mature i drugih matematičkih materijala.
Dobit ćeš OCR tekst (Mathpix Markdown) ispita, i po mogućnosti tekst s rješenjima/bodovanjem.

Tvoj zadatak:
1. Razdvoji ispit na pojedinačne zadatke (zadrži izvorni redni broj u polju privremeni_broj).
1b. AKO jedan zadatak sadrži VIŠE NUMERIRANIH VARIJANTI istog problema s različitim ulaznim
vrijednostima (čest slučaj u zbirkama, npr. 'Riješi pravokutni trokut ako je: 1) a=3, b=4  2) c=5, b=3
3) c=21, a=2'), NE ostavljaj ih spojene u jednom zadatku - RAZDVOJI SVAKU VARIJANTU U POTPUNO
SAMOSTALAN ZADATAK: ponovi zajednički uvodni tekst uz svaku varijantu tako da svaki proizvedeni
zadatak ima cjelovit, samostojeći tekst_zadatka_latex (npr. 'Riješi pravokutni trokut ako je a=3, b=4.',
zatim zaseban zadatak 'Riješi pravokutni trokut ako je c=5, b=3.', itd). Svaki takav pod-zadatak dobiva
svoj privremeni_broj nastavkom slovom (npr. '5a', '5b', '5c') da se zna da dijele isti izvorni broj.
Ako rješenja za pojedine varijante postoje odvojeno u tekstu rješenja, pridijeli svakoj svoje; ako ne,
polje rjesenje ostaje prazno za tu varijantu (vidi točku 3).
2. Za svaki zadatak izvuci ČIST TEKST PITANJA u polje tekst_zadatka_latex (LaTeX matematika unutar $...$, bez naredbi za formatiranje cijelog dokumenta). VAŽNO: NE uključuj ponuđene odgovore A/B/C/D u ovo polje - oni idu zasebno, vidi točku 13.
3. Ako je u ovoj poruci dan odjeljak 'TEKST RJEŠENJA/BODOVANJA', pronađi odgovarajuće rješenje za svaki zadatak po broju i uključi puni postupak ako postoji, inače samo finalni rezultat. AKO TAJ ODJELJAK NIJE DAN, OBAVEZNO ostavi polje rjesenje prazno ("") - NE smiješ sam rješavati zadatak niti nagađati odgovor, čak i ako znaš rješenje.
4. Dodijeli TOČNO JEDNU kategoriju i cjelinu IZ DANOG ŠIFRARNIKA — ne izmišljaj nove nazive, koristi postojeće doslovno.
4b. Dodijeli TOČNO JEDNO potpoglavlje IZ DANOG ŠIFRARNIKA POTPOGLAVLJA, isključivo od onih navedenih za dodijeljenu cjelinu — ne izmišljaj nove nazive. Ako niti jedno ponuđeno potpoglavlje za tu cjelinu ne odgovara (rijetko), ostavi polje potpoglavlje prazno ("") umjesto nagađanja.
4c. Ako izvorni materijal sadrži EKSPLICITNU uputu/naznaku za rješavanje odvojenu od punog rješenja (npr. "Uputa: ..." ili "Naznaka: ..." prije samog rješenja), izvuci je doslovno u polje uputa. NIKAD ne izmišljaj uputu koje nema u izvoru - ako je nema, polje uputa ostaje prazno ("").
5. Procijeni težinu: "lako", "srednje" ili "tesko".
6. Predloži 3-6 ključnih riječi/pojmova (kljucne_rijeci, odvojene zarezom).
7. vizualni_potencijal: "da" SAMO ako zadatak NEMA zadanu sliku ali bi GeoGebra vizualizacija pomogla razumijevanju (npr. tekstualni zadatak o funkciji bez priloženog grafa), inače "ne".
8. Ako pronađeš broj bodova za zadatak u tekstu bodovanja, upiši u max_bodovi (samo broj), inače ostavi prazno.
9. tip_rjesenja_izvor: "puni_postupak" ako rješenje sadrži korake, "samo_rezultat" ako je samo finalni odgovor, inače prazno.
10. Ako nisi siguran u OCR neke formule/rješenja, kratko napomeni u status_provjere (npr. "OCR nesiguran kod zadatka 5, provjeriti simbol"), inače ostavi prazno.
11. tip_zadatka: "visestruki_izbor" (ima ponuđene odgovore A/B/C/D), "kratki_odgovor" (traži se kratak numerički/simbolički odgovor, npr. "Odgovor: ____"), ili "prosireni_odgovor" (traži se prikaz cijelog postupka rješavanja).
12. slika_zadana: "da" ako je u tekstu ispita (Mathpix Markdown) uz ovaj zadatak priložena slika/graf/dijagram koji je DIO zadatka (student mora pročitati podatke sa slike da riješi zadatak) - PREPOZNAJ TO PO MARKDOWN REFERENCI NA SLIKU (oblika ![](url) ili slično) koja se nalazi neposredno uz tekst tog zadatka. Ako je slika_zadana="da", OBAVEZNO u polje slika_url upiši TOČAN URL te slike, prekopiran iz Mathpix Markdown teksta (ne izmišljaj URL). Ako nema takve slike, slika_zadana="ne" i slika_url prazan.
VAŽNO: slika_zadana i vizualni_potencijal se međusobno isključuju - zadatak sa zadanom slikom NIKAD ne dobiva vizualni_potencijal="da" (ne rekonstruiramo zadanu sliku preko GeoGebre, samo je izrežemo iz originala).
13. ponudjeni_odgovori: SAMO za tip_zadatka="visestruki_izbor" - JSON lista ponuđenih odgovora BEZ oznaka A/B/C/D, redoslijedom kako se pojavljuju (npr. ["5", "4.6", "4.58", "4.573"]). Za sve ostale tipove zadataka, prazna lista [].
14. konacan_odgovor: KRATAK, čist finalni odgovor, odvojen od punog postupka u polju rjesenje. Za visestruki_izbor: samo slovo točnog odgovora (npr. "C"). Za kratki_odgovor/prosireni_odgovor: kratka vrijednost (npr. "3", "1/2", "x=5"). Ako rjesenje nije dano (vidi točku 3), ostavi prazno.

VAŽNO: Odgovori ISKLJUČIVO JSON listom objekata, bez ikakvog teksta prije/poslije, bez markdown ograda (bez ```). Svaki objekt neka ima točno ova polja:
privremeni_broj, tekst_zadatka_latex, kategorija, cjelina, potpoglavlje, kljucne_rijeci, tezina, vizualni_potencijal, rjesenje, tip_rjesenja_izvor, max_bodovi, status_provjere, tip_zadatka, slika_zadana, slika_url, ponudjeni_odgovori, konacan_odgovor, uputa
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


SLIKA_EKSTENZIJE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def je_slika(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in SLIKA_EKSTENZIJE


def mathpix_process_image(image_bytes: bytes, filename: str, app_id: str, app_key: str) -> str:
    """OCR JEDNE slike preko Mathpixovog /v3/text endpointa. Za razliku od /v3/pdf,
    ovo je SINKRONI poziv - odgovor (Mathpix Markdown) stiže odmah u istom pozivu,
    bez pdf_id-a i bez pollinga (mathpix_wait_and_get ovdje nije potreban)."""
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.post(
        "https://api.mathpix.com/v3/text",
        headers=headers,
        files={"file": (filename, image_bytes)},
        data={"options_json": '{"math_inline_delimiters": ["$", "$"], "rm_spaces": true}'},
    )
    response.raise_for_status()
    return response.json().get("text", "")


def mathpix_ocr_datoteka(file_bytes: bytes, filename: str, app_id: str, app_key: str, log=None) -> str:
    """Jedinstvena ulazna točka za OCR JEDNE datoteke, PDF ILI slika - grana se
    automatski po ekstenziji imena datoteke. PDF ide na asinkroni /v3/pdf (pošalji
    pa čekaj), slika na sinkroni /v3/text (gotovo u istom pozivu)."""
    if je_slika(filename):
        if log:
            log(f"🖼️ Šaljem sliku na Mathpix ({filename})...")
        return mathpix_process_image(file_bytes, filename, app_id, app_key)
    if log:
        log(f"📄 Šaljem PDF na Mathpix ({filename})...")
    pdf_id = mathpix_process_pdf(file_bytes, filename, app_id, app_key)
    return mathpix_wait_and_get(pdf_id, app_id, app_key, log=log)


def mathpix_ocr_vise_datoteka(datoteke, app_id, app_key, log=None):
    """OCR liste uploadanih datoteka (bilo koja kombinacija PDF-ova i slika) i
    spajanje rezultata u jedan Mathpix Markdown tekst, razdvojen s '---' (isti
    obrazac kao dosadašnje spajanje rjesenja_pdf_1/rjesenja_pdf_2). Svaki element
    liste mora imati .getvalue() i .name (Streamlit UploadedFile objekti).
    Vraća None za praznu listu, da pozivatelj ne mora provjeravati posebno."""
    dijelovi = []
    for f in datoteke:
        tekst = mathpix_ocr_datoteka(f.getvalue(), f.name, app_id, app_key, log=log)
        dijelovi.append(tekst)
        if log:
            log(f"✅ OCR gotov ({f.name}, {len(tekst)} znakova)")
    return "\n\n---\n\n".join(dijelovi) if dijelovi else None


# --- Šifrarnik ---

def build_sifrarnik_text(sheet) -> str:
    ws = sheet.worksheet("Sifrarnik_cjelina")
    rows = ws.get_all_values()[1:]
    return "\n".join(f"- Kategorija: {r[0]} | Cjelina: {r[1]}" for r in rows if len(r) >= 2 and r[0])


def get_potpoglavlja_po_cjelini(sheet) -> dict:
    """Vraća {cjelina: [(potpoglavlje, redoslijed), ...]} sortirano po redoslijedu,
    čitano iz taba 'Sifrarnik_potpoglavlja' (stupci: cjelina, potpoglavlje, redoslijed)."""
    ws = sheet.worksheet("Sifrarnik_potpoglavlja")
    rows = ws.get_all_values()[1:]
    po_cjelini = {}
    for r in rows:
        if len(r) < 2 or not r[0] or not r[1]:
            continue
        cjelina, potpoglavlje = r[0].strip(), r[1].strip()
        try:
            redoslijed = float(r[2]) if len(r) > 2 and r[2] else 999
        except ValueError:
            redoslijed = 999
        po_cjelini.setdefault(cjelina, []).append((potpoglavlje, redoslijed))
    for cjelina in po_cjelini:
        po_cjelini[cjelina].sort(key=lambda t: t[1])
    return po_cjelini


def build_sifrarnik_potpoglavlja_text(sheet) -> str:
    po_cjelini = get_potpoglavlja_po_cjelini(sheet)
    lines = []
    for cjelina, stavke in po_cjelini.items():
        popis = ", ".join(p for p, _ in stavke)
        lines.append(f"- Cjelina: {cjelina} | Potpoglavlja: {popis}")
    return "\n".join(lines)


# --- Claude extrakcija (s automatskim dijeljenjem ako se odgovor odreže) ---

def extract_zadaci_with_claude(ispit_md, rjesenja_md, sifrarnik_text, anthropic_api_key,
                                sifrarnik_potpoglavlja_text="", model="claude-sonnet-5",
                                _preostala_dubina=2, log=None):
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    user_content = f"""ŠIFRARNIK (koristi isključivo ove kategorije/cjeline, doslovno):
{sifrarnik_text}

ŠIFRARNIK POTPOGLAVLJA (za svaku cjelinu, koristi isključivo navedena potpoglavlja, doslovno):
{sifrarnik_potpoglavlja_text}

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
                                               anthropic_api_key, sifrarnik_potpoglavlja_text,
                                               model, _preostala_dubina - 1, log)
            dio2 = extract_zadaci_with_claude(ispit_md[prijelom:], rjesenja_md, sifrarnik_text,
                                               anthropic_api_key, sifrarnik_potpoglavlja_text,
                                               model, _preostala_dubina - 1, log)
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

def upload_image_to_drive(drive_service, folder_id: str, filename: str, image_bytes: bytes, mimetype: str = "image/png"):
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype=mimetype, resumable=False)
    file_metadata = {"name": filename, "parents": [folder_id]}
    created = drive_service.files().create(
        body=file_metadata, media_body=media, fields="id,webViewLink", supportsAllDrives=True
    ).execute()
    return created.get("id"), created.get("webViewLink")


def preuzmi_i_spremi_slike(zadaci, izvor_naziv, mathpix_app_id, mathpix_app_key,
                            drive_service, slike_folder_id, log=None):
    """
    Preuzima slike i sprema ih u 02_SLIKE folder na Driveu (isti folder koji je u
    Colabu mountan na LATEX_BAZA_ROOT/02_SLIKE). U `slika_putanja` upisuje SAMO
    naziv datoteke (npr. "A2010_ljetni_zad17.png") - IZRAVNU, prenosivu referencu,
    a ne Drive "view" link (koji je krhak i beskoristan za PreTeXt build, koji
    slike čita izravno s diska). Puna putanja se sastavlja pri PreTeXt buildu kao
    os.path.join(LATEX_BAZA_ROOT, "02_SLIKE", slika_putanja).
    """
    broj_preuzetih = 0
    for z in zadaci:
        if z.get("slika_zadana") == "da" and z.get("slika_url"):
            try:
                headers = {"app_id": mathpix_app_id, "app_key": mathpix_app_key}
                resp = requests.get(z["slika_url"], headers=headers, timeout=30)
                resp.raise_for_status()
                naziv = f"{izvor_naziv}_zad{z.get('privremeni_broj', '0')}.png".replace(" ", "_")
                upload_image_to_drive(drive_service, slike_folder_id, naziv, resp.content)
                z["slika_putanja"] = naziv
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


def backup_sheet(drive_service, sheet_id: str, backup_folder_id: str, log=None):
    """
    Napravi potpunu, vremenski označenu kopiju cijelog Google Sheeta u
    zaseban backup folder. Poziva se nakon svake uspješne obrade - dodatna
    zaštita uz Google Sheetsov ugrađeni "Version history" (koji štiti
    unutar iste datoteke, ali ne i od brisanja same datoteke).
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    try:
        original = drive_service.files().get(fileId=sheet_id, fields="name", supportsAllDrives=True).execute()
        naziv_backupa = f"{original['name']}_backup_{timestamp}"
        drive_service.files().copy(
            fileId=sheet_id,
            body={"name": naziv_backupa, "parents": [backup_folder_id]},
            supportsAllDrives=True,
        ).execute()
        if log:
            log(f"💾 Backup baze spremljen: {naziv_backupa}")
    except Exception as e:
        if log:
            log(f"⚠️ Backup nije uspio (baza je i dalje sigurna, samo bez dodatne kopije): {e}")


def nadopuni_ili_dodaj_zadatke(ws_zadaci, zadaci, izvor_tip, izvor_naziv, godina, razina, broj_pdf_ulaza,
                                skenirano="ne", prag_slicnosti=0.85, prag_slicnosti_isti_naziv=0.75, log=None):
    all_values = ws_zadaci.get_all_values()
    data_rows = all_values[1:]

    _idx_naziv = ZADACI_HEADERS.index("izvor_naziv")
    _idx_latex = ZADACI_HEADERS.index("tekst_zadatka_latex")
    existing_lookup = [
        (i + 2, row[_idx_naziv] if len(row) > _idx_naziv else "",
         row[_idx_latex] if len(row) > _idx_latex else "")
        for i, row in enumerate(data_rows)
    ]

    id_prefix = izvor_naziv.replace(" ", "_")
    # Sljedeći broj ID-a računamo iz STVARNO postojećih brojeva (max + 1), NE brojanjem redaka -
    # brojanje je krhko: ako se redci obrišu (npr. deduplikacija), broj se pomakne i može
    # generirati ID koji se poklapa s nekim postojećim, preživjelim retkom (PreTeXt xml:id sudar).
    _broj_id_re = re.compile(rf"^{re.escape(id_prefix)}_(\d+)$")
    _postojeci_brojevi = []
    for r in data_rows:
        if r and r[0]:
            m = _broj_id_re.match(r[0])
            if m:
                _postojeci_brojevi.append(int(m.group(1)))
    _sljedeci_broj = (max(_postojeci_brojevi) + 1) if _postojeci_brojevi else 1

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
            # Slova stupaca računamo DINAMIČKI iz ZADACI_HEADERS (_col_letter) umjesto
            # hardkodiranih slova - dodavanje/premještanje kolone (npr. `potpoglavlje`)
            # više neće tiho pomaknuti ova ažuriranja na pogrešan stupac.
            rjesenje_novo = z.get("rjesenje", "")
            if rjesenje_novo:
                c1, c2 = _col_letter("rjesenje"), _col_letter("tip_rjesenja_izvor")
                ws_zadaci.update(range_name=f"{c1}{najbolji_redak}:{c2}{najbolji_redak}", values=[[
                    rjesenje_novo, "sluzbeno", z.get("tip_rjesenja_izvor", ""),
                ]])
            if z.get("potpoglavlje", ""):
                c = _col_letter("potpoglavlje")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("potpoglavlje", "")]])
            if z.get("slika_putanja", ""):
                c = _col_letter("slika_putanja")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("slika_putanja", "")]])
            if z.get("max_bodovi", ""):
                c = _col_letter("max_bodovi")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("max_bodovi", "")]])
            if z.get("tip_zadatka", ""):
                c = _col_letter("tip_zadatka")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("tip_zadatka", "")]])
            if z.get("slika_zadana", ""):
                c = _col_letter("slika_zadana")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("slika_zadana", "")]])
            if z.get("ponudjeni_odgovori"):
                c = _col_letter("ponudjeni_odgovori")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[" || ".join(z.get("ponudjeni_odgovori", []))]])
            if z.get("konacan_odgovor", ""):
                c = _col_letter("konacan_odgovor")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("konacan_odgovor", "")]])
            if z.get("uputa", ""):
                c = _col_letter("uputa")
                ws_zadaci.update(range_name=f"{c}{najbolji_redak}", values=[[z.get("uputa", "")]])
            if log:
                znak = "📄" if isti_naziv else "🔤"
                log(f"🔁 Zadatak #{z.get('privremeni_broj')} = duplikat retka {najbolji_redak} "
                    f"({znak}{najbolja_slicnost:.0%}, prag {prag:.0%}) - nadopunjen.")
            broj_azuriranih += 1
        else:
            zid = f"{id_prefix}_{_sljedeci_broj:03d}"
            _sljedeci_broj += 1
            row = [
                zid, izvor_tip, izvor_naziv, godina, broj_pdf_ulaza,
                razina, "",
                z.get("kategorija", ""), z.get("cjelina", ""), z.get("potpoglavlje", ""), z.get("kljucne_rijeci", ""),
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
                " || ".join(z.get("ponudjeni_odgovori", []) or []), z.get("konacan_odgovor", ""),
                z.get("uputa", ""),
            ]
            novi_redovi.append(row)
            broj_dodanih += 1

    if novi_redovi:
        ws_zadaci.append_rows(novi_redovi)

    return broj_dodanih, broj_azuriranih
