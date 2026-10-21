"""
CAKI — pages/8_uvoz_iz_foldera.py (15.10.2026.)
Uvoz zadataka iz FOLDERA na Driveu (slike i PDF-ovi) -> Mathpix OCR -> AI (Claude i/ili DeepSeek) -> pregled -> baza.

Isti obrazac kao "AI kontrola": folder (Shared Drive) se zada poveznicom, aplikacija sama čita datoteke, Mathpix se plaća
SAMO JEDNOM po datoteci (OCR se sprema u _uvoz_cache), a u tabu 'Uvoz_izvori' ostaje evidencija s kvačicama što je obrađeno.
NIŠTA ne ide u tab 'Zadaci' dok ne klikneš "Upiši u bazu" u koraku 3.

Sva logika je u uvoz_foldera.py (testirana bez mreže); ovdje je samo sučelje.

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, MATHPIX_APP_ID, MATHPIX_APP_KEY, APP_PASSWORD, SHEET_ID*, SLIKE_FOLDER_ID*
         + barem jedan od ANTHROPIC_API_KEY / DEEPSEEK_API_KEY. Opcionalno: UVOZ_FOLDER_ID (zadani folder).
Servisni račun mora imati pravo UREĐIVANJA (Content manager / Editor) na folderu - upisuje _uvoz_cache.
"""
import uputa_u_aplikaciji as _uputa  # 21.10.2026.: upute UNUTAR aplikacije (sklopivi blok)
import json
import re

import pandas as pd
import streamlit as st

import predmet_config
import uvoz_foldera as uf
from baza_zadataka_pipeline import (
    build_sifrarnik_potpoglavlja_text,
    build_sifrarnik_text,
    get_biblioteke_izvora,
    get_drive_service,
    get_gspread_client,
    get_or_create_worksheet,
    nadopuni_ili_dodaj_zadatke,
)

import secrets_json as _sj  # 21.10.2026.: tolerantno čitanje JSON-a iz Secrets
st.set_page_config(page_title="CAKI — Uvoz iz foldera", page_icon="📥", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_uvoz"] = st.session_state.get("lozinka_unos_uvoz") == st.secrets.get("APP_PASSWORD")

    if st.session_state.get("autoriziran_uvoz"):
        return True
    st.title("📥 CAKI Uvoz iz foldera")
    st.text_input("Lozinka", type="password", key="lozinka_unos_uvoz", on_change=na_unos)
    if st.session_state.get("autoriziran_uvoz") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

predmet = predmet_config.odaberi_predmet(st)
st.title("📥 Uvoz zadataka iz foldera (slike i PDF-ovi)")
_uputa.prikazi(st, "uvoz")
st.caption(f"Predmet: {predmet_config.postavke(predmet)['naziv']} · prompt verzija {uf.PROMPT_VERZIJA}")


def sa_info():
    return _sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON")


@st.cache_resource(show_spinner=False)
def _sheet(predmet_slug):
    return get_gspread_client(sa_info()).open_by_key(predmet_config.sheet_id(predmet_slug, st.secrets))


def drive_io() -> uf.DriveIO:
    return uf.DriveIO(lambda: get_drive_service(sa_info()))


# ---- provjere postavki
nedostaje = [k for k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "MATHPIX_APP_ID", "MATHPIX_APP_KEY") if k not in st.secrets]
if nedostaje:
    st.error("U Streamlit Secrets nedostaje: " + ", ".join(nedostaje))
    st.stop()
dostupni_modeli = [n for n, m in uf.MODELI.items() if uf.KLJUC_SECRETS[m["pruzatelj"]] in st.secrets]
if not dostupni_modeli:
    st.error("Nema nijednog AI ključa. Dodaj ANTHROPIC_API_KEY i/ili DEEPSEEK_API_KEY u Secrets.")
    st.stop()

try:
    sa_mail = sa_info().get("client_email", "")
except Exception:  # noqa: BLE001
    sa_mail = ""

