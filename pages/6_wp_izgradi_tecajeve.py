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


_TRANSLIT = str.maketrans({
    "č": "c", "ć": "c", "đ": "dj", "š": "s", "ž": "z",
    "Č": "c", "Ć": "c", "Đ": "dj", "Š": "s", "Ž": "z",
})


def slugify(tekst: str) -> str:
    t = (tekst or "").translate(_TRANSLIT).lower().strip()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "tecaj"


def dohvati_kategorije(wp_url, auth):
    r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/course-categories", auth=auth, timeout=20)
    r.raise_for_status()
    return r.json().get("categories", [])


def dohvati_curriculum(course_id, wp_url, auth) -> dict:
    r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum", auth=auth, timeout=20)
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


def kreiraj_tecaj(wp_url, auth, naslov, category_id):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/create"
    body = {"title": naslov, "slug": slugify(naslov), "category": [category_id]}
    r = requests.post(url, auth=auth, json=body, timeout=20)
    r.raise_for_status()
    data = r.json()
    return izvuci_id(data, "id", "course_id", "post_id"), data


def kreiraj_sekciju(wp_url, auth, course_id, naslov=""):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum/section"
    body = {"title": naslov, "order": 1}
    r = requests.post(url, auth=auth, json=body, timeout=20)
    r.raise_for_status()
    data = r.json()
    return izvuci_id(data, "id", "section_id"), data


def kreiraj_lekciju(wp_url, auth, course_id, section_id, naslov, order):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum/material"
    body = {
        "title": naslov, "section_id": section_id, "lesson_type": "text",
        "type": "text", "order": order,
    }
    r = requests.post(url, auth=auth, json=body, timeout=20)
    r.raise_for_status()
    data = r.json()
    post_id = izvuci_id(data, "post_id")
    material_id = izvuci_id(data, "id", "material_id")
    return post_id, material_id, data


def postavi_preview(wp_url, auth, post_id):
    url = f"{wp_url}/wp-json/masterstudy-lms/v2/lessons/{post_id}"
    r = requests.get(url, auth=auth, timeout=20)
    r.raise_for_status()
    lesson = r.json().get("lesson", r.json())
    lesson["preview"] = True
    r2 = requests.put(url, auth=auth, json=lesson, timeout=20)
    r2.raise_for_status()


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
        odabrana_kat = st.selectbox(
            "Kategorija (potrebna za NOVI tečaj - nijedna trenutna kategorija nije "
            "napravljena baš za ovaj tip 'tečaj po cjelini', odaberi privremeno najbližu)",
            list(opcije_kat.keys()), key="kategorija_izgradi",
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
            try:
                postavi_preview(wp_url, auth, post_id)
            except requests.exceptions.RequestException:
                pass  # nije kritično - profesor može kasnije ručno uključiti preview
            ws_tecajevi.append_row([
                cjelina, potpoglavlje, str(course_id), cjelina, str(section_id),
                str(post_id), potpoglavlje, "prazno", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ])
            rezultati.append({"potpoglavlje": potpoglavlje, "status": f"✅ kreirano (post_id {post_id})"})

        status_box.update(label="Gotovo.", state="complete")

    ucitaj_tecajevi_mapping.clear()
    st.subheader("Rezultat")
    st.dataframe(rezultati)
    if course_id:
        st.success(
            f"Provjeri uživo: https://www.cakipoduka.com/user-account-2/edit-course/{course_id}/curriculum/"
        )
