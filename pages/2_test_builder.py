"""
CAKI Matematika - pages/2_test_builder.py
Streamlit "Test Builder": profesor pretraži i odabere zadatke iz baze
(ili doda ručni/ad-hoc zadatak), posloži redoslijed strelicama, unese
naslov/datum/bodove (ako je test), i generira gotov PDF za print —
sve iz preglednika, bez LaTeX/Overleaf koraka.

Očekuje da su u istom repozitoriju/folderu prisutne datoteke:
  caki-style.sty, main_test_template.tex

Streamlit Cloud: za pdflatex, dodaj packages.txt (vidi README.md).
"""
import copy
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile

import gspread
import streamlit as st

from baza_zadataka_pipeline import (
    get_drive_service,
    get_gspread_client,
    get_potpoglavlja_po_cjelini,
    prikazi_opcije_markdown,
)

st.set_page_config(page_title="CAKI Test Builder", page_icon="📝", layout="wide")

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------
# Kategorije vrednovanja (kurikulum matematike) — profesor po zadatku
# može čekirati 1-3 kategorije i upisati koliko bodova od ukupnih
# bodova zadatka ide u svaku kategoriju (npr. RP: 1 bod + MK: 2 boda).
# Ovo je metapodatak SAMO za ovaj generirani dokument (analogno polju
# "bodovi" koje je već editabilno po odabranom zadatku, ne mijenja se
# baza) - NE zapisuje se natrag u Google Sheets bazu zadataka.
# ---------------------------------------------------------------

KATEGORIJE_INFO = [
    ("UZV", "Usvojenost znanja i vještina"),
    ("RP", "Rješavanje problema"),
    ("MK", "Matematička komunikacija"),
]

TIP_ZADATKA_OPCIJE = ["", "visestruki_izbor", "kratki_odgovor", "prosireni_odgovor"]
TIP_ZADATKA_LABELS = {
    "": "— (nije određeno)",
    "visestruki_izbor": "Višestruki izbor (A/B/C/D...)",
    "kratki_odgovor": "Kratki odgovor (crta za upis)",
    "prosireni_odgovor": "Prošireni odgovor / puni postupak",
}

# ---------------------------------------------------------------
# Tip dokumenta (izmjena 11.9.2026., na izričit zahtjev) — zamjenjuje
# raniju dvočlanu podjelu "Test" / "Skripta - radni listić" trima
# nastavnim oblicima. Precizni predlošci po tipu dolaze naknadno -
# za sada je "Pisana provjera znanja" jedini tip koji se BODUJE
# (kategorije vrednovanja, zaglavlje s "Ostvareno"/"Ocjena", zbroj
# bodova) - isto ponašanje koje je prije imao tip "Test". Preostala
# dva tipa ponašaju se kao dosadašnja "Skripta / radni listić"
# (bez bodovanja) dok se ne dogovori drukčije - PRETPOSTAVKA, lako
# promjenjiva kad stignu precizni predlošci po tipu.
# ---------------------------------------------------------------
TIP_DOKUMENTA_OPCIJE = ["Pisana provjera znanja", "Zadaci za vježbu na satu", "Domaća zadaća"]
KRAJ_OZNAKA_PO_TIPU = {
    "Pisana provjera znanja": "KRAJ TESTA",
    "Zadaci za vježbu na satu": "KRAJ ZADATAKA ZA VJEŽBU",
    "Domaća zadaća": "KRAJ DOMAĆE ZADAĆE",
}


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao u app.py)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_tb") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_tb"] = True
        else:
            st.session_state["autoriziran_tb"] = False

    if st.session_state.get("autoriziran_tb"):
        return True

    st.title("📝 CAKI Test Builder")
    st.text_input("Lozinka", type="password", key="lozinka_unos_tb", on_change=na_unos)
    if st.session_state.get("autoriziran_tb") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------
# Google Sheets — dohvat zadataka (keširano 5 min da ne udaramo API)
# ---------------------------------------------------------------

@st.cache_resource
def init_spreadsheet():
    import json
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


@st.cache_resource
def init_sheet():
    return init_spreadsheet().worksheet("Zadaci")


@st.cache_resource
def init_drive():
    import json
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return get_drive_service(sa_info)


@st.cache_data(ttl=600)
def dohvati_sliku_bytes(naziv_datoteke):
    """Dohvaća bajtove slike iz istog 02_SLIKE Drive foldera koji koristi i
    app.py (stranica 'Dodaj/zamijeni sliku'). Vraća None ako nije pronađena
    (npr. slika_putanja u bazi nije više valjana) umjesto da baci grešku -
    poziv koji koristi ovo mora sam odlučiti kako to prikazati/prijaviti."""
    if not naziv_datoteke:
        return None
    drive_service = init_drive()
    slike_folder_id = st.secrets["SLIKE_FOLDER_ID"]
    try:
        rezultat = drive_service.files().list(
            q=f"name='{naziv_datoteke}' and '{slike_folder_id}' in parents and trashed=false",
            fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        datoteke = rezultat.get("files", [])
        if not datoteke:
            return None
        return drive_service.files().get_media(fileId=datoteke[0]["id"], supportsAllDrives=True).execute()
    except Exception:
        return None


@st.cache_data(ttl=300)
def ucitaj_zadatke():
    ws = init_sheet()
    return ws.get_all_records()


@st.cache_data(ttl=600)
def ucitaj_potpoglavlja_po_cjelini():
    """{cjelina: [(potpoglavlje, redoslijed), ...]} iz taba 'Sifrarnik_potpoglavlja',
    za filter "Potpoglavlje" u pretrazi (§1) - da izbornik prati redoslijed iz šifrarnika,
    ne abecedni/slučajan poredak. Ako tab ne postoji ili je čitanje neuspješno, vraća {}
    - pozivatelj se tada oslanja na fallback izveden izravno iz stvarnih zadataka."""
    try:
        return get_potpoglavlja_po_cjelini(init_spreadsheet())
    except Exception:
        return {}


# ---------------------------------------------------------------
# Predlošci testova + autospremanje nacrta (14.9.2026.) — dva nova, isključivo
# Test-Builderova taba u ISTOM spreadsheetu kao 'Zadaci'. Namjerno definirano
# OVDJE (ne u baza_zadataka_pipeline.py) - ne dira dijeljenu logiku/shemu, čisto
# aditivno, izolirano na ovu stranicu. "TestBuilder_predlosci" čuva profesorove
# imenovane, ručno spremljene odabire (za ponovnu upotrebu iz godine u godinu);
# "TestBuilder_draft" čuva JEDAN "trenutni" redak koji se tiho prepisuje pri
# svakoj promjeni odabira, kao zaštita od gubitka rada ako se Streamlit sesija
# resetira (istek, hard refresh) usred slaganja testa.
# ---------------------------------------------------------------

PREDLOSCI_HEADERS = [
    "predlozak_id", "naziv", "datum_spremanja",
    "naslov_dokumenta", "tip_dokumenta", "prikazi_rjesenja",
    "broj_zadataka", "sadrzaj_json",
]
DRAFT_HEADERS = [
    "draft_id", "zadnja_izmjena",
    "naslov_dokumenta", "tip_dokumenta", "prikazi_rjesenja",
    "broj_zadataka", "sadrzaj_json",
]


def _dohvati_ili_kreiraj_tab(naziv, headers):
    spreadsheet = init_spreadsheet()
    try:
        return spreadsheet.worksheet(naziv)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=naziv, rows=200, cols=max(len(headers), 8))
        ws.append_row(headers)
        return ws


