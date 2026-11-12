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
    _je_obican_tekst,
    build_sifrarnik_potpoglavlja_text,
    build_sifrarnik_text,
    get_biblioteke_izvora,
    get_drive_service,
    get_gspread_client,
    get_potpoglavlja_po_cjelini,
    get_or_create_worksheet,
    nadopuni_ili_dodaj_zadatke,
    prikazi_opcije_markdown,
)

import secrets_json as _sj  # 21.10.2026.: tolerantno čitanje JSON-a iz Secrets
st.set_page_config(page_title="CAKI — Uvoz iz foldera", page_icon="📥", layout="wide")
import caki_stil as stil  # noqa: E402  (31.10.2026.: CAKI tema)
stil.primijeni()  # 31.10.2026.: CAKI tema


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
            st.session_state["uvoz_tablica"], key="uvoz_editor", width="stretch", hide_index=True,
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
                pd.DataFrame(izv), key="uvoz_izvori_editor", width="stretch", hide_index=True,
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
@st.cache_data(ttl=300)
def _potpoglavlja_po_cjelini():
    """{cjelina: [potpoglavlje, ...]} iz taba Sifrarnik_potpoglavlja - za izbornike u
    preglednoj tablici koraka 2. Kesirano jer se cita pri svakom reruna tablice."""
    try:
        return {c: [pp for pp, _ in v] for c, v in get_potpoglavlja_po_cjelini(sheet).items()}
    except Exception:  # noqa: BLE001 - sifrarnik nije kriticna ovisnost pregleda
        return {}


def ucitaj_izlaz(file_id):
    return drive_io().procitaj_json(file_id)


def _prikazi_bez_dolar(v: str) -> str:
    """Prikaz za polja koja baza sprema BEZ $ omotaca (npr. konacan_odgovor kod
    kratki_odgovor/prosireni_odgovor - isto pravilo kao ponudjeni_odgovori, v. D6 u
    sistemskom promptu u uvoz_foldera.py). Ista heuristika kao prikazi_opcije_markdown()
    u baza_zadataka_pipeline.py (ako vec ima $, ostavi; ako je obican tekst - recenica ili
    rijec - ostavi kao tekst; inace omotaj u $...$), samo bez A)/B) prefiksa jer je ovo
    JEDNA vrijednost."""
    v = (v or "").strip()
    if not v or "$" in v or _je_obican_tekst(v):
        return v
    return f"${v}$"


