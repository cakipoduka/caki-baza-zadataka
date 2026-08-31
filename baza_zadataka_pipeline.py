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


SLOVA_PONUDJENIH_ODGOVORA = ["A", "B", "C", "D", "E", "F", "G", "H"]


def prikazi_opcije_markdown(ponudjeni_odgovori) -> str:
    """Vraća Markdown string za PREGLED ponuđenih odgovora (višestruki izbor) u Streamlit
    sučelju (ne za LaTeX!) - Streamlitov st.markdown zna renderirati $...$ preko KaTeX-a.
    Baza sprema opcije BEZ $ omotača (čist LaTeX), pa ih ovdje samo omatamo radi prikaza -
    isto načelo kao formatiraj_opciju() u pages/2_test_builder.py, ali za Streamlit prikaz,
    ne za LaTeX izlaz. Zajednička funkcija za baza_zadataka_app.py (stranica 'Uredi zadatak')
    i pages/2_test_builder.py (pregled u pretrazi/odabiru) - da se prikaz opcija ne dupllicira
    na dva mjesta i ne razmimoiđe (npr. broj podržanih slova A-?)."""
    dijelovi = []
    for i, opcija in enumerate(ponudjeni_odgovori):
        opcija = (opcija or "").strip()
        if not opcija:
            continue
        prikaz = opcija if "$" in opcija else f"${opcija}$"
        slovo = SLOVA_PONUDJENIH_ODGOVORA[i] if i < len(SLOVA_PONUDJENIH_ODGOVORA) else str(i + 1)
        dijelovi.append(f"**{slovo})** {prikaz}")
    return "  ".join(dijelovi)


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

KRITIČNO za ispravnost JSON-a: ako bilo koje polje sadrži navodnik (npr. zapis kuta u stupnjevima/minutama/sekundama poput 12°34'56", oznaka inča, ili citat unutar teksta zadatka), TAJ NAVODNIK MORAŠ escapeati kao \" unutar JSON stringa. Isto vrijedi za obrnutu kosu crtu (\\ -> \\\\) i nove retke unutar stringa (koristi \\n, ne stvarni prijelom retka). Jedan neescapean navodnik ili obrnuta kosa crta učini CIJELI JSON odgovor neispravnim i cijela obrada zadataka propadne - budi posebno pažljiv kod zapisa kutova i LaTeX izraza.
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


def get_sifrarnik_cjelina(sheet) -> dict:
    """Vraća {cjelina: kategorija}, čitano iz taba 'Sifrarnik_cjelina' (stupci: kategorija,
    cjelina, razred_tipican, mathify_link), redoslijedom kako se pojavljuju u Sheetu. Koristi
    se za padajući izbornik "Cjelina" kod ručnog ispravka klasifikacije u aplikaciji - isti
    šifrarnik kojim se Claude već vodi kod klasifikacije pri unosu novog ispita (vidi
    build_sifrarnik_text), samo kao strukturirani rječnik umjesto teksta za AI prompt."""
    ws = sheet.worksheet("Sifrarnik_cjelina")
    rows = ws.get_all_values()[1:]
    kategorija_po_cjelini = {}
    for r in rows:
        if len(r) < 2 or not r[1]:
            continue
        kategorija_po_cjelini[r[1].strip()] = r[0].strip()
    return kategorija_po_cjelini


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


# --- Log obrade (upisuje se u Sheet, NE samo u Streamlit session_state) ---
#
# st.session_state i on-screen log (st.empty().text(...)) žive samo dok proces same
# Streamlit aplikacije radi - ako se aplikacija nenadano ugasi/restarta usred obrade
# (npr. hosting je ubije zbog memorije/timeouta), sve to nestane bez traga i korisnik
# ostane bez ikakve informacije o tome dokle je obrada stigla. Zato se ključni koraci
# UZ TO upisuju i u zaseban tab "Log_obrade" u istom Google Sheetu - to je vanjski,
# trajan zapis koji preživi čak i potpuni pad/restart aplikacije.

LOG_OBRADE_HEADERS = ["vrijeme", "izvor_naziv", "faza", "status", "poruka"]


def _get_or_create_log_worksheet(sheet, naziv="Log_obrade"):
    try:
        return sheet.worksheet(naziv)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=naziv, rows=2000, cols=len(LOG_OBRADE_HEADERS))
        ws.append_row(LOG_OBRADE_HEADERS)
        return ws