@st.cache_resource
def init_predlosci_ws():
    return _dohvati_ili_kreiraj_tab("TestBuilder_predlosci", PREDLOSCI_HEADERS)


@st.cache_resource
def init_draft_ws():
    return _dohvati_ili_kreiraj_tab("TestBuilder_draft", DRAFT_HEADERS)


def _stanje_za_spremanje(naslov_val, tip_dok_val, prikazi_rjesenja_val):
    """Serijalizira TRENUTNI st.session_state.odabrani + prateće metapodatke u
    oblik spreman za upis u Sheets red (predložak ili nacrt - isti format za oba)."""
    return {
        "naslov_dokumenta": naslov_val or "",
        "tip_dokumenta": tip_dok_val or "",
        "prikazi_rjesenja": bool(prikazi_rjesenja_val),
        "broj_zadataka": len(st.session_state.odabrani),
        "sadrzaj_json": json.dumps(st.session_state.odabrani, ensure_ascii=False),
    }


def _ucitaj_stanje(sadrzaj_json, naslov_dokumenta, tip_dokumenta, prikazi_rjesenja):
    """Postavlja učitani predložak/nacrt u session_state. Poziv MORA odmah nakon
    ovoga zvati st.rerun() - widgeti (naslov/tip dokumenta/rješenja) čitaju svoje
    vrijednosti iz session_state PRI SLJEDEĆEM pokretanju skripte, ne odmah."""
    try:
        st.session_state.odabrani = json.loads(sadrzaj_json) if sadrzaj_json else []
    except (json.JSONDecodeError, TypeError):
        st.session_state.odabrani = []
    if naslov_dokumenta:
        st.session_state["naslov_dok"] = naslov_dokumenta
    if tip_dokumenta in TIP_DOKUMENTA_OPCIJE:
        st.session_state["tip_dok_sel"] = tip_dokumenta
    st.session_state["prikazi_rjesenja_cb"] = str(prikazi_rjesenja).strip().lower() in ("true", "1", "da")


# ---------------------------------------------------------------
# LaTeX escape (izvan $...$ regija) — ista logika kao generate_tex.py
# ---------------------------------------------------------------

SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def escape_outside_math(text: str) -> str:
    if not text:
        return ""
    parts = re.split(r"(\$[^$]*\$)", text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part)
        else:
            out.append("".join(SPECIAL_CHARS.get(ch, ch) for ch in part))
    return "".join(out)


def izgradi_kategorije_tex(kategorije: dict) -> str:
    """kategorije: {"UZV": "2", "RP": "1", ...} -> LaTeX tekst prikazan kao mala
    oznaka na vrhu okvira zadatka u PDF-u, npr. "UZV: 2 bod.  RP: 1 bod."
    Redoslijed je UVIJEK UZV/RP/MK (fiksiran u KATEGORIJE_INFO), bez obzira
    kojim je redom profesor čekirao kategorije u sučelju. Ako je kategorija
    čekirana ali bodovi nisu upisani, prikazuje se samo kod kategorije."""
    dijelovi = []
    for kod, _naziv in KATEGORIJE_INFO:
        if kod not in kategorije:
            continue
        bod = str(kategorije.get(kod, "")).strip()
        if bod:
            dijelovi.append(f"{kod}: {escape_outside_math(bod)}\\space bod.")
        else:
            dijelovi.append(kod)
    return "\\quad ".join(dijelovi)


def broj_iz_stringa(vrijednost) -> float:
    """Parsira tekstualni unos bodova (dopušta i ',' kao decimalni zarez) u float.
    Baca ValueError za prazno/neispravno - poziv MORA to hvatati (koristi se i u
    UI upozorenju i u blokirajućoj provjeri prije generiranja)."""
    return float(str(vrijednost).strip().replace(",", "."))


def izgradi_kategorije_redovi(ukupno_po_kategoriji: dict) -> str:
    """ukupno_po_kategoriji: {"UZV": 3.0, "RP": 1.0, ...} (zbroj bodova te
    kategorije preko SVIH odabranih zadataka) -> LaTeX blok redaka za zaglavlje
    testa (\\cakiispithead #5) - PO JEDAN redak s "Ostvareno"/"Ocjena" za SVAKU
    kategoriju koja se stvarno koristi u testu (test se ocjenjuje po kategoriji,
    ne jednim cjelokupnim zbrojem/ocjenom - vidi #25 u CAKI_MASTER_BAZA).
    Kategorije bez ijednog dodijeljenog boda (0 ili nema u dictu) se preskaču."""
    redovi = []
    for kod, _naziv in KATEGORIJE_INFO:
        total = ukupno_po_kategoriji.get(kod) or 0
        if not total:
            continue
        total_str = f"{total:g}"
        redovi.append(
            "\\par\\vspace{2mm}\n"
            f"\\noindent\\textbf{{{kod} \\textemdash{{}} ukupno bodova:}} {total_str} \\quad "
            "\\textbf{Ostvareno:} \\makebox[2cm]{\\hrulefill} \\quad "
            "\\textbf{Ocjena:} \\makebox[2cm]{\\hrulefill}"
        )
    return "".join(redovi)


# ---------------------------------------------------------------
# Session state — odabrani zadaci (redoslijed = redoslijed u listi)
# ---------------------------------------------------------------

if "odabrani" not in st.session_state:
    st.session_state.odabrani = []  # [{id, tekst, video_url, bodovi, izvor, kategorije, ...}]


def dodaj_zadatak(row, bodovi_default=""):
    st.session_state.odabrani.append({
        "id": row.get("id", ""),
        "tekst": row.get("tekst_zadatka_latex", ""),
        "video_url": row.get("video_url", ""),
        "bodovi": str(row.get("max_bodovi") or bodovi_default or ""),
        "izvor": "baza",
        "tip_zadatka": row.get("tip_zadatka", ""),
        # U bazi je spremljeno kao " || " odvojen string (vidi nadopuni_ili_dodaj_zadatke
        # u pipeline.py) - ovdje ga odmah pretvaramo u listu radi lakšeg rada dalje.
        "ponudjeni_odgovori": [
            o.strip() for o in str(row.get("ponudjeni_odgovori", "")).split("||") if o.strip()
        ],
        # Po zadatku, ne globalno - profesor može isti tip zadatka (visestruki_izbor)
        # u jednom dijelu testa prikazati s opcijama, a u drugom bez (npr. dio "kratki
        # odgovori" gdje se isti zadatak koristi bez ponuđenih A/B/C/D).
        "prikazi_opcije": True,
        "slika_putanja": row.get("slika_putanja", "").strip() if row.get("slika_zadana") == "da" else "",
        "rjesenje": row.get("rjesenje", ""),
        "konacan_odgovor": row.get("konacan_odgovor", ""),
        # Kategorije vrednovanja (UZV/RP/MK) s bodovima po kategoriji - profesor
        # ih bira ovdje u Test Builderu, ne dolaze iz baze (vidi KATEGORIJE_INFO gore).
        "kategorije": {},
    })


def pomakni(idx, smjer):
    novi = idx + smjer
    lst = st.session_state.odabrani
    if 0 <= novi < len(lst):
        lst[idx], lst[novi] = lst[novi], lst[idx]


