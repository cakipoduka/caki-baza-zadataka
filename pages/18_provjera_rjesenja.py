"""CAKI — pages/18_provjera_rjesenja.py  (25.10.2026., prošireno 1.11.2026.)

🧑‍🏫 **Provjera i ispravak ocjena** — zasebna stranica (prečac).

1.11.2026.: sučelje je premješteno u `provjera_ocjena.py`, jer isti ekran sada stoji i kao **tab
🧑‍🏫 Provjera u kartici 📝 Testovi** (Cakijev zahtjev: „sve na jednom mjestu"). Ova stranica
zadržava isti kod, pa se dvije kopije ne mogu razići — ovdje su samo lozinka i učitavanje podataka.

Tri posla (detalji u `provjera_ocjena.py`):
  1. **⏳ Čeka odluku** — `ceka` (nema ključa / postupak) i `sumnja` (sličan zapis, nije odlučeno).
  2. **✏️ Ispravak po zadatku** — bilo koji rezultat, uključujući djelomične bodove.
  3. **🧮 Preračun starih rezultata** — pokaže što bi se promijenilo, pa upiše uz potvrdu.

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, APP_PASSWORD, CRM_SHEET_ID.
"""
import streamlit as st

import predmet_config
import provjera_ocjena
import testovi_admin as ta
from baza_zadataka_pipeline import get_gspread_client
from secrets_json import ucitaj as _ucitaj_json

st.set_page_config(page_title="CAKI — Provjera rješenja", page_icon="🧑‍🏫", layout="wide")
import caki_stil as stil  # noqa: E402  (31.10.2026.: CAKI tema)
stil.primijeni()  # 31.10.2026.: CAKI tema


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_provjera"] = (
            st.session_state.get("lozinka_provjera") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_provjera"):
        return True
    st.title("🧑‍🏫 CAKI — Provjera rješenja")
    st.text_input("Lozinka", type="password", key="lozinka_provjera", on_change=na_unos)
    if st.session_state.get("autoriziran_provjera") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

predmet = predmet_config.odaberi_predmet(st)
postavke = predmet_config.postavke(predmet)
st.title("🧑‍🏫 Provjera i ispravak ocjena")
st.caption(f"Predmet: **{postavke['naziv']}** · odluka o zadatku koji čeka, ručni ispravak bilo kojeg "
           f"rezultata i preračun testova predanih prije popravka ocjenjivanja. Isto je dostupno i u "
           f"kartici 📝 Testovi → tab **🧑‍🏫 Provjera**.")

if "CRM_SHEET_ID" not in st.secrets:
    st.error("U Streamlit Secrets nedostaje **CRM_SHEET_ID**.")
    st.stop()


@st.cache_resource(show_spinner=False)
def _crm(sheet_id: str):
    # parametar NE smije počinjati s `_` — Streamlit takve preskače u ključu keša (v. TRACKER 1.11.)
    sa = _ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    return get_gspread_client(sa).open_by_key(sheet_id)


@st.cache_data(ttl=120, show_spinner=False)
def _podaci(sheet_id: str):
    sheet = _crm(sheet_id)
    return ta.load_testovi(sheet), ta.load_rezultati(sheet)


crm_id = str(st.secrets["CRM_SHEET_ID"]).strip()
sheet = _crm(crm_id)
testovi, rezultati = _podaci(crm_id)

provjera_ocjena.prikazi(st, sheet, testovi, rezultati)
