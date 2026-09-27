"""
CAKI — WP Lekcije (teaser sadržaj za MasterStudy)

Stranica za suradnike/Caki-ja: generira primjere zadataka iz baze (Zadaci sheet) za
odabranu cjelinu, u istom vizualnom stilu kao PreTeXt (statement/rješenje kutije),
pretvara $...$ u [katex]...[/katex] (WP KaTeX plugin shortcode - NE renderira $...$
izravno, potvrđeno 27.9.2026.), prikazuje pravi vizualni pretpregled (KaTeX renderiran
unutar aplikacije) i vodi radni tok Skica -> Poslano na provjeru -> Odobreno -> Objavljeno
(dogovoreno s Cakijem 27.9.2026., v. WORKFLOW_HEADERS i UI niže).

RADNI TOK (dogovoreno 27.9.2026., ažurirano isti dan na 4 eksplicitna statusa):
- Svi (suradnici i Caki) rade "Nova lekcija": biraju zadatke IZ CIJELE cjeline (nema
  automatskog filtriranja - profesor sam prosuđuje što je pogodno, v. ⭐ oznaka samo
  kao pomoć, ne kao ograničenje), generiraju HTML, vide pravi vizualni pretpregled.
- "💾 Spremi kao skicu" - sprema trenutni rad (status "Skica") bez slanja na provjeru,
  da se profesor može vratiti kasnije (v. "Moje skice" niže na istom tabu).
- "📤 Pošalji na provjeru" - status "Poslano na provjeru".
- Objava je UVIJEK preko Caki-ja (v. ADMIN_NAMES niže) - suradnici ne mogu sami
  objaviti. Caki u tabu "Na čekanju" prvo "✅ Odobri" (status "Odobreno") ili
  "↩️ Vrati s napomenom" (status "Odbijeno"), pa zasebno "🚀 Objavi" na već odobrenima
  (status "Objavljeno"). Caki jedini ima i prečac "Objavi odmah" u tabu 1 koji
  preskače sve međukorake izravno na "Objavljeno" (i dalje se bilježi u Sheet).
- Ovo je SOFT (workflow) provjera po upisanom imenu, NE lozinka - stranica koristi
  ISTU APP_PASSWORD lozinku za sve (suradnici/profesori već imaju pristup Test
  Builderu s istom lozinkom, pa nema smisla izolirati baš ovu stranicu). Prava
  (hard) razdvojenost pristupa po osobi tražila bi puni per-professor login sustav
  (v. roadmap §16 - dogovoren, ali nije građen) - namjerno se ne gradi ovdje.
- Objava ide preko WP REST API-ja s Application Password (v. objavi_lekciju_na_wp
  niže), NE preko browser nonce/cookie sesije (ta metoda radi samo kad Claude sam
  klika kroz Course Builder u Browser pane-u - ovdje je server bez prijavljene
  sesije). TOČAN oblik PUT tijela za /lessons/{id} NIJE još potvrđen izvana (rađeno
  po analogiji na GET+PUT pattern koji je potvrđen za /courses/{id}/settings) -
  PRVI STVARNI TEST treba napraviti pažljivo na jednoj lekciji, uz provjeru na
  živoj stranici odmah nakon.

NOVO 27.9.2026. — automatsko otkrivanje WP lekcija (tab "🔄 Sinkroniziraj s WP-om"):
Umjesto da Caki ručno priprema popis cjelina/post_id-eva, aplikacija sama povlači
curriculum s WP-a (GET /courses/{id}/curriculum, pa GET /lessons/{post_id} za svaku
da provjeri je li sadržaj još prazan placeholder ili već popunjen) i upisuje/ažurira
WP_lekcije_mapping - uključujući status_sadrzaja ("prazno"/"popunjeno"), tako da se
odmah vidi koje lekcije još trebaju sadržaj. Treba samo upisati course ID-eve (isti
Application Password kao za objavu, samo GET pozivi - nerizično). Naslov WP lekcije se
matcha na cjelinu SAMO ako se nazivi točno poklapaju (potvrđeno da je to čest slučaj -
"Kvadratna jednadžba", "Realni brojevi" itd.) - nepoklopljeni naslovi se prikažu
označeni "(NEPREPOZNATO: ...)" da ih Caki ručno pridruži.

POTREBNI NOVI SECRETS (Streamlit → Settings → Secrets), uz postojeće:
  WP_URL               = "https://www.cakipoduka.com"
  WP_API_USER           = korisničko ime WP korisnika kreiranog za objavu
                           (npr. novi korisnik "streamlit-publisher", rola Author/Editor
                           - NE administrator, po principu najmanjih ovlasti)
  WP_API_APP_PASSWORD   = Application Password tog korisnika - WP Admin → Korisnici →
                           (klikni korisnika) → Profil → "Aplikacijske lozinke" →
                           upiši naziv (npr. "Streamlit WP Lekcije") → Add New
                           Application Password. WP je prikaže SAMO JEDNOM - kopiraj
                           odmah u Secrets, ne može se kasnije ponovno vidjeti (samo
                           obrisati i napraviti novu).

NOVI SHEET TABOVI (auto-kreiraju se sami pri prvom pokretanju, isti obrazac kao
Teorija_potpoglavlja - v. get_or_create_worksheet u baza_zadataka_pipeline.py):
  WP_lekcije_mapping   - cjelina -> WP course/lesson post_id + status_sadrzaja
  WP_lekcije_workflow  - povijest svih skica/poslanih/objavljenih lekcija sa statusima
"""

