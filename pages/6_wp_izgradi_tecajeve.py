"""
CAKI — Izgradi WP tečajeve po cjelini (admin alat)

Cilj (dogovoreno s Cakijem 27.9.2026.): NOVA, zasebna struktura na WP-u, paralelna
postojećim agregatnim "Matura A/B razina" tečajevima (koji ostaju kakvi jesu, rade po
drugom principu - sekcije, sve cjeline zajedno). Ovdje: JEDAN WP tečaj = JEDNA cjelina
iz šifrarnika (npr. "Realni brojevi"), a lekcije unutar njega = potpoglavlja te cjeline
(npr. Skupovi, Prirodni i cijeli brojevi, Racionalni brojevi...) - BEZ vidljivih sekcija,
isto kao 1 Google Classroom = 1 cjelina (postojeći monetizacijski model).

KAKO JE OTKRIVEN OVAJ FORMAT (27.9.2026.):
MasterStudy REST API (v2) ima rute za kreiranje (`courses/create`,
`.../curriculum/section`, `.../curriculum/material`), ali OPTIONS introspekcija ne
otkriva shemu (plugin ne registrira WP args, parsira JSON ručno) - format je utvrđen
kroz stvarni test: Caki je ručno kroz Course Builder UI napravio testni tečaj "Realni
brojevi" (course_id 7623) s jednom lekcijom "Skupovi brojeva" BEZ da je sam dodavao
sekciju - UI je ipak automatski napravio sekciju (id 92, title: "") jer je sekcija
OBAVEZAN spremnik u modelu podataka, ali prazan naslov znači da se vizualno ne vidi -
točno ono što treba za "bez sekcija" izgled. GET /courses/7623/curriculum je potvrdio
točan oblik: sections:[{id,title,order}], materials:[{id,title,post_id,post_type,
post_name,lesson_type,section_id,order}]. GET /lessons/7624 je otkrio da MasterStudy
SAM popuni default sadržaj lekcije kao `<p>{naslov lekcije}</p>` pri kreiranju (v.
je_prazan_sadrzaj u pages/5_wp_lekcije.py - ispravljeno da to prepozna kao prazno).

NAPOMENA — nesigurnost koja ostaje: uspješan odgovor na POST courses/create,
POST .../curriculum/section i POST .../curriculum/material NIJE viđen (samo su viđeni
422 error odgovori dok se tražio točan format zahtjeva) - funkcije niže pokušavaju
pročitati novi ID iz nekoliko mogućih oblika odgovora (`id`, `course_id`,
`course.id`, `data.id`...) i uvijek prikazuju SIROVI odgovor u aplikaciji, da se odmah
vidi ako pretpostavka ne odgovara stvarnosti. PRVI STVARNI TEST (izgradi ili dopuni
JEDNU cjelinu) treba napraviti pažljivo i odmah provjeriti rezultat u Course Builderu
i na živoj stranici prije nego se ponovi za sve ostale cjeline.

Isti principi kao pages/5_wp_lekcije.py: ista APP_PASSWORD lozinka, isti WP_URL/
WP_API_USER/WP_API_APP_PASSWORD secreti - ali ova stranica je namjerno SAMO za Caki-ja
(ADMIN_NAMES niže) jer stvara novi javni sadržaj (tečajeve), ne samo popunjava
postojeće lekcije.

IZMJENE 27.9.2026. (nakon što je SiteGround ticket 5139836 riješen - sgcaptcha/AI
Anti-Bot sustav isključen za cakipoduka.com, v. CAKI_MASTER_BAZA §32 - REST pozivi
sad prolaze bez mrežnog blokiranja):
  1. NOVO: podrška za "tečaj neobjavljen (draft)" - Caki je zatražio da novoizgrađeni
     tečajevi PO CJELINI ostanu neobjavljeni dok se ne popune stvarnim sadržajem.
     `kreiraj_tecaj()` sad šalje `status`/`post_status` u create body, i dodana je
     nova `postavi_status_tecaja()` (GET pa PUT flat na /courses/{id}/settings -
     ISTI potvrđeni obrazac kao u CAKI_matura_kalendar_embed dokumentu za course
     content/description) kao pouzdaniji backup poziv odmah nakon kreiranja, te kao
     zaseban gumb za VEĆ POSTOJEĆI tečaj (npr. 7623, kreiran ranije danas ručno kroz
     UI prije nego je ova funkcija postojala).
     ⚠️ NEPOTVRĐENO: točan naziv polja (`status` vs `post_status`) za MasterStudy
     course model nije bio moguće provjeriti uživo u trenutku pisanja - Browser pane
     sesija (koja bi to potvrdila preko GET/courses/{id}/settings s pravim nonce-om)
     odjavila se usred provjere, a cloud/device shell nemaju mrežni pristup do
     cakipoduka.com (nevezano za SiteGround - v. §32 - ovo je ORGANIZACIJSKI/sandbox
     egress allowlist, druga stvar). Funkcija šalje OBA kandidatska naziva odjednom
     (bezopasno - nepoznato polje se u pravilu samo ignorira) i UVIJEK prikazuje
     sirovi odgovor - PRVI STVARNI POZIV mora se provjeriti uživo (Course Builder +
     javna stranica tečaja) prije nego se na njega osloni za ostale cjeline.
  2. NOVO: nakon izgradnje/dopune tečaja, alat sad automatski postavlja `preview: true`
     na SVE lekcije tog tečaja u tom trenutku - ne samo na one koje je upravo sam
     kreirao u ovom pozivu, nego i na već postojeće (npr. lekcija "Skupovi brojeva",
     post_id 7624, kreirana ranije danas ručno) - ovo odgovara Cakijevom zahtjevu
     "sve lekcije da ih stavimo na pretpregled". Rezultat po lekciji (uspjeh/greška)
     sad se prikazuje eksplicitno umjesto da se greška tiho guta.
  ⚠️ OTVORENO, NIJE AUTOMATSKI RIJEŠENO OVIM PROLAZOM: postojeća lekcija "Skupovi
  brojeva" (post_id 7624) ima naziv koji se NE poklapa točno s nazivom potpoglavlja
  "Skupovi" iz Sifrarnik_potpoglavlja (v. napomena o exact-string matchingu niže u
  kodu) - multiselect je NEĆE automatski isključiti kao duplikat. Prije pokretanja
  izgradnje za cjelinu "Realni brojevi", ručno odznači "Skupovi" iz popisa (ili
  preimenuj postojeću lekciju u Course Builderu u točno "Skupovi") da se ne stvori
  duplikat.
"""

