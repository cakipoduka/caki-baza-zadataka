"""
CAKI — pages/13_pomoc_pri_ucenju.py  (22.10.2026.)

💡 Pomoć pri učenju — Cakijev pregled onoga što učenici pitaju bota tijekom rješavanja testa.

Dvije stvari:
  • **Pitanja** — tko je pitao, što, i je li filter spriječio da se pojavi rješenje.
  • **Video kandidati** — zadaci o kojima se najviše pita → najbolji kandidati za snimanje
    video rješenja koje se embeda u bazu.

Samo čita tab `AI_pomoc_log` iz CRM Sheeta; ništa ne piše.
"""
import json

import streamlit as st

import pomoc_admin as pa
from baza_zadataka_pipeline import get_gspread_client
from testovi_online import sa_info_za_testove

st.set_page_config(page_title="CAKI — Pomoć pri učenju", page_icon="💡", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_pomoc"] = (
            st.session_state.get("lozinka_unos_pomoc") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_pomoc"):
        return True
    st.title("💡 CAKI — Pomoć pri učenju")
    st.text_input("Lozinka", type="password", key="lozinka_unos_pomoc", on_change=na_unos)
    if st.session_state.get("autoriziran_pomoc") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

st.title("💡 Pomoć pri učenju — što učenici pitaju")
st.caption("Pitanja iz portala Moj CAKI. Bot se predstavlja kao profesor i **ne otkriva "
           "rješenje**; ako bi ga odgovor odao, zamijeni se uputom i ovdje piše **Filtrirano: Da**.")

if "CRM_SHEET_ID" not in st.secrets:
    st.error("U Secrets nedostaje **CRM_SHEET_ID** — isti ključ koji koristi 📝 Testovi.")
    st.stop()


@st.cache_resource(show_spinner=False)
def _sheet(crm_id: str):
    return get_gspread_client(sa_info_za_testove(st)).open_by_key(crm_id)


crm_id = str(st.secrets["CRM_SHEET_ID"])
try:
    sheet = _sheet(crm_id)
except Exception as e:                                  # noqa: BLE001
    st.error(f"CRM Sheet se ne može otvoriti: {e}")
    st.stop()

with st.sidebar:
    st.divider()
    if st.button("🔄 Osvježi"):
        st.cache_data.clear()
        st.rerun()

log = pa.load_log(sheet)
brojevi = pa.sazetak(log)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Pitanja", brojevi["pitanja"])
m2.metric("Učenika", brojevi["ucenika"])
m3.metric("Testova", brojevi["testova"])
m4.metric("Spriječeno rješenje", brojevi["filtrirano"],
          help="Koliko je puta odgovor sadržavao rješenje pa je zamijenjen uputom.")

if not log:
    st.info("Još nema pitanja. Pomoć se učeniku prikazuje samo kad je u objavi testa "
            "`pomoc` = Da (ili kad je u Secrets portala uključeno `AI_POMOC`).")
    st.stop()

tab_pitanja, tab_video = st.tabs([f"📋 Pitanja ({brojevi['pitanja']})",
                                  "🎬 Video kandidati"])

with tab_pitanja:
    st.dataframe(pa.tablica_loga(log), hide_index=True, width="stretch")
    st.download_button("⬇️ CSV — sva pitanja", data=pa.csv_loga(log).encode("utf-8-sig"),
                       file_name="pomoc_pitanja.csv", mime="text/csv", key="pom_csv_log")

with tab_video:
    st.markdown("**Zadaci o kojima se najviše pita** — najbolji kandidati za video rješenje.")
    st.caption("Broji se **koliko je različitih učenika** pitalo (ne samo koliko pitanja), "
               "da jedan učenik ne prevagne.")
    najmanje = st.slider("Prikaži zadatke koje je pitalo barem… učenika", 1, 10, 2,
                         key="pom_min")
    kandidati = pa.video_kandidati(log, min_pitanja=najmanje)
    if not kandidati:
        st.caption("Još nema zadataka s dovoljno pitanja.")
    else:
        st.dataframe(pa.tablica_kandidata(kandidati), hide_index=True, width="stretch")
        st.download_button("⬇️ CSV — video kandidati",
                           data=pa.csv_kandidata(kandidati).encode("utf-8-sig"),
                           file_name="video_kandidati.csv", mime="text/csv", key="pom_csv_vid")
        st.caption("Kad snimiš video, embedaj ga na zadatak u bazi (polje `video_url`) — "
                   "tada ga vidi i učenik u portalu.")