sheet = _sheet(predmet)
ws_zadaci = sheet.worksheet("Zadaci")
ws_evid = get_or_create_worksheet(sheet, uf.IZVORI_TAB, uf.IZVORI_HEADERS, rows=500)

tab1, tab2, tab3 = st.tabs(["1. Folder i obrada", "2. Pregled i usporedba", "3. Upis u bazu"])

# ===================================================================================================================
with tab1:
    st.markdown(
        f"**Kako:** zalijepi poveznicu na folder (Shared Drive je u redu). Servisni račun `{sa_mail}` mora biti dodan na "
        "folder s pravom **uređivanja** (zapisuje podmapu `_uvoz_cache`). Mathpix se zove samo jednom po datoteci."
    )
    c1, c2 = st.columns([4, 1])
    link = c1.text_input("Poveznica ili ID foldera", value=st.secrets.get("UVOZ_FOLDER_ID", ""), key="uvoz_link")
    rekurzivno = c2.checkbox("Uključi podmape", value=True)
    fid = uf.izvuci_folder_id(link)

    if st.button("📂 Učitaj popis datoteka", disabled=not fid):
        try:
            with st.spinner("Čitam folder..."):
                st.session_state["uvoz_datoteke"] = drive_io().popis(fid, rekurzivno=rekurzivno)
                st.session_state["uvoz_folder"] = fid
                st.session_state.pop("uvoz_tablica", None)
        except Exception as e:  # noqa: BLE001
            st.error(f"Folder se ne može pročitati: {e}. Je li servisni račun dodan na folder?")

    datoteke = st.session_state.get("uvoz_datoteke") or []
    if datoteke:
        po_id = {f["id"]: f for f in datoteke}
        nacin = st.selectbox(
            "Grupiranje datoteka u izvore",
            ["auto", "po_podmapi", "svaka_datoteka", "sve_jedan"],
            format_func={"auto": "Automatski po nazivu (list_03_001, list_03_002, list_03_rj → jedan izvor)",
                         "po_podmapi": "Jedna podmapa = jedan izvor", "svaka_datoteka": "Svaka datoteka = zaseban izvor",
                         "sve_jedan": "Sve u jedan izvor"}.get)
        if st.button("🔄 Predloži grupiranje") or "uvoz_tablica" not in st.session_state:
            st.session_state["uvoz_tablica"] = pd.DataFrame(uf.predlozi_grupiranje(datoteke, nacin))
        st.caption("Uloga i grupu možeš mijenjati u tablici. 'preskoči' = datoteka se ne obrađuje.")
        uredjeno = st.data_editor(
            st.session_state["uvoz_tablica"], key="uvoz_editor", use_container_width=True, hide_index=True,
            column_config={"id": None, "uloga": st.column_config.SelectboxColumn("uloga", options=uf.ULOGE, required=True)},
            disabled=["naziv", "putanja", "vrsta"])
        redovi = uredjeno.to_dict("records")
        grupe = uf.sastavi_grupe(redovi, po_id)

        evid = uf.ucitaj_evidenciju(ws_evid)
        izv = []
        for g, d in grupe.items():
            sve = d["zadaci"] + d["rjesenja"]
            otisak = uf.otisak_datoteka(sve)
            st_ = uf.stanje_izvora(g, otisak, evid)
            izv.append({"obradi": st_ in ("novo", "greska"), "stanje": uf.STANJA[st_] + " " + st_, "grupa": g,
                        "izvor_naziv": uf.sanitiziraj_izvor_naziv(g), "izvor_tip": "zbirka", "godina": uf.predlozi_godinu(g),
                        "zadaci": len(d["zadaci"]), "rjesenja": len(d["rjesenja"])})
        if not izv:
            st.warning("Nema datoteka za obradu (provjeri uloge).")
        else:
            st.subheader("Izvori")
            st.caption("✅ uneseno · ♻️ uneseno, ali su se datoteke promijenile · 🟡 AI gotov, čeka pregled · ❌ greška · ⬜ novo")
            izv_df = st.data_editor(
                pd.DataFrame(izv), key="uvoz_izvori_editor", use_container_width=True, hide_index=True,
                column_config={"izvor_tip": st.column_config.SelectboxColumn("izvor_tip", options=uf.IZVOR_TIPOVI, required=True)},
                disabled=["stanje", "grupa", "zadaci", "rjesenja"])
            c3, c4, c5 = st.columns(3)
            modeli = c3.multiselect("AI bot (za usporedbu odaberi dva)", dostupni_modeli,
                                    default=[m for m in uf.ZADANI_MODELI if m in dostupni_modeli] or dostupni_modeli[:1])
            ponovo = c4.checkbox("Ponovno obradi i već obrađene", value=False)
            skenirano = c5.selectbox("Skenirano?", ["da", "ne"], help="'da' za fotografije/skenove, 'ne' za digitalne PDF-ove")

            if st.button("🚀 Pokreni obradu odabranih izvora", type="primary", disabled=not modeli):
                odabrani = [r for r in izv_df.to_dict("records") if r["obradi"]]
                if not odabrani:
                    st.warning("Ništa nije označeno za obradu.")
                else:
                    dio = drive_io()
                    cache_id = dio.nadji_ili_napravi_podfolder(st.session_state["uvoz_folder"], uf.CACHE_FOLDER_NAZIV)
                    indeks = dio.indeks(cache_id)
                    sif = build_sifrarnik_text(sheet)
                    sifpp = build_sifrarnik_potpoglavlja_text(sheet)
                    with st.status("Obrada...", expanded=True) as status:
                        def log(p):
                            st.write(p)
                        for r in odabrani:
                            g = r["grupa"]
                            d = grupe[g]
                            sve = d["zadaci"] + d["rjesenja"]
                            otisak = uf.otisak_datoteka(sve)
                            if not ponovo and uf.stanje_izvora(g, otisak, evid).startswith("uneseno"):
                                continue
                            st.write(f"### 📚 {g}")
                            try:
                                def ocr_skup(lista):
                                    izlaz = []
                                    for f in lista:
                                        o = uf.ocr_datoteka_s_cacheom(dio, cache_id, indeks, f, st.secrets["MATHPIX_APP_ID"],
                                                                      st.secrets["MATHPIX_APP_KEY"], log=log)
                                        izlaz.append({"naziv": f["name"], **o})
                                    return izlaz
                                oz = ocr_skup(d["zadaci"])
                                orj = ocr_skup(d["rjesenja"])
                                ulaz_md, mapa, sljedeci = uf.sastavi_ulaz(oz, 1, "DATOTEKA")
                                rj_md, mapa2, _ = uf.sastavi_ulaz(orj, sljedeci, "RJEŠENJA") if orj else (None, {}, sljedeci)
                                mapa.update(mapa2)
                                vrsta = ", ".join(sorted({uf.vrsta_datoteke(f) for f in sve}))
                            except Exception as e:  # noqa: BLE001
                                st.error(f"OCR nije uspio za {g}: {e}")
                                for mn in modeli:
                                    uf.zapisi_evidenciju(ws_evid, {"grupa": g, "model": uf.kratki_naziv_modela(mn), "status": "greska",
                                                                   "otisak": otisak, "poruka": f"OCR: {e}"[:300]})
                                continue
                            for mn in modeli:
                                m = uf.MODELI[mn]
                                kratko = uf.kratki_naziv_modela(mn)
                                st.write(f"🤖 **{mn}**")
                                try:
                                    pozovi = uf.napravi_pozivatelja(mn, st.secrets[uf.KLJUC_SECRETS[m["pruzatelj"]]], log=log)
                                    res = uf.strukturiraj(pozovi, predmet, m["pruzatelj"], sif, sifpp, ulaz_md, rj_md,
                                                          izvor_naziv=r["izvor_naziv"], vrsta_ulaza=vrsta, tokeni=list(mapa),
                                                          max_znakova=m["dio_znakova"], max_izlaz=m["max_izlaz"], log=log)
                                    zad, izvj = uf.dovrsi_skup(res["zadaci"], mapa, ulaz_md, ", ".join(f["name"] for f in d["zadaci"]))
                                    brupoz = sum(1 for z in zad if z.get("status_provjere"))
                                    sadrzaj = {"grupa": g, "model": mn, "otisak": otisak, "zadaci": zad, "mapa_slika": mapa, "izvjestaj": izvj,
                                               "nepotpuno": res["nepotpuno"], "greske": res["greske"], "prompt_verzija": uf.PROMPT_VERZIJA,
                                               "izvor": {k: r[k] for k in ("izvor_naziv", "izvor_tip", "godina")}, "skenirano": skenirano}
                                    fid_izlaz = dio.spremi_json(cache_id, f"izlaz__{uf.sanitiziraj_izvor_naziv(g)}__{kratko}.json", sadrzaj,
                                                                indeks.get(f"izlaz__{uf.sanitiziraj_izvor_naziv(g)}__{kratko}.json"))
                                    indeks[f"izlaz__{uf.sanitiziraj_izvor_naziv(g)}__{kratko}.json"] = fid_izlaz
                                    uf.zapisi_evidenciju(ws_evid, {
                                        "grupa": g, "model": kratko, "izvor_naziv": r["izvor_naziv"], "status": "ai_gotovo", "otisak": otisak,
                                        "broj_jedinica": len(zad), "broj_upozorenja": brupoz, "tokeni_ulaz": res["tokeni_ulaz"],
                                        "tokeni_izlaz": res["tokeni_izlaz"], "izlaz_file_id": fid_izlaz,
                                        "datoteke": "; ".join(f["name"] for f in sve)[:500],
                                        "poruka": ("NEPOTPUNO: " if res["nepotpuno"] else "") + " | ".join(res["greske"])[:250]})
                                    st.write(f"✅ {mn}: {len(zad)} zadataka, {brupoz} za provjeru"
                                             + (" ⚠️ odgovor nepotpun" if res["nepotpuno"] else ""))
                                except Exception as e:  # noqa: BLE001
                                    st.error(f"{mn}: {e}")
                                    uf.zapisi_evidenciju(ws_evid, {"grupa": g, "model": kratko, "status": "greska", "otisak": otisak,
                                                                   "poruka": str(e)[:300]})
                        status.update(label="Obrada gotova — pogledaj korak 2", state="complete")
                    st.success("Gotovo. Idi na karticu '2. Pregled i usporedba'.")

