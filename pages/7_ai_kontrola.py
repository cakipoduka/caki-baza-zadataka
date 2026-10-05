"""
CAKI — pages/7_ai_kontrola.py
AI kontrola unesenih zadataka (DeepSeek API) — usporedba baze s originalnim ispitima.

TOK RADA (dogovoreno s Cakijem 3.10.2026.):
1. Aplikacija sama čita PDF-ove iz Drive foldera (npr. ...\\00_INBOX_PDF\\matura\\MATEMATIKA A razina)
   preko service accounta - nema ručnog uploada.
2. Datoteke se grupiraju po ispitu iz naziva: "A2026ljeto" = ispit, "A2026ljeto R1",
   "A2024ljetoRJ2", "A2024jesen rj2", "A2015_ljetniR" ... = rješenja. Svaka grupa se
   upari s izvor_naziv u bazi (automatski po godini + roku, ručno se može promijeniti).
3. Mathpix pretvori PDF u tekst SAMO JEDNOM - rezultat se sprema kao .md u podfolder
   "_mathpix_md" u istom Drive folderu i idući put se čita odande (ne plaća se ponovno).
4. DeepSeek dobiva: OCR ispita + OCR rješenja + zadatke iz baze za taj ispit, i vraća
   PRIJEDLOGE ispravaka (JSON). Šalje se JEDAN ispit po pozivu (kvaliteta + limit duljine
   odgovora), ali sve odabrane mature obrađuju se automatski jedna za drugom.
5. Prijedlozi se odmah spremaju u tab "AI_kontrola_prijedlozi" (ne gube se ako se zatvori
   preglednik). Obrađene mature se bilježe u "AI_kontrola_serije" - ponovno pokretanje
   preskače već obrađene (osim ako se izričito traži ponovna obrada).
6. NIŠTA se ne upisuje u tab "Zadaci" bez ljudske potvrde (tab "2. Pregled i primjena").
   Kod primjene se provjerava da se vrijednost u bazi u međuvremenu nije promijenila
   (ako jest -> prijedlog se označi "zastarjelo" i ne primjenjuje). Stara vrijednost ostaje
   zapisana u tabu prijedloga = mogućnost ručnog povratka.

Polje "uputa" se u ovom prolazu NAMJERNO ne dira - upute idu u zaseban, kasniji prolaz
(nakon što su tekstovi ispravljeni).

POTREBNI NOVI SECRET (Streamlit -> Settings -> Secrets):
  DEEPSEEK_API_KEY = "sk-..."
Opcionalno:
  AI_KONTROLA_FOLDER_ID = "<ID Drive foldera s maturama>"
"""

import difflib
import functools
import io
import json
import os
import re
import ssl
import threading
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from baza_zadataka_pipeline import (
    get_drive_service,
    get_gspread_client,
    get_or_create_worksheet,
    mathpix_ocr_datoteka,
    prikazi_opcije_markdown,
)
from ai_prijedlozi import (
    RAZDVOJI, UPOZORENJE_DOLARI, UPOZORENJE_SKRACIVANJE, je_samo_dolari, je_sumnjivo_skracivanje, naslov_prijedloga, oznaci_zamijenjene,
    primijeni_razdvajanje, prikazi_kontekst_prijedloga, prikazi_promjenu, uredi_razdvajanje,
)

st.set_page_config(page_title="CAKI — AI kontrola zadataka", page_icon="🔎", layout="wide")

TZ = ZoneInfo("Europe/Zagreb")
ZADANI_FOLDER_ID = "0B5HA0YxLCZWPejRYX0o1Z2xWZTA"  # MATEMATIKA A razina (00_INBOX_PDF/matura)
MD_PODFOLDER = "_mathpix_md"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
# Nazivi modela po DeepSeek dokumentaciji (listopad 2026.): v4-pro = jači (bez vida), flash = brži/jeftiniji.
# Oba su po zadanom u "thinking" načinu (razmišljaju prije odgovora) - to želimo za provjeru računa.
MODELI = ["deepseek-v4-pro", "deepseek-flash"]

DOZVOLJENA_POLJA = [
    "tekst_zadatka_latex", "ponudjeni_odgovori", "konacan_odgovor",
    "rjesenje", "tip_zadatka", "max_bodovi",
]
POLJA_ZA_AI = [
    "id", "tekst_zadatka_latex", "tip_zadatka", "ponudjeni_odgovori", "konacan_odgovor",
    "rjesenje", "rjesenje_status", "max_bodovi", "slika_zadana", "cjelina", "potpoglavlje",
]
MAX_RJESENJE_ZNAKOVA = 2500

PRIJEDLOZI_HEADERS = [
    "prijedlog_id", "vrijeme", "serija", "id_zadatka", "polje", "staro", "novo",
    "vrsta", "razlog", "sigurnost", "izvor_prijedloga", "status", "odlucio",
    "vrijeme_odluke", "model", "isjecak_originala",
]
SERIJE_HEADERS = [
    "serija", "vrijeme", "status", "broj_zadataka_u_bazi", "broj_prijedloga",
    "datoteke", "model", "tokeni_ulaz", "tokeni_izlaz", "poruka", "uparivanje_json",
]


def sada():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao ostale stranice - ISTA APP_PASSWORD)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_ai"] = (
            st.session_state.get("lozinka_unos_ai") == st.secrets.get("APP_PASSWORD")
        )

    if st.session_state.get("autoriziran_ai") or st.session_state.get("autoriziran"):
        st.session_state["autoriziran"] = True  # i glavna stranica (skok u "Provjera i uređivanje")
        return True
    st.title("🔎 CAKI — AI kontrola zadataka")
    st.text_input("Lozinka", type="password", key="lozinka_unos_ai", on_change=na_unos)
    if st.session_state.get("autoriziran_ai") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------
# Google
# ---------------------------------------------------------------

@st.cache_resource
def sa_info():
    return json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])


@st.cache_resource
def init_spreadsheet():
    return get_gspread_client(sa_info()).open_by_key(st.secrets["SHEET_ID"])


# Drive klijent PO DRETVI, ne dijeljen (5.10.2026.): googleapiclient koristi httplib2 koji NIJE
# thread-safe - jedan klijent iz st.cache_resource dijele sve Streamlit dretve/reruni, pa nakon
# duže neaktivnosti ili paralelnog korištenja dolazi do ssl.SSLError ("read" u _read_status).
_drive_lokalno = threading.local()


def init_drive():
    d = getattr(_drive_lokalno, "drive", None)
    if d is None:
        d = get_drive_service(sa_info())
        _drive_lokalno.drive = d
    return d


