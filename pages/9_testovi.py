"""
CAKI — pages/9_testovi.py  (21.10.2026.)

📝 Testovi — učiteljska strana sustava online testova:
  • popis svih objavljenih testova (tab `Testovi_zakazani` u CRM Sheetu),
  • uređivanje (naziv, trajanje, datumi, aktivan), kloniranje, pregled s točnim odgovorima,
  • rezultati po testu i USPJEH PO ZADATKU (koji zadatak učenici nisu znali) + CSV,
  • 👥 Zadaj grupi: isti test cijeloj grupi Upisa ili kanti Mature (jedan redak po učeniku,
    ista oznaka `serija`; rezultati se zbrajaju za seriju),
  • 🎯 Spremnost baze: koliko zadataka ovog predmeta ima konačan odgovor (može u test),
    po cjelinama — čita se samo na klik,
  • 🩺 Provjere: test bez odgovora, istekao rok, otvoren bez ijedne predaje.

Sva logika je u `testovi_admin.py` (testirana bez Streamlita i bez Googlea); ovdje je
samo sučelje. Pisanje ide SAMO u tab `Testovi_zakazani`; `Rezultati_testova`, `Grupe`,
`Rezervacije` i `Raspored_Matura_<sezona>` se samo čitaju.

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, APP_PASSWORD, CRM_SHEET_ID (ID Sheeta
„CAKI CRM — Prijave i baza”, isti kao u Test Builderu za objavu online testa).
"""
import json

import streamlit as st

import predmet_config
import testovi_admin as ta
from baza_zadataka_pipeline import ZADACI_HEADERS, get_gspread_client, get_or_create_worksheet

st.set_page_config(page_title="CAKI — Testovi", page_icon="📝", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_testovi"] = (
            st.session_state.get("lozinka_unos_testovi") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_testovi"):
        return True
    st.title("📝 CAKI Testovi — rezultati i upravljanje")
    st.text_input("Lozinka", type="password", key="lozinka_unos_testovi", on_change=na_unos)
    if st.session_state.get("autoriziran_testovi") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

predmet = predmet_config.odaberi_predmet(st)
postavke = predmet_config.postavke(predmet)

st.title("📝 Testovi — rezultati i upravljanje")
st.caption(f"Predmet: **{postavke['naziv']}** · podaci iz CRM Sheeta "
           f"(tabovi `Testovi_zakazani` i `Rezultati_testova`)")

if "CRM_SHEET_ID" not in st.secrets:
    st.error("U Streamlit Secrets nedostaje **CRM_SHEET_ID** — ID Sheeta „CAKI CRM — Prijave i baza”. "
             "Isti ključ koristi Test Builder za objavu online testa; bez njega ova stranica ne "
             "može vidjeti ni testove ni rezultate.")
    st.stop()


def _sa_info():
    return json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])


@st.cache_resource(show_spinner=False)
def _crm_sheet(crm_id: str):
    return get_gspread_client(_sa_info()).open_by_key(crm_id)


crm_id = str(st.secrets["CRM_SHEET_ID"])
try:
    sheet = _crm_sheet(crm_id)
except Exception as e:                                  # noqa: BLE001 — Caki mora vidjeti grešku
    st.error(f"CRM Sheet se ne može otvoriti: {e}")
    st.caption("Provjeri da je servisni račun dodan na Sheet „CAKI CRM — Prijave i baza” "
               "(barem kao Viewer, a za uređivanje testova kao Editor).")
    st.stop()

# Nakon spremanja/kloniranja `testovi_admin` postavi zastavicu — keš se čisti prije učitavanja,
# inače bi stranica nakon izmjene još 60 s pokazivala stare podatke.
if st.session_state.pop("testovi_osvjezi", False):
    st.cache_data.clear()


@st.cache_data(ttl=60)
def _testovi(crm_id_: str):
    return ta.load_testovi(_crm_sheet(crm_id_))


@st.cache_data(ttl=60)
def _rezultati(crm_id_: str):
    return ta.load_rezultati(_crm_sheet(crm_id_))


