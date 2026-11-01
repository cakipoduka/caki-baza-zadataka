"""
CAKI -- pages/10_pretpregled_testa.py  (21.10.2026.)

Pretpregled testa -- Caki sam rjesava bilo koji objavljeni test (tab `Testovi_zakazani`)
kao da je ucenik, da provjeri izgled zadataka i bodovanje PRIJE ili NAKON objave, bez
da to utjece na stvarne podatke:

  - test se bira iz postojeceg popisa (ucenik_id/program/aktivan/datumi se OVDJE ne
    provjeravaju -- pretpregled svjesno zaobilazi sve te filtre, to je cijela poanta),
  - kratki odgovor je cisti tekstualni unos (bez MathLive tipkovnice -- ta komponenta je
    u drugom repozitoriju, caki-booking-termina, i ovdje se namjerno ne duplicira),
  - NISTA se ne upisuje u `Rezultati_testova` niti bilo koji drugi tab -- ocjena se
    prikaze samo na ekranu i nestane kad stranicu zatvoris/refreshas.

Ocjenjivanje je u `ocjenjivanje_pretpregled.py`, a sama usporedba odgovora u
`provjera_odgovora.py` -- ISTI modul (bajt-identican) koristi i portal
`caki-booking-termina/testovi_online.py`, pa Pretpregled ne moze dati drugu ocjenu od portala.
(Do 1.11.2026. bila je namjerna kopija logike; razdvojila se i to je popravljeno.)

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, APP_PASSWORD, CRM_SHEET_ID (iste kao Test Builder
za objavu online testa).
"""
import uputa_u_aplikaciji as _uputa  # 21.10.2026.: upute UNUTAR aplikacije (sklopivi blok)
import streamlit as st

import testovi_online as _online
from baza_zadataka_pipeline import get_gspread_client
from ocjenjivanje_pretpregled import ocjeni, opcije_zadatka

st.set_page_config(page_title="CAKI -- Pretpregled testa", page_icon="\U0001f441", layout="wide")
import caki_stil as stil  # noqa: E402  (31.10.2026.: CAKI tema)
stil.primijeni()  # 31.10.2026.: CAKI tema


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_pretpregled"] = (
            st.session_state.get("lozinka_unos_pretpregled") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_pretpregled"):
        return True
    st.title("\U0001f441️ CAKI -- Pretpregled testa")
    st.text_input("Lozinka", type="password", key="lozinka_unos_pretpregled", on_change=na_unos)
    return False


if not provjeri_lozinku():
    st.stop()


@st.cache_resource
def _crm_sheet(_crm_id):
    sa = _online.sa_info_za_testove(st)
    return get_gspread_client(sa).open_by_key(_crm_id)


st.title("\U0001f441️ Pretpregled testa")
st.info("**Ovo je brzi pregled sadržaja** (radi i bez Googlea). Za pregled koji je **identičan onome što vidi učenik** — s matematičkim unosom, slikama, formulama i 💡 pomoći — otvori link **👁️ Otvori pretpregled** u 🧪 Test Builderu (stranica `/Pretpregled` na portalu). ")
_uputa.prikazi(st, "pretpregled")
st.caption("Rjesavas test kao sto bi ga vidio ucenik -- nista se ne sprema ni u jedan Sheet. "
           "Samo za tvoju provjeru prije/nakon objave.")

try:
    sheet = _crm_sheet(st.secrets["CRM_SHEET_ID"])
except ValueError as e:  # noqa: BLE001 -- 21.10.2026.: greška u Secrets, ne u pristupu Sheetu
    st.error(f"Greška u Secrets: {e}")
    st.stop()
except Exception as e:  # noqa: BLE001 -- Caki mora vidjeti sto Google kaze
    st.warning(
        "Treba `CRM_SHEET_ID` u Secrets (isti kao za „Objavi kao online test“ u Test Builderu).\n\n"
        f"Google javlja: {e}"
    )
    st.stop()