def _ponovi_drive(fn):
    """Do 3 pokušaja kod mrežne/SSL greške; prije novog pokušaja napravi svjež Drive klijent."""
    @functools.wraps(fn)
    def omot(*args, **kwargs):
        for pokusaj in range(3):
            try:
                return fn(*args, **kwargs)
            except (ssl.SSLError, ConnectionError, TimeoutError, OSError):
                if pokusaj == 2:
                    raise
                _drive_lokalno.drive = None
                time.sleep(2 * (pokusaj + 1))
    return omot


def ws_prijedlozi():
    ws = get_or_create_worksheet(init_spreadsheet(), "AI_kontrola_prijedlozi", PRIJEDLOZI_HEADERS, rows=2000)
    # Tab napravljen prije dodavanja stupca "isjecak_originala" - dopiši zaglavlje na kraj (jednom po sesiji).
    if not st.session_state.get("_ai_hdr_ok"):
        hdr = ws.row_values(1)
        if "isjecak_originala" not in hdr:
            if ws.col_count < len(hdr) + 1:
                ws.add_cols(1)
            ws.update_cell(1, len(hdr) + 1, "isjecak_originala")
        st.session_state["_ai_hdr_ok"] = True
    return ws


def ws_serije():
    return get_or_create_worksheet(init_spreadsheet(), "AI_kontrola_serije", SERIJE_HEADERS, rows=500)


def ucitaj_tab_kao_dictove(ws):
    """Vraća (header, lista_dictova s '_redak' = broj retka u Sheetu)."""
    vrijednosti = ws.get_all_values()
    if not vrijednosti:
        return [], []
    header = [h.strip() for h in vrijednosti[0]]
    redovi = []
    for i, r in enumerate(vrijednosti[1:], start=2):
        d = {h: (r[j] if j < len(r) else "") for j, h in enumerate(header)}
        d["_redak"] = i
        redovi.append(d)
    return header, redovi


def slovo_stupca(idx0: int) -> str:
    idx = idx0 + 1
    s = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


# ---------------------------------------------------------------
# Drive: popis, preuzimanje, spremanje .md
# ---------------------------------------------------------------

@_ponovi_drive
def drive_popis(folder_id):
    drive = init_drive()
    datoteke, token = [], None
    while True:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        datoteke += res.get("files", [])
        token = res.get("nextPageToken")
        if not token:
            return datoteke


@_ponovi_drive
def drive_preuzmi(file_id) -> bytes:
    req = init_drive().files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    gotovo = False
    while not gotovo:
        _, gotovo = dl.next_chunk()
    return buf.getvalue()