def zapisi_log_obrade(sheet, izvor_naziv, faza, status, poruka="", log=None):
    """Upiši jedan redak u 'Log_obrade' tab - vidi obrazloženje gore. Namjerno je
    omotano u try/except koji SAMO upozori (preko `log`), a ne baca dalje: upis loga
    ne smije srušiti/prekinuti stvarnu obradu ako npr. Sheets API kratko zapne."""
    from datetime import datetime
    try:
        ws = _get_or_create_log_worksheet(sheet)
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), izvor_naziv, faza, status, poruka])
    except Exception as e:
        if log:
            log(f"⚠️ Upis u Log_obrade nije uspio (samo evidencija - obrada se nastavlja): {e}")


# --- Claude extrakcija (s automatskim dijeljenjem ako se odgovor odreže) ---

def _parsiraj_uzastopne_json_vrijednosti(raw_text: str, log=None):
    """Pokušaj pročitati raw_text kao NIZ UZASTOPNIH JSON vrijednosti (jedna za drugom,
    bez zajedničke omotne liste), umjesto jedne JSON liste. Rješava slučaj kad Claude
    (najčešće kod vrlo malog dijela ispita, npr. nakon dijeljenja na pola pa pola) umjesto
    tražene JSON liste vrati jedan ili više ODVOJENIH objekata: '{...}\\n{...}' - takav
    odgovor json.loads() odbija s "Extra data", a POSTOJEĆI trik "odreži na zadnjem '}'
    prije greške i zatvori s ']'" ovdje ne pomaže (kandidat postaje "{...}]" - objekt s
    viškom uglate zagrade - i dalje neispravan JSON), pa je ovo zaseban, dodatni pokušaj.
    Koristi json.JSONDecoder().raw_decode() koji čita TOČNO jednu vrijednost i vraća poziciju
    gdje je stao, pa se to ponavlja dok ima još teksta. Zadatke koje Claude vrati kao listu
    proširujemo u rezultat, a pojedinačne objekte dodajemo jedan po jedan. Čim naiđemo na
    nešto što se uopće ne da parsirati kao JSON, stajemo i vraćamo što je do tad skupljeno
    (bolje spasiti dio nego ništa)."""
    decoder = json.JSONDecoder(strict=False)
    zadaci = []
    idx, n = 0, len(raw_text)
    while idx < n:
        while idx < n and raw_text[idx] in " \t\n\r":
            idx += 1
        if idx >= n:
            break
        try:
            obj, kraj = decoder.raw_decode(raw_text, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, list):
            zadaci.extend(obj)
        elif isinstance(obj, dict):
            zadaci.append(obj)
        else:
            break
        idx = kraj
    return zadaci


