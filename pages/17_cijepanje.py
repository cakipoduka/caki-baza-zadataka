"""CAKI — pages/17_cijepanje.py  (22.10.2026.)

✂️ **Cijepanje zadataka** — kontrolna soba za posao koji radi `radnik.py` na GitHub Actions.

Ova stranica NE izvodi dugi posao (Streamlit prekida skriptu kad se tab zatvori ili app
hibernira — vidi `upute/ARHITEKTURA_RADNIK.md`). Ona:
  1. 📊 pokaže audit (koliko je kandidata, koliko se dijeli deterministički, koliko traži AI),
  2. 👁️ pokaže PRIJE/POSLIJE za odabrani uzorak (uvod + a)/b) + rješenje po dijelu),
  3. 🚀 pokrene radnika na GitHubu (jedan klik) — isprobaj ili pravi prolaz, s limitom,
  4. 📈 pokaže napredak iz taba `Radnik_stanje` i omogući „↩️ Vrati seriju" (undo).
Zajednički kod (čitanje, upis, stanje, undo) je u `radnik.py`; ovdje je samo prikaz i pokretanje.
"""
import requests
import streamlit as st

import podjela_zadataka as pz
import predmet_config as pc
import radnik as rd
from baza_zadataka_pipeline import get_gspread_client
from secrets_json import ucitaj as _ucitaj_json

st.set_page_config(page_title="CAKI — Cijepanje zadataka", page_icon="✂️", layout="wide")

GITHUB_REPO = "cakipoduka/caki-baza-zadataka"
GITHUB_WORKFLOW = "radnik.yml"


# ---------------------------------------------------------------- lozinka (isti obrazac kao ostale stranice)
def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_cijepanje"] = (
            st.session_state.get("lozinka_cijepanje") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_cijepanje"):
        return True
    st.title("✂️ CAKI — Cijepanje zadataka")
    st.text_input("Lozinka", type="password", key="lozinka_cijepanje", on_change=na_unos)
    if st.session_state.get("autoriziran_cijepanje") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------- podaci
@st.cache_resource(show_spinner=False)
def _spreadsheet(_kljuc: str, _predmet: str):
    sa = _ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    return get_gspread_client(sa).open_by_key(pc.sheet_id(_predmet, st.secrets))


@st.cache_data(ttl=600, show_spinner=False)
def _redci(_predmet: str, _sheet_id: str):
    sheet = _spreadsheet(_sheet_id, _predmet)
    ws = sheet.worksheet(rd.ZADACI_TAB)
    _zaglavlja, redci = rd.ucitaj_zadatke(ws)
    return redci


def _pokreni_radnika(**ulazi) -> tuple[bool, str]:
    """Pošalji `workflow_dispatch` — posao dalje radi GitHub, neovisno o ovoj sesiji."""
    token = str(st.secrets.get("GITHUB_DISPATCH_TOKEN", "")).strip()
    if not token:
        return False, "U Secrets nedostaje GITHUB_DISPATCH_TOKEN (fine-grained, pravo 'Actions: write')."
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}",
                                        "Accept": "application/vnd.github+json"},
                          json={"ref": "main", "inputs": {k: str(v) for k, v in ulazi.items()}},
                          timeout=20)
    except Exception as e:                                  # noqa: BLE001
        return False, f"Nije moguće kontaktirati GitHub ({type(e).__name__})."
    if r.status_code == 204:
        return True, "Posao pokrenut na GitHubu (Actions → Radnik)."
    if r.status_code in (401, 403):
        return False, "GitHub je odbio token (istekao ili bez prava 'Actions: write')."
    if r.status_code == 404:
        return False, "Workflow nije nađen — je li `radnik.yml` pushan na granu main?"
    return False, f"GitHub je vratio grešku {r.status_code}."


def _tab_ili_nista(sheet, naziv):
    try:
        return sheet.worksheet(naziv)
    except Exception:                                      # noqa: BLE001
        return None


# ---------------------------------------------------------------- stranica
predmet = pc.odaberi_predmet(st)
st.title("✂️ Cijepanje zadataka na podpitanja")
st.caption("Posao radi radnik na GitHub Actions — stranicu možeš zatvoriti, posao se nastavlja.")

_sheet_id = pc.sheet_id(predmet, st.secrets)
redci = _redci(predmet, _sheet_id)
a = pz.analiza(redci)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Zadataka", a["ukupno"])
c2.metric("Kandidata", a["kandidati"])
c3.metric("Dijeli se", a["podijeljeno"])
c4.metric("Traži AI", a["treba_ai"])
c5.metric("Bez rješenja", a["bez_rjesenja"])