import json
import re
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth
import streamlit as st
import streamlit.components.v1 as components

from baza_zadataka_pipeline import get_gspread_client, get_or_create_worksheet

st.set_page_config(page_title="CAKI — WP Lekcije", page_icon="📄", layout="wide")


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao pages/2_test_builder.py - ISTA APP_PASSWORD)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_wp") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_wp"] = True
        else:
            st.session_state["autoriziran_wp"] = False

    if st.session_state.get("autoriziran_wp"):
        return True

    st.title("📄 CAKI — WP Lekcije")
    st.text_input("Lozinka", type="password", key="lozinka_unos_wp", on_change=na_unos)
    if st.session_state.get("autoriziran_wp") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------
# Tko si ti? (SOFT identifikacija - odlučuje prikazuje li se admin/objava dio.
# Nije sigurnosna granica, v. napomena na vrhu datoteke.)
# ---------------------------------------------------------------

ADMIN_NAMES = {"caki"}  # dodaj ovdje još imena (malim slovima) ako još netko smije izravno objavljivati

st.sidebar.text_input("Tvoje ime (za evidenciju u radnom toku)", key="autor_ime")
autor_ime = (st.session_state.get("autor_ime") or "").strip()
je_admin = autor_ime.strip().lower() in ADMIN_NAMES

if not autor_ime:
    st.sidebar.warning("Upiši svoje ime prije spremanja/slanja.")


# ---------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------

WORKFLOW_HEADERS = [
    "workflow_id", "lesson_post_id", "cjelina", "course_naziv", "autor",
    "datum_kreiranja", "zadaci_id_csv", "sadrzaj_html", "status",
    "napomena_review", "datum_objave",
]
MAPPING_HEADERS = [
    "cjelina", "potpoglavlje", "course_id", "course_naziv", "lesson_post_id",
    "lesson_naziv", "status_sadrzaja", "zadnja_provjera_wp",
]


def col_letter(headers: list, col_name: str) -> str:
    """Slovo stupca (A, B, C...) za dani naziv u danoj listi headera - vrijedi do 26
    stupaca, dovoljno za oba nova taba ovdje."""
    return chr(ord("A") + headers.index(col_name))


@st.cache_resource
def init_sheet():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


sheet = init_sheet()
ws_zadaci = sheet.worksheet("Zadaci")
ws_workflow = get_or_create_worksheet(sheet, "WP_lekcije_workflow", WORKFLOW_HEADERS, rows=1000)
ws_mapping = get_or_create_worksheet(sheet, "WP_lekcije_mapping", MAPPING_HEADERS, rows=200)


@st.cache_data(ttl=300)
def ucitaj_zadatke():
    all_values = ws_zadaci.get_all_values()
    headers = all_values[0]
    idx = {h: i for i, h in enumerate(headers)}
    return idx, all_values[1:]