def ukloni(idx):
    st.session_state.odabrani.pop(idx)


# ---------------------------------------------------------------
# UI — dvije kolone: pretraga baze (lijevo) / odabrani zadaci (desno)
# ---------------------------------------------------------------

st.title("📝 CAKI Test Builder")
st.caption("Odaberi zadatke iz baze ili dodaj ručne, posloži redoslijed, unesi metapodatke, generiraj PDF.")

# ---------------------------------------------------------------
# Ponuda za učitavanje spremljenog nacrta (14.9.2026.) — provjerava se JEDNOM
# po sesiji, i SAMO ako je trenutni odabir prazan (svježa sesija) - da profesor
# ne bude gnjavljen ponudom na svaki rerun, niti da mu se slučajno prepiše rad
# koji je već u tijeku u OVOJ sesiji.
# ---------------------------------------------------------------

if "draft_provjera_ucinjena" not in st.session_state:
    st.session_state["draft_provjera_ucinjena"] = True
    if not st.session_state.odabrani:
        try:
            _draft_redovi = init_draft_ws().get_all_records()
        except Exception:
            _draft_redovi = []
        if _draft_redovi and _draft_redovi[0].get("sadrzaj_json"):
            st.session_state["_pronadjen_draft"] = _draft_redovi[0]

if st.session_state.get("_pronadjen_draft"):
    _d = st.session_state["_pronadjen_draft"]
    st.info(
        f"📥 Pronađen spremljeni nacrt od {_d.get('zadnja_izmjena', '?')} "
        f"({_d.get('broj_zadataka', '?')} zadataka, naslov: „{_d.get('naslov_dokumenta') or '—'}”)."
    )
    _dcol1, _dcol2 = st.columns([1, 1])
    if _dcol1.button("📂 Učitaj nacrt"):
        _ucitaj_stanje(
            _d.get("sadrzaj_json", ""), _d.get("naslov_dokumenta", ""),
            _d.get("tip_dokumenta", ""), _d.get("prikazi_rjesenja", ""),
        )
        st.session_state["_pronadjen_draft"] = None
        st.rerun()
    if _dcol2.button("🗑️ Odbaci nacrt"):
        st.session_state["_pronadjen_draft"] = None
        st.rerun()

col_pretraga, col_odabrano = st.columns([1, 1], gap="large")

with col_pretraga:
    st.subheader("1. Pretraga baze")
    try:
        zadaci = ucitaj_zadatke()
    except Exception as e:
        st.error(f"Ne mogu učitati bazu: {e}")
        zadaci = []

    sve_cjeline = sorted({z.get("cjelina", "") for z in zadaci if z.get("cjelina")})
    sve_tezine = sorted({z.get("tezina", "") for z in zadaci if z.get("tezina")})

    f_cjelina = st.multiselect("Cjelina", sve_cjeline)

    potpoglavlja_po_cjelini = ucitaj_potpoglavlja_po_cjelini()
    if f_cjelina:
        opcije_potpoglavlje = []
        for _c in f_cjelina:
            for _p, _ in potpoglavlja_po_cjelini.get(_c, []):
                if _p not in opcije_potpoglavlje:
                    opcije_potpoglavlje.append(_p)
        if not opcije_potpoglavlje:
            # Šifrarnik nedostupan/prazan za odabranu cjelinu - fallback na potpoglavlja
            # koja se stvarno pojavljuju u bazi za tu cjelinu (bolje nego prazan izbornik).
            opcije_potpoglavlje = sorted({
                z.get("potpoglavlje", "") for z in zadaci
                if z.get("cjelina") in f_cjelina and z.get("potpoglavlje")
            })
    else:
        opcije_potpoglavlje = sorted({z.get("potpoglavlje", "") for z in zadaci if z.get("potpoglavlje")})
    f_potpoglavlje = st.multiselect("Potpoglavlje", opcije_potpoglavlje)

    f_tezina = st.multiselect("Težina", sve_tezine)
    f_tekst = st.text_input("Pretraži tekst / ključne riječi")

    filtrirano = zadaci
    if f_cjelina:
        filtrirano = [z for z in filtrirano if z.get("cjelina") in f_cjelina]
    if f_potpoglavlje:
        filtrirano = [z for z in filtrirano if z.get("potpoglavlje") in f_potpoglavlje]
    if f_tezina:
        filtrirano = [z for z in filtrirano if z.get("tezina") in f_tezina]
    if f_tekst:
        upit = f_tekst.lower()
        filtrirano = [
            z for z in filtrirano
            if upit in (z.get("tekst_zadatka_latex", "") or "").lower()
            or upit in (z.get("kljucne_rijeci", "") or "").lower()
        ]

    # ID-jevi zadataka koji su VEĆ u "2. Odabrani zadaci" - za kvačicu/oznaku
    # niže i onemogućavanje ponovnog dodavanja istog zadatka (zahtjev 14.9.2026.:
    # profesor je znao slučajno dodati isti zadatak dvaput jer ništa u popisu
    # pretrage nije pokazivalo da je zadatak već odabran).
    ids_odabranih = {z.get("id") for z in st.session_state.odabrani if z.get("id")}

    # Paginacija umjesto tvrdog reza na prvih 30 (popravak 14.9.2026.) - stari kod je
    # UVIJEK prikazivao samo filtrirano[:30], bez obzira koliko je zadataka stvarno
    # zadovoljavalo filter (cjelina/potpoglavlje/težina). To je uzrokovalo TOČNO
    # prijavljeni bug: kod filtriranja po cjelini/potpoglavlju znalo je postojati
    # >30 podudaranja pa su zadaci iza 30. mjesta bili nevidljivi, ali kad bi se
    # DODAO i tekstualni filtar, ukupan broj podudaranja bi pao ispod 30 i ti isti
    # "nestali" zadaci bi se odjednom pojavili - profesor je to protumačio kao da ih
    # pretraga po cjelini uopće ne nalazi, iako je uzrok bio isključivo prikaz prvih
    # 30 rezultata. Sad se početnih 50 prikazuje odmah, a gumb "Prikaži još" otkriva
    # ostatak u koracima od 50 - brojač se resetira na 50 čim se bilo koji filter
    # promijeni (novi filter_potpis), da rezultati prošle pretrage ne "cure" u novu.
    filter_potpis = (tuple(sorted(f_cjelina)), tuple(sorted(f_potpoglavlje)), tuple(sorted(f_tezina)), f_tekst)
    if st.session_state.get("tb_filter_potpis") != filter_potpis:
        st.session_state["tb_filter_potpis"] = filter_potpis
        st.session_state["tb_broj_prikaza"] = 50
    broj_prikaza = st.session_state.get("tb_broj_prikaza", 50)

    if len(filtrirano) > broj_prikaza:
        st.caption(f"{len(filtrirano)} zadataka pronađeno (prikazano prvih {broj_prikaza})")
    else:
        st.caption(f"{len(filtrirano)} zadataka pronađeno (prikazani svi)")

    # Masovno dodavanje (15.9.2026., UX prijedlog - stavka 3) - dodaje sve TRENUTNO
    # PRIKAZANE (do broj_prikaza) zadatke koji još nisu u "2. Odabrani zadaci" u jednom
    # potezu, umjesto pojedinačnog "➕ Dodaj" po zadatku. Namjerno ograničeno na
    # prikazane (ne na CIJELI filtrirano skup) - da profesor uvijek zna točno koliko
    # će i kojih zadataka dodati, bez iznenađenja ako filter vrati npr. 200 podudaranja
    # - suzi filter (ili klikni "Prikaži još") ako treba dodati više odjednom.
    _neprikazani_dodani = [row for row in filtrirano[:broj_prikaza] if row.get("id") not in ids_odabranih]
    if _neprikazani_dodani:
        if st.button(f"➕ Dodaj sve prikazane ({len(_neprikazani_dodani)})", key="tb_dodaj_sve_prikazane"):
            for row in _neprikazani_dodani:
                dodaj_zadatak(row)
            st.rerun()

    for row in filtrirano[:broj_prikaza]:
        with st.container(border=True):
            _vec_dodan = row.get("id") in ids_odabranih
            _oznaka_dodano = "✅ " if _vec_dodan else ""
            st.markdown(
                f"{_oznaka_dodano}`{row.get('id','')}` · {row.get('cjelina','')} · "
                f"{row.get('tezina','')} · {row.get('max_bodovi','') or '?'} bod."
            )
            st.markdown(row.get("tekst_zadatka_latex", ""))
            if row.get("tip_zadatka") == "visestruki_izbor":
                _opc_raw = [o.strip() for o in str(row.get("ponudjeni_odgovori", "")).split("||") if o.strip()]
                if _opc_raw:
                    st.markdown(prikazi_opcije_markdown(_opc_raw))
            if row.get("slika_zadana") == "da" and row.get("slika_putanja", "").strip():
                # Sličica izravno u popisu (popravak 14.9.2026., §25.11) - prije je
                # trebalo kliknuti "Prikaži sliku" za SVAKI redak posebno; sad se mala
                # sličica prikazuje odmah (Streamlitov st.image ima ugrađenu ikonu za
                # uvećanje na hover, nije potreban zaseban gumb/klik za veći prikaz).
                # Napomena: usporava prvi prikaz stranice ako je vidljivo mnogo
                # zadataka sa slikama odjednom (svaka nova slika = Drive API poziv),
                # ali dohvati_sliku_bytes je keširan 10 min pa ponovni pregled iste
                # stranice/filtera ne ponavlja iste pozive.
                _slika_bytes = dohvati_sliku_bytes(row["slika_putanja"].strip())
                if _slika_bytes:
                    st.image(_slika_bytes, width=130)
                else:
                    st.warning("Slika nije pronađena na Driveu (možda stari/neispravan zapis).")
            if _vec_dodan:
                st.button("✅ Već dodano", key=f"add_{row.get('id')}", disabled=True)
            elif st.button("➕ Dodaj", key=f"add_{row.get('id')}"):
                dodaj_zadatak(row)
                st.rerun()

    if len(filtrirano) > broj_prikaza:
        if st.button(f"⬇️ Prikaži još ({min(50, len(filtrirano) - broj_prikaza)})", key="tb_prikazi_jos"):
            st.session_state["tb_broj_prikaza"] = broj_prikaza + 50
            st.rerun()

    with st.expander("➕ Dodaj ručni (ad-hoc) zadatak"):
        rucni_tekst = st.text_area("Tekst zadatka (LaTeX matematika unutar $...$)", key="rucni_tekst")
        rucni_video = st.text_input("Video URL (opcionalno)", key="rucni_video")
        rucni_bodovi = st.text_input("Bodovi (opcionalno)", key="rucni_bodovi")
        rucni_tip = st.selectbox(
            "Tip zadatka", TIP_ZADATKA_OPCIJE, format_func=lambda t: TIP_ZADATKA_LABELS[t],
            key="rucni_tip",
        )
        rucni_odgovori_raw = ""
        if rucni_tip == "visestruki_izbor":
            rucni_odgovori_raw = st.text_input(
                "Ponuđeni odgovori, odvojeni s ';' (npr. $x=1$; $x=2$; $x=4$; $x=6$)",
                key="rucni_odgovori",
            )
        rucni_rjesenje = st.text_area("Rješenje - puni postupak (opcionalno)", key="rucni_rjesenje")
        rucni_konacan = st.text_input("Konačan odgovor (opcionalno)", key="rucni_konacan")
        if st.button("➕ Dodaj ručni zadatak"):
            if rucni_tekst.strip():
                st.session_state.odabrani.append({
                    "id": None, "tekst": rucni_tekst, "video_url": rucni_video,
                    "bodovi": rucni_bodovi, "izvor": "ad_hoc",
                    "tip_zadatka": rucni_tip,
                    "ponudjeni_odgovori": [
                        o.strip() for o in rucni_odgovori_raw.split(";") if o.strip()
                    ] if rucni_tip == "visestruki_izbor" else [],
                    "prikazi_opcije": True,
                    "slika_putanja": "",
                    "rjesenje": rucni_rjesenje,
                    "konacan_odgovor": rucni_konacan,
                    "kategorije": {},
                })
                st.rerun()
            else:
                st.warning("Upiši tekst zadatka.")