tab_audit, tab_pregled, tab_pokreni, tab_log = st.tabs(
    ["📊 Audit", "👁️ Pregled prije/poslije", "🚀 Pokreni radnika", "📈 Napredak i undo"])

with tab_audit:
    st.markdown("**Po izvorima** (kandidati):")
    st.table({"izvor": [i for i, _ in a["po_izvoru"]], "kandidata": [n for _, n in a["po_izvoru"]]})
    st.caption("„Dijeli se\" = deterministički (oznake u tekstu i rješenju se poklapaju). "
               "„Traži AI\" = oznake se ne poklapaju, treba pregled.")

with tab_pregled:
    koliko = st.slider("Koliko primjera pokazati", 5, 50, 10)
    izvor = st.selectbox("Izvor (opcionalno)", ["(svi)"] + [i for i, _ in a["po_izvoru"]])
    prikaz = []
    for r in redci:
        if izvor != "(svi)" and r.get("izvor_naziv") != izvor:
            continue
        p = pz.podijeli(r)
        if p:
            prikaz.append((r, p))
        if len(prikaz) >= koliko:
            break
    for r, p in prikaz:
        with st.expander(f"`{p['id']}` — {r.get('izvor_naziv', '')} · {len(p['stavke'])} dijelova"
                         + ("" if p["sigurno"] else " · ⚠️ nije sigurno")):
            st.caption("PRIJE (izvorni zadatak)")
            st.markdown(r.get("tekst_zadatka_latex", ""))
            st.caption("POSLIJE — skupina (uvod)")
            st.markdown(p["uvod"] or "_(bez zajedničkog uvoda)_")
            for s in p["stavke"]:
                st.markdown(f"**{s['oznaka']})** {s['tekst']}")
                st.caption(f"rješenje: {s['rjesenje'][:300] or '—'} · kratki odgovor: "
                           f"{s['konacan_odgovor'] or '—'}")
            if p["napomene"]:
                st.warning("; ".join(p["napomene"]))

with tab_pokreni:
    st.markdown("Radnik radi na GitHubu (Actions → **Radnik**). Ovdje ga samo pokrećeš.")
    col1, col2 = st.columns(2)
    limit = col1.number_input("Najviše zadataka u ovom pokretanju", 1, 5000, 50, step=50)
    isprobaj = col2.checkbox("🧪 Isprobaj (ništa se ne upisuje)", value=True)
    if st.button("🚀 Pokreni radnika", type="primary"):
        ok, poruka = _pokreni_radnika(posao="cijepanje", predmet=predmet, limit=int(limit),
                                      serija="", isprobaj="da" if isprobaj else "ne", vrati="")
        (st.success if ok else st.error)(poruka)
    st.info("Prvi pravi prolaz pusti na **kopiji** baze, s limitom 50. Undo je uvijek dostupan "
            "u tabu „📈 Napredak i undo\".")

with tab_log:
    sheet = _spreadsheet(_sheet_id, predmet)
    ws_stanje = _tab_ili_nista(sheet, rd.STANJE_TAB)
    ws_log = _tab_ili_nista(sheet, rd.LOG_TAB)
    if ws_stanje is None:
        st.caption("Radnik još nije pokretan (nema taba `Radnik_stanje`).")
    else:
        try:
            stanja = ws_stanje.get_all_records()
        except Exception:                                  # noqa: BLE001
            stanja = []
        st.markdown("**Serije**")
        st.dataframe(stanja, hide_index=True, width="stretch") if stanja else st.caption("Prazno.")
        if stanja:
            serija = st.selectbox("Serija za undo", [s.get("serija", "") for s in stanja][::-1])
            potvrda = st.checkbox("Potvrđujem vraćanje serije (vraća stare vrijednosti i briše dodane retke)")
            if potvrda and st.button("↩️ Vrati seriju", key="vrati_seriju"):
                ok, poruka = _pokreni_radnika(posao="cijepanje", predmet=predmet, limit="0",
                                              serija="", isprobaj="ne", vrati=serija)
                (st.success if ok else st.error)(poruka)
    if ws_log is not None:
        try:
            zadnje = ws_log.get_all_records()[-20:]
        except Exception:                                  # noqa: BLE001
            zadnje = []
        st.markdown("**Zadnjih 20 promjena** (`Promjene_log`)")
        st.dataframe(zadnje, hide_index=True, width="stretch") if zadnje else st.caption("Prazno.")