@st.cache_data(ttl=300)
def ucitaj_mapiranje():
    rows = ws_mapping.get_all_values()[1:]
    mapiranje = {}
    for r in rows:
        if len(r) < 1 or not r[0]:
            continue
        mapiranje[r[0].strip()] = {
            "potpoglavlje": r[1].strip() if len(r) > 1 else "",
            "course_id": r[2].strip() if len(r) > 2 else "",
            "course_naziv": r[3].strip() if len(r) > 3 else "",
            "lesson_post_id": r[4].strip() if len(r) > 4 else "",
            "lesson_naziv": r[5].strip() if len(r) > 5 else "",
            "status_sadrzaja": r[6].strip() if len(r) > 6 else "",
            "zadnja_provjera_wp": r[7].strip() if len(r) > 7 else "",
        }
    return mapiranje


def get_polje(row, idx, col):
    i = idx.get(col)
    return row[i] if i is not None and i < len(row) else ""


# ---------------------------------------------------------------
# HTML generiranje (isti vizualni stil kao PreTeXt statement/solution kutije)
# ---------------------------------------------------------------

def dollar_u_katex(tekst: str) -> str:
    """$...$ -> [katex]...[/katex] (WP KaTeX plugin shortcode)."""
    return re.sub(r"\$([^$]+?)\$", r"[katex]\1[/katex]", tekst or "")


def izgradi_lekciju_html(cjelina: str, ukupno_zadataka: int, odabrani_zadaci: list) -> str:
    """odabrani_zadaci: lista dictova {id, tekst, rjesenje, konacan_odgovor}."""
    dijelovi = [
        f'<p>Evo {len(odabrani_zadaci)} od {ukupno_zadataka} zadataka iz cjeline '
        f'&quot;{cjelina}&quot;, s punim rješenjem:</p>',
        "",
    ]
    for n, z in enumerate(odabrani_zadaci, start=1):
        dijelovi.append(
            '<div style="border:1px solid #dbe3ea;border-left:4px solid #2563EB;'
            'padding:12px 16px;margin:16px 0 0;background:#f8fafc;">\n'
            f"<p><strong>Zadatak {n}</strong><br>\n{dollar_u_katex(z['tekst'])}</p>\n</div>"
        )
        rjesenje_dio = (
            f"<strong>Rješenje:</strong><br>\n{dollar_u_katex(z['rjesenje'])}<br>\n"
            if (z.get("rjesenje") or "").strip() else ""
        )
        odgovor_dio = (
            f"<strong>Odgovor:</strong> {dollar_u_katex(z['konacan_odgovor'])}"
            if (z.get("konacan_odgovor") or "").strip() else ""
        )
        dijelovi.append(
            '<div style="border:1px solid #dbe3ea;border-left:4px solid #0D9488;'
            'padding:12px 16px;margin:0 0 24px;background:#f0fdfa;">\n'
            f"<p>{rjesenje_dio}{odgovor_dio}</p>\n</div>"
        )
    dijelovi.append(
        "<p>Puni pristup — teorija, video rješenja i vježbe za sve potpoglavlja — "
        "dostupan je kroz CAKI Classroom.</p>"
    )
    return "\n".join(dijelovi)


def html_za_pretpregled(html_katex: str) -> str:
    """[katex]/[/katex] -> \\( \\) (KaTeX auto-render standardni delimiteri) SAMO za
    pretpregled unutar aplikacije - u bazi/na WP-u ostaje shortcode oblik."""
    return html_katex.replace("[katex]", r"\(").replace("[/katex]", r"\)")


def prikazi_pretpregled(html_katex: str, height: int = 500):
    html_doc = f"""
    <html><head>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"></script>
    <style>body{{font-family:sans-serif;font-size:15px;line-height:1.5;padding:8px;}}</style>
    </head><body>
    <div id="sadrzaj">{html_za_pretpregled(html_katex)}</div>
    <script>
      renderMathInElement(document.getElementById("sadrzaj"), {{
        delimiters: [{{left: "\\\\(", right: "\\\\)", display: false}}]
      }});
    </script>
    </body></html>
    """
    components.html(html_doc, height=height, scrolling=True)


