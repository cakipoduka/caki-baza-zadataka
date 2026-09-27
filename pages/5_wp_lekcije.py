"""
CAKI — WP Lekcije (teaser sadržaj za MasterStudy)

Stranica za suradnike/Caki-ja: generira 1-3 primjera zadatka iz baze (Zadaci sheet) za
odabranu cjelinu, u istom vizualnom stilu kao PreTeXt (statement/rješenje kutije),
pretvara $...$ u [katex]...[/katex] (WP KaTeX plugin shortcode - NE renderira $...$
izravno, potvrđeno 27.9.2026.), prikazuje pravi vizualni pretpregled (KaTeX renderiran
unutar aplikacije) i vodi radni tok Skica -> Poslano na provjeru -> Objavljeno.

RADNI TOK (dogovoreno 27.9.2026.):
- Svi (suradnici i Caki) rade "Nova lekcija" i šalju na provjeru.
- Objava je UVIJEK preko Caki-ja (v. ADMIN_NAMES niže) - suradnici ne mogu sami
  objaviti, samo poslati na provjeru.
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
  WP_lekcije_mapping   - cjelina -> WP course/lesson post_id (popuni ručno za
                          postojeće tečajeve, ili aplikacija sama zapamti ako upišeš
                          post_id ručno prvi put uz kvačicu "Zapamti mapiranje")
  WP_lekcije_workflow  - povijest svih poslanih/objavljenih lekcija sa statusima
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
    st.sidebar.warning("Upiši svoje ime prije slanja na provjeru.")


# ---------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------

WORKFLOW_HEADERS = [
    "workflow_id", "lesson_post_id", "cjelina", "course_naziv", "autor",
    "datum_kreiranja", "zadaci_id_csv", "sadrzaj_html", "status",
    "napomena_review", "datum_objave",
]
MAPPING_HEADERS = ["cjelina", "potpoglavlje", "course_id", "course_naziv", "lesson_post_id", "lesson_naziv"]


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


# ---------------------------------------------------------------
# WP objava (Application Password - v. napomena na vrhu datoteke)
# ---------------------------------------------------------------

def objavi_lekciju_na_wp(lesson_post_id: str, html_sadrzaj: str) -> tuple:
    """Vraća (uspjeh: bool, poruka: str). GET pa PUT natrag CIJELI lesson objekt
    (isti GET+PUT obrazac kao /courses/{id}/settings - v. learnings-and-workflow.md) -
    NEPOTVRĐENO izvana za /lessons/ endpoint, prvi test raditi oprezno na jednoj lekciji."""
    wp_url = st.secrets.get("WP_URL", "").rstrip("/")
    user = st.secrets.get("WP_API_USER", "")
    app_pw = st.secrets.get("WP_API_APP_PASSWORD", "")
    if not (wp_url and user and app_pw):
        return False, "WP_URL / WP_API_USER / WP_API_APP_PASSWORD nisu postavljeni u Secrets."

    lessons_url = f"{wp_url}/wp-json/masterstudy-lms/v2/lessons/{lesson_post_id}"
    auth = HTTPBasicAuth(user, app_pw)
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


# ================================================================
# UI
# ================================================================

st.title("📄 CAKI — WP Lekcije (teaser sadržaj)")
st.caption("Generiraj primjere zadataka iz baze za WP lekciju, pošalji na provjeru ili objavi.")

nazivi_tabova = ["✍️ Nova lekcija"]
if je_admin:
    nazivi_tabova.append("🔎 Na čekanju (objava)")
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
        st.success(
            f"WP lekcija: **{info_mapiranja.get('course_naziv') or '(bez naziva)'}** "
            f"→ post_id {info_mapiranja['lesson_post_id']}"
        )
        lesson_post_id = info_mapiranja["lesson_post_id"]
    else:
        st.warning("Ova cjelina još nema zapisano mapiranje na WP lekciju.")
        lesson_post_id = st.text_input("WP lesson post_id (ručno, iz Course Buildera)", key="rucni_post_id")
        if lesson_post_id and st.checkbox("Zapamti ovo mapiranje za sljedeći put", key="zapamti_mapping"):
            ws_mapping.append_row([cjelina, "", "", "", lesson_post_id, ""])
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

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Pošalji na provjeru", type="primary", disabled=not autor_ime):
                workflow_id = f"wf_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                ws_workflow.append_row([
                    workflow_id, lesson_post_id, cjelina,
                    (info_mapiranja or {}).get("course_naziv", ""),
                    autor_ime, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    st.session_state.get("generirani_zadaci_id", ""), uredjeni_html,
                    "Poslano na provjeru", "", "",
                ])
                st.success("Poslano na provjeru.")
                st.session_state.pop("generirani_html", None)

        with col2:
            if je_admin and lesson_post_id:
                if st.button("✅ Objavi odmah (preskače provjeru)"):
                    uspjeh, poruka = objavi_lekciju_na_wp(lesson_post_id, uredjeni_html)
                    if uspjeh:
                        st.success(poruka)
                        st.session_state.pop("generirani_html", None)
                    else:
                        st.error(poruka)

# ---------------- TAB 2: Na čekanju (samo admin) ----------------
if je_admin:
    with tab_objekti[1]:
        redovi_wf = ws_workflow.get_all_values()
        headers_wf = redovi_wf[0] if redovi_wf else WORKFLOW_HEADERS
        idx_wf = {h: i for i, h in enumerate(headers_wf)}
        na_cekanju = [
            (broj_retka, r) for broj_retka, r in enumerate(redovi_wf[1:], start=2)
            if get_polje(r, idx_wf, "status") == "Poslano na provjeru"
        ]
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
                lesson_id = get_polje(r, idx_wf, "lesson_post_id")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Objavi", key=f"objavi_{broj_retka}"):
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
