"""
CAKI — pages/16_razvrstavanje.py  (22.10.2026.)

🧩 **Razvrstavanje zadataka u potpoglavlja + težina** (AI predlaže, Caki potvrđuje).

Namjena (Cakijev zahtjev 22.10.2026.): svi Dakićevi udžbenici u bazi + uneseni zadaci, te još
jedna provjera fizike. Za osnovnu školu kurikulum još nije spreman — preskače se.

Kako radi:
1. Gore odabereš izvore (npr. sve s „daki” u nazivu), cjeline i što želiš popuniti
   (samo prazna potpoglavlja / samo prazne težine / oboje).
2. **🤖 Predloži** — DeepSeek dobiva ZATVORENI popis potpoglavlja po cjelini iz Šifrarnika i
   vraća prijedloge u serijama; ništa se još ne upisuje.
3. Pregledaš tablicu (Caki označi što prihvaća) i klikneš **✅ Primijeni označeno** — tada se
   potpoglavlje i težina upisuju u tab `Zadaci` jednim `batch_update` pozivom.
"""
import requests
import streamlit as st

import raspodjela_potpoglavlja as R
from baza_zadataka_pipeline import get_gspread_client
from secrets_json import ucitaj as _ucitaj_json

st.set_page_config(page_title="CAKI — Potpoglavlja i težine", page_icon="🧩", layout="wide")

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODELI = ["deepseek-v4-pro", "deepseek-flash"]


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_razvrst"] = (
            st.session_state.get("lozinka_unos_razvrst") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_razvrst"):
        return True
    st.title("🧩 CAKI — Potpoglavlja i težine")
    st.text_input("Lozinka", type="password", key="lozinka_unos_razvrst", on_change=na_unos)
    if st.session_state.get("autoriziran_razvrst") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


@st.cache_resource(show_spinner=False)
def _spreadsheet(_kljuc: str):
    sa = _ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    return get_gspread_client(sa).open_by_key(str(st.secrets["SHEET_ID"]))


@st.cache_data(ttl=600, show_spinner=False)
def _zadaci(_kljuc: str):
    return _spreadsheet(_kljuc).worksheet("Zadaci").get_all_records()


try:
    sheet = _spreadsheet(str(st.secrets.get("SHEET_ID", "")))
    zadaci = _zadaci(str(st.secrets.get("SHEET_ID", "")))
except Exception as e:                                  # noqa: BLE001
    st.error(f"Baza se ne može otvoriti: {e}")
    st.stop()

st.title("🧩 Razvrstavanje u potpoglavlja i težine")
st.caption("AI predlaže, ti potvrđuješ. Ništa se ne upisuje dok ne klikneš **Primijeni označeno**.")

mapping = R.sifrarnik(sheet)
if not mapping:
    st.error("Šifrarnik potpoglavlja je prazan ili tab `Sifrarnik_potpoglavlja` ne postoji — "
             "bez njega se ne može razvrstavati.")
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric("Zadataka u bazi", len(zadaci))
m2.metric("Cjelina u šifrarniku", len(mapping))
m3.metric("Bez potpoglavlja", sum(1 for z in zadaci if not R._t(z.get("potpoglavlje"))))

# ---------------------------------------------------------------- filtri
with st.expander("🎯 Što razvrstavati", expanded=True):
    svi_izvori = sorted({R._t(z.get("izvor_naziv")) for z in zadaci if R._t(z.get("izvor_naziv"))})
    zadani = [i for i in svi_izvori if "daki" in R._bez_dijakritika(i)]
    izvori = st.multiselect("Izvori (prazno = svi)", svi_izvori, default=zadani,
                            help="Zadano su svi Dakićevi udžbenici/zbirke. Ostavi prazno za sve izvore.")
    cjeline = st.multiselect("Samo ove cjeline (prazno = sve)", sorted(mapping))
    c1, c2, c3 = st.columns(3)
    samo_potp = c1.toggle("Samo bez potpoglavlja", value=True)
    samo_tez = c2.toggle("Samo bez težine", value=False)
    najvise = c3.number_input("Najviše zadataka u ovom prolazu", 10, 600, 120, 10)

odabrani = R.odaberi(zadaci, izvori=izvori, samo_bez_potpoglavlja=samo_potp,
                     samo_bez_tezine=samo_tez, cjeline=cjeline, najvise=int(najvise))
st.info(f"Za razvrstavanje odabrano **{len(odabrani)}** zadataka.")