def wp_auth_iz_secreta():
    wp_url = st.secrets.get("WP_URL", "").rstrip("/")
    user = st.secrets.get("WP_API_USER", "")
    app_pw = st.secrets.get("WP_API_APP_PASSWORD", "")
    if not (wp_url and user and app_pw):
        return None, None
    return wp_url, HTTPBasicAuth(user, app_pw)


# ---------------------------------------------------------------
# WP objava (Application Password - v. napomena na vrhu datoteke)
# ---------------------------------------------------------------

def objavi_lekciju_na_wp(lesson_post_id: str, html_sadrzaj: str) -> tuple:
    """Vraća (uspjeh: bool, poruka: str). GET pa PUT natrag CIJELI lesson objekt
    (isti GET+PUT obrazac kao /courses/{id}/settings - v. learnings-and-workflow.md) -
    NEPOTVRĐENO izvana za /lessons/ endpoint, prvi test raditi oprezno na jednoj lekciji."""
    wp_url, auth = wp_auth_iz_secreta()
    if not wp_url:
        return False, "WP_URL / WP_API_USER / WP_API_APP_PASSWORD nisu postavljeni u Secrets."

    lessons_url = f"{wp_url}/wp-json/masterstudy-lms/v2/lessons/{lesson_post_id}"
    try:
        r = requests.get(lessons_url, auth=auth, timeout=20)
        r.raise_for_status()
        data = r.json()
        lesson = data.get("lesson", data)
        lesson["content"] = html_sadrzaj
        lesson["preview"] = True
        r2 = requests.put(lessons_url, auth=auth, json=lesson, timeout=20)
        r2.raise_for_status()
        return True, "Objavljeno."
    except requests.exceptions.RequestException as e:
        odgovor = getattr(e, "response", None)
        detalj = odgovor.text[:500] if odgovor is not None else str(e)
        return False, f"Greška pri objavi: {detalj}"


def upisi_workflow_red(lesson_post_id, cjelina, course_naziv, autor, zadaci_id_csv, sadrzaj_html, status):
    workflow_id = f"wf_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    ws_workflow.append_row([
        workflow_id, lesson_post_id, cjelina, course_naziv, autor,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), zadaci_id_csv, sadrzaj_html,
        status, "", datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "Objavljeno" else "",
    ])


# ---------------------------------------------------------------
# WP sinkronizacija/otkrivanje (curriculum GET - v. napomena na vrhu datoteke)
# ---------------------------------------------------------------

PRAZAN_SADRZAJ_UZORCI = {"", "<p>.</p>", "<p></p>", "."}


def je_prazan_sadrzaj(html: str, naslov: str = "") -> bool:
    """Prazno = ništa, generički placeholder, ILI MasterStudyjev auto-placeholder pri
    kreiranju lekcije - potvrđeno 27.9.2026. (test-lekcija 'Skupovi brojeva' je nakon
    kreiranja imala sadržaj TOČNO '<p>Skupovi brojeva</p>', dulje od 20 znakova pa bi
    prošlo staru provjeru kao 'popunjeno' - lažni negativ, ovdje ispravljeno)."""
    h = (html or "").strip()
    if h in PRAZAN_SADRZAJ_UZORCI or len(h) < 20:
        return True
    if naslov and h.lower() == f"<p>{naslov.strip().lower()}</p>":
        return True
    return False


def dohvati_course_naslov(course_id: str, wp_url: str, auth) -> str:
    try:
        r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/settings", auth=auth, timeout=20)
        r.raise_for_status()
        course = r.json().get("course", {})
        return course.get("post_title") or course.get("title") or ""
    except requests.exceptions.RequestException:
        return ""


def dohvati_curriculum(course_id: str, wp_url: str, auth) -> list:
    r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/courses/{course_id}/curriculum", auth=auth, timeout=20)
    r.raise_for_status()
    return r.json().get("materials", [])


def dohvati_lesson_sadrzaj(post_id, wp_url: str, auth) -> str:
    r = requests.get(f"{wp_url}/wp-json/masterstudy-lms/v2/lessons/{post_id}", auth=auth, timeout=20)
    r.raise_for_status()
    lesson = r.json().get("lesson", r.json())
    return lesson.get("content") or ""


