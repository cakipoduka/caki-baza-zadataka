"""
CAKI — pages/15_radovi.py  (22.10.2026.)

📸 **Radovi učenika** — slike/skenovi rada na papiru koje su učenici poslali nakon predaje testa.

Prikaz je namjerno **bez downloadanja**: svaki rad ima gumb **Otvori u Driveu** (pregled u
pregledniku), a slike se prikazuju i inline. Tu je i **brisanje po roku** (7 dana) i brisanje
cijele školske godine — Cakijeva pravila od 22.10.2026.

Tab u CRM Sheetu: `Radovi` (piše ga portal).
"""
import streamlit as st

import radovi_admin as R
from baza_zadataka_pipeline import get_drive_service, get_gspread_client
from secrets_json import ucitaj as _ucitaj_json
from testovi_online import sa_info_za_testove

st.set_page_config(page_title="CAKI — Radovi", page_icon="📸", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_radovi"] = (
            st.session_state.get("lozinka_unos_radovi") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_radovi"):
        return True
    st.title("📸 CAKI — Radovi učenika")
    st.text_input("Lozinka", type="password", key="lozinka_unos_radovi", on_change=na_unos)
    if st.session_state.get("autoriziran_radovi") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

if "CRM_SHEET_ID" not in st.secrets:
    st.error("U Secrets nedostaje **CRM_SHEET_ID**.")
    st.stop()


@st.cache_resource(show_spinner=False)
def _crm(crm_id: str):
    return get_gspread_client(sa_info_za_testove(st)).open_by_key(crm_id)


@st.cache_resource(show_spinner=False)
def _drive(_kljuc: str):
    return get_drive_service(_ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON"))


try:
    sheet = _crm(str(st.secrets["CRM_SHEET_ID"]))
except Exception as e:                                  # noqa: BLE001
    st.error(f"CRM Sheet se ne može otvoriti: {e}")
    st.stop()

st.title("📸 Radovi učenika")
st.caption(f"Radovi se čuvaju **{R.DANI_CUVANJA} dana** od predaje — briši ih gumbom ispod ili na "
           "kraju školske godine. Datoteke su na Driveu; ovdje su linkovi za brzi pregled.")

radovi = R.load_radovi(sheet)
if not radovi:
    st.info("Još nema poslanih radova. Učenik ih šalje nakon predaje testa za koji je u objavi "
            "označeno **📷 Učenik šalje svoj rad**.")
    st.stop()

# ---------------------------------------------------------------- filtri
c1, c2, c3 = st.columns([2, 2, 1])
testovi_dostupni = sorted({R._tekst(r.get("test_id")) for r in radovi})
test_odabir = c1.multiselect("Test", testovi_dostupni)
ucenici_dostupni = sorted({R._tekst(r.get("ucenik_id")).upper() for r in radovi})
ucenik_odabir = c2.multiselect("Učenik", ucenici_dostupni)
samo_novi = c3.toggle("Samo novi", value=True, key="rad_samo_novi")

prikaz = [r for r in radovi
          if (not test_odabir or R._tekst(r.get("test_id")) in test_odabir)
          and (not ucenik_odabir or R._tekst(r.get("ucenik_id")).upper() in ucenik_odabir)
          and (not samo_novi or R._tekst(r.get("status")) != "Obrisano")]

m1, m2, m3 = st.columns(3)
m1.metric("Radova", len(prikaz))
m2.metric("Učenika", len({R._tekst(r.get("ucenik_id")) for r in prikaz}))
m3.metric("Testova", len({R._tekst(r.get("test_id")) for r in prikaz}))

st.dataframe(R.tablica(prikaz), hide_index=True, width="stretch",
             column_config={"Otvori": st.column_config.LinkColumn("Otvori u Driveu")})

# ---------------------------------------------------------------- pregled + brisanje
with st.expander("🔎 Pregled radova (slike se prikazuju, PDF se otvara u Driveu)", expanded=False):
    for r in prikaz:
        naziv = R._tekst(r.get("naziv"))
        vrsta = R._tekst(r.get("vrsta")).lower()
        st.markdown(f"**{R._tekst(r.get('ucenik_id')).upper()}** · {R._tekst(r.get('test_id'))} · "
                    f"{R._tekst(r.get('kreirano'))} · `{naziv}`")
        st.link_button("🔗 Otvori u Driveu", R._tekst(r.get("link")), key=f"rad_link_{r.get('rad_id')}")
        if vrsta in ("jpg", "jpeg", "png"):
            try:
                _drive_srv = _drive(str(st.secrets.get("SHEET_ID", "")))
                _bajtovi = _drive_srv.files().get_media(
                    fileId=R._tekst(r.get("file_id")), supportsAllDrives=True).execute()
                if _bajtovi:
                    st.image(_bajtovi, caption=naziv)
            except Exception as e:                      # noqa: BLE001
                st.caption(f"Slika se ne može prikazati ({type(e).__name__}).")
        st.divider()

# ---------------------------------------------------------------- čišćenje
st.subheader("🧹 Brisanje")
za_brisanje = R.stariji_od(prikaz, dana=R.DANI_CUVANJA)
st.caption(f"Starije od {R.DANI_CUVANJA} dana: **{len(za_brisanje)}** radova.")

c4, c5 = st.columns([1, 1])
if c4.button(f"🧹 Obriši {len(za_brisanje)} starijih od {R.DANI_CUVANJA} dana",
             disabled=not za_brisanje, key="rad_obrisi_stare"):
    _drive_srv = _drive(str(st.secrets.get("SHEET_ID", "")))
    obrisano, greske = 0, []
    for r in za_brisanje:
        try:
            _drive_srv.files().delete(fileId=R._tekst(r.get("file_id")),
                                      supportsAllDrives=True).execute()
            R.oznaci_obrisano(sheet, R._tekst(r.get("rad_id")))
            obrisano += 1
        except Exception as e:                          # noqa: BLE001
            greske.append(f"{r.get('naziv')}: {type(e).__name__}")
    st.success(f"Obrisano {obrisano} radova.")
    for g in greske:
        st.warning(g)
    st.cache_data.clear()
    st.rerun()

if c5.button("🗑️ Obriši SVE radove (kraj školske godine)", key="rad_obrisi_sve"):
    _drive_srv = _drive(str(st.secrets.get("SHEET_ID", "")))
    obrisano = 0
    for r in prikaz:
        try:
            _drive_srv.files().delete(fileId=R._tekst(r.get("file_id")),
                                      supportsAllDrives=True).execute()
            R.oznaci_obrisano(sheet, R._tekst(r.get("rad_id")))
            obrisano += 1
        except Exception:                               # noqa: BLE001
            continue
    st.success(f"Obrisano {obrisano} radova (zapisi ostaju označeni kao Obrisano).")
    st.cache_data.clear()
    st.rerun()