def _spasi_djelomican_json_popis(raw_text: str, log=None):
    """Pokušaj standardni json.loads(); ako Claudeov odgovor NIJE ispravan JSON
    (najčešće: odgovor je odrezan zbog max_tokens čak i nakon što je iscrpljen
    budžet automatskog dijeljenja, ili je negdje u tekstu ostao neescapean
    navodnik, npr. u zapisu kuta 12°34'56"), ne bacamo cijeli rezultat - umjesto
    toga odrežemo odgovor na mjestu ZADNJEG potpuno zatvorenog objekta PRIJE
    mjesta greške i spasimo te zadatke. Bolje spasiti npr. 18 od 20 zadataka
    nego izgubiti svih 20 zbog jednog pokvarenog znaka na kraju odgovora.
    Ako niti to ne upali (tipično kod greške "Extra data" - Claude je vratio jedan ili
    više ODVOJENIH JSON objekata umjesto jedne liste), probamo drugu strategiju:
    _parsiraj_uzastopne_json_vrijednosti - vidi njezin docstring.

    Vraća (zadaci, je_li_potpuno: bool). Ako se ništa ne može spasiti, ponovno
    baca originalnu json.JSONDecodeError (isto ponašanje kao prije - poziv
    gore u lancu i dalje mora znati da je obrada za ovaj dio propala)."""
    try:
        rezultat = json.loads(raw_text, strict=False)
        if isinstance(rezultat, dict):
            # Claude je (unatoč uputi da odgovori JSON LISTOM) vratio jedan JEDINI
            # objekt bez omotne liste - čest slučaj kod vrlo malog dijela ispita
            # (npr. samo 1 preostali zadatak nakon dijeljenja). Ne odbacujemo ga -
            # samo ga omotamo u listu od jednog elementa.
            if log:
                log("⚠️ Claudeov odgovor je JEDAN objekt bez omotne JSON liste - tretiram ga kao listu od 1 zadatka.")
            rezultat = [rezultat]
        return rezultat, True
    except json.JSONDecodeError as e:
        if log:
            log(f"⚠️ Claudeov odgovor nije ispravan JSON ({e}) - pokušavam spasiti "
                f"zadatke parsirane prije mjesta greške...")
        granica = e.pos
        kraj_objekta = raw_text.rfind("}", 0, granica)
        while kraj_objekta != -1:
            kandidat = raw_text[:kraj_objekta + 1]
            # Gruba provjera ravnoteže zagrada - dovoljno za ovaj slučaj uporabe
            # (izbjegava da probamo parsirati na mjestu "}" koji je dio stringa).
            if kandidat.count("{") == kandidat.count("}"):
                try:
                    zadaci = json.loads(kandidat + "]", strict=False)
                    if log:
                        log(f"✅ Spašeno {len(zadaci)} zadataka prije mjesta greške "
                            f"(ostatak ovog Claude odgovora je odbačen kao nepouzdan).")
                    return zadaci, False
                except json.JSONDecodeError:
                    pass
            kraj_objekta = raw_text.rfind("}", 0, kraj_objekta)

        # Prvi pokušaj (gore) ne pomaže kad raw_text nije "lista koja je odrezana", nego
        # jedan ili više ODVOJENIH JSON objekata (npr. "{...}\n{...}") - tipičan uzrok
        # greške "Extra data". Probaj drugu strategiju prije nego potpuno odustanemo.
        zadaci_iz_niza = _parsiraj_uzastopne_json_vrijednosti(raw_text, log=log)
        if zadaci_iz_niza:
            if log:
                log(f"✅ Spašeno {len(zadaci_iz_niza)} zadataka čitanjem kao niz odvojenih "
                    f"JSON vrijednosti (Claudeov odgovor nije bio omotan u jednu JSON listu).")
            return zadaci_iz_niza, False

        if log:
            log("❌ Nije uspjelo spasiti nijedan zadatak iz ovog odgovora - obrada ovog dijela propada.")
        raise