import json
import re
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth
import streamlit as st

from baza_zadataka_pipeline import (
    get_gspread_client,
    get_or_create_worksheet,
    get_sifrarnik_cjelina,
    get_potpoglavlja_po_cjelini,
)

st.set_page_config(page_title="CAKI — Izgradi WP tečajeve", page_icon="🏗️", layout="wide")


# ---------------------------------------------------------------
# Lozinka + admin provjera (ISTA APP_PASSWORD kao ostatak app-a)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_izgradi") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_izgradi"] = True
        else:
            st.session_state["autoriziran_izgradi"] = False

    if st.session_state.get("autoriziran_izgradi"):
        return True

    st.title("🏗️ CAKI — Izgradi WP tečajeve")
    st.text_input("Lozinka", type="password", key="lozinka_unos_izgradi", on_change=na_unos)
    if st.session_state.get("autoriziran_izgradi") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

ADMIN_NAMES = {"caki"}
st.sidebar.text_input("Tvoje ime", key="autor_ime_izgradi")
autor_ime = (st.session_state.get("autor_ime_izgradi") or "").strip()

if autor_ime.strip().lower() not in ADMIN_NAMES:
    st.warning("Ova stranica (kreiranje novih WP tečajeva) je samo za Caki-ja.")
    st.stop()


# ---------------------------------------------------------------
# WP auth + pomoćne funkcije
# ---------------------------------------------------------------

def wp_auth_iz_secreta():
    wp_url = st.secrets.get("WP_URL", "").rstrip("/")
    user = st.secrets.get("WP_API_USER", "")
    app_pw = st.secrets.get("WP_API_APP_PASSWORD", "")
    if not (wp_url and user and app_pw):
        return None, None
    return wp_url, HTTPBasicAuth(user, app_pw)