def sinkroniziraj_course(course_id: str, wp_url: str, auth, poznate_cjeline: set) -> tuple:
    """Vraća (redovi_za_upsert, greske). Svaki redak odgovara MAPPING_HEADERS redoslijedu."""
    greske = []
    redovi = []
    course_naziv = dohvati_course_naslov(course_id, wp_url, auth)
    try:
        materijali = dohvati_curriculum(course_id, wp_url, auth)
    except requests.exceptions.RequestException as e:
        return [], [f"Course {course_id}: greška pri dohvatu curriculuma - {e}"]

    for m in materijali:
        post_id = m.get("post_id")
        naslov = (m.get("title") or "").strip()
        if not post_id:
            continue
        cjelina_pogodak = naslov if naslov in poznate_cjeline else f"(NEPREPOZNATO: {naslov})"
        try:
            sadrzaj = dohvati_lesson_sadrzaj(post_id, wp_url, auth)
            status_sadrzaja = "prazno" if je_prazan_sadrzaj(sadrzaj, naslov) else "popunjeno"
        except requests.exceptions.RequestException as e:
            status_sadrzaja = "greška pri dohvatu"
            greske.append(f"Lekcija {post_id} ({naslov}): {e}")
        redovi.append([
            cjelina_pogodak, "", course_id, course_naziv, str(post_id), naslov,
            status_sadrzaja, datetime.now().strftime("%Y-%m-%d %H:%M"),
        ])
    return redovi, greske


def upsert_mapping_redovi(redovi: list):
    """Ažurira postojeći redak (po lesson_post_id) ili dodaje novi, u WP_lekcije_mapping."""
    postojeci = ws_mapping.get_all_values()
    headers_map = postojeci[0] if postojeci else MAPPING_HEADERS
    idx_map = {h: i for i, h in enumerate(headers_map)}
    post_id_col = idx_map.get("lesson_post_id")
    postojeci_po_post_id = {}
    if post_id_col is not None:
        for broj, row in enumerate(postojeci[1:], start=2):
            if len(row) > post_id_col and row[post_id_col]:
                postojeci_po_post_id[row[post_id_col]] = broj

    for red in redovi:
        pid = red[4]  # lesson_post_id je 5. stupac u MAPPING_HEADERS
        if pid in postojeci_po_post_id:
            broj_retka = postojeci_po_post_id[pid]
            ws_mapping.update(f"A{broj_retka}:H{broj_retka}", [red])
        else:
            ws_mapping.append_row(red)


# ================================================================
# UI
# ================================================================

st.title("📄 CAKI — WP Lekcije (teaser sadržaj)")
st.caption("Generiraj primjere zadataka iz baze za WP lekciju, pošalji na provjeru ili objavi.")

nazivi_tabova = ["✍️ Nova lekcija", "🔄 Sinkroniziraj s WP-om"]
if je_admin:
    nazivi_tabova.append("🔎 Na čekanju (odobri/objavi)")
tab_objekti = st.tabs(nazivi_tabova)