@st.cache_data(ttl=120)
def _grupe_upisa(crm_id_: str):
    """Grupe Upisa s učenicima (tabovi Grupe + Rezervacije, samo status Potvrđeno)."""
    sheet_ = _crm_sheet(crm_id_)
    return ta.ucenici_upisa(ta.load_grupe(sheet_), ta.load_rezervacije(sheet_))


@st.cache_data(ttl=120)
def _kante_mature(crm_id_: str):
    """Kante rasporeda Mature s učenicima (tab Raspored_Matura_<sezona>)."""
    return ta.kante_mature(ta.load_raspored_mature(_crm_sheet(crm_id_)))


@st.cache_data(ttl=600, show_spinner=False)
def _zadaci_baze(predmet_slug: str):
    """Svi retci taba `Zadaci` ovog predmeta. Poziva se SAMO kad Caki klikne „Učitaj” —
    20.000 redaka se ne čita pri svakom otvaranju stranice."""
    sheet_ = get_gspread_client(_sa_info()).open_by_key(
        predmet_config.sheet_id(predmet_slug, st.secrets))
    return get_or_create_worksheet(sheet_, "Zadaci", ZADACI_HEADERS).get_all_records()


with st.sidebar:
    st.divider()
    if st.button("🔄 Osvježi testove i rezultate"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Ako je učenik upravo predao test, klikni Osvježi — podaci se inače pamte 60 s.")

with st.expander("ℹ️ Kako radi — korak po korak"):
    st.markdown(
        "1. **Sastavi test** u 🧪 Test Builder (odaberi zadatke lijevo) i na dnu klikni "
        "**📝 Objavi kao online test**.\n"
        "2. Test se pojavi **ovdje** i u portalu **Moj CAKI → 📝 Testovi** kod učenika kojem je "
        "objavljen, u razdoblju „otvoren od–do”.\n"
        "3. Učenik rješava, a portal upisuje rezultat u `Rezultati_testova` — **jedan upis po predaji**.\n"
        "4. Ovdje vidiš **tko je predao**, s koliko bodova i **koji zadatak razred nije znao**.\n"
        "5. **👥 Zadaj grupi**: odaberi postojeći test i grupu (Upisi) ili kantu (Matura) — svaki "
        "učenik dobije svoj test s istom oznakom serije; rezultati se zbrajaju za cijelu seriju.\n"
        "6. Ako u zadatku nađeš grešku: ispravi ga u bazi i **objavi novi test**, pa ovaj "
        "**⏸️ Deaktiviraj** — predani rezultati ostaju kakvi su bili.\n\n"
        "Ništa se ne šalje učenicima samo: test vide kad otvore portal."
    )

testovi_svi = _testovi(crm_id)
rezultati = _rezultati(crm_id)

samo_predmet = st.checkbox(
    f"Prikaži samo testove predmeta „{postavke['naziv']}”", value=True,
    help="Isključi ako želiš vidjeti testove svih predmeta (Matematika, Matematika OŠ, Fizika).")

testovi = ta.filtruj_po_predmetu(testovi_svi, predmet) if samo_predmet else testovi_svi

if samo_predmet and len(testovi) < len(testovi_svi):
    st.caption(f"Prikazano **{len(testovi)}** od ukupno **{len(testovi_svi)}** objavljenih testova "
               f"(ostali su za druge predmete).")

# Rezultati se filtriraju na prikazane testove — inače bi u metrike ulazili i tuđi predmeti.
if samo_predmet:
    dozvoljeni = {str(t.get("test_id", "")).strip() for t in testovi}
    rezultati = [r for r in rezultati if str(r.get("test_id", "")).strip() in dozvoljeni]

ta.prikazi_stranicu(st, sheet, testovi, rezultati, predmet=predmet if samo_predmet else "",
                    autor="Caki", grupe=_grupe_upisa(crm_id), kante=_kante_mature(crm_id),
                    ucitaj_bazu=lambda: _zadaci_baze(predmet))
