"""
CAKI — pages/12_raspodjela_cjelina.py  (21.10.2026.)
🧩 RAZVRSTAVANJE ZADATAKA U CJELINE IZ ŠIFRARNIKA — Caki ne mora ručno razvrstavati.

Zašto: u bazu je ušlo 1842 fizikalna zadatka u 21 cjelinu, a šifrarnik ima 55 — sadržaj 35 cjelina
pomiješan je unutar širokih. Model predlaže cjelinu za svaki zadatak, Caki pregleda i potvrđuje;
**ništa se ne upisuje samo**.

Logika je u `raspodjela_cjelina.py` (testirano bez Streamlita, bez Googlea i bez API-ja). Ovdje je
samo sučelje. Pisanje ide SAMO u stupac `cjelina` (+ `cjelina_prije` kao podsjetnik za vraćanje).

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, APP_PASSWORD, SHEET_ID / SHEET_ID_FIZIKA,
         ANTHROPIC_API_KEY ili DEEPSEEK_API_KEY (ovisno koji model odabereš).
"""
import uputa_u_aplikaciji as _uputa  # 21.10.2026.: upute UNUTAR aplikacije (sklopivi blok)
import json

import streamlit as st

import predmet_config
import raspodjela_cjelina as rc
import uvoz_foldera as uf
from baza_zadataka_pipeline import ZADACI_HEADERS, get_gspread_client, get_or_create_worksheet

