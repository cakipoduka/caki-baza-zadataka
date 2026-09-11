"""
CAKI Matematika - pages/3_teorija.py
Streamlit stranica za unos/uređivanje teorije po potpoglavlju (§27.2) - jednokratni
unos, izmjene rijetke (pol/godišnje). Sprema se u tab 'Teorija_potpoglavlja' (jedan
redak = jedno (cjelina, potpoglavlje), overwrite pri spremanju - nema povijesti verzija).

Izvor teorije: direktan LaTeX paste (preporučeno, isti $...$ zapis kao u ostatku baze),
ILI upload PDF-a/slike -> Mathpix OCR kao POLAZNI predložak koji se OBAVEZNO pregleda/
uredi prije spremanja (OCR ovdje NIKAD ne sprema izravno, samo puni tekstualno polje).

Prikaz u PreTeXt izlazu (Korak 3.1): <introduction> na početku sekcije potpoglavlja,
prije <example>/<exercises> - vidi _build_introduction_lines u baza_zadataka_pipeline.py.
GeoGebra (geogebra_material_id) se ovdje samo UNOSI/sprema - PreTeXt embed generiranje
za nju čeka §27.4 (točna sintaksa još nije potvrđena, ne pogađa se unaprijed).
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


def _spremi_teoriju(cjelina, potpoglavlje, tekst, video_url, geogebra_material_id):
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
        "zadnja_izmjena": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if redak_broj is None:
        ws.append_row([vrijednosti[h] for h in TEORIJA_HEADERS])
    else:
        azuriranja = [
            {"range": f"{_col_letter(h, headers=TEORIJA_HEADERS)}{redak_broj}", "values": [[vrijednosti[h]]]}
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
        "izvezi kao PDF - OCR ovdje podržava isključivo PDF i slike, isto kao kod obrade ispita."
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
    with st.expander("👁️ Pregled (renderirano, ne sirovi LaTeX)", expanded=True):
        for odlomak in novi_tekst.split("\n\n"):
            odlomak = odlomak.strip()
            if odlomak:
                st.write(odlomak)

st.subheader("3. Video / GeoGebra (opcionalno)")
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

st.divider()
if st.button("💾 Spremi teoriju", type="primary", key=f"spremi_teorija_{cjelina}_{potpoglavlje}"):
    novi = _spremi_teoriju(cjelina, potpoglavlje, novi_tekst.strip(), video_url.strip(), geogebra_material_id.strip())
    st.success(("✅ Dodan novi redak" if novi else "✅ Ažuriran postojeći redak") + f" za {cjelina} → {potpoglavlje}.")
    _ucitaj_teoriju.clear()
    st.rerun()