with col_odabrano:
    st.subheader(f"2. Odabrani zadaci ({len(st.session_state.odabrani)})")

    with st.expander("📁 Predlošci testova (spremi/učitaj gotov odabir)"):
        try:
            _predlosci_redovi = init_predlosci_ws().get_all_records()
        except Exception as _e:
            _predlosci_redovi = []
            st.caption(f"Ne mogu učitati predloške: {_e}")

        if _predlosci_redovi:
            _opcije_predlozaka = {
                f"{r.get('naziv') or '(bez naziva)'} — {r.get('broj_zadataka', '?')} zad., "
                f"{r.get('datum_spremanja', '')}": r
                for r in _predlosci_redovi
            }
            _odabrani_naziv_predloska = st.selectbox(
                "Postojeći predlošci", list(_opcije_predlozaka.keys()), key="predlozak_odabir"
            )
            _pcol1, _pcol2 = st.columns([1, 1])
            if _pcol1.button("📂 Učitaj predložak"):
                _r = _opcije_predlozaka[_odabrani_naziv_predloska]
                _ucitaj_stanje(
                    _r.get("sadrzaj_json", ""), _r.get("naslov_dokumenta", ""),
                    _r.get("tip_dokumenta", ""), _r.get("prikazi_rjesenja", ""),
                )
                st.rerun()
            if _pcol2.button("🗑️ Obriši predložak"):
                _r = _opcije_predlozaka[_odabrani_naziv_predloska]
                try:
                    _ws_pred = init_predlosci_ws()
                    _celija = _ws_pred.find(str(_r.get("predlozak_id", "")), in_column=1)
                    if _celija:
                        _ws_pred.delete_rows(_celija.row)
                    st.rerun()
                except Exception as _e:
                    st.error(f"Brisanje nije uspjelo: {_e}")
        else:
            st.caption("Još nema spremljenih predložaka.")

        st.divider()
        _novi_naziv_predloska = st.text_input("Naziv za spremanje trenutnog odabira", key="novi_naziv_predloska")
        if st.button("💾 Spremi trenutni odabir kao predložak", disabled=not st.session_state.odabrani):
            if not _novi_naziv_predloska.strip():
                st.warning("Upiši naziv predloška.")
            else:
                try:
                    _ws_pred = init_predlosci_ws()
                    _postojeci_idjevi = [
                        int(r.get("predlozak_id") or 0) for r in _ws_pred.get_all_records()
                        if str(r.get("predlozak_id", "")).strip().isdigit()
                    ]
                    _novi_id = (max(_postojeci_idjevi) + 1) if _postojeci_idjevi else 1
                    _stanje = _stanje_za_spremanje(
                        st.session_state.get("naslov_dok", ""),
                        st.session_state.get("tip_dok_sel", ""),
                        st.session_state.get("prikazi_rjesenja_cb", True),
                    )
                    _ws_pred.append_row([
                        str(_novi_id), _novi_naziv_predloska.strip(),
                        datetime.datetime.now().strftime("%d.%m.%Y. %H:%M"),
                        _stanje["naslov_dokumenta"], _stanje["tip_dokumenta"],
                        str(_stanje["prikazi_rjesenja"]), str(_stanje["broj_zadataka"]),
                        _stanje["sadrzaj_json"],
                    ])
                    st.success(f"Predložak „{_novi_naziv_predloska.strip()}” spremljen.")
                    st.rerun()
                except Exception as _e:
                    st.error(f"Spremanje nije uspjelo: {_e}")

    if not st.session_state.odabrani:
        st.info("Još nema odabranih zadataka — dodaj ih s lijeve strane.")

    # Redoslijed preko brojeva pozicija (15.9.2026., UX prijedlog - stavka 2) - dopuna
    # uz postojeće ⬆️/⬇️ strelice (ostaju, za brzo fino-podešavanje za 1 mjesto), korisno
    # kad treba premjestiti zadatak npr. s pozicije 2 na poziciju 15 u dužoj listi bez
    # 13 uzastopnih klikova. Isti obrazac (broj pozicije + gumb "Primijeni") kao stranica
    # "Redoslijed zadataka po potpoglavlju" u baza_zadataka_app.py - stabilno sortiranje,
    # izvorni indeks kao tie-breaker kod jednakih upisanih pozicija.
    _nove_pozicije = []

    for idx, z in enumerate(st.session_state.odabrani):
        if "kategorije" not in z:
            z["kategorije"] = {}
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**Zadatak {idx + 1}** · izvor: {z['izvor']}")
                st.markdown(
                    (z["tekst"][:220] + "…") if len(z["tekst"]) > 220 else z["tekst"]
                )
                if z.get("tip_zadatka") == "visestruki_izbor" and z.get("ponudjeni_odgovori"):
                    st.markdown(prikazi_opcije_markdown(z["ponudjeni_odgovori"]))
                    z["prikazi_opcije"] = st.checkbox(
                        "Prikaži ponuđene odgovore (A/B/C/D) za ovaj zadatak",
                        value=z.get("prikazi_opcije", True), key=f"mc_prikazi_{idx}",
                    )
                if z.get("slika_putanja"):
                    _slika_bytes = dohvati_sliku_bytes(z["slika_putanja"])
                    if _slika_bytes:
                        st.image(_slika_bytes, width=220)
                    else:
                        st.warning(f"⚠️ Slika '{z['slika_putanja']}' nije pronađena na Driveu.")
                z["bodovi"] = st.text_input("Bodovi", value=z["bodovi"], key=f"bod_{idx}")

                st.caption("Kategorije vrednovanja (može više odjednom, bodovi po kategoriji):")
                kat_cols = st.columns(3)
                for kcol, (kod, naziv) in zip(kat_cols, KATEGORIJE_INFO):
                    with kcol:
                        odabrano_kat = st.checkbox(
                            kod, value=kod in z["kategorije"],
                            key=f"kat_{kod}_{idx}", help=naziv,
                        )
                        if odabrano_kat:
                            z["kategorije"][kod] = st.text_input(
                                f"Bodovi ({kod})", value=z["kategorije"].get(kod, ""),
                                key=f"katbod_{kod}_{idx}", label_visibility="collapsed",
                                placeholder="bod.",
                            )
                        else:
                            z["kategorije"].pop(kod, None)

                # Kompaktan, UVIJEK vidljiv status zbroja (15.9.2026., UX prijedlog -
                # stavka 6) - prije se poruka prikazivala SAMO kad je zbroj neispravan
                # (i.f. na klik "Generiraj PDF"), pa profesor nije imao NIKAKVU potvrdu
                # da je zbroj već ispravan dok ga ručno ne izbroji ili ne pokuša
                # generirati PDF. Sad je status vidljiv odmah, u sva tri stanja
                # (nedostaju bodovi zadatka / neispravno / uskladeno). Stvarno
                # BLOKIRANJE generiranja PDF-a i dalje radi provjeri_zbroj_kategorija()
                # niže, pozvana na klik "Generiraj PDF" - ovo je samo prikaz uživo.
                if z["kategorije"]:
                    if not str(z["bodovi"]).strip():
                        st.caption("➖ Upiši ukupne bodove zadatka da provjerim zbroj po kategorijama.")
                    else:
                        try:
                            zbroj_kat = sum(
                                broj_iz_stringa(v) for v in z["kategorije"].values() if str(v).strip()
                            )
                            ukupno_zad = broj_iz_stringa(z["bodovi"])
                            if abs(zbroj_kat - ukupno_zad) > 1e-9:
                                st.caption(
                                    f"❌ Zbroj po kategorijama: {zbroj_kat:g} / {ukupno_zad:g} bod. — "
                                    f"generiranje PDF-a blokirano dok se ne uskladi."
                                )
                            else:
                                st.caption(f"✅ Zbroj po kategorijama: {zbroj_kat:g} / {ukupno_zad:g} bod.")
                        except ValueError:
                            st.caption("❌ Bodovi po kategoriji moraju biti brojevi.")
            with c2:
                _nove_pozicije.append(st.number_input(
                    "Poz.", min_value=1, max_value=len(st.session_state.odabrani),
                    value=idx + 1, step=1, key=f"pozicija_{idx}",
                    label_visibility="collapsed",
                    help="Nova pozicija - upiši broj i klikni 'Primijeni novi redoslijed' ispod liste.",
                ))
                if st.button("⬆️", key=f"up_{idx}", disabled=(idx == 0)):
                    pomakni(idx, -1)
                    st.rerun()
                if st.button("⬇️", key=f"down_{idx}", disabled=(idx == len(st.session_state.odabrani) - 1)):
                    pomakni(idx, 1)
                    st.rerun()
                if st.button("🗑️", key=f"del_{idx}"):
                    ukloni(idx)
                    st.rerun()

    if len(st.session_state.odabrani) > 1:
        if st.button("🔀 Primijeni novi redoslijed (prema upisanim pozicijama)", key="tb_primijeni_redoslijed"):
            _parovi = list(zip(_nove_pozicije, range(len(st.session_state.odabrani)), st.session_state.odabrani))
            _parovi.sort(key=lambda p: (p[0], p[1]))  # stabilno: izvorni indeks kao tie-breaker
            st.session_state.odabrani = [z for _, _, z in _parovi]
            st.rerun()

