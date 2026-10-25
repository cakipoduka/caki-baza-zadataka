"""CAKI — pages/18_provjera_rjesenja.py  (25.10.2026.)

🧑‍🏫 **Provjera rješenja** — Caki pregledava predane testove prije nego ocjena postane konačna.

Zašto postoji: kratki odgovori bez jedinstvenog rješenja i zadaci tipa `prosireni_odgovor`
(postupak) ne mogu se automatski ocijeniti. Do sada su dobivali **0** — što je bilo netočno i
nepošteno. Sada takvi zadaci nose status **`ceka`** i ovdje ih Caki potvrđuje (✅ točno / ❌
netočno / ⏳ ostavi otvoreno); tek tada rezultat prelazi u `ocjenjeno`.

Logika je u `testovi_admin.py` (`potrebna_provjera`, `zadaci_za_provjeru`, `primijeni_provjeru`)
i testirana je bez Streamlita. Ovdje je samo sučelje; upisuje se SAMO u `Rezultati_testova`.

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, APP_PASSWORD, CRM_SHEET_ID.
"""
import streamlit as st

import predmet_config
import testovi_admin as ta
from baza_zadataka_pipeline import get_gspread_client
from secrets_json import ucitaj as _ucitaj_json

st.set_page_config(page_title="CAKI — Provjera rješenja", page_icon="🧑‍🏫", layout="wide")


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
st.title("🧑‍🏫 Provjera rješenja")
st.caption(f"Predmet: **{postavke['naziv']}** · zadaci koje sustav ne može ocijeniti sam "
           f"(bez ključa ili postupak) čekaju tvoju odluku.")

if "CRM_SHEET_ID" not in st.secrets:
    st.error("U Streamlit Secrets nedostaje **CRM_SHEET_ID**.")
    st.stop()


@st.cache_resource(show_spinner=False)
def _crm(_id: str):
    sa = _ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    return get_gspread_client(sa).open_by_key(_id)


@st.cache_data(ttl=120, show_spinner=False)
def _podaci(_id: str):
    sheet = _crm(_id)
    return ta.load_testovi(sheet), ta.load_rezultati(sheet)


crm_id = str(st.secrets["CRM_SHEET_ID"]).strip()
testovi, rezultati = _podaci(crm_id)

na_cekanju = [r for r in rezultati
              if ta.potrebna_provjera(r) or str(r.get("provjera", "")).strip() == "ceka"]
st.markdown(f"**Rezultata koji čekaju provjeru: {len(na_cekanju)}** "
            f"(od ukupno {len(rezultati)} predaja)")

if not na_cekanju:
    st.success("Nema što provjeravati — svi rezultati su zaključeni.")
    st.stop()

oznake = [f"{r.get('ime_djeteta') or r.get('ucenik_id')} · {r.get('naziv_testa')} · "
          f"{str(r.get('vrijeme_predaje', ''))[:16]} · {r.get('bodovi')}/{r.get('bodovi_max')} b"
          for r in na_cekanju]
odabrano = st.selectbox("Rezultat za provjeru", range(len(na_cekanju)),
                        format_func=lambda i: oznake[i])
rezultat = na_cekanju[int(odabrano)]
test = ta.nadji_test(testovi, str(rezultat.get("test_id", ""))) or {}
zadaci = ta.zadaci_iz_testa(test) if test else []
detalji = ta.detalji_iz_retka(rezultat)

if not test:
    st.warning("Test iz ovog rezultata više ne postoji u tabu `Testovi_zakazani` — "
               "zadaci se ne mogu prikazati, ali provjera se može spremiti ako je test bio obrisan.")

st.divider()
odluke = {}
for i, d in ta.zadaci_za_provjeru(rezultat):
    zadatak = zadaci[i] if i < len(zadaci) else {}
    with st.expander(f"#{i + 1} · {zadatak.get('tekst', '')[:70]}…", expanded=True):
        st.markdown(zadatak.get("tekst", "_(tekst zadatka nije dostupan)_"))
        c1, c2 = st.columns(2)
        c1.markdown("**Učenikov odgovor:**")
        c1.markdown(f"> {d.get('odgovor') or '_nije odgovoreno_'}")
        c2.markdown("**Očekivano rješenje:**")
        c2.markdown(f"> {d.get('ocekivano') or '_nema ključa_'}")
        st.caption(f"Bodovi zadatka: {d.get('max')} · status: {d.get('status', '')}")
        izbor = st.radio(
            "Odluka", ["⏳ ostavi otvoreno", "✅ točno", "❌ netočno"],
            key=f"odluka_{rezultat.get('rezultat_id')}_{i}", horizontal=True,
        )
        if izbor == "✅ točno":
            odluke[i] = {"status": "tocno"}
        elif izbor == "❌ netočno":
            odluke[i] = {"status": "netocno"}

st.divider()
if st.button("💾 Spremi provjeru", type="primary"):
    if not odluke:
        st.warning("Nijedna odluka nije odabrana — ništa nije spremljeno.")
    else:
        ws = _crm(crm_id).worksheet(ta.REZ_TAB)
        try:
            idovi = [str(v).strip() for v in ws.col_values(1)]
            redak = idovi.index(str(rezultat.get("rezultat_id", "")).strip()) + 1
        except Exception:                              # noqa: BLE001
            st.error("Ne mogu naći redak rezultata u tabu `Rezultati_testova`.")
            st.stop()
        polja = ta.primijeni_provjeru(ws, redak, rezultat, odluke, provjerio="Caki")
        _podaci.clear()
        st.success(f"✅ Spremljeno: {polja['bodovi']} b ({polja['postotak']} %), "
                   f"status provjere: **{polja['provjera']}**.")
        st.rerun()
