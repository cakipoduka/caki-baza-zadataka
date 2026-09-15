"""
CAKI Matematika - pages/3_teorija.py

IZMJENE (14.9.2026, u odnosu na prethodnu verziju):
  1. Dodane konvencije za pisanje u tekst_teorije_latex, obradjuje ih novi modul
     teorija_markup.py: !!isticanje!! , \\pojam{Naziv} , [RJESENJE]...[/RJESENJE]
  2. Pregled je sada DVOSTRUKI (Ucenik / Profesor) - koristi teorija_markup da Caki
     odmah vidi hoce li ucenik vidjeti rjesenje ili ne, PRIJE spremanja.
  3. Novo polje "Veza za vjezbanje" (veza_vjezbaj) - rucno zalijepljen link na
     praksa.cakipoduka.com za tu cjelinu/potpoglavlje, koristi se za "Vjezbaj ovo"
     poveznicu u PreTeXt izlazu.

VAZNO - PRIJE PRVOG KORISTENJA OVE VERZIJE:
  - U baza_zadataka_pipeline.py, TEORIJA_HEADERS MORA dobiti novi element "veza_vjezbaj"
    (redoslijed po zelji, npr. odmah iza "geogebra_material_id", prije "zadnja_izmjena").
  - U samom Google Sheetu, tab "Teorija_potpoglavlja" mora dobiti STUPAC s tocno istim
    nazivom zaglavlja "veza_vjezbaj" na istom mjestu kao u TEORIJA_HEADERS.
    Bez ovoga se novo polje NECE spremati (tiho ce se izgubiti pri snimanju).
  - teorija_markup.py mora biti u istom repou (uz baza_zadataka_pipeline.py).

Izvor teorije: direktan LaTeX paste (preporučeno, isti $...$ zapis kao u ostatku baze),
ILI upload PDF-a/slike -> Mathpix OCR kao POLAZNI predložak koji se OBAVEZNO pregleda/
uredi prije spremanja (OCR ovdje NIKAD ne sprema izravno, samo puni tekstualno polje).

Prikaz u PreTeXt izlazu (Korak 3.1): <introduction> na početku sekcije potpoglavlja,
prije <example>/<exercises> - vidi _build_introduction_lines u baza_zadataka_pipeline.py,
koja sada za sadrzaj paragrafa treba pozvati teorija_markup.teorija_u_ptx_odlomke() -
vidi UPUTA_integracija_teorija.md za tocan nacin.
"""
import json
from datetime import datetime

import streamlit as st

from baza_zadataka_pipeline import (
    _col_letter,
    TEORIJA_HEADERS,
    get_gspread_client,
    get_or_create_worksheet,
    get_potpoglavlja_po_cjelini,
    get_teorija_po_potpoglavlju,
    mathpix_ocr_datoteka,
)
from teorija_markup import ukloni_markup_za_pregled

st.set_page_config(page_title="CAKI Teorija", page_icon="📖", layout="wide")


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao u app.py i 2_test_builder.py)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_teorija") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_teorija"] = True
        else:
            st.session_state["autoriziran_teorija"] = False

    if st.session_state.get("autoriziran_teorija"):
        return True

    st.title("📖 CAKI Teorija po potpoglavlju")
    st.text_input("Lozinka", type="password", key="lozinka_unos_teorija", on_change=na_unos)
    if st.session_state.get("autoriziran_teorija") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------

@st.cache_resource
def init_sheet():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


@st.cache_data(ttl=3600)
def _ucitaj_sifrarnik_potpoglavlja():
    return get_potpoglavlja_po_cjelini(init_sheet())


@st.cache_data(ttl=60)
def _ucitaj_teoriju():
    return get_teorija_po_potpoglavlju(init_sheet())


def _teorija_worksheet():
    return get_or_create_worksheet(init_sheet(), "Teorija_potpoglavlja", TEORIJA_HEADERS)