@_ponovi_drive
def drive_podfolder(parent_id, naziv):
    drive = init_drive()
    res = drive.files().list(
        q=(f"'{parent_id}' in parents and name = '{naziv}' and "
           "mimeType = 'application/vnd.google-apps.folder' and trashed = false"),
        fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    if res:
        return res[0]["id"]
    nov = drive.files().create(
        body={"name": naziv, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
        fields="id", supportsAllDrives=True,
    ).execute()
    return nov["id"]


@_ponovi_drive
def drive_spremi_tekst(folder_id, naziv, tekst):
    media = MediaIoBaseUpload(io.BytesIO(tekst.encode("utf-8")), mimetype="text/markdown", resumable=False)
    init_drive().files().create(
        body={"name": naziv, "parents": [folder_id]}, media_body=media,
        fields="id", supportsAllDrives=True,
    ).execute()


def ocr_s_cacheom(datoteka, md_folder_id, md_postojeci, log):
    """Vraća Mathpix Markdown za jednu Drive datoteku - iz cachea ako postoji."""
    md_naziv = re.sub(r"\.(pdf|png|jpe?g)$", "", datoteka["name"], flags=re.I) + ".md"
    if md_naziv in md_postojeci:
        log(f"♻️ {datoteka['name']}: tekst već postoji (bez Mathpixa)")
        return drive_preuzmi(md_postojeci[md_naziv]).decode("utf-8")
    log(f"📄 {datoteka['name']}: šaljem na Mathpix...")
    sadrzaj = drive_preuzmi(datoteka["id"])
    ime = datoteka["name"]
    if datoteka.get("mimeType") == "application/pdf" and not ime.lower().endswith(".pdf"):
        ime += ".pdf"
    tekst = mathpix_ocr_datoteka(sadrzaj, ime, st.secrets["MATHPIX_APP_ID"], st.secrets["MATHPIX_APP_KEY"])
    drive_spremi_tekst(md_folder_id, md_naziv, tekst)
    md_postojeci[md_naziv] = "(upravo spremljeno)"
    log(f"✅ {datoteka['name']}: OCR gotov ({len(tekst)} znakova), spremljen u {MD_PODFOLDER}")
    return tekst


# ---------------------------------------------------------------
# Prepoznavanje naziva: A2026ljeto, A2026ljeto R1, A2024ljetoRJ2, A2024jesen rj2,
# A2015_ljetniR, A2019-ljeto-R2, A2010_zimski, A2011_ljetni_produzeni odgovori RJ ...
# ---------------------------------------------------------------

_NAZIV_RE = re.compile(
    r"^\s*([AB])?[\s_\-]*(\d{4})[\s_\-]*(ljet|jesen|zim)(?:o|ni|na|ski|ska|a)?(.*)$", re.I
)
_ROK = {"ljet": "ljeto", "jesen": "jesen", "zim": "zima"}


def parsiraj_naziv(naziv: str):
    """-> (razina, godina, rok, je_rjesenje) ili None ako naziv nije prepoznat."""
    stem = re.sub(r"\.(pdf|png|jpe?g|md)$", "", naziv.strip(), flags=re.I)
    m = _NAZIV_RE.match(stem)
    if not m:
        return None
    razina = (m.group(1) or "").upper()
    ostatak = m.group(4) or ""
    # rješenja: ostatak naziva sadrži zasebnu oznaku R / RJ / R1 / RJ2 / rj2 ...
    je_rjesenje = bool(re.search(r"(^|[\s_\-])rj?\d*([\s_\-]|$)", ostatak, re.I))
    return razina, m.group(2), _ROK[m.group(3).lower()], je_rjesenje


def kljuc_ispita(razina, godina, rok):
    return f"{razina or '?'}{godina} {rok}"


def grupiraj_datoteke(datoteke):
    grupe, neprepoznate = {}, []
    for d in datoteke:
        if d.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        p = parsiraj_naziv(d["name"])
        if not p:
            neprepoznate.append(d["name"])
            continue
        razina, godina, rok, je_rj = p
        k = kljuc_ispita(razina, godina, rok)
        g = grupe.setdefault(k, {"kljuc": k, "razina": razina, "godina": godina, "rok": rok,
                                  "ispit": [], "rjesenja": []})
        (g["rjesenja"] if je_rj else g["ispit"]).append(d)
    for g in grupe.values():
        g["ispit"].sort(key=lambda d: d["name"])
        g["rjesenja"].sort(key=lambda d: d["name"])
    return dict(sorted(grupe.items(), key=lambda kv: kv[0], reverse=True)), neprepoznate


def auto_izvor_naziv(grupa, izvori_u_bazi):
    """izvor_naziv iz baze s istom razinom/godinom/rokom (samo ako je jednoznačno)."""
    kandidati = []
    for izv in izvori_u_bazi:
        p = parsiraj_naziv(izv)
        if p and p[1] == grupa["godina"] and p[2] == grupa["rok"] and (not p[0] or not grupa["razina"] or p[0] == grupa["razina"]):
            kandidati.append(izv)
    return kandidati[0] if len(kandidati) == 1 else ""


# ---------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------

SUSTAVSKI_PROMPT = r"""Ti si iskusan profesor matematike u Hrvatskoj i kontrolor kvalitete baze zadataka CAKI centra.
Dobivaš:
(1) OCR tekst ORIGINALNOG ispita državne mature (Mathpix Markdown),
(2) OCR tekst SLUŽBENIH rješenja / ključa (ako postoji),
(3) JSON popis zadataka iz BAZE koji su ranije automatski izvučeni iz tog ispita.

CILJ: pronaći greške u bazi usporedbom s originalom. Ti NE mijenjaš bazu - samo predlažeš ispravke koje će čovjek pregledati.

PRAVILA:
1. Upari svaki zadatak iz baze s brojem zadatka u originalu (npr. "7", "7a", "15b").
   Napomena: zadaci s podzadacima a), b), c) u bazi su NAMJERNO razdvojeni u zasebne zadatke i svaki ponavlja zajednički uvod - to NIJE greška.
1b. Ako JEDAN redak u bazi sadrži VIŠE podzadataka spojenih u jedan tekst (npr. 25.1, 25.2, 25.3 ili a., b., c.),
   NIKAKO ne predlaži skraćivanje teksta (izgubili bi se podzadaci). Umjesto toga navedi taj redak u "razdvajanja":
   svaki dio kao POTPUNO SAMOSTALAN zadatak koji ponavlja zajednički uvod (formulu, zadane podatke) + svoje pitanje,
   s vlastitim tip_zadatka, konacan_odgovor (iz ključa), max_bodovi i rjesenje (ako ga ključ daje). Ako podzadatak
   ovisi o rezultatu prethodnog, taj rezultat navedi kao zadan podatak. Prvi dio zamijenit će postojeći redak, ostali
   postaju novi redci. Za takav redak NE šalji druge prijedloge za tekst_zadatka_latex, a te podzadatke
   NE navodi u "nedostaju_u_bazi" (nisu nestali, nego su spojeni - rješava ih razdvajanje).
2. Predlaži ispravak SAMO kad postoji stvarna razlika prema originalu ili ključu: OCR greška (krivi broj, znak, eksponent, indeks, razlomak, nestali minus, zamijenjena slova), nedostaje ili je višak dio teksta/podatka, krive ili ispremiještane ponuđene opcije, kriv konačan odgovor, kriv tip zadatka, neuparen ili pogrešno postavljen $.
   NE mijenjaj stil, formulaciju ni interpunkciju ako je sadržaj isti. NE "uljepšavaj".
3. Konvencije zapisa u bazi (novo MORA ih poštivati):
   - u poljima tekst_zadatka_latex i rjesenje matematika je UVIJEK unutar $...$, običan tekst izvan;
     NIKAD ne predlaži uklanjanje $ iz ta dva polja (bez $ se formula ne prikazuje). Izuzetak bez $ su SAMO
     ponudjeni_odgovori (v. niže). Decimalni zarez kao {,} (npr. $2{,}5$);
   - otvoreni interval \langle a, b \rangle; \operatorname{tg}, \operatorname{ctg}, \log, \cdot; LaTeX naredbe umjesto Unicode simbola (\infty, \cup, \leq ...);
   - ponudjeni_odgovori: opcije BEZ slova A/B/C/D, odvojene s " || ", LaTeX BEZ $ (npr. "\frac{1}{2} || 2 || -3");
   - konacan_odgovor: za visestruki_izbor SAMO slovo (npr. "C"); inače kratka vrijednost;
   - tip_zadatka: visestruki_izbor, kratki_odgovor ili prosireni_odgovor.
4. SLUŽBENI KLJUČ je mjerodavan. Ako se konacan_odgovor u bazi razlikuje od ključa -> prijedlog s izvor_prijedloga "kljuc".
   Ako sam izračunaš drugačije od ključa -> NE predlaži promjenu, nego napiši napomenu.
   Ako ključa nema, a konacan_odgovor je prazan -> smiješ predložiti svoj izračun s izvor_prijedloga "ai_izracun" i sigurnost najviše "srednja".
   Za visestruki_izbor provjeri da slovo odgovara točnoj opciji redoslijedom u ponudjeni_odgovori.
5. Slike ne vidiš. Podatke koji su samo na slici ne mijenjaj; ako sumnjaš - napomena.
6. Polje "uputa" i klasifikaciju (cjelina/potpoglavlje) u ovom prolazu NE diraj.
7. Ako je rjesenje u ulazu označeno "[SKRAĆENO]", ne predlaži izmjenu polja rjesenje.
8. Polje "novo" je CIJELA nova vrijednost polja (ne samo izmijenjeni dio).
9. Zadatke iz originala kojih nema u bazi navedi u "nedostaju_u_bazi" (ne izmišljaj ID).

ODGOVORI ISKLJUČIVO JSON OBJEKTOM ovog oblika (bez teksta prije/poslije, bez ```):
{
  "uparivanje": [{"id": "...", "broj_u_originalu": "7"}],
  "prijedlozi": [
    {"id": "...", "polje": "tekst_zadatka_latex|ponudjeni_odgovori|konacan_odgovor|rjesenje|tip_zadatka|max_bodovi",
     "novo": "...", "vrsta": "ocr_greska|nedostaje_tekst|format_konvencija|kriv_odgovor|kriva_opcija|kriv_tip|ostalo",
     "razlog": "kratko, s brojem zadatka u originalu", "sigurnost": "visoka|srednja|niska",
     "izvor_prijedloga": "original|kljuc|ai_izracun",
     "isjecak_originala": "DOSLOVNO prepisan dio OCR teksta originala ili ključa na kojem temeljiš ispravak (najviše ~300 znakova; prazno za ai_izracun)"}
  ],
  "razdvajanja": [
    {"id": "...", "razlog": "...", "isjecak_originala": "...",
     "dijelovi": [{"oznaka": "25.1", "tekst_zadatka_latex": "...", "tip_zadatka": "kratki_odgovor",
                   "konacan_odgovor": "...", "max_bodovi": "", "rjesenje": ""}]}
  ],
  "nedostaju_u_bazi": [{"broj_u_originalu": "15", "kratki_opis": "..."}],
  "napomene": [{"id": "...", "napomena": "..."}]
}
U JSON stringovima obavezno escapeaj obrnutu kosu crtu (\\frac) i navodnike (\").
Ako nema grešaka, vrati prazne liste."""


def pripremi_zadatke_za_ai(redovi):
    out = []
    for r in redovi:
        z = {k: r.get(k, "") for k in POLJA_ZA_AI}
        if len(z["rjesenje"]) > MAX_RJESENJE_ZNAKOVA:
            z["rjesenje"] = z["rjesenje"][:MAX_RJESENJE_ZNAKOVA] + " [SKRAĆENO]"
        out.append(z)
    return out


def izvuci_json(tekst: str):
    t = (tekst or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise


def pozovi_deepseek(model, korisnicka_poruka, max_tokens, log):
    headers = {"Authorization": f"Bearer {st.secrets['DEEPSEEK_API_KEY']}", "Content-Type": "application/json"}
    tijelo = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUSTAVSKI_PROMPT},
            {"role": "user", "content": korisnicka_poruka},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    zadnja_greska = None
    for pokusaj in range(1, 4):
        try:
            r = requests.post(DEEPSEEK_URL, headers=headers, json=tijelo, timeout=900)
            if r.status_code == 400 and "response_format" in tijelo:
                # neki modeli ne podržavaju JSON mode - pokušaj bez njega
                tijelo.pop("response_format")
                log("ℹ️ Model ne prihvaća JSON mode, ponavljam bez njega...")
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                zadnja_greska = f"HTTP {r.status_code}: {r.text[:300]}"
                log(f"⏳ DeepSeek zauzet ({r.status_code}), pokušaj {pokusaj}/3 za 20 s...")
                time.sleep(20)
                continue
            r.raise_for_status()
            odg = r.json()
            izbor = odg["choices"][0]
            return {
                "tekst": izbor["message"].get("content", ""),
                "finish_reason": izbor.get("finish_reason"),
                "tokeni_ulaz": odg.get("usage", {}).get("prompt_tokens", ""),
                "tokeni_izlaz": odg.get("usage", {}).get("completion_tokens", ""),
            }
        except requests.exceptions.Timeout:
            zadnja_greska = "timeout"
            log(f"⏳ Timeout, pokušaj {pokusaj}/3...")
    raise RuntimeError(f"DeepSeek nije odgovorio: {zadnja_greska}")


# ---------------------------------------------------------------
# Obrada jedne serije (jednog ispita)
# ---------------------------------------------------------------

def obradi_seriju(grupa, izvor_naziv, zadaci_redovi, header_zadaci, md_folder_id, md_postojeci,
                  model, max_tokens, log, vec_postojeci=None):
    """vec_postojeci: skup (id, polje, novo) prijedloga koji već postoje u tabu (bilo kojeg
    statusa) - kod PONOVNE obrade iste mature isti prijedlog se ne dodaje dvaput."""
    vec_postojeci = vec_postojeci or set()
    datoteke_nazivi = ", ".join(d["name"] for d in grupa["ispit"] + grupa["rjesenja"])
    ispit_md = "\n\n---\n\n".join(ocr_s_cacheom(d, md_folder_id, md_postojeci, log) for d in grupa["ispit"])
    rj_md = "\n\n---\n\n".join(ocr_s_cacheom(d, md_folder_id, md_postojeci, log) for d in grupa["rjesenja"])

    zadaci = [r for r in zadaci_redovi if r.get("izvor_naziv", "").strip() == izvor_naziv]
    if not zadaci:
        return {"status": "preskoceno", "poruka": "nema zadataka u bazi", "prijedlozi": [],
                "datoteke": datoteke_nazivi}

    poruka = (
        f"ISPIT: {izvor_naziv}\n\n"
        f"=== (1) OCR ORIGINALNOG ISPITA ===\n{ispit_md}\n\n"
        f"=== (2) OCR SLUŽBENIH RJEŠENJA / KLJUČA ===\n{rj_md or '(nema)'}\n\n"
        f"=== (3) ZADACI IZ BAZE ({len(zadaci)}) ===\n"
        f"{json.dumps(pripremi_zadatke_za_ai(zadaci), ensure_ascii=False, indent=1)}"
    )
    log(f"🤖 DeepSeek ({model}) provjerava {len(zadaci)} zadataka... (može potrajati 1-5 min)")
    odg = pozovi_deepseek(model, poruka, max_tokens, log)
    if odg["finish_reason"] == "length":
        raise RuntimeError("Odgovor je odrezan (max_tokens). Povećaj limit izlaza i obradi ponovno.")
    podaci = izvuci_json(odg["tekst"])

    po_id = {r["id"]: r for r in zadaci}
    vrijeme = sada()
    prijedlozi = []

    def novi(id_z, polje, staro, novo, vrsta, razlog, sigurnost, izvor, isjecak=""):
        if (id_z, polje, str(novo).strip()) in vec_postojeci:
            return
        prijedlozi.append([
            uuid.uuid4().hex[:10], vrijeme, izvor_naziv, id_z, polje, staro, novo,
            vrsta, razlog, sigurnost, izvor, "novo", "", "", model, str(isjecak or "")[:2000],
        ])

    za_razdvojiti = set()
    for r in podaci.get("razdvajanja", []) or []:
        id_z = str(r.get("id", "")).strip()
        dijelovi = [d for d in (r.get("dijelovi") or []) if str(d.get("tekst_zadatka_latex", "")).strip()]
        if id_z not in po_id or len(dijelovi) < 2:
            log(f"⚠️ Odbačeno neispravno razdvajanje: {id_z}")
            continue
        za_razdvojiti.add(id_z)
        novi(id_z, RAZDVOJI, po_id[id_z].get("tekst_zadatka_latex", ""),
             json.dumps(dijelovi, ensure_ascii=False), "razdvajanje", r.get("razlog", ""),
             "visoka", "original", r.get("isjecak_originala", ""))

    for p in podaci.get("prijedlozi", []) or []:
        id_z, polje = str(p.get("id", "")).strip(), str(p.get("polje", "")).strip()
        if id_z in za_razdvojiti and polje == "tekst_zadatka_latex":
            continue  # tekst tog retka rješava razdvajanje
        if id_z not in po_id or polje not in DOZVOLJENA_POLJA:
            log(f"⚠️ Odbačen prijedlog s nepoznatim id/poljem: {id_z} / {polje}")
            continue
        staro = po_id[id_z].get(polje, "")
        novo = str(p.get("novo", ""))
        if novo.strip() == staro.strip():
            continue
        if je_samo_dolari({"polje": polje, "staro": staro, "novo": novo}):
            log(f"🧹 Odbačen prijedlog koji samo briše $ ({id_z} / {polje})")
            continue
        novi(id_z, polje, staro, novo, p.get("vrsta", ""), p.get("razlog", ""),
             p.get("sigurnost", ""), p.get("izvor_prijedloga", ""), p.get("isjecak_originala", ""))

    for n in podaci.get("napomene", []) or []:
        id_z = str(n.get("id", "")).strip()
        if id_z in po_id and n.get("napomena"):
            novi(id_z, "status_provjere", po_id[id_z].get("status_provjere", ""),
                 f"AI: {n['napomena']}", "napomena", n["napomena"], "", "ai")

    oznake_razdvojenih = {
        str(d.get("oznaka", "")).strip()
        for r in podaci.get("razdvajanja", []) or [] for d in (r.get("dijelovi") or [])
    } - {""}
    for n in podaci.get("nedostaju_u_bazi", []) or []:
        if str(n.get("broj_u_originalu", "")).strip() in oznake_razdvojenih:
            continue  # podzadatak je dio razdvajanja, nije stvarno nestao
        novi("", "-", "", "", "nedostaje_u_bazi",
             f"Zad. {n.get('broj_u_originalu', '?')}: {n.get('kratki_opis', '')}", "", "original")

    uparivanje = podaci.get("uparivanje", []) or []
    if "broj_u_izvoru" in header_zadaci:
        for u in uparivanje:
            id_z = str(u.get("id", "")).strip()
            broj = str(u.get("broj_u_originalu", "")).strip()
            if id_z in po_id and broj and po_id[id_z].get("broj_u_izvoru", "").strip() != broj:
                novi(id_z, "broj_u_izvoru", po_id[id_z].get("broj_u_izvoru", ""), broj,
                     "uparivanje", "", "visoka", "original")

    return {
        "status": "gotovo", "poruka": "", "prijedlozi": prijedlozi, "datoteke": datoteke_nazivi,
        "broj_zadataka": len(zadaci), "tokeni_ulaz": odg["tokeni_ulaz"],
        "tokeni_izlaz": odg["tokeni_izlaz"], "uparivanje": uparivanje,
    }


def ocr_serije(izvor_naziv, folder_id):
    """(ispit_md, rjesenja_md) iz spremljenih Mathpix .md datoteka za već obrađenu seriju
    (nazivi PDF-ova čitaju se iz taba AI_kontrola_serije, stupac 'datoteke')."""
    _, serije = ucitaj_tab_kao_dictove(ws_serije())
    datoteke = ""
    for r in serije:
        if r.get("serija") == izvor_naziv and r.get("datoteke"):
            datoteke = r["datoteke"]
    if not datoteke:
        return "", ""
    md_folder = drive_podfolder(folder_id, MD_PODFOLDER)
    md_mapa = {d["name"]: d["id"] for d in drive_popis(md_folder)}
    ispit, rj = [], []
    for ime in [x.strip() for x in datoteke.split(",") if x.strip()]:
        md_ime = re.sub(r"\.(pdf|png|jpe?g)$", "", ime, flags=re.I) + ".md"
        if md_ime not in md_mapa:
            continue
        tekst = drive_preuzmi(md_mapa[md_ime]).decode("utf-8")
        p = parsiraj_naziv(ime)
        (rj if p and p[3] else ispit).append(tekst)
    return "\n\n---\n\n".join(ispit), "\n\n---\n\n".join(rj)


def zatrazi_razdvajanje(izvor_naziv, red, folder_id, model):
    """Ciljani DeepSeek poziv: razdvoji JEDAN redak sa spojenim podzadacima. Vraća listu dijelova."""
    ispit_md, rj_md = ocr_serije(izvor_naziv, folder_id)
    poruka = (
        f"POSEBAN ZADATAK: u bazi je redak id \"{red.get('id')}\" u kojem je više podzadataka spojeno u "
        "jedan tekst. Razdvoji ga prema pravilu 1b. Vrati JSON u kojem je popunjena SAMO lista "
        f"\"razdvajanja\" (jedan element, za id \"{red.get('id')}\"); sve ostale liste neka budu prazne.\n\n"
        f"=== OCR ORIGINALNOG ISPITA ===\n{ispit_md or '(nije dostupan - koristi tekst iz baze)'}\n\n"
        f"=== OCR SLUŽBENIH RJEŠENJA / KLJUČA ===\n{rj_md or '(nema)'}\n\n"
        f"=== REDAK IZ BAZE ===\n{json.dumps(pripremi_zadatke_za_ai([red])[0], ensure_ascii=False, indent=1)}"
    )
    odg = pozovi_deepseek(model, poruka, 16000, lambda _t: None)
    podaci = izvuci_json(odg["tekst"])
    for r in podaci.get("razdvajanja", []) or []:
        if str(r.get("id", "")).strip() == red.get("id"):
            return [d for d in (r.get("dijelovi") or []) if str(d.get("tekst_zadatka_latex", "")).strip()], \
                r.get("razlog", ""), bool(ispit_md)
    return [], "", bool(ispit_md)


# ---------------------------------------------------------------
# UI
# ---------------------------------------------------------------

st.title("🔎 AI kontrola zadataka (DeepSeek)")
odlucio = st.sidebar.text_input("Tvoje ime (za evidenciju)", value="caki")

if "DEEPSEEK_API_KEY" not in st.secrets:
    st.error("Nedostaje DEEPSEEK_API_KEY u Streamlit Secrets (Settings → Secrets).")
    st.stop()

tab_obrada, tab_pregled, tab_povijest = st.tabs(
    ["1. Obrada (DeepSeek)", "2. Pregled i primjena", "3. Povijest serija"]
)

# ======================= TAB 1: OBRADA =======================
with tab_obrada:
    folder_id = st.text_input(
        "ID Drive foldera s ispitima",
        value=st.secrets.get("AI_KONTROLA_FOLDER_ID", ZADANI_FOLDER_ID),
        help="Dio linka foldera iza .../folders/", key="ai_folder_id",
    ).strip()
    folder_id = folder_id.split("/folders/")[-1].split("?")[0]

    if st.button("📂 Učitaj popis datoteka iz foldera"):
        with st.spinner("Čitam Drive folder i bazu..."):
            datoteke = drive_popis(folder_id)
            grupe, neprepoznate = grupiraj_datoteke(datoteke)
            header_z, redovi_z = ucitaj_tab_kao_dictove(init_spreadsheet().worksheet("Zadaci"))
            _, serije = ucitaj_tab_kao_dictove(ws_serije())
        st.session_state["ai_grupe"] = grupe
        st.session_state["ai_neprepoznate"] = neprepoznate
        st.session_state["ai_header_z"] = header_z
        st.session_state["ai_redovi_z"] = redovi_z
        st.session_state["ai_gotove_serije"] = {s["serija"] for s in serije if s.get("status") == "gotovo"}

    grupe = st.session_state.get("ai_grupe")
    if grupe:
        redovi_z = st.session_state["ai_redovi_z"]
        brojac = {}
        for r in redovi_z:
            brojac[r.get("izvor_naziv", "").strip()] = brojac.get(r.get("izvor_naziv", "").strip(), 0) + 1
        izvori = sorted(k for k in brojac if k)
        gotove = st.session_state["ai_gotove_serije"]

        if st.session_state["ai_neprepoznate"]:
            with st.expander(f"⚠️ Neprepoznati nazivi datoteka ({len(st.session_state['ai_neprepoznate'])}) - preskaču se"):
                st.write(st.session_state["ai_neprepoznate"])

        tablica = []
        for k, g in grupe.items():
            izv = auto_izvor_naziv(g, izvori)
            tablica.append({
                "obradi": False,
                "ispit": k,
                "datoteke_ispita": ", ".join(d["name"] for d in g["ispit"]) or "⚠️ NEMA",
                "datoteke_rjesenja": ", ".join(d["name"] for d in g["rjesenja"]) or "—",
                "izvor_naziv_u_bazi": izv,
                "zadataka_u_bazi": brojac.get(izv, 0),
                "vec_obradeno": "✅" if izv in gotove else "",
            })

        st.caption("Označi mature za obradu. Ako izvor_naziv nije pronađen automatski, odaberi ga ručno. "
                   "Za prvi put preporuka: 2-3 mature kao proba.")
        uredeno = st.data_editor(
            tablica, key="ai_tablica", hide_index=True, use_container_width=True,
            column_config={
                "obradi": st.column_config.CheckboxColumn("Obradi"),
                "izvor_naziv_u_bazi": st.column_config.SelectboxColumn(
                    "izvor_naziv u bazi", options=[""] + izvori),
                "zadataka_u_bazi": st.column_config.NumberColumn("U bazi (pri učitavanju)"),
            },
            disabled=["ispit", "datoteke_ispita", "datoteke_rjesenja", "zadataka_u_bazi", "vec_obradeno"],
        )

        c1, c2, c3 = st.columns(3)
        model = c1.selectbox("Model", MODELI, key="ai_model", help="v4-pro = jači i pouzdaniji za provjeru računa; flash = brži i jeftiniji")
        max_tokens = c2.number_input("Max. duljina odgovora (tokeni)", 2000, 64000,
                                     32000, step=1000)
        ponovno = c3.checkbox("Ponovno obradi i već obrađene", value=False)

        if st.button("▶️ Pokreni obradu označenih", type="primary"):
            odabrane = [r for r in uredeno if r["obradi"]]
            if not odabrane:
                st.warning("Nije označena nijedna matura.")
            else:
                log_mjesto = st.empty()
                log_linije = []

                def log(txt):
                    log_linije.append(f"{datetime.now(TZ).strftime('%H:%M:%S')}  {txt}")
                    log_mjesto.code("\n".join(log_linije[-40:]))

                md_folder_id = drive_podfolder(folder_id, MD_PODFOLDER)
                md_postojeci = {d["name"]: d["id"] for d in drive_popis(md_folder_id)}
                napredak = st.progress(0.0)
                ukupno_prijedloga = 0
                _, _svi_p = ucitaj_tab_kao_dictove(ws_prijedlozi())
                vec_postojeci = {(x.get("id_zadatka", ""), x.get("polje", ""), x.get("novo", "").strip())
                                 for x in _svi_p}

                for i, red in enumerate(odabrane, start=1):
                    g = grupe[red["ispit"]]
                    izv = (red["izvor_naziv_u_bazi"] or "").strip()
                    log(f"━━━ [{i}/{len(odabrane)}] {red['ispit']} → {izv or '(nije uparen)'}")
                    if not izv:
                        log("⏭️ Preskačem - nije odabran izvor_naziv u bazi.")
                    elif not g["ispit"]:
                        log("⏭️ Preskačem - nema datoteke ispita.")
                    elif izv in gotove and not ponovno:
                        log("⏭️ Već obrađeno ranije (uključi 'Ponovno obradi' ako želiš opet).")
                    else:
                        try:
                            rez = obradi_seriju(g, izv, redovi_z, st.session_state["ai_header_z"],
                                                md_folder_id, md_postojeci, model, int(max_tokens), log,
                                                vec_postojeci=vec_postojeci)
                            if rez["prijedlozi"]:
                                ws_prijedlozi().append_rows(rez["prijedlozi"], value_input_option="RAW")
                            ws_serije().append_row([
                                izv, sada(), rez["status"], rez.get("broj_zadataka", 0),
                                len(rez["prijedlozi"]), rez["datoteke"], model,
                                rez.get("tokeni_ulaz", ""), rez.get("tokeni_izlaz", ""), rez["poruka"],
                                json.dumps(rez.get("uparivanje", []), ensure_ascii=False)[:45000],
                            ], value_input_option="RAW")
                            ukupno_prijedloga += len(rez["prijedlozi"])
                            gotove.add(izv)
                            log(f"✅ {izv}: {len(rez['prijedlozi'])} prijedloga spremljeno.")
                        except Exception as e:  # jedna matura ne smije srušiti cijelu obradu
                            log(f"❌ {izv}: {e}")
                            try:
                                ws_serije().append_row([izv, sada(), "greska", "", 0, "", model, "", "",
                                                        str(e)[:500], ""], value_input_option="RAW")
                            except Exception:
                                pass
                    napredak.progress(i / len(odabrane))

                st.success(f"Gotovo. Ukupno novih prijedloga: {ukupno_prijedloga}. Pregledaj ih u tabu 2.")

# ======================= TAB 2: PREGLED =======================

# --- Slika zadatka (isti 02_SLIKE folder kao Test Builder i "Provjera i uređivanje") ---

@st.cache_data(ttl=600, show_spinner=False)
def dohvati_sliku(naziv):
    if not naziv:
        return None
    try:
        drive = init_drive()
        q_naziv = naziv.replace("'", "\\'")
        res = drive.files().list(
            q=f"name='{q_naziv}' and '{st.secrets['SLIKE_FOLDER_ID']}' in parents and trashed=false",
            fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if not res:
            return None
        bajtovi = drive.files().get_media(fileId=res[0]["id"], supportsAllDrives=True).execute()
        from PIL import Image  # provjera PRIJE st.image (oštećena slika može srušiti proces, v. Test Builder)
        with Image.open(io.BytesIO(bajtovi)) as im:
            im.verify()
        return bajtovi
    except Exception:
        return None


def prikazi_zadatak_iz_baze(z):
    putanja = os.path.basename((z.get("slika_putanja") or "").strip())
    if putanja:
        slika = dohvati_sliku(putanja)
        if slika:
            st.image(slika, width=380, caption="Slika zadatka")
        else:
            st.warning(f"Zadatak ima sliku ({putanja}), ali nije pronađena na Driveu.")
    elif z.get("slika_zadana") == "da":
        st.warning("Zadatak je označen da ima sliku, ali slika nije povezana (slika_putanja je prazna).")
    with st.expander("📝 Cijeli zadatak (kako je trenutno u bazi)"):
        st.markdown(z.get("tekst_zadatka_latex") or "*(prazno)*")
        opcije = [o.strip() for o in (z.get("ponudjeni_odgovori") or "").split("||") if o.strip()]
        if opcije:
            st.markdown(prikazi_opcije_markdown(opcije))
        if z.get("konacan_odgovor"):
            st.caption(f"Konačan odgovor: {z['konacan_odgovor']}")


with tab_pregled:
    if st.button("🔄 Osvježi prijedloge"):
        st.session_state.pop("ai_prijedlozi_cache", None)
        st.session_state.pop("ai_zadaci_po_id", None)
    if "ai_zadaci_po_id" not in st.session_state:
        _, _rz = ucitaj_tab_kao_dictove(init_spreadsheet().worksheet("Zadaci"))
        st.session_state["ai_zadaci_po_id"] = {r.get("id", ""): r for r in _rz}
    zadaci_po_id = st.session_state["ai_zadaci_po_id"]
    if "ai_prijedlozi_cache" not in st.session_state:
        st.session_state["ai_prijedlozi_cache"] = ucitaj_tab_kao_dictove(ws_prijedlozi())
    header_p, prijedlozi = st.session_state["ai_prijedlozi_cache"]
    otvoreni = [p for p in prijedlozi if p.get("status") == "novo"]

    if not otvoreni:
        st.info("Nema otvorenih prijedloga.")
    else:
        po_seriji = {}
        for p in otvoreni:
            po_seriji.setdefault(p["serija"], []).append(p)
        serija = st.selectbox("Serija (ispit)", list(po_seriji),
                              format_func=lambda s: f"{s} ({len(po_seriji[s])} otvorenih)")
        filt_sig = st.multiselect("Sigurnost", ["visoka", "srednja", "niska", ""],
                                  default=["visoka", "srednja", "niska", ""])
        lista = [p for p in po_seriji[serija] if p.get("sigurnost", "") in filt_sig]
        st.caption("Za svaki prijedlog odaberi odluku. 'Novo' polje možeš i ručno doraditi prije primjene. "
                   "Napomene se dopisuju u status_provjere, a 'nedostaje u bazi' se samo označava pregledanim.")

        ids_serije = list(dict.fromkeys(p["id_zadatka"] for p in lista if p.get("id_zadatka")))
        if ids_serije:
            oc1, oc2 = st.columns([2, 1])
            id_otvori = oc1.selectbox("✏️ Otvori zadatak u uređivanju (cijeli zadatak, slika i AI prijedlozi uz njega)",
                                      ids_serije, key="ai_otvori_sel")
            oc2.write("")
            if oc2.button("Otvori u 'Provjera i uređivanje' →"):
                st.session_state["ai_otvori_id"] = id_otvori
                st.session_state["ai_otvori_lista"] = ids_serije
                st.session_state["glavna_stranica"] = "🔍✏️ Provjera i uređivanje zadataka"
                st.switch_page("baza_zadataka_app.py")

        with st.expander("✂️ Razdvoji zadatak na podzadatke (kad su u bazi spojeni npr. 25.1, 25.2, 25.3)",
                         expanded=any(je_sumnjivo_skracivanje(p) for p in lista)):
            sumnjivi = [p["id_zadatka"] for p in lista if je_sumnjivo_skracivanje(p)]
            kandidati = list(dict.fromkeys(sumnjivi + ids_serije))
            if kandidati:
                id_rz = st.selectbox("Zadatak", kandidati, key="ai_rz_sel",
                                     format_func=lambda i: f"{i}  ⚠️ skraćuje tekst" if i in sumnjivi else i)
                st.caption("DeepSeek pripremi dijelove (svaki samostalan, s odgovorom iz ključa). Pojavit će se kao "
                           "prijedlog „✂️ razdvajanje” koji možeš doraditi. Stari prijedlog skraćivanja i "
                           "„nedostaje u bazi” za te podzadatke automatski se uklanjaju iz popisa.")
                if st.button("🤖 Pripremi razdvajanje", key="ai_rz_btn") and id_rz in zadaci_po_id:
                    red_rz = zadaci_po_id[id_rz]
                    _fid = (st.session_state.get("ai_folder_id") or
                            st.secrets.get("AI_KONTROLA_FOLDER_ID", ZADANI_FOLDER_ID)).split("/folders/")[-1].split("?")[0]
                    _model = st.session_state.get("ai_model", MODELI[0])
                    with st.spinner(f"DeepSeek ({_model}) razdvaja {id_rz}..."):
                        try:
                            dijelovi, razlog_rz, ima_ocr = zatrazi_razdvajanje(serija, red_rz, _fid, _model)
                        except Exception as e:
                            dijelovi, razlog_rz, ima_ocr = [], f"greška: {e}", False
                    if len(dijelovi) < 2:
                        st.error(f"DeepSeek nije vratio razdvajanje ({razlog_rz or 'nema dijelova'}).")
                    else:
                        ws_prijedlozi().append_row([
                            uuid.uuid4().hex[:10], sada(), serija, id_rz, RAZDVOJI,
                            red_rz.get("tekst_zadatka_latex", ""), json.dumps(dijelovi, ensure_ascii=False),
                            "razdvajanje", razlog_rz or "Razdvajanje spojenih podzadataka",
                            "visoka" if ima_ocr else "srednja", "original" if ima_ocr else "ai_izracun",
                            "novo", "", "", _model, "",
                        ], value_input_option="RAW")
                        oznake = [str(d.get("oznaka", "")).strip() for d in dijelovi if d.get("oznaka")]
                        zamijenjeni = [
                            p for p in po_seriji[serija]
                            if (p["id_zadatka"] == id_rz and p["polje"] == "tekst_zadatka_latex")
                            or (p["polje"] == "-" and any(p.get("razlog", "").startswith(f"Zad. {o}:") for o in oznake))
                        ]
                        oznaci_zamijenjene(init_spreadsheet(), zamijenjeni, odlucio)
                        st.session_state.pop("ai_prijedlozi_cache", None)
                        st.success(f"Razdvajanje na {len(dijelovi)} dijela pripremljeno - pogledaj ga u popisu.")
                        st.rerun()

        with st.form(f"forma_{serija}"):
            odluke = {}
            for p in lista:
                pid = p["prijedlog_id"]
                st.markdown(f"#### {naslov_prijedloga(p)}")
                prikazi_kontekst_prijedloga(p)
                if p.get("id_zadatka") in zadaci_po_id:
                    prikazi_zadatak_iz_baze(zadaci_po_id[p["id_zadatka"]])
                if p["polje"] == RAZDVOJI:
                    novo_uredeno = uredi_razdvajanje(p, f"rz_{pid}")
                elif p["polje"] not in ("-", "status_provjere"):
                    if je_sumnjivo_skracivanje(p):
                        st.error(UPOZORENJE_SKRACIVANJE)
                    if je_samo_dolari(p):
                        st.error(UPOZORENJE_DOLARI)
                    st.caption("🔍 Promjena (crveno = briše se, zeleno = dodaje se):")
                    prikazi_promjenu(p)
                    with st.expander("Prikaz formula prije / poslije i ručna izmjena"):
                        a, b = st.columns(2)
                        a.markdown("**U bazi:**")
                        a.markdown(p["staro"] or "*(prazno)*")
                        b.markdown("**Prijedlog:**")
                        b.markdown(p["novo"] or "*(prazno)*")
                        novo_uredeno = st.text_area("Nova vrijednost (možeš urediti prije prihvaćanja)",
                                                    p["novo"], key=f"tx_{pid}", height=90)
                else:
                    novo_uredeno = p["novo"]
                odluka = st.radio("Odluka", ["⏸️ kasnije", "✅ prihvati", "❌ odbij"],
                                  index=2 if je_samo_dolari(p) else 0,
                                  horizontal=True, key=f"od_{pid}")
                odluke[pid] = (odluka, novo_uredeno)
                st.divider()
            potvrdi = st.form_submit_button("💾 Spremi odluke i primijeni prihvaćene", type="primary")

        if potvrdi:
            ws_z = init_spreadsheet().worksheet("Zadaci")
            header_z, redovi_z = ucitaj_tab_kao_dictove(ws_z)  # svježe stanje baze
            red_po_id = {r.get("id", ""): r for r in redovi_z}
            izmjene_z, izmjene_p = [], []
            col_status = slovo_stupca(header_p.index("status"))
            col_odlucio = slovo_stupca(header_p.index("odlucio"))
            col_vrijeme = slovo_stupca(header_p.index("vrijeme_odluke"))
            col_novo = slovo_stupca(header_p.index("novo"))
            br_primijenjeno = br_zastarjelo = br_odbijeno = 0

            for p in lista:
                odluka, novo_val = odluke[p["prijedlog_id"]]
                if odluka.startswith("⏸️"):
                    continue
                novi_status = "odbijeno"
                if odluka.startswith("✅") and p["polje"] == RAZDVOJI:
                    st_r = primijeni_razdvajanje(init_spreadsheet(), ws_z, p, odlucio,  # sam zapisuje status
                                                 novo_val if novo_val != p["novo"] else None)
                    if st_r == "primijenjeno":
                        br_primijenjeno += 1
                    elif st_r == "zastarjelo":
                        br_zastarjelo += 1
                    else:
                        st.warning(f"Razdvajanje {p['id_zadatka']}: {st_r}")
                    continue
                if odluka.startswith("✅"):
                    if p["polje"] == "-":
                        novi_status = "pregledano"
                    else:
                        r = red_po_id.get(p["id_zadatka"])
                        if not r or p["polje"] not in header_z:
                            novi_status = "greska_nema_retka_ili_stupca"
                        elif p["polje"] != "status_provjere" and r.get(p["polje"], "").strip() != p["staro"].strip():
                            novi_status = "zastarjelo"
                            br_zastarjelo += 1
                        else:
                            if p["polje"] == "status_provjere":
                                sad = r.get("status_provjere", "").strip()
                                novo_val = f"{sad}; {novo_val}" if sad else novo_val
                            celija = f"{slovo_stupca(header_z.index(p['polje']))}{r['_redak']}"
                            izmjene_z.append({"range": celija, "values": [[novo_val]]})
                            r[p["polje"]] = novo_val
                            novi_status = "primijenjeno"
                            br_primijenjeno += 1
                else:
                    br_odbijeno += 1
                rr = p["_redak"]
                izmjene_p += [
                    {"range": f"{col_status}{rr}", "values": [[novi_status]]},
                    {"range": f"{col_odlucio}{rr}", "values": [[odlucio]]},
                    {"range": f"{col_vrijeme}{rr}", "values": [[sada()]]},
                ]
                if novi_status == "primijenjeno" and novo_val != p["novo"]:
                    izmjene_p.append({"range": f"{col_novo}{rr}", "values": [[novo_val]]})

            if izmjene_z:
                ws_z.batch_update(izmjene_z, value_input_option="RAW")
            if izmjene_p:
                ws_prijedlozi().batch_update(izmjene_p, value_input_option="RAW")
            st.session_state.pop("ai_prijedlozi_cache", None)
            st.session_state.pop("ai_zadaci_po_id", None)
            st.success(f"Primijenjeno: {br_primijenjeno} · odbijeno: {br_odbijeno} · "
                       f"zastarjelo (baza se u međuvremenu promijenila): {br_zastarjelo}")
            st.button("Nastavi")

# ======================= TAB 3: POVIJEST =======================
with tab_povijest:
    if st.button("Prikaži povijest obrade"):
        _, serije = ucitaj_tab_kao_dictove(ws_serije())
        st.dataframe(
            [{k: v for k, v in s.items() if k not in ("_redak", "uparivanje_json")} for s in serije],
            use_container_width=True, hide_index=True,
        )