import secrets_json as _sj  # 21.10.2026.: tolerantno čitanje JSON-a iz Secrets
st.set_page_config(page_title="CAKI — Raspodjela po cjelinama", page_icon="🧩", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_raspodjela"] = (
            st.session_state.get("lozinka_unos_raspodjela") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_raspodjela"):
        return True
    st.title("🧩 CAKI — Raspodjela po cjelinama")
    st.text_input("Lozinka", type="password", key="lozinka_unos_raspodjela", on_change=na_unos)
    if st.session_state.get("autoriziran_raspodjela") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

predmet = predmet_config.odaberi_predmet(st)
postavke = predmet_config.postavke(predmet)

st.title("🧩 Raspodjela zadataka po cjelinama")
_uputa.prikazi(st, "raspodjela")
st.caption(f"Predmet: **{postavke['naziv']}** · model predlaže cjelinu iz šifrarnika, ti potvrđuješ. "
           "Ništa se ne upisuje samo.")

st.info("**Zašto ovo postoji:** kad u bazi ima manje cjelina nego u šifrarniku, sadržaj je pomiješan "
        "u širokim cjelinama (npr. „Sile i Newtonovi zakoni” drži i kosinu, i impuls sile, i gibanje "
        "po kružnici). Alat predlaže točniju cjelinu za svaki zadatak — **ti pregledaš i potvrdiš**.")


@st.cache_data(ttl=600, show_spinner=False)
def _sa_info():
    return _sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON")


@st.cache_resource(show_spinner=False)
def _baza_sheet(predmet_slug: str):
    return get_gspread_client(_sa_info()).open_by_key(predmet_config.sheet_id(predmet_slug, st.secrets))


@st.cache_data(ttl=600, show_spinner=False)
def _zadaci(predmet_slug: str):
    ws = get_or_create_worksheet(_baza_sheet(predmet_slug), "Zadaci", ZADACI_HEADERS)
    return ws.get_all_records()


@st.cache_data(ttl=600, show_spinner=False)
def _sifrarnik(predmet_slug: str) -> list:
    """Cjeline iz taba `Sifrarnik_cjelina` (kategorija + cjelina). Prazno ako taba nema."""
    sheet = _baza_sheet(predmet_slug)
    try:
        ws = sheet.worksheet("Sifrarnik_cjelina")
    except Exception:                                # noqa: BLE001 — tab ne postoji
        return []
    zagl = [str(h).strip().lower() for h in (ws.row_values(1) or [])]
    i_kat = zagl.index("kategorija") if "kategorija" in zagl else 0
    i_cj = zagl.index("cjelina") if "cjelina" in zagl else 1
    return [{"kategorija": str(r[i_kat]).strip() if len(r) > i_kat else "",
             "cjelina": str(r[i_cj]).strip() if len(r) > i_cj else ""}
            for r in ws.get_all_values()[1:] if len(r) > i_cj and str(r[i_cj]).strip()]


if st.button("🔄 Osvježi podatke iz Sheeta"):
    st.cache_data.clear()
    st.rerun()

zadaci = _zadaci(predmet)
cjeline = rc.popis_cjelina(_sifrarnik(predmet))

if not zadaci:
    st.error("Tab `Zadaci` je prazan ili se ne može pročitati.")
    st.stop()
if not cjeline:
    st.error("Tab `Sifrarnik_cjelina` je prazan — bez popisa cjelina alat ne može razvrstavati. "
             "Dodaj tab sa stupcima `kategorija` i `cjelina`.")
    st.stop()

# ---------------------------------------------------------------- 1. što razvrstavati
st.divider()
st.subheader("1. Što razvrstavati")

po_cjelini = {}
for z in zadaci:
    cj = str(z.get("cjelina") or "").strip() or "— bez cjeline —"
    po_cjelini[cj] = po_cjelini.get(cj, 0) + 1
sif_imena = [c["cjelina"] for c in cjeline]
prazne = [c for c in sif_imena if c not in po_cjelini]

c1, c2, c3 = st.columns(3)
c1.metric("Zadataka u bazi", len(zadaci))
c2.metric("Cjelina u šifrarniku", len(sif_imena))
c3.metric("Cjelina bez ijednog zadatka", len(prazne))

nacin = st.radio("Koje zadatke uzeti", [
    f"Sve ({len(zadaci)})",
    f"Samo iz odabranih cjelina ({len(po_cjelini)})",
    "Samo zadaci bez cjeline",
], horizontal=True, key="rc_nacin")

if nacin.startswith("Samo iz odabranih"):
    odabrane = st.multiselect("Iz kojih cjelina (sadašnjih)", sorted(po_cjelini),
                              format_func=lambda k: f"{k} ({po_cjelini[k]})", key="rc_cjeline")
    skup = [z for z in zadaci if (str(z.get("cjelina") or "").strip() or "— bez cjeline —") in odabrane]
elif nacin.startswith("Samo zadaci bez"):
    skup = [z for z in zadaci if not str(z.get("cjelina") or "").strip()]
else:
    skup = list(zadaci)

st.caption(f"Odabrano za razvrstavanje: **{len(skup)}** zadataka.")
if prazne:
    st.caption("Cjeline iz šifrarnika koje u bazi nemaju nijedan zadatak (njih ovo razvrstavanje može "
               "popuniti): " + ", ".join(prazne))

# ---------------------------------------------------------------- 2. model i pokretanje
st.divider()
st.subheader("2. Razvrstavanje")
m1, m2 = st.columns([2, 1])
model_naziv = m1.selectbox("Model", list(uf.MODELI), index=0, key="rc_model")
velicina = m2.number_input("Zadataka po pozivu", min_value=10, max_value=40, value=rc.BATCH, step=5,
                           key="rc_batch",
                           help="Manji paket = točniji i kraći odgovor; veći = manje poziva (brže/jeftinije).")

kljuc = ""
try:
    pruzatelj = uf.MODELI[model_naziv]["pruzatelj"]
    kljuc = str(st.secrets.get(uf.KLJUC_SECRETS[pruzatelj], "") or "")
except Exception:                                    # noqa: BLE001 — nema secrets.toml
    kljuc = ""
if not kljuc:
    st.warning(f"U Secrets nema `{uf.KLJUC_SECRETS.get(uf.MODELI[model_naziv]['pruzatelj'], '?')}` — "
               f"model {model_naziv} se ne može pozvati.")

if st.button("▶ Razvrsti", type="primary", disabled=not skup or not kljuc, key="rc_pokreni"):
    napredak = st.progress(0.0, text="Priprema…")

    def _p(gotovo, ukupno):
        napredak.progress(min(gotovo / ukupno, 1.0), text=f"Razvrstano {gotovo} / {ukupno}")

    with st.spinner(f"{model_naziv} razvrstava {len(skup)} zadataka…"):
        rez = rc.razvrsti(skup, cjeline, uf.napravi_pozivatelja(model_naziv, kljuc),
                          batch=int(velicina), napredak=_p)
    st.session_state["rc_rez"] = rez
    st.session_state["rc_otisak"] = (len(skup), model_naziv)
    napredak.empty()

rez = st.session_state.get("rc_rez")
if not rez:
    st.stop()

predlozi = rez["predlozi"]
s = rc.sazetak(predlozi)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Prijedloga", s["ukupno"])
k2.metric("Mijenja cjelinu", s["mijenja"])
k3.metric("Ostaje isto", s["isto"])
k4.metric("Nesigurno / niska", s["nesigurno"])
st.caption(f"Model: **{st.session_state.get('rc_otisak', ('', model_naziv))[1]}** · "
           f"tokeni: {rez['tokeni_ulaz']} ulaz / {rez['tokeni_izlaz']} izlaz")
for u in rez["upozorenja"][:8]:
    st.warning(u)
if len(rez["upozorenja"]) > 8:
    st.caption(f"… i još {len(rez['upozorenja']) - 8} upozorenja.")

# ---------------------------------------------------------------- 3. pregled
st.divider()
st.subheader("3. Pregled prije upisa")
p1, p2 = st.columns(2)
samo_promjene = p1.checkbox("Prikaži samo one koji mijenjaju cjelinu", value=True, key="rc_samo_promjene")
samo_nesigurne = p2.checkbox("Prikaži samo nesigurne (niska sigurnost)", value=False, key="rc_samo_nesigurne")

prikaz = [p for p in predlozi
          if (not samo_promjene or str(p.get("cjelina")) != str(p.get("sada")))
          and (not samo_nesigurne or str(p.get("sigurnost")) == "niska")]
tab = rc.tablica_prijedloga(prikaz)
st.dataframe(tab, hide_index=True, width="stretch", height=420)
st.download_button("⬇️ CSV — svi prijedlozi (backup prije upisa)",
                   data=tab.to_csv(index=False).encode("utf-8-sig"),
                   file_name=f"raspodjela_{predmet}.csv", mime="text/csv", key="rc_csv")

st.markdown("**Nova raspodjela** (koliko bi zadataka imala svaka cjelina nakon primjene):")
novi = rc.novi_po_cjelini(predlozi)
if novi:
    st.dataframe({"Cjelina": list(novi), "Zadataka": list(novi.values())},
                 hide_index=True, width="stretch", height=260)
    ostaju_prazne = [c for c in sif_imena if c not in novi]
    if ostaju_prazne:
        st.warning(f"**{len(ostaju_prazne)} cjelina ostaje bez zadataka** i nakon ovog razvrstavanja — "
                   "za njih treba novih zadataka (nije greška razvrstavanja): " + ", ".join(ostaju_prazne))

# ---------------------------------------------------------------- 4. upis
st.divider()
st.subheader("4. Upis u Sheet")
st.caption("Upisuje se **samo** stupac `cjelina`. Stara vrijednost se pamti u `cjelina_prije`, pa se "
           "promjena može vratiti. Sve u jednom pozivu prema Googleu (kvota).")

samo_sigurne = st.checkbox("Primijeni samo sigurne (visoka i srednja) — nesigurne preskoči", value=True,
                           key="rc_samo_sigurne")
potvrda = st.checkbox("Razumijem da mijenjam cjelinu u bazi i da je ovo samo prijedlog modela koji sam "
                      "pregledao.", key="rc_potvrda")

za_upis = {p["id"]: p["cjelina"] for p in predlozi
           if str(p.get("cjelina")) not in ("", "NESIGURNO")
           and str(p.get("cjelina")) != str(p.get("sada"))
           and (not samo_sigurne or str(p.get("sigurnost")) in ("visoka", "srednja"))}
st.caption(f"Za upis: **{len(za_upis)}** zadataka.")

if st.button(f"💾 Upiši {len(za_upis)} cjelina u Sheet", type="primary",
             disabled=not (za_upis and potvrda), key="rc_upisi"):
    try:
        upisano = rc.primijeni(_baza_sheet(predmet), za_upis)
        st.success(f"Upisano **{upisano}** zadataka. Provjeri 🎯 Spremnost baze → 🧩 Pokrivenost.")
        st.cache_data.clear()
    except Exception as e:                            # noqa: BLE001 — Caki mora vidjeti grešku
        st.error(f"Upis nije uspio: {e}")