def _spremi_teoriju(cjelina, potpoglavlje, tekst, video_url, geogebra_material_id, veza_vjezbaj):
    """Upisuje/ažurira TOČNO JEDAN redak za (cjelina, potpoglavlje) - traži postojeći
    redak po tom paru, ažurira ga preko batch_update ako postoji, inače dodaje novi."""
    ws = _teorija_worksheet()
    all_values = ws.get_all_values()
    headers = all_values[0] if all_values else TEORIJA_HEADERS
    idx = {h: i for i, h in enumerate(headers)}

    def get(row, col):
        i = idx.get(col)
        return row[i] if i is not None and i < len(row) else ""

    redak_broj = None
    for i, row in enumerate(all_values[1:], start=2):
        if get(row, "cjelina").strip() == cjelina and get(row, "potpoglavlje").strip() == potpoglavlje:
            redak_broj = i
            break

    vrijednosti = {
        "cjelina": cjelina,
        "potpoglavlje": potpoglavlje,
        "tekst_teorije_latex": tekst,
        "video_url": video_url,
        "geogebra_material_id": geogebra_material_id,
        "veza_vjezbaj": veza_vjezbaj,
        "zadnja_izmjena": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if redak_broj is None:
        ws.append_row([vrijednosti.get(h, "") for h in TEORIJA_HEADERS])
    else:
        azuriranja = [
            {"range": f"{_col_letter(h, headers=TEORIJA_HEADERS)}{redak_broj}", "values": [[vrijednosti.get(h, "")]]}
            for h in TEORIJA_HEADERS
        ]
        ws.batch_update(azuriranja)
    return redak_broj is None


# ---------------------------------------------------------------
# UI
# ---------------------------------------------------------------

st.title("📖 Teorija po potpoglavlju")
st.caption(
    "Jednokratni unos teorije koja se prikazuje na POČETKU svakog potpoglavlja u generiranom "
    "PreTeXt izlazu (prije primjera/vježbi) - kao `<introduction>` blok. Izmjene su rijetke "
    "(polugodišnje/godišnje) - ako ne diraš postojeći unos, PreTeXt build i dalje koristi "
    "zadnje spremljeno stanje bez ikakve dodatne akcije."
)

with st.expander("🖊️ Kako pisati teoriju (konvencije za tipkanje)"):
    st.markdown(
        """
Ovo su tri oznake koje možeš koristiti izravno u tekstu ispod, slobodno kombinirane:

- `!!vazan tekst ili formula!!` — istaknuto (npr. crvenom bojom) u konačnom izlazu.
- `\\pojam{Naziv pojma}` — obavezno omotaj **sam naziv pojma koji definiraš**, ne
  formulu iza njega. Primjer: `\\pojam{Nultočka funkcije} je vrijednost argumenta x
  za koju je f(x) = 0.` (a ne `\\pojam{f(x)=0}`). Ovo se koristi i za automatski
  pojmovnik.
- `[RJESENJE]` ... `[/RJESENJE]` — svaki marker na svom retku. Sve između se u
  učeničkoj verziji u potpunosti briše, a u profesorskoj ostaje, jasno označeno.
  Primjer:

```
Primjer 8. Nacrtajmo graf funkcije f(x) = -2x + 3.

[RJESENJE]
Za x = 0 dobivamo f(0) = 3, a za x = 1 dobivamo f(1) = 1.
[/RJESENJE]
```
        """
    )

if st.button("🔄 Osvježi", key="osvjezi_teorija"):
    _ucitaj_sifrarnik_potpoglavlja.clear()
    _ucitaj_teoriju.clear()

potpoglavlja_po_cjelini = _ucitaj_sifrarnik_potpoglavlja()
if not potpoglavlja_po_cjelini:
    st.warning("Šifrarnik potpoglavlja je prazan - popuni tab 'Sifrarnik_potpoglavlja' prvo.")
    st.stop()

cjelina = st.selectbox("Cjelina", sorted(potpoglavlja_po_cjelini.keys()), key="teorija_cjelina")
potpoglavlja = [p for p, _ in potpoglavlja_po_cjelini.get(cjelina, []) if p]
if not potpoglavlja:
    st.info("Ova cjelina nema definirana potpoglavlja u šifrarniku.")
    st.stop()
potpoglavlje = st.selectbox("Potpoglavlje", potpoglavlja, key="teorija_potpoglavlje")

teorija_dict = _ucitaj_teoriju()
postojeci = teorija_dict.get((cjelina, potpoglavlje), {})
if postojeci.get("tekst_teorije_latex"):
    st.caption(f"✅ Teorija za ovo potpoglavlje već postoji (zadnja izmjena: {postojeci.get('zadnja_izmjena') or '—'}).")
else:
    st.caption("ℹ️ Za ovo potpoglavlje još nema unesene teorije - PreTeXt build ga jednostavno preskače (bez greške).")

# key ovisi o (cjelina, potpoglavlje) - kad se promijeni odabir, Streamlit polje tretira kao
# NOVO (drugi key), pa se ispravno napuni trenutnim spremljenim stanjem za NOVI odabir umjesto
# da zadrži tekst ostavljen za PRETHODNO odabrano potpoglavlje.
tekst_key = f"teorija_tekst_{cjelina}_{potpoglavlje}"
if tekst_key not in st.session_state:
    st.session_state[tekst_key] = postojeci.get("tekst_teorije_latex", "")

st.divider()
st.subheader("1. Izvor teksta")

with st.expander("📄 Učitaj iz PDF-a/slike (OCR) kao polazni predložak - opcionalno"):
    st.caption(
        "OCR (Mathpix, isti pipeline kao za zadatke) ovdje NIKAD ne sprema izravno - samo "
        "predloži tekst u polje ispod, koje MORAŠ pregledati i po potrebi ispraviti prije "
        "spremanja (formule iz OCR-a znaju biti krivo pročitane). Word dokument prvo spremi/"
        "izvezi kao PDF - OCR ovdje podržava isključivo PDF i slike, isto kao kod obrade ispita. "
        "OCR ne poznaje konvencije !!...!!, \\pojam{} ni [RJESENJE] - te oznake dodaješ ručno "
        "nakon OCR-a."
    )
    ocr_datoteka = st.file_uploader(
        "PDF ili slika teorije", type=["pdf", "png", "jpg", "jpeg", "gif", "webp"], key=f"ocr_upload_{tekst_key}",
    )
    if ocr_datoteka is not None and st.button("🔎 Pokreni OCR i predloži tekst", key=f"ocr_run_{tekst_key}"):
        with st.spinner("OCR u tijeku..."):
            try:
                ocr_tekst = mathpix_ocr_datoteka(
                    ocr_datoteka.getvalue(), ocr_datoteka.name,
                    st.secrets["MATHPIX_APP_ID"], st.secrets["MATHPIX_APP_KEY"],
                )
                st.session_state[tekst_key] = ocr_tekst
                st.success("✅ OCR gotov - tekst ispod je PREDLOŽAK, pregledaj/ispravi prije spremanja.")
                st.rerun()
            except Exception as e:
                st.error(f"OCR nije uspio: {e}")

st.subheader("2. Tekst teorije (LaTeX)")
st.caption(
    "Matematika unutar `$...$` (npr. `$x^2-5x+6=0$`). Odlomci se razdvajaju PRAZNIM retkom "
    "(prazan red između dva pasusa) - svaki odlomak postaje zaseban `<p>` u PreTeXt izlazu."
)
novi_tekst = st.text_area(
    "Tekst teorije (tekst_teorije_latex)", height=300, key=tekst_key,
)

if novi_tekst.strip():
    verzija_pregleda = st.radio(
        "👁️ Pregled za:", ["ucenik", "profesor"], horizontal=True,
        format_func=lambda v: "Učenik (bez rješenja)" if v == "ucenik" else "Profesor (s rješenjima)",
        key=f"teorija_pregled_verzija_{cjelina}_{potpoglavlje}",
    )
    with st.expander(f"👁️ Pregled — {verzija_pregleda}", expanded=True):
        pregled = ukloni_markup_za_pregled(novi_tekst, verzija=verzija_pregleda)
        for odlomak in pregled.split("\n\n"):
            if odlomak.strip():
                st.write(odlomak)

st.subheader("3. Video / GeoGebra / vježba (opcionalno)")
video_url = st.text_input(
    "YouTube video (video_url)", value=postojeci.get("video_url", ""),
    key=f"teorija_video_{cjelina}_{potpoglavlje}",
    help="Isti format kao kod zadataka - trenutno se sprema sirovo, prikazuje se u PreTeXt izlazu kao <video>.",
)
geogebra_material_id = st.text_input(
    "GeoGebra material ID (geogebra_material_id)", value=postojeci.get("geogebra_material_id", ""),
    key=f"teorija_geogebra_{cjelina}_{potpoglavlje}",
    help=(
        "Priprema za §27.4 - polje se sprema, ali PreTeXt build GA JOŠ NE PRIKAZUJE "
        "(točna sintaksa GeoGebra embeda u PreTeXt-u nije potvrđena, ne pogađa se unaprijed)."
    ),
)
veza_vjezbaj = st.text_input(
    "Veza za vježbanje na praksa.cakipoduka.com (veza_vjezbaj)",
    value=postojeci.get("veza_vjezbaj", ""),
    key=f"teorija_vjezbaj_{cjelina}_{potpoglavlje}",
    help=(
        "Ručno zalijepljen link na relevantnu stranicu/cjelinu u Baza Zadataka. Prikazuje se "
        "kao 'Vježbaj ovo' poveznica na kraju teorije u PreTeXt izlazu. Prazno polje = "
        "poveznica se jednostavno ne prikazuje."
    ),
)

st.divider()
if st.button("💾 Spremi teoriju", type="primary", key=f"spremi_teorija_{cjelina}_{potpoglavlje}"):
    novi = _spremi_teoriju(
        cjelina, potpoglavlje, novi_tekst.strip(), video_url.strip(),
        geogebra_material_id.strip(), veza_vjezbaj.strip(),
    )
    st.success(("✅ Dodan novi redak" if novi else "✅ Ažuriran postojeći redak") + f" za {cjelina} → {potpoglavlje}.")
    _ucitaj_teoriju.clear()
    st.rerun()