# ---------------- TAB 1: Nova lekcija ----------------
with tab_objekti[0]:
    idx, redovi = ucitaj_zadatke()
    mapiranje = ucitaj_mapiranje()

    sve_cjeline = sorted({
        get_polje(r, idx, "cjelina").strip() for r in redovi if get_polje(r, idx, "cjelina").strip()
    })
    cjelina = st.selectbox("Cjelina", sve_cjeline, key="odabir_cjelina")

    info_mapiranja = mapiranje.get(cjelina)
    lesson_post_id = ""
    if info_mapiranja and info_mapiranja["lesson_post_id"]:
        oznaka_statusa = {
            "popunjeno": "⚠️ WP lekcija VEĆ IMA sadržaj - provjeri prije nego prepišeš",
            "prazno": "✅ WP lekcija je još prazna - slobodno popuni",
        }.get(info_mapiranja.get("status_sadrzaja", ""), "")
        st.success(
            f"WP lekcija: **{info_mapiranja.get('course_naziv') or '(bez naziva)'}** "
            f"→ post_id {info_mapiranja['lesson_post_id']}. {oznaka_statusa}"
        )
        lesson_post_id = info_mapiranja["lesson_post_id"]
    else:
        st.warning(
            "Ova cjelina još nema zapisano mapiranje na WP lekciju - koristi tab "
            "'🔄 Sinkroniziraj s WP-om' da ga aplikacija sama pronađe, ili upiši ručno:"
        )
        lesson_post_id = st.text_input("WP lesson post_id (ručno, iz Course Buildera)", key="rucni_post_id")
        if lesson_post_id and st.checkbox("Zapamti ovo mapiranje za sljedeći put", key="zapamti_mapping"):
            ws_mapping.append_row([cjelina, "", "", "", lesson_post_id, "", "", ""])
            ucitaj_mapiranje.clear()

    zadaci_cjeline = [r for r in redovi if get_polje(r, idx, "cjelina").strip() == cjelina]

    st.caption(
        f"Cjelina '{cjelina}' ima {len(zadaci_cjeline)} zadataka u bazi. "
        "Pregledaj i sam/sama odaberi koji su pogodni za objavu - aplikacija ne bira umjesto tebe."
    )
    upit = st.text_input(
        "🔍 Pretraga unutar cjeline (po ID-u ili tekstu zadatka)", key="pretraga_zadataka"
    )
    samo_oznaceni = st.checkbox(
        "Prikaži samo zadatke označene kao 'koristi_kao_primjer_na_satu'",
        value=False, key="samo_oznaceni_filtar",
    )

    prikaz_liste = zadaci_cjeline
    if samo_oznaceni:
        prikaz_liste = [
            r for r in prikaz_liste
            if get_polje(r, idx, "koristi_kao_primjer_na_satu").strip().lower() == "da"
        ]
    if upit.strip():
        u = upit.strip().lower()
        prikaz_liste = [
            r for r in prikaz_liste
            if u in get_polje(r, idx, "id").lower()
            or u in get_polje(r, idx, "tekst_zadatka_latex").lower()
        ]

    st.caption(f"Prikazano {len(prikaz_liste)} od {len(zadaci_cjeline)} zadataka (suzi pretragom/filtrom po potrebi).")

    def oznaci_zadatak_labelu(t):
        oznaka = "⭐ " if get_polje(t[1], idx, "koristi_kao_primjer_na_satu").strip().lower() == "da" else "　 "
        return f"{oznaka}#{t[0]} — {get_polje(t[1], idx, 'tekst_zadatka_latex')[:80]}..."

    opcije_zadataka = [(get_polje(r, idx, "id"), r) for r in prikaz_liste]
    odabrani = st.multiselect(
        "Odaberi zadatke za ovu lekciju (⭐ = već označen kao primjer na satu)",
        opcije_zadataka,
        format_func=oznaci_zadatak_labelu,
        key="odabir_zadataka",
    )

    if odabrani:
        zadaci_za_html = [
            {
                "id": t[0],
                "tekst": get_polje(t[1], idx, "tekst_zadatka_latex"),
                "rjesenje": get_polje(t[1], idx, "rjesenje"),
                "konacan_odgovor": get_polje(t[1], idx, "konacan_odgovor"),
            }
            for t in odabrani
        ]
        if st.button("🛠️ Generiraj HTML", key="generiraj_html"):
            st.session_state["generirani_html"] = izgradi_lekciju_html(
                cjelina, len(zadaci_cjeline), zadaci_za_html
            )
            st.session_state["generirani_zadaci_id"] = ",".join(z["id"] for z in zadaci_za_html)

    if st.session_state.get("generirani_html"):
        st.subheader("Uredi HTML prije slanja")
        uredjeni_html = st.text_area(
            "HTML sadržaj (uključuje [katex] shortcode)",
            value=st.session_state["generirani_html"], height=300, key="html_edit",
        )

        st.subheader("👁️ Vizualni pretpregled")
        prikazi_pretpregled(uredjeni_html)

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("💾 Spremi kao skicu", disabled=not autor_ime):
                upisi_workflow_red(
                    lesson_post_id, cjelina, (info_mapiranja or {}).get("course_naziv", ""),
                    autor_ime, st.session_state.get("generirani_zadaci_id", ""), uredjeni_html, "Skica",
                )
                st.success("Spremljeno kao skica.")
        with col2:
            if st.button("📤 Pošalji na provjeru", type="primary", disabled=not autor_ime):
                upisi_workflow_red(
                    lesson_post_id, cjelina, (info_mapiranja or {}).get("course_naziv", ""),
                    autor_ime, st.session_state.get("generirani_zadaci_id", ""), uredjeni_html,
                    "Poslano na provjeru",
                )
                st.success("Poslano na provjeru.")
                st.session_state.pop("generirani_html", None)
        with col3:
            if je_admin and lesson_post_id:
                if st.button("✅ Objavi odmah (preskače provjeru)"):
                    uspjeh, poruka = objavi_lekciju_na_wp(lesson_post_id, uredjeni_html)
                    if uspjeh:
                        upisi_workflow_red(
                            lesson_post_id, cjelina, (info_mapiranja or {}).get("course_naziv", ""),
                            autor_ime or "Caki", st.session_state.get("generirani_zadaci_id", ""),
                            uredjeni_html, "Objavljeno",
                        )
                        st.success(poruka)
                        st.session_state.pop("generirani_html", None)
                    else:
                        st.error(poruka)

    # --- Moje skice ---
    if autor_ime:
        redovi_wf_sve = ws_workflow.get_all_values()
        if redovi_wf_sve:
            headers_wf_sve = redovi_wf_sve[0]
            idx_wf_sve = {h: i for i, h in enumerate(headers_wf_sve)}
            moje_skice = [
                r for r in redovi_wf_sve[1:]
                if get_polje(r, idx_wf_sve, "status") == "Skica"
                and get_polje(r, idx_wf_sve, "autor").strip().lower() == autor_ime.lower()
            ]
            if moje_skice:
                st.divider()
                st.subheader(f"📝 Moje skice ({len(moje_skice)})")
                for r in moje_skice:
                    naslov_skice = (
                        f"{get_polje(r, idx_wf_sve, 'cjelina')} "
                        f"({get_polje(r, idx_wf_sve, 'datum_kreiranja')})"
                    )
                    with st.expander(naslov_skice):
                        st.code(get_polje(r, idx_wf_sve, "sadrzaj_html"), language="html")
                        st.caption("Kopiraj sadržaj gore natrag u polje za uređivanje iznad ako želiš nastaviti.")