st.divider()

# ---------------------------------------------------------------
# 3. Metapodaci + generiranje
# ---------------------------------------------------------------

st.subheader("3. Metapodaci i generiranje")

mc1, mc2, mc3 = st.columns(3)
naslov = mc1.text_input("Naslov dokumenta", value="Test — Kvadratna jednadžba", key="naslov_dok")
datum = mc2.date_input("Datum", value=datetime.date.today())
tip_dok = mc3.selectbox("Tip dokumenta", TIP_DOKUMENTA_OPCIJE, key="tip_dok_sel")

je_test = tip_dok == "Pisana provjera znanja"
ukupno_bodova = ""
if je_test:
    # Popravak 14.9.2026. (§25.11): stari zbroj (`int(...)` + `.isdigit()`) je TIHO
    # preskakao svaki zadatak s praznim, decimalnim (npr. "2,5") ili na bilo koji drugi
    # način neispravnim upisom bodova - profesor nije imao NIKAKAV signal da prikazani
    # zbroj ne uključuje sve zadatke. Sad koristi isti broj_iz_stringa (podržava
    # decimalni zarez, isto kao provjera kategorija) PLUS eksplicitno upozorenje koji
    # točno zadaci nemaju valjan broj bodova, umjesto tihog izostavljanja iz zbroja.
    _zbroj_bodova = 0.0
    _bez_bodova = []
    for _i_bod, _z_bod in enumerate(st.session_state.odabrani, start=1):
        _sirovo_bod = str(_z_bod.get("bodovi", "")).strip()
        if not _sirovo_bod:
            _bez_bodova.append((_i_bod, _z_bod.get("id") or "ručni zadatak"))
            continue
        try:
            _zbroj_bodova += broj_iz_stringa(_sirovo_bod)
        except ValueError:
            _bez_bodova.append((_i_bod, _z_bod.get("id") or "ručni zadatak"))
    ukupno_bodova = f"{_zbroj_bodova:g}" if st.session_state.odabrani else ""
    st.caption(f"Ukupno bodova (automatski zbroj): **{ukupno_bodova or '—'}**")
    if _bez_bodova:
        st.warning(
            f"⚠️ {len(_bez_bodova)} zadatak(a) NEMA upisan valjan broj bodova pa NIJE uračunat "
            "u zbroj iznad: " + ", ".join(f"Zadatak {_i} ({_zid})" for _i, _zid in _bez_bodova)
            + ". Provjeri polje 'Bodovi' uz svaki zadatak u koloni '2. Odabrani zadaci' prije generiranja."
        )