# Otkriveno 27.9.2026.: SiteGround WAF je prvo blokirao zadani "python-requests/x.x"
# User-Agent kao sumnjiv/bot. Kad smo ga zamijenili STATIČNIM Chrome UA stringom,
# SiteGround tehnicka podrska (ticket 5139836) je potvrdila da WAF BAS TAJ konkretan
# static Chrome/124.0.0.0 string prepoznaje kao potpis poznat po bot/scanner alatima
# i zato ga i dalje blokira. Njihova preporuka: koristiti CUSTOM, prepoznatljiv UA
# (ne pretvarati se da smo browser) - to WAF ne blokira.
WP_REQUEST_HEADERS = {
    "User-Agent": "CakiPodukaWPSync/1.0 (+https://cakipoduka.com; info@cakipoduka.com)"
}


_TRANSLIT = str.maketrans({
    "č": "c", "ć": "c", "đ": "dj", "š": "s", "ž": "z",
    "Č": "c", "Ć": "c", "Đ": "dj", "Š": "s", "Ž": "z",
})


def slugify(tekst: str) -> str:
    t = (tekst or "").translate(_TRANSLIT).lower().strip()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "tecaj"


def dohvati_kategorije(wp_url, auth):
    r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/course-categories", auth=auth, headers=WP_REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("categories", [])


def dohvati_curriculum(course_id, wp_url, auth) -> dict:
    r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum", auth=auth, headers=WP_REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def izvuci_id(data: dict, *kljucevi_kandidati):
    """Obrambeno vađenje novog ID-a iz odgovora nepoznatog oblika - proba nekoliko
    uobičajenih WP/MasterStudy konvencija redom."""
    for k in kljucevi_kandidati:
        if k in data and data[k]:
            return data[k]
    for omot in ("course", "section", "material", "data", "lesson"):
        unutra = data.get(omot)
        if isinstance(unutra, dict):
            for k in kljucevi_kandidati:
                if k in unutra and unutra[k]:
                    return unutra[k]
    return None