# ===================================================================================================================
def ucitaj_izlaz(file_id):
    return drive_io().procitaj_json(file_id)


with tab2:
    evid = [r for r in uf.ucitaj_evidenciju(ws_evid) if r.get("izlaz_file_id")]
    if not evid:
        st.info("Još nema obrađenih izvora.")
    else:
        grupe_ev = sorted({r["grupa"] for r in evid})
        g = st.selectbox("Izvor", grupe_ev, key="pregled_grupa")
        moji = [r for r in evid if r["grupa"] == g]
        st.dataframe(pd.DataFrame(moji)[["model", "status", "vrijeme", "broj_jedinica", "broj_upozorenja", "tokeni_ulaz", "tokeni_izlaz", "poruka"]],
                     hide_index=True, use_container_width=True)
        izlazi = {}
        for r in moji:
            try:
                izlazi[r["model"]] = ucitaj_izlaz(r["izlaz_file_id"])
            except Exception as e:  # noqa: BLE001
                st.warning(f"{r['model']}: ne mogu pročitati izlaz ({e})")
        if len(izlazi) >= 2:
            (ma, a), (mb, b) = list(izlazi.items())[:2]
            st.subheader(f"Usporedba: {ma} ↔ {mb}")
            us = uf.usporedi_rezultate(a["zadaci"], b["zadaci"])
            st.dataframe(pd.DataFrame(us), hide_index=True, use_container_width=True)
        if izlazi:
            mk = st.selectbox("Prikaži rezultat modela", list(izlazi), key="pregled_model")
            iz = izlazi[mk]
            if iz.get("nepotpuno") or iz.get("greske"):
                st.warning("Upozorenja obrade: " + " | ".join(iz.get("greske", [])))
            for u in iz.get("izvjestaj", {}).get("upozorenja_skupa", []):
                st.warning(u)
            samo = st.checkbox("Samo zadaci s upozorenjem", value=False)
            tab = pd.DataFrame([{"br": z["privremeni_broj"], "uloga": z["uloga"], "tip": z["tip_zadatka"], "odgovor": z["konacan_odgovor"],
                                 "slika": z["slika_url"], "status_provjere": z["status_provjere"],
                                 "tekst": z["tekst_zadatka_latex"][:160]} for z in iz["zadaci"]
                                if not samo or z["status_provjere"]])
            st.dataframe(tab, hide_index=True, use_container_width=True)
            br = st.selectbox("Detalj zadatka", [z["privremeni_broj"] for z in iz["zadaci"]], key="pregled_detalj")
            z = next(z for z in iz["zadaci"] if z["privremeni_broj"] == br)
            st.markdown(z["tekst_zadatka_latex"])
            if z["ponudjeni_odgovori"]:
                st.markdown("\n".join(f"- **{'ABCDEFGH'[i]}**  {o}" for i, o in enumerate(z["ponudjeni_odgovori"])))
            st.json({k: v for k, v in z.items() if k not in ("tekst_zadatka_latex", "tekst_zadatka_mathjax")}, expanded=False)

