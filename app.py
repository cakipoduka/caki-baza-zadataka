"""
CAKI Matematika - app.py
Streamlit sučelje za obradu PDF ispita: upload -> Mathpix OCR -> Claude
strukturiranje -> upis u centralnu Google Sheets bazu (s detekcijom
duplikata). Zamišljeno za suradnike koji ne trebaju koristiti Colab.
"""
import json
import os

import streamlit as st

from pipeline import (
    build_sifrarnik_text,
    extract_zadaci_with_claude,
    get_drive_service,
    get_gspread_client,
    mathpix_process_pdf,
    mathpix_wait_and_get,
    nadopuni_ili_dodaj_zadatke,
    preuzmi_i_spremi_slike,
)

st.set_page_config(page_title="CAKI Matematika — Obrada ispita", page_icon="📚", layout="centered")


# --- Jednostavna zaštita lozinkom (protiv slučajnih posjetitelja s interneta, ne protiv suradnika) ---

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran"] = True
        else:
            st.session_state["autoriziran"] = False

    if st.session_state.get("autoriziran"):
        return True

    st.title("📚 CAKI Matematika")
    st.text_input("Lozinka", type="password", key="lozinka_unos", on_change=na_unos)
    if st.session_state.get("autoriziran") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# --- Google klijenti (keširano - ne spaja se iznova na svaki rerun) ---

@st.cache_resource
def init_google_clients():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    drive_service = get_drive_service(sa_info)
    sheet = gc.open_by_key(st.secrets["SHEET_ID"])
    return drive_service, sheet


drive_service, sheet = init_google_clients()
ws_zadaci = sheet.worksheet("Zadaci")

st.title("📚 CAKI Matematika — Obrada ispita")
st.caption("Upload PDF-ova → OCR → Claude strukturiranje → upis u bazu")

with st.form("obrada_form", clear_on_submit=False):
    st.subheader("1. Datoteke")
    ispit_datoteka = st.file_uploader("Ispit (PDF) — obavezno", type="pdf")
    rjesenja_datoteka_1 = st.file_uploader("Rješenja — kratki ključ (opcionalno)", type="pdf")
    rjesenja_datoteka_2 = st.file_uploader("Rješenja — bodovanje (opcionalno)", type="pdf")

    st.subheader("2. Metapodaci")
    col1, col2, col3 = st.columns(3)
    izvor_tip = col1.selectbox("Izvor", ["matura", "zbirka", "udzbenik", "vlastiti_materijal"])
    razina = col2.selectbox("Razina", ["A", "B", "-"])
    godina = col3.text_input("Godina", "")

    posalji = st.form_submit_button("🚀 Obradi")

if posalji:
    if not ispit_datoteka:
        st.error("Moraš priložiti barem PDF ispita.")
        st.stop()

    log_prostor = st.empty()
    log_redovi = []

    def log(poruka: str):
        log_redovi.append(poruka)
        log_prostor.text("\n".join(log_redovi))

    mathpix_id = st.secrets["MATHPIX_APP_ID"]
    mathpix_key = st.secrets["MATHPIX_APP_KEY"]
    anthropic_key = st.secrets["ANTHROPIC_API_KEY"]
    slike_folder_id = st.secrets["SLIKE_FOLDER_ID"]

    izvor_naziv = os.path.splitext(ispit_datoteka.name)[0]
    prilozi_rjesenja = [f for f in [rjesenja_datoteka_1, rjesenja_datoteka_2] if f]
    broj_pdf_ulaza = 1 + len(prilozi_rjesenja)

    with st.spinner("Obrada u tijeku — ovo može potrajati 1-3 minute..."):
        log(f"📄 Obrađujem: {izvor_naziv} ({broj_pdf_ulaza} datoteka)")

        try:
            # 1. Mathpix OCR ispita
            pdf_id = mathpix_process_pdf(ispit_datoteka.getvalue(), ispit_datoteka.name, mathpix_id, mathpix_key)
            ispit_md = mathpix_wait_and_get(pdf_id, mathpix_id, mathpix_key, log=log)
            log(f"✅ Ispit OCR gotov ({len(ispit_md)} znakova)")

            # 2. Mathpix OCR rješenja (ako postoje)
            rjesenja_md_parts = []
            for f in prilozi_rjesenja:
                pid = mathpix_process_pdf(f.getvalue(), f.name, mathpix_id, mathpix_key)
                md_dio = mathpix_wait_and_get(pid, mathpix_id, mathpix_key, log=log)
                rjesenja_md_parts.append(md_dio)
                log(f"✅ Rješenja OCR gotov ({f.name}, {len(md_dio)} znakova)")
            rjesenja_md = "\n\n---\n\n".join(rjesenja_md_parts) if rjesenja_md_parts else None

            # 3. Claude strukturiranje
            log("🤖 Claude strukturira zadatke...")
            sifrarnik_text = build_sifrarnik_text(sheet)
            zadaci = extract_zadaci_with_claude(ispit_md, rjesenja_md, sifrarnik_text, anthropic_key, log=log)
            log(f"✅ Claude vratio {len(zadaci)} zadataka")

            # 4. Preuzmi/spremi slike (zadatci sa slika_zadana=da)
            log("🖼️ Provjeravam zadatke sa zadanom slikom...")
            zadaci = preuzmi_i_spremi_slike(
                zadaci, izvor_naziv, mathpix_id, mathpix_key, drive_service, slike_folder_id, log=log
            )

            # 5. Upis u Sheet (s detekcijom duplikata)
            broj_dodanih, broj_azuriranih = nadopuni_ili_dodaj_zadatke(
                ws_zadaci, zadaci, izvor_tip, izvor_naziv, godina, razina, broj_pdf_ulaza, log=log
            )
            log(f"✅ {broj_dodanih} novih zadataka, {broj_azuriranih} nadopunjeno (duplikat)")

        except Exception as e:
            st.error(f"Greška tijekom obrade: {e}")
            st.stop()

    st.success(f"Gotovo! {broj_dodanih} novih zadataka dodano, {broj_azuriranih} nadopunjeno.")

    za_provjeru = [z for z in zadaci if z.get("status_provjere")]
    if za_provjeru:
        st.warning(f"⚠️ {len(za_provjeru)} zadataka označeno za ručnu provjeru:")
        for z in za_provjeru:
            st.write(f"- #{z.get('privremeni_broj')}: {z.get('status_provjere')}")

    st.markdown(f"[🔗 Otvori bazu u Google Sheets]({sheet.url})")