with tab2:
    evid = [r for r in uf.ucitaj_evidenciju(ws_evid) if r.get("izlaz_file_id")]
    if not evid:
        st.info("Još nema obrađenih izvora.")
    else:
        grupe_ev = sorted({r["grupa"] for r in evid})
        g = st.selectbox("Izvor", grupe_ev, key="pregled_grupa")
        moji = [r for r in evid if r["grupa"] == g]
        st.dataframe(pd.DataFrame(moji)[["model", "status", "vrijeme", "broj_jedinica", "broj_upozorenja", "tokeni_ulaz", "tokeni_izlaz", "poruka"]],
                     hide_index=True, width="stretch")
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
            st.dataframe(pd.DataFrame(us), hide_index=True, width="stretch")
        if izlazi:
            mk = st.selectbox("Prikaži rezultat modela", list(izlazi), key="pregled_model")
            iz = izlazi[mk]
            r_model = next(r for r in moji if r["model"] == mk)
            if iz.get("nepotpuno") or iz.get("greske"):
                st.warning("Upozorenja obrade: " + " | ".join(iz.get("greske", [])))
            for u in iz.get("izvjestaj", {}).get("upozorenja_skupa", []):
                st.warning(u)
            if iz.get("mapa_slika"):
                with st.expander(f"📎 Dostupne oznake slika u ovom izvoru ({len(iz['mapa_slika'])}) - za ručno popunjavanje polja ispod"):
                    for oznaka, info in sorted(iz["mapa_slika"].items()):
                        st.markdown(f"`{oznaka}` — [otvori]({'https://drive.google.com/file/d/' + info['drive_id'] + '/view'})")
            baza_kljuc = r_model["izlaz_file_id"]
            samo = st.checkbox("Samo zadaci s upozorenjem", value=False, key=f"samo_upoz_{baza_kljuc}")

            # 12.11.2026. (Cakijev zahtjev): PREGLEDNA TABLICA prije upisa. Jedan redak = jedan
            # zadatak, pa se najveci dio posla - maknuti kvacicu zadatku koji ne zelim, popraviti
            # bodove, dodijeliti cjelinu/potpoglavlje - odradi BEZ renderanja stotina LaTeX
            # kartica (kod 300-500 zadataka mjesecno to je razlika izmedu upotrebljivog i ne).
            # Kartice ispod ostaju za zadatke kojima stvarno treba pogledati tekst/sliku/rjesenje.
            # Sve se sprema u ISTU cache datoteku na Driveu, pa korak 3 vidi ispravljenu verziju.
            _pp_po_cjelini = _potpoglavlja_po_cjelini()
            _sve_cjeline = [z.get("cjelina") for z in iz["zadaci"]]
            _opcije_cjelina = uf.opcije_za_stupac(_pp_po_cjelini.keys(), _sve_cjeline)
            _opcije_potpoglavlja = uf.opcije_za_stupac(
                uf.potpoglavlja_u_opsegu(_pp_po_cjelini, _sve_cjeline),
                [z.get("potpoglavlje") for z in iz["zadaci"]])
            _opcije_tezina = uf.opcije_za_stupac(
                ["lako", "srednje", "tesko"], [z.get("tezina") for z in iz["zadaci"]])
            _opcije_tip = uf.opcije_za_stupac(
                ["visestruki_izbor", "kratki_odgovor", "prosireni_odgovor"],
                [z.get("tip_zadatka") for z in iz["zadaci"]])

            with st.expander("⚡ Masovno postavi cjelinu/potpoglavlje za SVE zadatke ovog izvora"):
                st.caption(
                    "Za zbirke i udzbenike gdje cijelo poglavlje ide u istu cjelinu. Primjenjuje se "
                    "na sve zadatke izvora (i one skrivene filterom), odmah se sprema na Drive."
                )
                mc1, mc2, mc3 = st.columns([3, 3, 1])
                _mas_cj = mc1.selectbox("Cjelina", [""] + sorted(_pp_po_cjelini),
                                        key=f"mas_cj_{baza_kljuc}")
                _mas_pp = mc2.selectbox("Potpoglavlje (neobavezno)",
                                        [""] + list(_pp_po_cjelini.get(_mas_cj, [])),
                                        key=f"mas_pp_{baza_kljuc}", disabled=not _mas_cj)
                mc3.write("")
                if mc3.button("Primijeni", key=f"mas_go_{baza_kljuc}", disabled=not _mas_cj):
                    for z in iz["zadaci"]:
                        z["cjelina"] = _mas_cj
                        if _mas_pp:
                            z["potpoglavlje"] = _mas_pp
                    try:
                        drive_io().spremi_json(None, None, iz, postojeci_id=baza_kljuc)
                        st.session_state.pop(f"grid_{baza_kljuc}", None)
                        st.success(f"Postavljeno na {len(iz['zadaci'])} zadataka i spremljeno.")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Spremanje nije uspjelo: {e}")

            _redci = []
            for z in iz["zadaci"]:
                if samo and not z["status_provjere"]:
                    continue
                _redci.append({
                    "unesi": bool(z.get("unesi", True)),
                    "br": z["privremeni_broj"],
                    "uloga": z["uloga"],
                    "tip": z["tip_zadatka"],
                    "cjelina": z.get("cjelina", ""),
                    "potpoglavlje": z.get("potpoglavlje", ""),
                    "tezina": z.get("tezina", ""),
                    "bodovi": z.get("max_bodovi", ""),
                    "slika": len([x for x in str(z.get("slika_url") or "").split("|") if x.strip()]),
                    "odgovor": z["konacan_odgovor"],
                    "upozorenje": z["status_provjere"],
                    "tekst": z["tekst_zadatka_latex"][:160],
                })
            _grid = st.data_editor(
                pd.DataFrame(_redci), key=f"grid_{baza_kljuc}", hide_index=True, width="stretch",
                column_config={
                    "unesi": st.column_config.CheckboxColumn(
                        "✓", default=True, width="small",
                        help="Makni kvacicu zadatku koji ne zelis u bazi. Odznacena skupina "
                             "povlaci i sve svoje stavke."),
                    "br": st.column_config.TextColumn("br", width="small"),
                    "uloga": st.column_config.TextColumn("uloga", width="small"),
                    "tip": st.column_config.SelectboxColumn("tip", options=_opcije_tip),
                    "cjelina": st.column_config.SelectboxColumn("cjelina", options=_opcije_cjelina, width="medium"),
                    "potpoglavlje": st.column_config.SelectboxColumn("potpoglavlje", options=_opcije_potpoglavlja, width="medium"),
                    "tezina": st.column_config.SelectboxColumn("tezina", options=_opcije_tezina, width="small"),
                    "bodovi": st.column_config.TextColumn("bodovi", width="small"),
                    "slika": st.column_config.NumberColumn("🖼️", width="small", help="Broj slika pridruzenih zadatku"),
                    "odgovor": st.column_config.TextColumn("odgovor", width="small"),
                    "upozorenje": st.column_config.TextColumn("upozorenje", width="medium"),
                    "tekst": st.column_config.TextColumn("tekst (pocetak)", width="large"),
                },
                disabled=["br", "uloga", "slika", "tekst"],
            )
            _r_grid = _grid.to_dict("records")
            _lose_pp = [
                r for r in _r_grid
                if str(r["potpoglavlje"] or "").strip()
                and str(r["potpoglavlje"]).strip() not in _pp_po_cjelini.get(str(r["cjelina"] or "").strip(), [])
            ]
            if _lose_pp:
                st.warning(
                    f"⚠️ {len(_lose_pp)} zadataka ima potpoglavlje koje po sifrarniku ne pripada svojoj "
                    "cjelini: " + ", ".join(f"#{r['br']}" for r in _lose_pp[:12])
                    + ("…" if len(_lose_pp) > 12 else "")
                )
            _bez_pp = sum(1 for r in _r_grid if not str(r["potpoglavlje"] or "").strip())
            if _bez_pp:
                st.info(
                    f"ℹ️ {_bez_pp} zadataka jos nema potpoglavlje. Takvi zadaci se u Test Builderu "
                    "vide samo preko opcije „— (bez potpoglavlja)” - bolje ih dodijeliti sada nego poslije."
                )
            st.caption(
                f"Za upis oznaceno **{sum(1 for r in _r_grid if r['unesi'])}** od {len(_r_grid)} "
                "prikazanih zadataka. Promjene vrijede tek nakon gumba „💾 Spremi izmjene” na dnu."
            )
            # 27.10.2026.: SVI (filtrirani) zadaci odjednom, ne jedan po jedan iz padajućeg
            # izbornika (Caki - usporava pregled) - isti st.container(border=True) stil kao
            # popis zadataka u pages/2_test_builder.py, radi vizualne dosljednosti.
            #
            # 27.10.2026. (ista večer, iduća izmjena): polja su UREDIVA izravno ovdje, PRIJE
            # upisa u bazu (Caki eksplicitno - ne želi ispravljati NAKON upisa, nego prije).
            # Widgeti pišu u st.session_state (ključ po izlaz_file_id + privremeni_broj, da se
            # ne miješaju između grupa/modela). Gumb "Spremi izmjene" ispod upisuje NATRAG u
            # ISTU cache datoteku na Driveu (prepisuje izlaz_file_id preko DriveIO.spremi_json
            # s postojeci_id) - ucitaj_izlaz() NIJE keširan (obično st.cache_data), pa tab 3
            # "Upiši u bazu" kod sljedećeg čitanja automatski vidi ispravljenu verziju, bez
            # dodatnog koraka sinkronizacije.
            st.divider()
            _za_kartice = [z for z in iz["zadaci"] if not (samo and not z["status_provjere"])]
            _kljuc_prikaz = f"kartice_prikaz_{baza_kljuc}"
            _prikaz = st.session_state.get(_kljuc_prikaz, 20)
            st.markdown(f"#### ✏️ Kartice ({len(_za_kartice)}) — tekst, ponudeni odgovori, slika, rjesenje")
            st.caption(
                "Cjelinu, potpoglavlje, tezinu, bodove i kvacicu za upis brze mijenjas u tablici gore. "
                "Kartice se prikazuju po 20 da stranica ostane brza."
            )
            for z in _za_kartice[:_prikaz]:
                broj = z["privremeni_broj"]
                pref = f"ured_{baza_kljuc}_{broj}_"
                with st.container(border=True):
                    st.markdown(f"**#{broj}** · {z['uloga']} · {z['tip_zadatka']}")
                    st.markdown(z["tekst_zadatka_latex"])
                    if z["ponudjeni_odgovori"]:
                        st.markdown(prikazi_opcije_markdown(z["ponudjeni_odgovori"]))
                    if z.get("konacan_odgovor"):
                        st.markdown(f"**Rješenje (konačan odgovor):** {_prikazi_bez_dolar(z['konacan_odgovor'])}")
                    with st.expander("✏️ Uredi (tekst, odgovori, slika, puni postupak, status)"):
                        st.text_area("Tekst zadatka", value=z["tekst_zadatka_latex"], key=pref + "tekst", height=100)
                        if z["tip_zadatka"] == "visestruki_izbor" or z["ponudjeni_odgovori"]:
                            st.text_input(
                                "Ponuđeni odgovori (odvoji s ||)", value=" || ".join(z["ponudjeni_odgovori"]), key=pref + "opcije",
                            )
                        c1, c2 = st.columns(2)
                        c1.text_input("Konačan odgovor", value=z["konacan_odgovor"], key=pref + "odgovor")
                        c2.text_input("Oznaka slike (slika_url, npr. SLIKA_08)", value=z["slika_url"], key=pref + "slika")
                        st.text_area("Rješenje (puni postupak)", value=z.get("rjesenje", ""), key=pref + "rjesenje", height=80)
                        st.text_input("status_provjere (isprazni kad ispraviš)", value=z["status_provjere"], key=pref + "status")
            if len(_za_kartice) > _prikaz:
                if st.button(f"⬇️ Prikazi jos ({len(_za_kartice) - _prikaz} preostalo)",
                             key=f"jos_kartica_{baza_kljuc}"):
                    st.session_state[_kljuc_prikaz] = _prikaz + 20
                    st.rerun()

            if st.button("💾 Spremi izmjene u ovaj izvor", key=f"spremi_izmjene_{baza_kljuc}"):
                # Prvo tablica (metapodaci), pa kartice (tekst/slike) - kartice imaju zadnju rijec
                # nad poljima koja uredjuju obje, jer ih covjek tamo gleda zajedno s tekstom.
                _po_broju = {str(r["br"]): r for r in _r_grid}
                for z in iz["zadaci"]:
                    r = _po_broju.get(str(z["privremeni_broj"]))
                    if r is None:
                        continue  # zadatak skriven filterom "samo upozorenja" - ne diraj
                    z["unesi"] = bool(r["unesi"])
                    z["tip_zadatka"] = str(r["tip"] or "").strip()
                    z["cjelina"] = str(r["cjelina"] or "").strip()
                    z["potpoglavlje"] = str(r["potpoglavlje"] or "").strip()
                    z["tezina"] = str(r["tezina"] or "").strip()
                    z["max_bodovi"] = str(r["bodovi"] or "").strip()
                    z["konacan_odgovor"] = str(r["odgovor"] or "").strip()
                    z["status_provjere"] = str(r["upozorenje"] or "").strip()
                for z in iz["zadaci"]:
                    broj = z["privremeni_broj"]
                    pref = f"ured_{baza_kljuc}_{broj}_"
                    if pref + "tekst" not in st.session_state:
                        continue  # zadatak trenutno skriven filterom "samo upozorenja" - ne diraj
                    novi_tekst = st.session_state[pref + "tekst"]
                    z["tekst_zadatka_latex"] = novi_tekst
                    z["tekst_zadatka_mathjax"] = novi_tekst.replace("\\\\", "<br>")
                    if pref + "opcije" in st.session_state:
                        z["ponudjeni_odgovori"] = [o.strip() for o in st.session_state[pref + "opcije"].split("||") if o.strip()]
                    z["konacan_odgovor"] = st.session_state[pref + "odgovor"]
                    nova_slika = st.session_state[pref + "slika"].strip()
                    z["slika_url"] = nova_slika
                    if nova_slika:
                        z["slika_zadana"] = "da"
                    z["rjesenje"] = st.session_state[pref + "rjesenje"]
                    z["status_provjere"] = st.session_state[pref + "status"]
                try:
                    drive_io().spremi_json(None, None, iz, postojeci_id=baza_kljuc)
                    st.success("✅ Izmjene spremljene - korak 3 ('Upiši u bazu') sad koristi ovu, ispravljenu verziju.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"Spremanje nije uspjelo: {e}")

with tab3:
    evid = [r for r in uf.ucitaj_evidenciju(ws_evid) if r.get("izlaz_file_id")]
    if not evid:
        st.info("Nema ničega za upis.")
    else:
        opcije = [f"{r['grupa']} · {r['model']} ({r['broj_jedinica']} jedinica, {r['broj_upozorenja']} upozorenja)" for r in evid]
        # 29.10.2026.: VIŠESTRUKI odabir (Caki - "da izaberem više poglavlja zadaci i primjeri
        # da ne moram pojedinačno birati") - multiselect umjesto selectbox. Kod JEDNOG odabira
        # ponašanje je IDENTIČNO kao prije (izvor_naziv/tip/godina editabilni) - regresijska
        # garancija, nema promjene za postojeći tijek rada. Kod VIŠE odabranih, izvor_naziv/
        # izvor_tip/godina se NE prikazuju kao zajednička polja za uređivanje (svaka grupa ima
        # svoj, već upisan kod obrade u Tab 1/2 - uređuju se tamo ako treba) - prikazuje se samo
        # pregledna tablica, a razina/biblioteka/primjer_na_satu/samo_cisti su ZAJEDNIČKI za sve
        # odabrane (pretpostavka: ista knjiga/isto poglavlje, isti stupanj) - upis ide redom,
        # grupa po grupa, jedna greška ne prekida ostale (svaka grupa je zaseban try/except).
        odabrani_idx = st.multiselect(
            "Što upisati (odaberi jedan ili više izvora odjednom)",
            range(len(evid)), format_func=lambda k: opcije[k], key="upis_odabrani_idx",
        )
        if not odabrani_idx:
            st.info("Odaberi bar jedan izvor iznad.")
        elif len(odabrani_idx) == 1:
            # --- JEDAN odabran: STARO ponašanje, bez promjene ---
            i = odabrani_idx[0]
            r = evid[i]
            iz = ucitaj_izlaz(r["izlaz_file_id"])
            st.write(f"Izvor: **{iz['izvor']['izvor_naziv']}** · tip {iz['izvor']['izvor_tip']} · godina {iz['izvor']['godina'] or '—'}")
            c1, c2, c3 = st.columns(3)
            izvor_naziv = c1.text_input("izvor_naziv", iz["izvor"]["izvor_naziv"])
            izvor_tip = c2.selectbox("izvor_tip", uf.IZVOR_TIPOVI, index=uf.IZVOR_TIPOVI.index(iz["izvor"]["izvor_tip"]))
            godina = c3.text_input("godina", iz["izvor"]["godina"])
            razina = st.selectbox("razina", predmet_config.razine(predmet))
            biblioteka = st.selectbox("Biblioteka izvora (neobavezno)", [""] + list(get_biblioteke_izvora(sheet)))
            primjer_na_satu = st.checkbox(
                "📘 Cijela ova serija su primjeri (koristi_kao_primjer_na_satu)", value=False,
                help="Uključi SAMO ako je cijeli ovaj izvor serija riješenih primjera (npr. udžbenički \"Primjer 1./2./3.\" "
                     "blok s rješenjem), ne zadaci za samostalnu vježbu. Postavlja koristi_kao_primjer_na_satu=\"da\" na SVE "
                     "zadatke ovog upisa - u PreTeXt izlazu idu kao primjer (§27.3), a Test Builder ih svejedno prikazuje "
                     "jednako kao i sve ostale (ne isključuje ih iz pretrage).")
            samo_cisti = st.checkbox("Upiši samo zadatke BEZ upozorenja", value=False)
            # 12.11.2026.: kvačica "unesi" iz pregledne tablice (korak 2). Zadaci bez te kvačice
            # NE idu u bazu; odznačena skupina povlači i svoje stavke (v. uf.primijeni_odabir).
            _odznaceno = sum(1 for z in iz["zadaci"] if not z.get("unesi", True))
            if _odznaceno:
                st.caption(f"✓ U pregledu je {_odznaceno} zadataka odznačeno — oni se neće upisati.")
            if iz.get("nepotpuno"):
                st.warning("Odgovor modela je bio nepotpun — provjeri da nedostaju zadnji zadaci.")
            if st.button("✅ Upiši u bazu", type="primary"):
                try:
                    dio = drive_io()
                    slike_folder = predmet_config.slike_folder_id(predmet, st.secrets)
                    zad, _por_odabir = uf.primijeni_odabir(
                        [z for z in iz["zadaci"] if not (samo_cisti and z["status_provjere"])])
                    for _p in _por_odabir:
                        st.caption(f"• {_p}")
                    if not zad:
                        st.warning("Nijedan zadatak nije označen za upis — ništa nije upisano.")
                        st.stop()
                    with st.spinner("Kopiram slike i upisujem..."):
                        zad = uf.pripremi_za_upis(zad, iz["mapa_slika"], izvor_naziv, dio, slike_folder)
                        dodano, azur = nadopuni_ili_dodaj_zadatke(
                            ws_zadaci, zad, izvor_tip, izvor_naziv, godina, razina, max(1, len((r.get("datoteke") or "").split("; "))),
                            skenirano=iz.get("skenirano", "da"), biblioteka_izvora=biblioteka,
                            koristi_kao_primjer_na_satu=("da" if primjer_na_satu else ""))
                    uf.zapisi_evidenciju(ws_evid, {"grupa": r["grupa"], "model": r["model"], "status": "uneseno", "otisak": r["otisak"],
                                                   "dodano": dodano, "nadopunjeno": azur})
                    st.success(f"✅ Dodano {dodano}, nadopunjeno {azur}.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"Upis nije uspio: {e}")
        else:
            # --- VIŠE odabrano: zajedničke postavke, upis redom za svaku grupu ---
            odabrani = [evid[k] for k in odabrani_idx]
            pregled_rows = []
            for r in odabrani:
                iz_r = ucitaj_izlaz(r["izlaz_file_id"])
                pregled_rows.append({
                    "grupa": r["grupa"], "model": r["model"],
                    "izvor_naziv": iz_r["izvor"]["izvor_naziv"], "izvor_tip": iz_r["izvor"]["izvor_tip"],
                    "godina": iz_r["izvor"]["godina"] or "—",
                    "jedinica": r["broj_jedinica"], "upozorenja": r["broj_upozorenja"],
                })
            st.dataframe(pd.DataFrame(pregled_rows), hide_index=True, width="stretch")
            st.caption("izvor_naziv / izvor_tip / godina se NE uređuju ovdje kod više odabranih izvora - "
                       "koriste se onakvi kakvi su već zapisani kod obrade (Tab 1/2). Ako nešto od toga treba "
                       "promijeniti, odaberi SAMO taj jedan izvor gore (vraća se stari način s poljima za uređivanje).")
            razina = st.selectbox("razina (zajednička za sve odabrane)", predmet_config.razine(predmet), key="upis_vise_razina")
            biblioteka = st.selectbox(
                "Biblioteka izvora (neobavezno, zajednička za sve odabrane)",
                [""] + list(get_biblioteke_izvora(sheet)), key="upis_vise_biblioteka",
            )
            primjer_na_satu = st.checkbox(
                "📘 Cijela ova serija su primjeri (koristi_kao_primjer_na_satu) - za SVE odabrane",
                value=False, key="upis_vise_primjer",
                help="Postavlja koristi_kao_primjer_na_satu=\"da\" na SVE zadatke iz SVIH odabranih izvora.",
            )
            samo_cisti = st.checkbox(
                "Upiši samo zadatke BEZ upozorenja - za SVE odabrane", key="upis_vise_samo_cisti",
            )
            if st.button(f"✅ Upiši svih {len(odabrani)} odabranih izvora u bazu", type="primary", key="upis_vise_gumb"):
                dio = drive_io()
                slike_folder = predmet_config.slike_folder_id(predmet, st.secrets)
                ukupno_dodano = 0
                ukupno_azur = 0
                rezultati = []
                with st.spinner(f"Kopiram slike i upisujem ({len(odabrani)} izvora)..."):
                    for r in odabrani:
                        try:
                            iz_r = ucitaj_izlaz(r["izlaz_file_id"])
                            zad, _por_odabir = uf.primijeni_odabir(
                                [z for z in iz_r["zadaci"] if not (samo_cisti and z["status_provjere"])])
                            if not zad:
                                rezultati.append(f"⏭️ {r['grupa']} · {r['model']}: nijedan zadatak nije označen za upis")
                                continue
                            zad = uf.pripremi_za_upis(zad, iz_r["mapa_slika"], iz_r["izvor"]["izvor_naziv"], dio, slike_folder)
                            dodano, azur = nadopuni_ili_dodaj_zadatke(
                                ws_zadaci, zad, iz_r["izvor"]["izvor_tip"], iz_r["izvor"]["izvor_naziv"],
                                iz_r["izvor"]["godina"], razina, max(1, len((r.get("datoteke") or "").split("; "))),
                                skenirano=iz_r.get("skenirano", "da"), biblioteka_izvora=biblioteka,
                                koristi_kao_primjer_na_satu=("da" if primjer_na_satu else ""))
                            uf.zapisi_evidenciju(ws_evid, {"grupa": r["grupa"], "model": r["model"], "status": "uneseno",
                                                           "otisak": r["otisak"], "dodano": dodano, "nadopunjeno": azur})
                            ukupno_dodano += dodano
                            ukupno_azur += azur
                            rezultati.append(
                                f"✅ {r['grupa']} · {r['model']}: dodano {dodano}, nadopunjeno {azur}"
                                + (f" ({' '.join(_por_odabir)})" if _por_odabir else ""))
                        except Exception as e:  # noqa: BLE001
                            rezultati.append(f"❌ {r['grupa']} · {r['model']}: GREŠKA - {e}")
                st.success(f"Ukupno: dodano {ukupno_dodano}, nadopunjeno {ukupno_azur} (od {len(odabrani)} odabranih izvora).")
                for poruka in rezultati:
                    st.write(poruka)