with tab3:
    evid = [r for r in uf.ucitaj_evidenciju(ws_evid) if r.get("izlaz_file_id")]
    if not evid:
        st.info("Nema ničega za upis.")
    else:
        opcije = [f"{r['grupa']} · {r['model']} ({r['broj_jedinica']} jedinica, {r['broj_upozorenja']} upozorenja)" for r in evid]
        i = st.selectbox("Što upisati", range(len(evid)), format_func=lambda k: opcije[k])
        r = evid[i]
        iz = ucitaj_izlaz(r["izlaz_file_id"])
        st.write(f"Izvor: **{iz['izvor']['izvor_naziv']}** · tip {iz['izvor']['izvor_tip']} · godina {iz['izvor']['godina'] or '—'}")
        c1, c2, c3 = st.columns(3)
        izvor_naziv = c1.text_input("izvor_naziv", iz["izvor"]["izvor_naziv"])
        izvor_tip = c2.selectbox("izvor_tip", uf.IZVOR_TIPOVI, index=uf.IZVOR_TIPOVI.index(iz["izvor"]["izvor_tip"]))
        godina = c3.text_input("godina", iz["izvor"]["godina"])
        razina = st.selectbox("razina", predmet_config.razine(predmet))
        biblioteka = st.selectbox("Biblioteka izvora (neobavezno)", [""] + list(get_biblioteke_izvora(sheet)))
        samo_cisti = st.checkbox("Upiši samo zadatke BEZ upozorenja", value=False)
        if iz.get("nepotpuno"):
            st.warning("Odgovor modela je bio nepotpun — provjeri da nedostaju zadnji zadaci.")
        if st.button("✅ Upiši u bazu", type="primary"):
            try:
                dio = drive_io()
                slike_folder = predmet_config.slike_folder_id(predmet, st.secrets)
                zad = [z for z in iz["zadaci"] if not (samo_cisti and z["status_provjere"])]
                with st.spinner("Kopiram slike i upisujem..."):
                    zad = uf.pripremi_za_upis(zad, iz["mapa_slika"], izvor_naziv, dio, slike_folder)
                    dodano, azur = nadopuni_ili_dodaj_zadatke(
                        ws_zadaci, zad, izvor_tip, izvor_naziv, godina, razina, max(1, len((r.get("datoteke") or "").split("; "))),
                        skenirano=iz.get("skenirano", "da"), biblioteka_izvora=biblioteka)
                uf.zapisi_evidenciju(ws_evid, {"grupa": r["grupa"], "model": r["model"], "status": "uneseno", "otisak": r["otisak"],
                                               "dodano": dodano, "nadopunjeno": azur})
                st.success(f"✅ Dodano {dodano}, nadopunjeno {azur}.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Upis nije uspio: {e}")