prikazi_rjesenja = st.checkbox("Uključi rješenja na kraju dokumenta", value=True, key="prikazi_rjesenja_cb")
st.caption(
    "💡 Prikaz ponuđenih odgovora (A/B/C/D) za višestruki izbor, kategorije vrednovanja "
    "(UZV/RP/MK) i bodovi uređuju se **po zadatku** — vidi kontrole uz svaki zadatak u "
    "koloni '2. Odabrani zadaci' gore."
)

# Gruba procjena broja stranica (§25.11, 14.9.2026.) — NIJE točan broj (stvaran
# raspored ovisi o pdflatexu), samo orijentir PRIJE čekanja na kompajliranje.
# Kalibrirano na empirijski nalaz iz §25 (13 mix zadataka ≈ 2 stranice sa
# zaglavljem/rješenjima) — "težina" po zadatku raste za dulji tekst, sliku i broj
# ponuđenih odgovora.
if st.session_state.odabrani:
    _tezina_ukupno = 0.0
    for _z_proc in st.session_state.odabrani:
        _t = 1.0
        if len(_z_proc.get("tekst", "") or "") > 250:
            _t += 0.5
        if _z_proc.get("slika_putanja"):
            _t += 1.0
        if _z_proc.get("tip_zadatka") == "visestruki_izbor":
            _t += 0.15 * len(_z_proc.get("ponudjeni_odgovori") or [])
        _tezina_ukupno += _t
    _str_zadaci = max(1, math.ceil(_tezina_ukupno / 6.5))
    _str_rjesenja = max(1, math.ceil(len(st.session_state.odabrani) / 15)) if prikazi_rjesenja else 0
    _tekst_procjene = f"📄 Gruba procjena: ~{_str_zadaci} str. zadataka"
    if _str_rjesenja:
        _tekst_procjene += f" + ~{_str_rjesenja} str. rješenja"
    st.caption(_tekst_procjene + " — stvarni PDF (nakon kompajliranja) može odstupati.")

# ---------------------------------------------------------------
# Autospremanje nacrta (§25.11, 14.9.2026.) — štiti od gubitka rada ako se
# Streamlit sesija resetira (istek, hard refresh) dok profesor slaže test.
# Sprema SAMO kad se sadržaj stvarno promijenio od zadnjeg spremanja (usporedba
# hasha), ne na svaki rerun (npr. otvaranje/zatvaranje expandera) - da se ne
# troši Sheets write-kvota nepotrebno (v. §12 CAKI_MASTER_BAZA, dokumentiran
# presedan 429 grešaka kod prevelikog broja pisanja u minuti). Greška u pisanju
# se tiho guta - autospremanje NIKAD ne smije prekinuti profesorov rad.
# ---------------------------------------------------------------

if st.session_state.odabrani:
    _draft_stanje = _stanje_za_spremanje(naslov, tip_dok, prikazi_rjesenja)
    _draft_potpis = hashlib.sha256(_draft_stanje["sadrzaj_json"].encode("utf-8")).hexdigest()
    if st.session_state.get("_draft_zadnji_potpis") != _draft_potpis:
        try:
            _ws_draft = init_draft_ws()
            _draft_redak = [
                "trenutni", datetime.datetime.now().strftime("%d.%m.%Y. %H:%M"),
                _draft_stanje["naslov_dokumenta"], _draft_stanje["tip_dokumenta"],
                str(_draft_stanje["prikazi_rjesenja"]), str(_draft_stanje["broj_zadataka"]),
                _draft_stanje["sadrzaj_json"],
            ]
            if len(_ws_draft.get_all_values()) < 2:
                _ws_draft.append_row(_draft_redak)
            else:
                _ws_draft.update(range_name="A2:G2", values=[_draft_redak])
            st.session_state["_draft_zadnji_potpis"] = _draft_potpis
        except Exception:
            pass

dodaj_mamac = st.checkbox(
    "➕ Dodaj mamac opciju svim zadacima višestrukog izbora "
    "(npr. \"Ništa od navedenog\") — primjenjuje se na sve odjednom",
)
mamac_tekst = "Ništa od navedenog"
if dodaj_mamac:
    mamac_tekst = st.text_input("Tekst mamac opcije", value=mamac_tekst)


def formatiraj_opciju(opcija):
    """Baza sprema ponudjeni_odgovori kao ČIST LaTeX BEZ $...$ omotača kad je
    opcija matematika (npr. "\\frac{1}{(2 a-1)^{3}}") - PreTeXt build ih sam
    omata. Ali OPREZ: neke opcije su čist tekst bez ikakve matematike (npr.
    "trostrana piramida" kod zadataka o geometrijskim tijelima) - te NE SMIJU
    u $...$, jer LaTeX matematički način rada IGNORIRA razmake među riječima
    (postalo bi "trostranapiramida", bez razmaka - stvarni bug koji smo vidjeli).

    Razlikovanje: ako opcija sadrži LaTeX naredbu ili math-specifičan znak
    (\\, ^, _) → tretiramo kao čistu matematiku, omatamo u $...$ BEZ escapiranja
    (escapiranje bi razbilo \\frac{...}). Inače → čist tekst, ide kroz
    escape_outside_math (čuva razmake, escapira posebne znakove poput %/&)."""
    opcija = opcija.strip()
    if "$" in opcija:
        # Već ima $ (npr. profesor ručno upisao "$x=1$" u ad-hoc polje po
        # uputi u sučelju) - slobodan tekst s ugrađenom matematikom.
        return escape_outside_math(opcija)
    if re.search(r"[\\^_]", opcija):
        # Sadrži LaTeX naredbu (\frac, \sqrt...) ili ^ / _ - čista matematika.
        return f"${opcija}$"
    # Obični tekst bez ikakve matematike - NE omatati u $...$.
    return escape_outside_math(opcija)