# ---------------- TAB 2: Sinkroniziraj s WP-om ----------------
with tab_objekti[1]:
    st.write(
        "Upiši WP course ID-eve (odvojene zarezom, npr. `1678`) da aplikacija sama povuče "
        "popis lekcija s WP-a i provjeri koje već imaju sadržaj, a koje su još prazne. "
        "Ovo su samo GET pozivi (čitanje) - ništa se ne mijenja na živoj stranici."
    )
    course_ids_input = st.text_input("Course ID-evi", key="sync_course_ids", placeholder="npr. 1678")
    if st.button("🔄 Povuci s WP-a i osvježi mapiranje"):
        wp_url, auth = wp_auth_iz_secreta()
        if not wp_url:
            st.error("WP_URL / WP_API_USER / WP_API_APP_PASSWORD nisu postavljeni u Secrets.")
        else:
            idx_z, redovi_z = ucitaj_zadatke()
            poznate_cjeline = {
                get_polje(r, idx_z, "cjelina").strip() for r in redovi_z if get_polje(r, idx_z, "cjelina").strip()
            }
            svi_redovi, sve_greske = [], []
            course_id_lista = [c.strip() for c in course_ids_input.split(",") if c.strip()]
            for course_id in course_id_lista:
                redovi_course, greske_course = sinkroniziraj_course(course_id, wp_url, auth, poznate_cjeline)
                svi_redovi.extend(redovi_course)
                sve_greske.extend(greske_course)

            if sve_greske:
                st.error("\n".join(sve_greske))
            if svi_redovi:
                upsert_mapping_redovi(svi_redovi)
                ucitaj_mapiranje.clear()
                st.success(f"Ažurirano {len(svi_redovi)} lekcija iz {len(course_id_lista)} tečaja(eva).")
                st.dataframe(
                    [
                        {
                            "cjelina": r[0], "course_id": r[2], "course_naziv": r[3],
                            "lesson_post_id": r[4], "lesson_naziv": r[5], "status_sadrzaja": r[6],
                        }
                        for r in svi_redovi
                    ]
                )
            elif not sve_greske:
                st.info("Nema lekcija za prikazati (provjeri course ID).")

