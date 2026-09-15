"""
CAKI Matematika - pages/4_skripta.py

Streamlit stranica za PRIPREMU zahtjeva za "skriptu" (§27.5, 15.9.2026.) - bira SAMO
parametre (cjelina, učenik/profesor verzija teorije, filtriraj li se na fiksni skup
"u_skriptu"). NE gradi PDF ovdje - stvarni PreTeXt/xelatex build i dalje radi Colab
(Korak 3.1 -> 3.3 -> 5), NAMJERNO: xelatex/TeX Live je pretežak/presporo za ovaj lagani
Streamlit Cloud hosting koji SVAKODNEVNO koriste i profesori (Test Builder) i Caki
(unos zadataka) - ubacivanje LaTeX buildanja u tu istu aplikaciju bi riskiralo usporiti
ili srušiti je za sve, za značajku koja se koristi rijetko (par puta godišnje).

Ova stranica samo zapisuje zahtjev u tab 'Skripta_zahtjevi' (poštanski sandučić) -
Colab (Korak 3.1) čita POSLJEDNJI zahtjev preko ucitaj_zadnji_zahtjev_skripte() PRIJE
poziva build_pretext_article. Ovo NE pokreće build samo od sebe - Caki i dalje ručno
pokreće Colab kad želi, isto kao dosad za običan build. Vidi
UPUTA_skripta_streamlit_colab.md za točan redak koji treba dodati u tu Colab ćeliju.
"""
import json

import streamlit as st

from baza_zadataka_pipeline import (
    get_gspread_client,
    get_sifrarnik_cjelina,
    spremi_zahtjev_skripte,
    ucitaj_zadnji_zahtjev_skripte,
)

st.set_page_config(page_title="CAKI Skripta", page_icon="📘", layout="wide")


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao u app.py, 2_test_builder.py, 3_teorija.py)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_skripta") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_skripta"] = True
        else:
            st.session_state["autoriziran_skripta"] = False

    if st.session_state.get("autoriziran_skripta"):
        return True

    st.title("📘 CAKI Skripta")
    st.text_input("Lozinka", type="password", key="lozinka_unos_skripta", on_change=na_unos)
    if st.session_state.get("autoriziran_skripta") is False:
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
def _ucitaj_cjeline():
    return sorted(get_sifrarnik_cjelina(init_sheet()).keys())


# ---------------------------------------------------------------
# UI
# ---------------------------------------------------------------

st.title("📘 Priprema skripte")
st.info(
    "Ova stranica NE generira PDF - samo bilježi ŠTO Colab treba izgraditi sljedeći put "
    "kad ručno pokreneš Korak 3.1. Sam PDF build ostaje u Colabu (xelatex je pretežak za "
    "ovaj hosting) - klikom ovdje ništa se odmah ne događa na webu ni kod studenata."
)

if st.button("🔄 Osvježi popis cjelina"):
    _ucitaj_cjeline.clear()

cjeline = _ucitaj_cjeline()
if not cjeline:
    st.warning("Šifrarnik cjelina je prazan - popuni tab 'Sifrarnik_cjelina' prvo.")
    st.stop()

cjelina = st.selectbox("Cjelina", cjeline, key="skripta_cjelina")

verzija = st.radio(
    "Verzija teorije",
    ["ucenik", "profesor"],
    horizontal=True,
    format_func=lambda v: "Učenik (bez rješenja iz primjera)" if v == "ucenik" else "Profesor (s rješenjima)",
    key="skripta_verzija",
)

filtriraj = st.checkbox(
    "Samo zadaci označeni za skriptu (u_skriptu = DA)",
    value=True,
    key="skripta_filtriraj",
    help=(
        "Uključeno (preporučeno za skriptu): koristi se fiksni skup 'zadaci za rad na "
        "satu' koje si ručno označila. Isključeno: build uzima CIJELI fond zadataka za "
        "ovu cjelinu, kao web izlaz - vjerojatno neželjeno za tiskanu skriptu."
    ),
)

st.divider()
if st.button("💾 Pripremi zahtjev za Colab", type="primary"):
    spremi_zahtjev_skripte(init_sheet(), cjelina, verzija_teorije=verzija, filtriraj_u_skriptu=filtriraj)
    st.success(
        f"✅ Zahtjev spremljen: **{cjelina}** / "
        f"**{'učenik' if verzija == 'ucenik' else 'profesor'}** / "
        f"**{'samo u_skriptu=DA' if filtriraj else 'cijeli fond'}**. "
        "Sad pokreni Korak 3.1 u Colabu - pročitat će ovaj zahtjev."
    )
    st.cache_data.clear()

st.divider()
st.subheader("Posljednji zapisan zahtjev")
zadnji = ucitaj_zadnji_zahtjev_skripte(init_sheet())
if zadnji:
    st.json(zadnji)
else:
    st.caption("Još nema nijednog zahtjeva.")