def izgradi_opcije_blok(ponudjeni_odgovori):
    """Gradi LaTeX za prikaz ponuđenih odgovora (A/B/C/D...) ispod teksta zadatka,
    kao PRIRODAN tok teksta (ne fiksna tablica/popis) - LaTeX sam odlučuje hoće
    li sve stati u jedan redak (kompaktno, štedi papir) ili prelomiti na više
    redaka. Radi za BILO KOJI broj opcija (2, 3, 4, 5, 6+) - važno jer dodatak
    "Ništa od navedenog" (vidi dodaj_nista_od_navedenog niže) može gurnuti
    zadatak koji je već imao 5 opcija na 6.
    VAŽNO: ovaj blok se NE smije propuštati kroz escape_outside_math kao cjelina -
    dodaje se NAKON escapiranja teksta zadatka, jer sadrži prave LaTeX naredbe
    (\\textbf, \\quad...), a ne slobodni tekst profesora. Svaka POJEDINA opcija
    se obrađuje zasebno preko formatiraj_opciju() (vidi gore)."""
    slova = ["A", "B", "C", "D", "E", "F", "G", "H"]
    opcije = [formatiraj_opciju(o) for o in ponudjeni_odgovori if o.strip()]
    if not opcije:
        return ""
    dijelovi = [f"\\textbf{{{slova[j]})}}~{opc}" for j, opc in enumerate(opcije)]
    return "\n\\par\\vspace{3mm}\n\\noindent " + "\\quad ".join(dijelovi) + "\\par"


def izgradi_tex(zadaci_odabrani, ukljuci_rjesenja, slike_bytes=None, dodaj_mamac=False, mamac_tekst=""):
    slike_bytes = slike_bytes or {}
    zad_lines = []
    rjes_lines = []
    for i, z in enumerate(zadaci_odabrani, start=1):
        tekst = escape_outside_math(z["tekst"].strip())
        video = (z["video_url"] or "").strip()
        bodovi = (z["bodovi"] or "").strip() if je_test else ""
        tip_z = (z.get("tip_zadatka") or "").strip()
        kategorije_tex = izgradi_kategorije_tex(z.get("kategorije") or {})

        if z.get("prikazi_opcije", True) and z.get("tip_zadatka") == "visestruki_izbor" and z.get("ponudjeni_odgovori"):
            # Lokalna kopija (ne diramo spremljeni z["ponudjeni_odgovori"]) - mamac
            # se dodaje samo za OVO generiranje, profesor ga može uključiti/isključiti
            # za sljedeći test bez da je "zapečen" u odabranom zadatku.
            opcije_za_prikaz = list(z["ponudjeni_odgovori"])
            if dodaj_mamac and mamac_tekst.strip():
                opcije_za_prikaz.append(mamac_tekst.strip())
            tekst += izgradi_opcije_blok(opcije_za_prikaz)

        putanja = z.get("slika_putanja")
        slika_rel = f"images/{putanja}" if putanja and slike_bytes.get(putanja) else ""
        zad_lines.append(
            f"\\zadatakbod{{{tekst}}}{{{video}}}{{{bodovi}}}{{{slika_rel}}}{{{tip_z}}}{{{kategorije_tex}}}"
        )
        zad_lines.append("")
        if ukljuci_rjesenja:
            rjesenje_raw = str(z.get("rjesenje") or "").strip()
            konacan_raw = str(z.get("konacan_odgovor") or "").strip()
            if rjesenje_raw or konacan_raw:
                rjesenje_tex = escape_outside_math(rjesenje_raw) if rjesenje_raw else "\\textit{Puni postupak nije unesen u bazu.}"
                konacan_tex = escape_outside_math(konacan_raw)
            else:
                rjesenje_tex = "\\textit{Rješenje se dodaje naknadno.}"
                konacan_tex = ""
            rjes_lines.append(f"\\rjesenje{{{i}}}{{{rjesenje_tex}}}{{{konacan_tex}}}")
            rjes_lines.append("")
    return "\n".join(zad_lines), "\n".join(rjes_lines)


def broj_dolara(text):
    """Broji '$' znakove koji NISU escapirani (\\$) - koristi se za provjeru
    parnosti prije slanja u LaTeX. Neparan broj = zadatak će razbiti kompajliranje.

    NAPOMENA (15.9.2026.): neka polja (konacan_odgovor, rjesenje) znaju stići kao
    broj (int/float) umjesto string - stari kod (`text or ""`) je takvu vrijednost
    slao izravno u re.findall, što baca TypeError. str() to ispravlja bez obzira
    na tip; None i prazan string i dalje daju 0."""
    return len(re.findall(r"(?<!\\)\$", str(text) if text is not None else ""))


def pronadji_neuparene_dolare(zadaci_odabrani):
    """Vraća listu (index, opis, polje, tekst) za zadatke gdje BILO KOJE polje
    koje ide u LaTeX (tekst, rješenje, konačan odgovor, ponuđene opcije) ima
    neparan broj $ znakova - najčešći uzrok pucanja kompajliranja."""
    problemi = []
    for i, z in enumerate(zadaci_odabrani, start=1):
        zid = z.get("id") or "ručni zadatak"
        polja_za_provjeru = [
            ("tekst zadatka", z.get("tekst", "")),
            ("rješenje", z.get("rjesenje", "")),
            ("konačan odgovor", z.get("konacan_odgovor", "")),
        ]
        for j, opcija in enumerate(z.get("ponudjeni_odgovori") or []):
            slovo = ["A", "B", "C", "D", "E", "F", "G", "H"][j] if j < 8 else str(j + 1)
            polja_za_provjeru.append((f"opcija {slovo}", opcija))
        for naziv_polja, sadrzaj in polja_za_provjeru:
            if broj_dolara(sadrzaj) % 2 != 0:
                problemi.append((i, zid, naziv_polja, sadrzaj))
    return problemi


def provjeri_zbroj_kategorija(zadaci_odabrani):
    """BLOKIRAJUĆA provjera (dogovoreno 25.8.2026.): za svaki zadatak koji ima
    BAREM JEDNU čekiranu kategoriju, zbroj bodova po kategorijama MORA točno
    odgovarati polju 'Bodovi' tog zadatka - inače se PDF ne generira. Zadaci
    BEZ ijedne dodijeljene kategorije se ne provjeravaju (kategorizacija je i
    dalje opcionalna po zadatku, samo je zbroj obavezan KAD SE koristi).
    Vraća listu (index, id_zadatka, poruka) - prazna lista = sve u redu."""
    problemi = []
    for i, z in enumerate(zadaci_odabrani, start=1):
        kategorije = z.get("kategorije") or {}
        if not kategorije:
            continue
        zid = z.get("id") or "ručni zadatak"

        neispravno = []
        zbroj = 0.0
        for kod, bod in kategorije.items():
            try:
                zbroj += broj_iz_stringa(bod)
            except ValueError:
                neispravno.append(kod)
        if neispravno:
            problemi.append((i, zid, f"nedostaju/neispravni bodovi za kategorije: {', '.join(neispravno)}"))
            continue

        try:
            ukupno_zad = broj_iz_stringa(z.get("bodovi", ""))
        except ValueError:
            problemi.append((i, zid, "zadatak ima dodijeljene kategorije, ali polje 'Bodovi' nije valjan broj"))
            continue

        if abs(zbroj - ukupno_zad) > 1e-9:
            problemi.append(
                (i, zid, f"zbroj bodova po kategorijama ({zbroj:g}) ne odgovara bodovima zadatka ({ukupno_zad:g})")
            )
    return problemi