# ---------------------------------------------------------------- poziv modela
def _pozovi(api_kljuc: str, model: str):
    def pozovi(system: str, user: str) -> dict:
        tijelo = {"model": model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "temperature": 0.2, "max_tokens": 3000}
        r = requests.post(DEEPSEEK_URL, json=tijelo, timeout=180,
                          headers={"Authorization": f"Bearer {api_kljuc}",
                                   "Content-Type": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"DeepSeek {r.status_code}")
        podaci = r.json()
        uporaba = podaci.get("usage") or {}
        return {"tekst": (podaci.get("choices") or [{}])[0].get("message", {}).get("content", ""),
                "tokeni_ulaz": uporaba.get("prompt_tokens", 0),
                "tokeni_izlaz": uporaba.get("completion_tokens", 0)}
    return pozovi


c_btn, c_model = st.columns([1, 1])
model = c_model.selectbox("Model", MODELI, index=0,
                          help="v4-pro je jači (preporučeno za razvrstavanje), flash je jeftiniji.")

if c_btn.button("🤖 Predloži potpoglavlja i težine", type="primary", disabled=not odabrani):
    if "DEEPSEEK_API_KEY" not in st.secrets:
        st.error("U Secrets nedostaje `DEEPSEEK_API_KEY`.")
        st.stop()
    traka = st.progress(0.0, text="Šaljem u serijama…")
    try:
        rezultat = R.razvrsti(
            odabrani, mapping, _pozovi(str(st.secrets["DEEPSEEK_API_KEY"]), model),
            trazi_potpoglavlje=True,
            napredak=lambda g, u: traka.progress(min(1.0, g / max(1, u)), text=f"{g}/{u}"))
    except Exception as e:                              # noqa: BLE001
        st.error(f"Razvrstavanje nije uspjelo: {e}")
        st.stop()
    st.session_state["razvrst_rezultat"] = rezultat
    st.session_state["razvrst_odabrani"] = {R._t(z.get("id")) for z in odabrani}
    traka.empty()

rezultat = st.session_state.get("razvrst_rezultat")
if not rezultat:
    st.stop()

predlozi = rezultat.get("predlozi") or []
if not predlozi:
    st.warning("Model nije vratio nijedan valjan prijedlog.")
    for u in (rezultat.get("upozorenja") or [])[:10]:
        st.caption(f"⚠️ {u}")
    st.stop()

st.success(f"Prijedloga: **{len(predlozi)}** · "
           f"tokeni: {rezultat.get('tokeni_ulaz', 0)} ulaz / {rezultat.get('tokeni_izlaz', 0)} izlaz")
if rezultat.get("upozorenja"):
    with st.expander(f"⚠️ {len(rezultat['upozorenja'])} upozorenja"):
        for u in rezultat["upozorenja"][:50]:
            st.caption(u)

# ---------------------------------------------------------------- pregled i primjena
import pandas as pd  # noqa: E402

tablica = R.tablica_prijedloga(predlozi)
tablica.insert(0, "Primijeni", [
    bool(R._t(p.get("sigurnost")) in ("visoka", "srednja") and
         ((R._t(p.get("potpoglavlje")) and R._t(p.get("potpoglavlje")) != R._t(p.get("sada_potpoglavlje")))
          or (R._t(p.get("tezina")) and R._t(p.get("tezina")) != R._t(p.get("sada_tezina")))))
    for p in predlozi])

st.markdown("**Pregled prijedloga** — odznači što ne želiš primijeniti.")
uredeno = st.data_editor(tablica, hide_index=True, width="stretch", key="razvrst_tablica",
                         disabled=[c for c in tablica.columns if c != "Primijeni"])

if st.button(f"✅ Primijeni označeno ({int(uredeno['Primijeni'].sum())})", type="primary"):
    oznaceni = {R._t(p.get("id")) for p, ok in zip(predlozi, uredeno["Primijeni"]) if ok}
    za_upis = [p for p in predlozi if R._t(p.get("id")) in oznaceni]
    try:
        upisano = R.primijeni(sheet, za_upis, stupci=("potpoglavlje", "tezina"))
    except Exception as e:                              # noqa: BLE001
        st.error(f"Upis nije uspio: {e}")
    else:
        st.success(f"✅ Upisano u {upisano} zadataka. Stare vrijednosti su u "
                   f"`potpoglavlje_prije` / `tezina_prije`.")
        st.session_state.pop("razvrst_rezultat", None)
        _zadaci.clear()
        st.cache_data.clear()
        st.rerun()