def kreiraj_tecaj(wp_url, auth, naslov, category_id, status=None):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/create"
    body = {"title": naslov, "slug": slugify(naslov), "category": [category_id]}
    if status:
        # Nepotvrđen naziv polja (v. napomena na vrhu datoteke) - šaljemo oba
        # kandidata, neiskorišteni se u pravilu samo ignorira.
        body["status"] = status
        body["post_status"] = status
    r = requests.post(url, auth=auth, json=body, headers=WP_REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return izvuci_id(data, "id", "course_id", "post_id"), data


def postavi_status_tecaja(wp_url, auth, course_id, status="draft"):
    """GET pa PUT flat na /courses/{id}/settings - isti potvrđeni obrazac kao za
    course content/description (v. CAKI_matura_kalendar_embed dokument). Backup/
    samostalan poziv za slučaj da courses/create ignorira status u create body-ju,
    i jedini put za tečaj koji već postoji (kreiran prije ove funkcije). NEPOTVRĐENO
    27.9.2026. da MasterStudy uopće poštuje jedno od ova dva polja - v. napomena na
    vrhu datoteke. Vraća (uspjeh: bool, sirovi_odgovor: dict) - poziv NIKAD ne baca
    iznimku dalje (status-postavljanje je "nice to have", ne smije prekinuti ostatak
    toka gradnje tečaja/lekcija) - pozivatelj odlučuje kako prikazati rezultat."""
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/settings"
    try:
        r = requests.get(url, auth=auth, headers=WP_REQUEST_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        course = data.get("course", data)
        course["status"] = status
        course["post_status"] = status
        r2 = requests.put(url, auth=auth, json=course, headers=WP_REQUEST_HEADERS, timeout=20)
        r2.raise_for_status()
        return True, r2.json()
    except requests.exceptions.RequestException as e:
        return False, {"error": str(e)}


def kreiraj_sekciju(wp_url, auth, course_id, naslov=""):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum/section"
    body = {"title": naslov, "order": 1}
    r = requests.post(url, auth=auth, json=body, headers=WP_REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return izvuci_id(data, "id", "section_id"), data


def kreiraj_lekciju(wp_url, auth, course_id, section_id, naslov, order):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum/material"
    body = {
        "title": naslov, "section_id": section_id, "lesson_type": "text",
        "type": "text", "order": order,
    }
    r = requests.post(url, auth=auth, json=body, headers=WP_REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    post_id = izvuci_id(data, "post_id")
    material_id = izvuci_id(data, "id", "material_id")
    return post_id, material_id, data


def postavi_preview(wp_url, auth, post_id):
    """Postavlja preview=true na lekciju. Vraća (uspjeh: bool, poruka: str) umjesto
    da baca iznimku - 27.9.2026. promijenjeno iz tihog "except: pass" jer je "sve
    lekcije u pretpregledu" sad eksplicitan zahtjev, ne samo nice-to-have, pa
    neuspjeh treba biti vidljiv Cakiju, ne tiho progutan."""
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/lessons/{post_id}"
    try:
        r = requests.get(url, auth=auth, headers=WP_REQUEST_HEADERS, timeout=20)
        r.raise_for_status()
        lesson = r.json().get("lesson", r.json())
        lesson["preview"] = True
        r2 = requests.put(url, auth=auth, json=lesson, headers=WP_REQUEST_HEADERS, timeout=20)
        r2.raise_for_status()
        return True, "ok"
    except requests.exceptions.RequestException as e:
        return False, str(e)


# ---------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------

TECAJ_MAPPING_HEADERS = [
    "cjelina", "potpoglavlje", "course_id", "course_naziv", "section_id",
    "lesson_post_id", "lesson_naziv", "status_sadrzaja", "datum_kreiranja",
]


@st.cache_resource
def init_sheet():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


sheet = init_sheet()
ws_tecajevi = get_or_create_worksheet(sheet, "WP_tecajevi_po_cjelini", TECAJ_MAPPING_HEADERS, rows=500)


@st.cache_data(ttl=120)
def ucitaj_tecajevi_mapping():
    rows = ws_tecajevi.get_all_values()[1:]
    po_cjelini = {}
    for r in rows:
        if not r or not r[0]:
            continue
        po_cjelini.setdefault(r[0].strip(), []).append(r)
    return po_cjelini


# ================================================================
# UI
# ================================================================

st.title("🏗️ CAKI — Izgradi WP tečajeve po cjelini")
st.caption(
    "Tečaj = cjelina iz šifrarnika, lekcije = potpoglavlja (bez vidljivih sekcija). "
    "Namjerno samo za Caki-ja - ovo stvara nove javne stranice na WP-u."
)

wp_url, auth = wp_auth_iz_secreta()
if not wp_url:
    st.error("WP_URL / WP_API_USER / WP_API_APP_PASSWORD nisu postavljeni u Secrets.")
    st.stop()

kategorija_po_cjelini = get_sifrarnik_cjelina(sheet)
potpoglavlja_po_cjelini = get_potpoglavlja_po_cjelini(sheet)
tecajevi_mapping = ucitaj_tecajevi_mapping()

sve_cjeline = sorted(potpoglavlja_po_cjelini.keys())
cjelina = st.selectbox("Cjelina", sve_cjeline, key="cjelina_izgradi")

vec_ima_redove = tecajevi_mapping.get(cjelina, [])
postojeci_course_id = ""
if vec_ima_redove:
    postojeci_course_id = vec_ima_redove[0][2]  # course_id iz prvog retka za tu cjelinu
    st.info(
        f"Ova cjelina već ima {len(vec_ima_redove)} zapisanih lekcija u mapiranju "
        f"(course_id {postojeci_course_id})."
    )

course_id_input = st.text_input(
    "Course ID (upiši ako tečaj za ovu cjelinu već postoji na WP-u, npr. iz ručnog testa "
    "- ostavi prazno da se kreira NOVI tečaj)",
    value=postojeci_course_id, key="course_id_izgradi",
)

postojeci_materijali = []
if course_id_input.strip():
    try:
        curr = dohvati_curriculum(course_id_input.strip(), wp_url, auth)
        postojeci_materijali = curr.get("materials", [])
        st.success(
            f"Pronađen postojeći tečaj (course_id {course_id_input}) - ima "
            f"{len(curr.get('sections', []))} sekcija i {len(postojeci_materijali)} lekcija."
        )
        with st.expander("Postojeće lekcije u tom tečaju"):
            for m in postojeci_materijali:
                st.write(f"- {m.get('title')} (post_id {m.get('post_id')})")
    except requests.exceptions.RequestException as e:
        st.error(f"Ne mogu dohvatiti course_id {course_id_input}: {e}")

kategorija_id = None
if not course_id_input.strip():
    try:
        kategorije = dohvati_kategorije(wp_url, auth)
        opcije_kat = {f"{k['name']} (id {k['id']})": k["id"] for k in kategorije}
        popis_kat = list(opcije_kat.keys())
        # 27.9.2026.: Caki potvrdio kategoriju za nove tečajeve "po cjelini" (matematika) -
        # "Instrukcije za srednju školu", id 26 (potvrđeno uživo preko javnog filtera na
        # /pripreme/ - checkbox name="category[]" value="26"). Samo default odabir u
        # dropdownu - Caki i dalje može ručno promijeniti za bilo koji drugi predmet/slučaj.
        default_index = next(
            (i for i, naziv in enumerate(popis_kat) if opcije_kat[naziv] == 26), 0
        )
        odabrana_kat = st.selectbox(
            "Kategorija (za matematičke cjeline: 'Instrukcije za srednju školu', id 26 - "
            "potvrđeno s Cakijem 27.9.2026. i predodabrano niže; promijeni ručno za drugi slučaj)",
            popis_kat, index=default_index, key="kategorija_izgradi",
        )
        kategorija_id = opcije_kat[odabrana_kat]
    except requests.exceptions.RequestException as e:
        st.error(f"Ne mogu dohvatiti kategorije: {e}")

postojeci_naslovi = {(m.get("title") or "").strip().lower() for m in postojeci_materijali}
potpoglavlja = [p for p, _ in potpoglavlja_po_cjelini.get(cjelina, [])]
pretpostavljeni_odabir = [p for p in potpoglavlja if p.strip().lower() not in postojeci_naslovi]

if len(pretpostavljeni_odabir) < len(potpoglavlja):
    st.caption(
        "Napomena: neka potpoglavlja su unaprijed isključena jer im NAZIV TOČNO odgovara "
        "postojećoj WP lekciji - provjeri ručno ako je stvarni naziv malo drukčiji "
        "(npr. 'Skupovi' u šifrarniku vs. 'Skupovi brojeva' na WP-u) da ne dupliciraš."
    )

odabrana_potpoglavlja = st.multiselect(
    "Potpoglavlja za kreirati kao nove lekcije (odznači ono što već postoji pod drugim nazivom)",
    potpoglavlja, default=pretpostavljeni_odabir, key="potpoglavlja_izgradi",
)

st.divider()

neobjavljen = st.checkbox(
    "Tečaj neobjavljen (draft) - eksperimentalno, 27.9.2026.: naziv polja koje MasterStudy "
    "stvarno poštuje NIJE potvrđen uživo (v. napomena na vrhu datoteke) - provjeri rezultat "
    "u Course Builderu/na javnoj stranici nakon prvog pokretanja",
    value=True, key="draft_izgradi",
)

if course_id_input.strip():
    if st.button("🔒 Postavi POSTOJEĆI tečaj (course_id gore) kao draft - bez diranja lekcija"):
        uspjeh, raw = postavi_status_tecaja(wp_url, auth, course_id_input.strip(), "draft")
        st.json(raw, expanded=False)
        if uspjeh:
            st.success("Poziv je prošao (HTTP 200) - provjeri uživo je li tečaj stvarno draft, jer polje nije unaprijed potvrđeno.")
        else:
            st.error("Poziv nije uspio - v. JSON iznad.")

if st.button("🏗️ Izgradi / dopuni tečaj", type="primary", disabled=not odabrana_potpoglavlja):
    course_id = course_id_input.strip()
    section_id = None
    rezultati = []

    with st.status("Radim...", expanded=True) as status_box:
        if not course_id:
            status_box.write(f"Kreiram novi tečaj '{cjelina}'...")
            try:
                course_id, raw = kreiraj_tecaj(wp_url, auth, cjelina, kategorija_id)
                st.json(raw, expanded=False)
            except requests.exceptions.RequestException as e:
                status_box.update(label="Greška pri kreiranju tečaja", state="error")
                st.error(f"Greška: {e}")
                st.stop()
            if not course_id:
                status_box.update(label="Nisam prepoznao course_id u odgovoru", state="error")
                st.error("Tečaj je možda kreiran, ali nisam uspio pročitati njegov ID iz odgovora (v. JSON iznad). Provjeri ručno u Course Builderu i upiši course_id gore da nastaviš.")
                st.stop()
            status_box.write(f"Tečaj kreiran: course_id {course_id}")
            if neobjavljen:
                status_box.write("Postavljam tečaj kao draft (backup poziv na /settings)...")
                uspjeh_draft, raw_draft = postavi_status_tecaja(wp_url, auth, course_id, "draft")
                st.json(raw_draft, expanded=False)
                if not uspjeh_draft:
                    status_box.write("⚠️ Draft-poziv nije uspio - tečaj je vjerojatno objavljen, postavi ručno u Course Builderu.")
        else:
            try:
                curr = dohvati_curriculum(course_id, wp_url, auth)
                sekcije = curr.get("sections", [])
                if sekcije:
                    section_id = sekcije[0].get("id")
            except requests.exceptions.RequestException as e:
                status_box.update(label="Greška pri dohvatu postojećeg tečaja", state="error")
                st.error(f"Greška: {e}")
                st.stop()

        if not section_id:
            status_box.write("Kreiram sekciju (prazan naziv - neće se vidjeti)...")
            try:
                section_id, raw = kreiraj_sekciju(wp_url, auth, course_id, "")
                st.json(raw, expanded=False)
            except requests.exceptions.RequestException as e:
                status_box.update(label="Greška pri kreiranju sekcije", state="error")
                st.error(f"Greška: {e}")
                st.stop()
            if not section_id:
                status_box.update(label="Nisam prepoznao section_id u odgovoru", state="error")
                st.error("Sekcija je možda kreirana, ali nisam uspio pročitati njen ID (v. JSON iznad). Provjeri ručno u Course Builderu.")
                st.stop()
            status_box.write(f"Sekcija: section_id {section_id}")

        for n, potpoglavlje in enumerate(odabrana_potpoglavlja, start=1):
            status_box.write(f"Kreiram lekciju '{potpoglavlje}'...")
            try:
                post_id, material_id, raw = kreiraj_lekciju(wp_url, auth, course_id, section_id, potpoglavlje, n)
            except requests.exceptions.RequestException as e:
                rezultati.append({"potpoglavlje": potpoglavlje, "status": f"GREŠKA: {e}"})
                continue
            if not post_id:
                rezultati.append({"potpoglavlje": potpoglavlje, "status": "kreirano, ali post_id nepoznat - v. JSON"})
                st.json(raw, expanded=False)
                continue
            ws_tecajevi.append_row([
                cjelina, potpoglavlje, str(course_id), cjelina, str(section_id),
                str(post_id), potpoglavlje, "prazno", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ])
            rezultati.append({"potpoglavlje": potpoglavlje, "status": f"✅ kreirano (post_id {post_id})"})

        # 27.9.2026.: nakon izgradnje/dopune, postavi preview:true na SVE lekcije
        # ovog tečaja u ovom trenutku - ne samo one koje je OVAJ poziv kreirao, nego
        # i već postojeće (npr. lekcije napravljene ranije ručno kroz Course Builder,
        # v. napomena na vrhu datoteke o "Skupovi brojeva"/post_id 7624). Odgovara
        # Cakijevom zahtjevu "sve lekcije da ih stavimo na pretpregled".
        status_box.write("Postavljam pretpregled (preview) na sve lekcije ovog tečaja...")
        preview_rezultati = []
        try:
            svi_materijali = dohvati_curriculum(course_id, wp_url, auth).get("materials", [])
        except requests.exceptions.RequestException as e:
            svi_materijali = []
            status_box.write(f"⚠️ Ne mogu ponovno dohvatiti curriculum za pregled pretpregleda: {e}")
        for m in svi_materijali:
            pid = m.get("post_id")
            if not pid:
                continue
            uspjeh_prev, poruka_prev = postavi_preview(wp_url, auth, pid)
            preview_rezultati.append({
                "lekcija": m.get("title"), "post_id": pid,
                "pretpregled": "✅" if uspjeh_prev else f"❌ {poruka_prev}",
            })

        status_box.update(label="Gotovo.", state="complete")

    ucitaj_tecajevi_mapping.clear()
    st.subheader("Rezultat — nove/dopunjene lekcije")
    st.dataframe(rezultati)
    if preview_rezultati:
        st.subheader("Rezultat — pretpregled (preview) na svim lekcijama tečaja")
        st.dataframe(preview_rezultati)
        neuspjesi = [p for p in preview_rezultati if "❌" in str(p["pretpregled"])]
        if neuspjesi:
            st.warning(f"{len(neuspjesi)} lekcija/a nije uspjelo postaviti pretpregled - v. tablicu iznad, provjeri ručno u Course Builderu.")
    if course_id:
        st.success(
            f"Provjeri uživo: https://www.cakipoduka.com/user-account-2/edit-course/{course_id}/curriculum/"
        )