if st.button("🖨️ Generiraj PDF", type="primary", disabled=not st.session_state.odabrani):
    problemi = pronadji_neuparene_dolare(st.session_state.odabrani)
    if problemi:
        st.error(
            f"❌ {len(problemi)} zadatak(a) ima neparan broj `$` znakova u tekstu — "
            f"to sigurno razbija kompajliranje. Ispravi ih (ovdje ili izravno u bazi) "
            f"i pokušaj ponovno:"
        )
        for idx, zid, polje, tekst in problemi:
            st.markdown(f"**Zadatak {idx}** (`{zid}`) — polje *{polje}*:")
            st.code(tekst, language="text")
        st.stop()

    problemi_kat = provjeri_zbroj_kategorija(st.session_state.odabrani)
    if problemi_kat:
        st.error(
            f"❌ {len(problemi_kat)} zadatak(a) ima neusklađen zbroj bodova po kategorijama "
            f"s ukupnim bodovima zadatka — zbroj MORA odgovarati. Ispravi i pokušaj ponovno:"
        )
        for idx, zid, poruka in problemi_kat:
            st.markdown(f"**Zadatak {idx}** (`{zid}`) — {poruka}")
        st.stop()

    # Prvo dohvati slike (bajtove) za sve zadatke koji ih trebaju - MORA biti
    # prije izgradi_tex(), da znamo koje slike stvarno postoje na Driveu i ne
    # referenciramo u LaTeX-u datoteku koje neće biti u temp folderu (što bi
    # bacilo "File not found" i srušilo cijelo kompajliranje).
    slike_bytes = {}
    nedostaju_slike = []
    for z in st.session_state.odabrani:
        putanja = z.get("slika_putanja")
        if putanja and putanja not in slike_bytes:
            _bytes = dohvati_sliku_bytes(putanja)
            slike_bytes[putanja] = _bytes
            if not _bytes:
                nedostaju_slike.append(putanja)
    if nedostaju_slike:
        st.warning(
            f"⚠️ {len(nedostaju_slike)} slika nije pronađena na Driveu (nastavljam bez njih): "
            + ", ".join(nedostaju_slike)
        )

    zadaci_tex, rjesenja_tex = izgradi_tex(
        st.session_state.odabrani, prikazi_rjesenja, slike_bytes, dodaj_mamac, mamac_tekst
    )

    rjesenja_sekcija = ""
    if prikazi_rjesenja:
        rjesenja_sekcija = (
            "\\newpage\n"
            "{\\color{MathSecondary}\\sffamily\\bfseries\\Large Rješenja}\\par\n"
            "\\vspace{2mm}\\hrule height 1pt \\color{MathSecondary}\\vspace{4mm}\n"
            "\\input{generated/rjesenja_body}"
        )

    kraj_oznaka = KRAJ_OZNAKA_PO_TIPU.get(tip_dok, "KRAJ")

    # Zbroj bodova po kategoriji PREKO SVIH odabranih zadataka - ako je barem
    # jedna kategorija ikad korištena, zaglavlje testa prikazuje "Ostvareno"/
    # "Ocjena" PO KATEGORIJI umjesto jednog cjelokupnog zbroja/ocjene (dogovoreno
    # 25.8.2026., v. §25 CAKI_MASTER_BAZA). Samo za tip "Test" - kod radnog
    # listića se ništa ne ocjenjuje, kao ni dosadašnji {{UKUPNO_BODOVA}}.
    kategorije_redovi_tex = ""
    if je_test:
        ukupno_po_kategoriji = {}
        for z in st.session_state.odabrani:
            for kod, bod in (z.get("kategorije") or {}).items():
                try:
                    ukupno_po_kategoriji[kod] = ukupno_po_kategoriji.get(kod, 0) + broj_iz_stringa(bod)
                except ValueError:
                    pass  # provjeri_zbroj_kategorija() gore već bi ovo blokirala prije nego stignemo ovdje
        kategorije_redovi_tex = izgradi_kategorije_redovi(ukupno_po_kategoriji)

    with open(os.path.join(TEMPLATE_DIR, "main_test_template.tex"), encoding="utf-8") as f:
        main_tex = f.read()
    main_tex = (
        main_tex
        .replace("{{NASLOV}}", escape_outside_math(naslov))
        .replace("{{DATUM}}", datum.strftime("%d.%m.%Y."))
        .replace("{{TIP}}", tip_dok)
        .replace("{{UKUPNO_BODOVA}}", ukupno_bodova)
        .replace("{{KATEGORIJE_REDOVI}}", kategorije_redovi_tex)
        .replace("{{KRAJ_OZNAKA}}", kraj_oznaka)
        .replace("{{RJESENJA_SEKCIJA}}", rjesenja_sekcija)
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "generated"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "images"), exist_ok=True)
        with open(os.path.join(tmpdir, "main.tex"), "w", encoding="utf-8") as f:
            f.write(main_tex)
        with open(os.path.join(tmpdir, "generated", "zadaci_body.tex"), "w", encoding="utf-8") as f:
            f.write(zadaci_tex)
        with open(os.path.join(tmpdir, "generated", "rjesenja_body.tex"), "w", encoding="utf-8") as f:
            f.write(rjesenja_tex)
        with open(os.path.join(TEMPLATE_DIR, "caki-style.sty"), encoding="utf-8") as f:
            style_content = f.read()
        with open(os.path.join(tmpdir, "caki-style.sty"), "w", encoding="utf-8") as f:
            f.write(style_content)

        # Slike su već dohvaćene gore (prije izgradi_tex) - ovdje ih samo pišemo
        # na disk za pdflatex, bez ponovnog Drive API poziva.
        for putanja, _bytes in slike_bytes.items():
            if _bytes:
                with open(os.path.join(tmpdir, "images", putanja), "wb") as f:
                    f.write(_bytes)

        with st.spinner("Kompajliram PDF..."):
            ok = True
            log_tail = ""
            for _ in range(2):  # dva prolaza (breakable okviri, fancyhdr)
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                    cwd=tmpdir, capture_output=True, text=True, timeout=60,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode != 0:
                    ok = False
                    log_tail = "\n".join(result.stdout.splitlines()[-40:])
                    break

        if not ok:
            st.error("Kompajliranje nije uspjelo. Najčešći uzrok: neuparen `$` u tekstu zadatka.")
            st.code(log_tail, language="text")
        else:
            pdf_path = os.path.join(tmpdir, "main.pdf")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            st.success("PDF generiran!")
            st.download_button(
                "⬇️ Preuzmi PDF", data=pdf_bytes,
                file_name=f"{naslov.replace(' ', '_')}.pdf", mime="application/pdf",
            )