testovi = _online.load_testovi(sheet)
if not testovi:
    st.info("Jos nema objavljenih testova u `Testovi_zakazani`.")
    st.stop()

testovi = sorted(testovi, key=lambda t: _online._tekst(t.get("kreirano")), reverse=True)
oznake = [
    f"{t.get('naziv', '--')}  .  {t.get('ucenik_id') or 'svi'}  .  {t.get('kreirano', '')}  .  {t.get('test_id')}"
    for t in testovi
]
izbor = st.selectbox("Odaberi test za pretpregled", range(len(testovi)), format_func=lambda i: oznake[i])
test = testovi[izbor]
zadaci = _online.zadaci_iz_retka(test)

if not zadaci:
    st.error("Ovaj test nema ispravno spremljene zadatke (`zadaci_json` je prazan/neispravan) -- "
             "stvarni ucenik bi dobio istu gresku u portalu.")
    st.stop()

st.divider()
st.markdown(f"### \U0001f4dd {test.get('naziv', '')}")
st.caption(f"{len(zadaci)} zadataka . {test.get('bodovi_ukupno', '')} bodova . "
           f"trajanje: {test.get('trajanje_min', '')} min . aktivan: {test.get('aktivan', '')} . "
           f"otvara: {test.get('otvara_od', '') or '--'} . zatvara: {test.get('zatvara_do', '') or '--'}")

odgovori: dict[int, str] = {}
test_id = _online._tekst(test.get("test_id"))
for i, z in enumerate(zadaci):
    with st.container(border=True):
        st.markdown(f"**Zadatak {i + 1}.** ({float(z.get('bodovi') or 1):g} bod.)")
        st.markdown(z.get("tekst", ""))
        if z.get("slika"):
            st.caption(f"Uz zadatak ide slika: `{z.get('slika')}` -- provjeri postoji li datoteka "
                       f"(ovdje se slike ne prikazuju, portal ih prikazuje po imenu datoteke).")
        if _online._tekst(z.get("tip")) == "visestruki_izbor" and opcije_zadatka(z):
            opcije = opcije_zadatka(z)
            slova = [""] + [chr(65 + k) for k in range(len(opcije))]
            odgovori[i] = st.radio(
                "Odgovor", slova, index=0, horizontal=False, key=f"pretpregled_{test_id}_{i}",
                format_func=lambda s, o=opcije: "-- odaberi --" if not s else f"{s}) {o[ord(s) - 65]}",
            )
        else:
            odgovori[i] = st.text_input(
                "Odgovor -- upisi LaTeX (npr. \\frac{1}{2}); u portalu je ovo MathLive tipkovnica",
                key=f"pretpregled_{test_id}_{i}",
            )

if st.button("Ocijeni (samo na ekranu, nista se ne sprema)", type="primary"):
    bodovi, maks, detalji = ocjeni(zadaci, odgovori)
    st.success(f"Rezultat: **{bodovi:g} / {maks:g}** bodova "
               f"({round(100 * bodovi / maks) if maks else 0}%).")
    # 1.11.2026.: statusi "ceka" i "sumnja" NISU konačna nula — u portalu ih rješava Caki
    # u 🧑‍🏫 Provjeri rješenja (v. provjera_odgovora.py)
    _oznaka = {"tocno": "OK", "sumnja": "SUMNJA", "ceka": "CEKA"}
    for i, d in enumerate(detalji):
        ikona = _oznaka.get(str(d.get("status", "")), "X")
        st.write(f"[{ikona}] Zadatak {i + 1}: upisao/la si „{d['odgovor'] or '(prazno)'}“, "
                 f"tocan odgovor je „{d['ocekivano']}“ -- {d['bodovi']:g}/{d['max']:g} bod.")
        if d.get("zasto"):
            st.caption(f"    {d['zasto']} · izvor: {d.get('izvor', '')}")