# ---------------- TAB 3: Na čekanju (samo admin) ----------------
if je_admin:
    with tab_objekti[2]:
        redovi_wf = ws_workflow.get_all_values()
        headers_wf = redovi_wf[0] if redovi_wf else WORKFLOW_HEADERS
        idx_wf = {h: i for i, h in enumerate(headers_wf)}

        na_cekanju = [
            (broj_retka, r) for broj_retka, r in enumerate(redovi_wf[1:], start=2)
            if get_polje(r, idx_wf, "status") == "Poslano na provjeru"
        ]
        odobreno = [
            (broj_retka, r) for broj_retka, r in enumerate(redovi_wf[1:], start=2)
            if get_polje(r, idx_wf, "status") == "Odobreno"
        ]

        st.subheader(f"🔎 Na čekanju provjere ({len(na_cekanju)})")
        if not na_cekanju:
            st.info("Nema stavki na čekanju.")
        for broj_retka, r in na_cekanju:
            naslov = (
                f"{get_polje(r, idx_wf, 'cjelina')} — poslao/la {get_polje(r, idx_wf, 'autor')} "
                f"({get_polje(r, idx_wf, 'datum_kreiranja')})"
            )
            with st.expander(naslov):
                sadrzaj = get_polje(r, idx_wf, "sadrzaj_html")
                prikazi_pretpregled(sadrzaj, height=400)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Odobri", key=f"odobri_{broj_retka}"):
                        ws_workflow.batch_update([
                            {"range": f"{col_letter(WORKFLOW_HEADERS, 'status')}{broj_retka}",
                             "values": [["Odobreno"]]},
                        ])
                        st.success("Odobreno - spremno za objavu niže.")
                        st.rerun()
                with c2:
                    napomena = st.text_input("Napomena (ako vraćaš)", key=f"napomena_{broj_retka}")
                    if st.button("↩️ Vrati s napomenom", key=f"vrati_{broj_retka}"):
                        ws_workflow.batch_update([
                            {"range": f"{col_letter(WORKFLOW_HEADERS, 'status')}{broj_retka}",
                             "values": [["Odbijeno"]]},
                            {"range": f"{col_letter(WORKFLOW_HEADERS, 'napomena_review')}{broj_retka}",
                             "values": [[napomena]]},
                        ])
                        st.success("Vraćeno suradniku.")
                        st.rerun()

        st.divider()
        st.subheader(f"🚀 Odobreno - spremno za objavu ({len(odobreno)})")
        if not odobreno:
            st.info("Nema odobrenih stavki koje čekaju objavu.")
        for broj_retka, r in odobreno:
            naslov = f"{get_polje(r, idx_wf, 'cjelina')} — odobreno, poslao/la {get_polje(r, idx_wf, 'autor')}"
            with st.expander(naslov):
                sadrzaj = get_polje(r, idx_wf, "sadrzaj_html")
                prikazi_pretpregled(sadrzaj, height=400)
                lesson_id = get_polje(r, idx_wf, "lesson_post_id")
                if st.button("🚀 Objavi", key=f"objavi_{broj_retka}"):
                    uspjeh, poruka = objavi_lekciju_na_wp(lesson_id, sadrzaj)
                    if uspjeh:
                        ws_workflow.batch_update([
                            {"range": f"{col_letter(WORKFLOW_HEADERS, 'status')}{broj_retka}",
                             "values": [["Objavljeno"]]},
                            {"range": f"{col_letter(WORKFLOW_HEADERS, 'datum_objave')}{broj_retka}",
                             "values": [[datetime.now().strftime('%Y-%m-%d %H:%M:%S')]]},
                        ])
                        st.success(poruka)
                        st.rerun()
                    else:
                        st.error(poruka)