def extract_zadaci_with_claude(ispit_md, rjesenja_md, sifrarnik_text, anthropic_api_key,
                                sifrarnik_potpoglavlja_text="", model="claude-sonnet-5",
                                _preostala_dubina=2, log=None, _preostali_pokusaji_praznog=2):
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
        # Claude Sonnet 5 po defaultu koristi "adaptive thinking" (effort "high"), a tokeni
        # potrošeni na razmišljanje broje se u ISTI max_tokens budžet kao i sam odgovor -
        # kod složenijih/dužih ispita to zna pojesti cijeli budžet PRIJE nego što Claude
        # uopće počne pisati JSON (stop_reason=max_tokens, sadržaj=samo "thinking" blok, bez
        # teksta - vidljivo u logovima kao "prazan odgovor" čak i nakon ponovnih pokušaja).
        # Za ovaj strukturirani JSON zadatak razmišljanje ne donosi korist, pa ga isključujemo
        # da cijelih 16000 tokena ide na stvarni odgovor.
        thinking={"type": "disabled"},
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
    # Ukloni "nevidljive" unicode znakove (BOM, zero-width space i sl.) koje obično .strip()
    # NE smatra whitespaceom - jedan takav znak na samom početku dovoljan je da json.loads
    # padne s "Expecting value: line 1 column 1 (char 0)" iako raw_text izgleda neprazan.
    raw_text = raw_text.strip("﻿​‌‍")

    if raw_text and not raw_text.startswith(("[", "{")):
        # Claude je (unatoč uputi da odgovori ISKLJUČIVO JSON-om) ipak dodao neki uvodni tekst
        # prije same JSON liste (npr. "Evo JSON odgovora:\n[...]") - potraži prvu '[' i odbaci
        # sve prije nje, umjesto da cijeli poziv propadne zbog par riječi viška na početku.
        prvi_zagrada = raw_text.find("[")
        if prvi_zagrada > 0:
            if log:
                log(f"⚠️ Claudeov odgovor sadrži tekst prije JSON liste "
                    f"('{raw_text[:prvi_zagrada].strip()[:80]}') - odbacujem taj uvod.")
            raw_text = raw_text[prvi_zagrada:]

    if not raw_text:
        # "Expecting value: line 1 column 1 (char 0)" iz json.loads() uvijek znači BAŠ ovo -
        # Claude je vratio 0 znakova teksta (različito od odrezanog/pokvarenog JSON-a, koje
        # rješava _spasi_djelomican_json_popis niže). Bilježimo stop_reason i tipove content
        # blokova radi dijagnoze, i pokušavamo ponovno prije nego odustanemo - prazan odgovor
        # je tipično prolazna stvar (API hiccup), ne stvarni problem sa sadržajem ispita.
        broj_blokova = len(response.content)
        tipovi_blokova = [b.type for b in response.content]
        if log:
            log(f"⚠️ Claude je vratio PRAZAN odgovor (stop_reason={response.stop_reason}, "
                f"broj_blokova={broj_blokova}, tipovi={tipovi_blokova}).")
        if _preostali_pokusaji_praznog > 0:
            if log:
                log(f"🔁 Prazan odgovor je često prolazna greška - pokušavam ponovno "
                    f"(preostalo pokušaja: {_preostali_pokusaji_praznog})...")
            return extract_zadaci_with_claude(
                ispit_md, rjesenja_md, sifrarnik_text, anthropic_api_key,
                sifrarnik_potpoglavlja_text, model, _preostala_dubina, log,
                _preostali_pokusaji_praznog - 1,
            )
        raise ValueError(
            f"Claude je vratio prazan odgovor i nakon ponovnih pokušaja "
            f"(stop_reason={response.stop_reason}, broj_blokova={broj_blokova})."
        )

    zadaci, potpuno = _spasi_djelomican_json_popis(raw_text, log=log)
    if not potpuno and log:
        log("⚠️ POZOR: gornji zadaci su spašeni iz NEPOTPUNOG Claude odgovora - "
            "preporučamo nakon obrade provjeriti bazu (zadnji zadatak u ovom dijelu "
            "ispita je vjerojatno izostavljen) i po potrebi ručno dodati/ponoviti obradu.")

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
                                skenirano="ne", prag_slicnosti=0.85, prag_slicnosti_isti_naziv=0.75, log=None,
                                ogranici_po_cjelini=False):
    """
    ogranici_po_cjelini=False (zadano): usporedba svakog novog zadatka sa SVIM postojećim
    zadacima u bazi, kao dosad - najsigurnije, ali kod baze od 20-30 tisuća zadataka
    najsporije (O(broj_novih x broj_postojecih) SequenceMatcher.ratio() poziva).

    ogranici_po_cjelini=True: usporedba se ograničava SAMO na postojeće zadatke iz ISTE
    cjeline (npr. "Trigonometrija") kao novi zadatak - jer bi dva zadatka koja su stvarni
    duplikat gotovo uvijek trebala biti klasificirana u istu cjelinu. Ovo je red veličine
    brže na velikoj bazi (dijeli posao otprilike na broj cjelina u šifrarniku), ALI nosi
    mali rizik: ako Claude pri dvije odvojene obrade ISTOG zadatka (npr. slučajno
    uploadan isti ispit dvaput) dodijeli RAZLIČITU cjelinu, taj duplikat neće biti
    prepoznat i bit će dodan kao nov zadatak. Radi sigurnosti, postojeći zadaci BEZ
    upisane cjeline (prazno polje - stariji/ručno dodani unosi) uvijek se uspoređuju sa
    SVIM novim zadacima, bez obzira na ovu postavku - da migrirani/nekategorizirani
    unosi ne postanu "slijepa točka" za detekciju duplikata.
    """
    all_values = ws_zadaci.get_all_values()
    data_rows = all_values[1:]

    _idx_naziv = ZADACI_HEADERS.index("izvor_naziv")
    _idx_latex = ZADACI_HEADERS.index("tekst_zadatka_latex")
    _idx_cjelina = ZADACI_HEADERS.index("cjelina")
    # Normalizirani tekst i njegova duljina računaju se OVDJE, JEDNOM za svaki postojeći
    # redak - ne iznova za svaki novi zadatak (kako je bilo prije). Kod baze od nekoliko
    # tisuća zadataka to je bila stvarna, mjerljiva sporost: normalizacija (regex) postojećih
    # redaka izvodila se broj_novih_zadataka x broj_postojecih_redaka puta umjesto samo
    # broj_postojecih_redaka puta. Rezultat provjere duplikata ostaje IDENTIČAN kad je
    # ogranici_po_cjelini=False - ovo je čisto ubrzanje, ne mijenja logiku usporedbe.
    existing_lookup = []
    grupe_po_cjelini = {}
    for i, row in enumerate(data_rows):
        existing_naziv = row[_idx_naziv] if len(row) > _idx_naziv else ""
        existing_latex = row[_idx_latex] if len(row) > _idx_latex else ""
        existing_cjelina = (row[_idx_cjelina] if len(row) > _idx_cjelina else "").strip()
        norm_existing = _normalize_za_usporedbu(existing_latex)
        stavka = (i + 2, existing_naziv, norm_existing, len(norm_existing))
        existing_lookup.append(stavka)
        grupe_po_cjelini.setdefault(existing_cjelina, []).append(stavka)
    # "Bez cjeline" grupa (prazan string) - uvijek dio kandidata, vidi obrazloženje gore.
    bez_cjeline = grupe_po_cjelini.get("", [])

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
    # Sve izmjene POSTOJEĆIH redaka (duplikata) skupljamo ovdje umjesto da svaku šaljemo
    # kao zaseban ws_zadaci.update() poziv - Google Sheets API ima limit "Write requests
    # per minute per user" (tipično 60/min), a svaki duplikat je dosad slao do 8 ODVOJENIH
    # write poziva (rjesenje, potpoglavlje, slika, bodovi, tip_zadatka, slika_zadana,
    # ponudjeni_odgovori, uputa) - kod ispita s puno duplikata (npr. ponovna obrada već
    # unesenog ispita) to je vrlo brzo probijalo limit (429 "Quota exceeded"). Sve te
    # izmjene sad idu u JEDAN ws_zadaci.batch_update() poziv na kraju cijele funkcije -
    # bez obzira koliko duplikata ima u ovoj obradi, to je i dalje samo JEDAN write zahtjev
    # (plus jedan za append_rows), umjesto potencijalno stotina.
    _sheet_naziv_za_raspon = "'" + ws_zadaci.title.replace("'", "''") + "'"

    def _puni_raspon(bare_range):
        return f"{_sheet_naziv_za_raspon}!{bare_range}"

    sva_azuriranja_polja = []

    for z in zadaci:
        norm_novi = _normalize_za_usporedbu(z.get("tekst_zadatka_latex", ""))
        duljina_novi = len(norm_novi)
        najbolji_redak, najbolja_slicnost, najbolji_naziv = None, 0.0, None

        if ogranici_po_cjelini:
            nova_cjelina = (z.get("cjelina") or "").strip()
            kandidati = grupe_po_cjelini.get(nova_cjelina, [])
            if nova_cjelina and bez_cjeline:
                kandidati = kandidati + bez_cjeline
        else:
            kandidati = existing_lookup

        for row_number, existing_naziv, norm_existing, duljina_existing in kandidati:
            if duljina_novi and abs(duljina_existing - duljina_novi) / duljina_novi > 0.4:
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
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c1}{najbolji_redak}:{c2}{najbolji_redak}"),
                    "values": [[rjesenje_novo, "sluzbeno", z.get("tip_rjesenja_izvor", "")]],
                })
            if z.get("potpoglavlje", ""):
                c = _col_letter("potpoglavlje")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("potpoglavlje", "")]],
                })
            if z.get("slika_putanja", ""):
                c = _col_letter("slika_putanja")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("slika_putanja", "")]],
                })
            if z.get("max_bodovi", ""):
                c = _col_letter("max_bodovi")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("max_bodovi", "")]],
                })
            if z.get("tip_zadatka", ""):
                c = _col_letter("tip_zadatka")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("tip_zadatka", "")]],
                })
            if z.get("slika_zadana", ""):
                c = _col_letter("slika_zadana")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("slika_zadana", "")]],
                })
            if z.get("ponudjeni_odgovori"):
                c = _col_letter("ponudjeni_odgovori")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"),
                    "values": [[" || ".join(z.get("ponudjeni_odgovori", []))]],
                })
            if z.get("konacan_odgovor", ""):
                c = _col_letter("konacan_odgovor")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("konacan_odgovor", "")]],
                })
            if z.get("uputa", ""):
                c = _col_letter("uputa")
                sva_azuriranja_polja.append({
                    "range": _puni_raspon(f"{c}{najbolji_redak}"), "values": [[z.get("uputa", "")]],
                })
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

    if sva_azuriranja_polja:
        # JEDAN poziv za SVE izmjene duplikata iz ove obrade - vidi obrazloženje gore
        # (rješava "Quota exceeded... Write requests per minute" grešku).
        ws_zadaci.batch_update(sva_azuriranja_polja)

    return broj_dodanih, broj_azuriranih
