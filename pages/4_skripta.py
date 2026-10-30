"""
CAKI Matematika - pages/4_skripta.py (30.10.2026.)

DVA NAČINA RADA (radio na vrhu stranice):

1. 📗 Iz knjige (jednostavno) - za skriptu iz JEDNE knjige/zbirke (npr. "ŠK-Matematika na
   maturi"). Popis poglavlja se sam pronađe u bazi (izvor_naziv "PoglavljeX.Y_primjeri" /
   "PoglavljeX.Y_zadaci"), Caki poreda poglavlja, upiše nazive, pojedinačno označi koje
   primjere/zadatke želi i po potrebi promijeni tip (Primjer / Zadatak - upisuje se u bazu,
   vrijedi i za buduće skripte). Generiraju se DVIJE verzije PDF-a:
     - za učenike: primjeri BEZ rješenja, zadaci BEZ rješenja + rješenja zadataka na kraju
     - za profesora: isto + konačni odgovori primjera na kraju („Primjeri rješenja”)
   Gradnja ide preko GitHub Actions (PreTeXt -> XeLaTeX), isto kao dosad.

2. ⚙️ Napredni filtri - STARIJI način (razina/cjelina/izvor/biblioteka/godina). Ostaje
   nepromijenjen da ništa postojeće ne pukne; nazivi i redoslijed poglavlja se i tamo čitaju
   iz istog taba.

TEMELJ JE CLAUDEOV RAD od 29.10.2026. (commit 9009e10 + overparen fix d2579eb): tab
'Sifrarnik_poglavlja_knjige' (poglavlje_kljuc, naslov_prikaz, redoslijed), get_naslovi_poglavlja,
get_redoslijed_poglavlja, spremi_naslove_poglavlja, _poglavlje_sort_key_s_redoslijedom i
kronološki build u baza_zadataka_pipeline.py / skripta_build.py. Ova stranica ne gradi PDF
u Streamlitu (xelatex je pretežak za hosting) - samo sprema plan i pokreće GitHub radnika.
"""
import json
import re

import pandas as pd
import streamlit as st

import predmet_config
from baza_zadataka_pipeline import (
    _je_primjer_na_satu,          # isti kriterij kao build (kvačica ILI naziv serije)
    _je_primjer_za_skriptu,       # isto + lokalna promjena tipa iz plana (primjer <-> zadatak)
    _poglavlje_sort_key,          # prirodni poredak 2.9 < 2.10 (Claude, 28.10.)
    get_drive_service,
    get_gspread_client,
    get_naslovi_poglavlja,
    get_odabir_poglavlja,
    get_redoslijed_poglavlja,
    get_sifrarnik_cjelina,
    parsiraj_poglavlje_iz_izvora,
    pokreni_github_build_skripte,
    popis_zahtjeva_skripte,
    preuzmi_datoteku_iz_drivea,
    spremi_naslove_poglavlja,
    spremi_tipove_zadataka,
    spremi_zahtjev_skripte,
    ucitaj_zadnji_zahtjev_skripte,
)
from filtriraj_zadatke_za_skriptu import filtriraj_zadatke, opis_filtara

import secrets_json as _sj  # 21.10.2026.: tolerantno čitanje JSON-a iz Secrets

st.set_page_config(page_title="CAKI Skripta", page_icon="📘", layout="wide")

ZADANA_KNJIGA = "ŠK-Matematika na maturi"
_STATUS_OZNAKA = {"cekanje": "⏳ čeka", "u_radu": "🛠️ u izradi", "gotovo": "✅ gotovo",
                  "greska": "❌ greška"}


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao u app.py, 2_test_builder.py, 3_teorija.py)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_skripta") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_skripta"] = True
        else:
            st.session_state["autoriziran_skripta"] = False

    if st.session_state.get("autoriziran_skripta"):
        return True

    st.title("📘 CAKI Skripta")
    st.text_input("Lozinka", type="password", key="lozinka_unos_skripta", on_change=na_unos)
    if st.session_state.get("autoriziran_skripta") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------
# Google Sheets / Drive (jedan Sheet po predmetu, v. predmet_config.py)
# ---------------------------------------------------------------

PREDMET = predmet_config.odaberi_predmet(st)


@st.cache_resource
def _init_sheet_za(predmet):
    sa_info = _sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(predmet_config.sheet_id(predmet, st.secrets))


def init_sheet():
    return _init_sheet_za(PREDMET)


@st.cache_resource
def _init_drive_za(predmet):
    return get_drive_service(_sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON"))


def init_drive():
    return _init_drive_za(PREDMET)


@st.cache_data(ttl=600)
def _ucitaj_zadatke_za(predmet):
    """Svi retci taba Zadaci (17k+) - keširani 10 min; stranica ih filtrira u memoriji."""
    return _init_sheet_za(predmet).worksheet("Zadaci").get_all_records()


def ucitaj_zadatke():
    return _ucitaj_zadatke_za(PREDMET)


@st.cache_data(ttl=60)
def _ucitaj_plan_za(predmet):
    """Nazivi + redoslijed + pojedinačni odabir poglavlja iz taba Sifrarnik_poglavlja_knjige."""
    sheet = _init_sheet_za(predmet)
    return {
        "naslovi": get_naslovi_poglavlja(sheet),
        "redoslijed": get_redoslijed_poglavlja(sheet),
        "odabir": get_odabir_poglavlja(sheet),
    }


def ucitaj_plan():
    return _ucitaj_plan_za(PREDMET)


@st.cache_data(ttl=3600)
def _ucitaj_cjeline_za(predmet):
    return sorted(get_sifrarnik_cjelina(_init_sheet_za(predmet)).keys())


def ucitaj_cjeline():
    return _ucitaj_cjeline_za(PREDMET)


# ---------------------------------------------------------------
# Mali pomoćnici za prikaz
# ---------------------------------------------------------------

def _cist_tekst(tekst: str) -> str:
    return " ".join(str(tekst or "").split()).strip()


def _preview(tekst, najvise: int = 110) -> str:
    """Kratki pregled teksta zadatka za tablicu (data_editor ne renderira LaTeX)."""
    t = str(tekst or "")
    t = re.sub(r"\\[a-zA-Z]+\*?", "", t)      # \frac, \cdot, \begin ... ostavljaju smeće
    t = t.replace("$", "").replace("{", "").replace("}", "").replace("\\", "")
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:najvise] + "…") if len(t) > najvise else t


def _serija_broj(id_zadatka):
    """Redni broj iz id-a ('Poglavlje2.14_zadaci_006' -> 6), ili None."""
    m = re.search(r"_(\d+)\s*$", str(id_zadatka or ""))
    return int(m.group(1)) if m else None


def _kljuc_za_poredak(kljuc, redoslijed):
    rucni = (redoslijed or {}).get(kljuc)
    if rucni is not None:
        return (0, rucni, str(kljuc).lower())
    return (1,) + _poglavlje_sort_key(kljuc)


def _grupisi_po_poglavlju(redovi, knjiga):
    """{poglavlje_kljuc: {"primjeri": [...], "zadaci": [...]}} za JEDNU knjigu.
    Redoslijed redaka unutar grupe = redoslijed u Sheetu (Cakijev uvjet: ne mijenjati)."""
    knjiga_norm = _cist_tekst(knjiga).lower()
    grupe = {}
    for r in redovi:
        if knjiga_norm and _cist_tekst(r.get("biblioteka_izvora")).lower() != knjiga_norm:
            continue
        kljuc = _cist_tekst(parsiraj_poglavlje_iz_izvora(r.get("izvor_naziv", "")))
        if not kljuc:
            continue
        grupa = grupe.setdefault(kljuc, {"primjeri": [], "zadaci": []})
        grupa["primjeri" if _je_primjer_na_satu(r) else "zadaci"].append(r)
    return grupe


def _odabrani_broj(redovi, izbor) -> int:
    if izbor is None:
        return len(redovi)
    skup = {str(x) for x in izbor}
    return sum(1 for r in redovi if str(r.get("id", "")) in skup)


def _tip_efektivni(red, tipovi) -> str:
    """'primjer' ili 'zadatak' za OVU skriptu (lokalna promjena ima prednost nad bazom)."""
    return "primjer" if _je_primjer_za_skriptu(red, tipovi) else "zadatak"


def _podijeli_po_tipu(grupa, tipovi):
    """(primjeri, zadaci) poglavlja prema EFEKTIVNOM tipu (uz lokalne promjene).
    Redoslijed unutar svake skupine ostaje redoslijed iz baze."""
    primjeri, zadaci = [], []
    for red in (grupa.get("primjeri") or []) + (grupa.get("zadaci") or []):
        (primjeri if _tip_efektivni(red, tipovi) == "primjer" else zadaci).append(red)
    return primjeri, zadaci


def _lista_odabranih(redovi, izbor):
    if izbor is None:
        return [str(r.get("id", "")) for r in redovi]
    skup = {str(x) for x in izbor}
    return [str(r.get("id", "")) for r in redovi if str(r.get("id", "")) in skup]


# ---------------------------------------------------------------
# Plan poglavlja (session_state) + spremanje u Sheet
# ---------------------------------------------------------------

def _pocetni_plan(grupe, spremljeno):
    naslovi = spremljeno["naslovi"]
    redoslijed = spremljeno["redoslijed"]
    odabir = spremljeno["odabir"]
    plan = []
    for kljuc in sorted(grupe, key=lambda k: _kljuc_za_poredak(k, redoslijed)):
        o = odabir.get(kljuc) or {}
        plan.append({
            "kljuc": kljuc,
            "naslov": naslovi.get(kljuc, ""),
            "redoslijed": redoslijed.get(kljuc, float((len(plan) + 1) * 10)),
            "ukljuceno": o.get("ukljuceno", True),
            "primjeri": o.get("primjeri", None),
            "zadaci": o.get("zadaci", None),
            # 30.10.2026.: {id: "primjer"|"zadatak"} - lokalna promjena tipa za ovu skriptu.
            "tipovi": dict(o.get("tipovi") or {}),
        })
    return plan


def _zapisi_za_spremanje(plan, spremljeno):
    """Svi retci za tab Sifrarnik_poglavlja_knjige: poglavlja OVE knjige iz plana + sva
    ostala poglavlja koja su već u tabu (druge knjige) - da se prebacivanjem knjige ne
    izbrišu tuđi nazivi i odabiri."""
    izlaz = []
    kljucevi_plana = {p["kljuc"] for p in plan}
    for p in plan:
        odabir = {}
        if p["primjeri"] is not None:
            odabir["primjeri"] = list(p["primjeri"])
        if p["zadaci"] is not None:
            odabir["zadaci"] = list(p["zadaci"])
        izlaz.append({
            "poglavlje_kljuc": p["kljuc"],
            "naslov_prikaz": _cist_tekst(p["naslov"]),
            "redoslijed": p["redoslijed"],
            "odabir_json": json.dumps(odabir, ensure_ascii=False) if odabir else "",
            "ukljuceno": "da" if p["ukljuceno"] else "ne",
            # 30.10.2026.: lokalna promjena tipa (primjer <-> zadatak) samo za ovu skriptu.
            "tipovi_json": json.dumps(p["tipovi"], ensure_ascii=False) if p.get("tipovi") else "",
        })
    for kljuc in sorted(set(spremljeno["naslovi"]) | set(spremljeno["redoslijed"])
                        | set(spremljeno["odabir"])):
        if kljuc in kljucevi_plana:
            continue
        o = spremljeno["odabir"].get(kljuc) or {}
        odabir = {}
        if o.get("primjeri") is not None:
            odabir["primjeri"] = list(o["primjeri"])
        if o.get("zadaci") is not None:
            odabir["zadaci"] = list(o["zadaci"])
        izlaz.append({
            "poglavlje_kljuc": kljuc,
            "naslov_prikaz": spremljeno["naslovi"].get(kljuc, ""),
            "redoslijed": spremljeno["redoslijed"].get(kljuc, ""),
            "odabir_json": json.dumps(odabir, ensure_ascii=False) if odabir else "",
            "ukljuceno": "da" if o.get("ukljuceno", True) else "ne",
            "tipovi_json": json.dumps(o.get("tipovi") or {}, ensure_ascii=False) if o.get("tipovi") else "",
        })
    return izlaz


def _spremi_plan(plan, spremljeno) -> bool:
    try:
        spremi_naslove_poglavlja(init_sheet(), _zapisi_za_spremanje(plan, spremljeno))
        _ucitaj_plan_za.clear()
        return True
    except Exception as e:  # noqa: BLE001
        st.error(f"Ne mogu spremiti plan poglavlja: {e}")
        return False


def _spremi_sve(plan, spremljeno) -> bool:
    """Spremi plan + promjene tipa trajno u bazu (koristi_kao_primjer_na_satu).

    Promjena tipa iz plana ('tipovi') upisuje se u tab 'Zadaci': "da" = primjer, "ne" =
    zadatak. Time vrijedi i za SVE buduće skripte, ne samo za ovu. Ako upis u bazu ne uspije,
    lokalni 'tipovi' ostaju pa se ova skripta i dalje gradi ispravno, ali se prikazuje greška
    (buduće skripte neće imati promjenu dok se ne upiše)."""
    if not _spremi_plan(plan, spremljeno):
        return False
    promjene = {}
    for p in plan:
        for zadatak_id, tip in (p.get("tipovi") or {}).items():
            promjene[str(zadatak_id)] = tip
    if not promjene:
        return True
    try:
        broj = spremi_tipove_zadataka(init_sheet(), promjene)
    except Exception as e:  # noqa: BLE001
        st.error(f"Tipovi nisu upisani u bazu: {e}. Za ovu skriptu i dalje vrijede lokalno, "
                 f"ali buduće skripte neće imati promjenu dok se ne upiše.")
        return True
    if not broj:
        st.warning("Nijedan zadatak nije pronađen u tabu 'Zadaci' — tip nije upisan u bazu.")
        return True
    if broj < len(promjene):
        st.warning(f"U bazu je upisano {broj} od {len(promjene)} promjena — ostali id-evi nisu "
                   f"pronađeni u tabu 'Zadaci'; za njih promjena ostaje samo lokalna.")
        return True
    # Uspješno upisano u bazu -> lokalni override više ne treba (baza je sada izvor istine).
    for p in plan:
        p["tipovi"] = {}
    _spremi_plan(plan, spremljeno)
    _ucitaj_zadatke_za.clear()
    st.info(f"✅ Tip upisan u bazu za {broj} zadataka — vrijedi i za buduće skripte.")
    return True


# ---------------------------------------------------------------
# 1. SKRIPTA IZ KNJIGE
# ---------------------------------------------------------------

def _skripta_iz_knjige():
    st.subheader("📗 Skripta iz knjige")
    st.caption(
        "Poglavlja se pronalaze sama iz baze (naziv serije `PoglavljeX.Y_primjeri` / "
        "`PoglavljeX.Y_zadaci`). Ti poredaš poglavlja, upišeš nazive i pojedinačno označiš "
        "primjere/zadatke. U PDF-u svako poglavlje počinje na novoj stranici, ima vidljive "
        "skupine **Primjeri** i **Zadaci za vježbu**, a na kraju **Rješenja**: učenici dobiju "
        "samo rješenja zadataka, a tvoja verzija još i konačne odgovore primjera."
    )

    try:
        svi = ucitaj_zadatke()
    except Exception as e:  # noqa: BLE001
        st.error(f"Ne mogu učitati tab Zadaci: {e}")
        return

    knjige = sorted({_cist_tekst(r.get("biblioteka_izvora")) for r in svi
                     if _cist_tekst(r.get("biblioteka_izvora"))})
    if not knjige:
        st.warning("U tabu 'Zadaci' nema nijedne biblioteke izvora (`biblioteka_izvora`). "
                   "Popuni taj stupac pri uvozu (npr. „ŠK-Matematika na maturi”).")
        return

    zadana = next((k for k in knjige if k.lower() == ZADANA_KNJIGA.lower()), knjige[0])
    knjiga = st.selectbox("Knjiga / biblioteka izvora", knjige, index=knjige.index(zadana),
                          key="skripta_knjiga_odabir",
                          help="Samo redci s tom vrijednošću u stupcu biblioteka_izvora ulaze u skriptu.")

    grupe = _grupisi_po_poglavlju(svi, knjiga)
    if not grupe:
        st.warning(f"Za knjigu „{knjiga}” nema redaka s prepoznatljivim nazivom poglavlja "
                   f"(npr. „Poglavlje2.14_primjeri”).")
        return

    try:
        spremljeno = ucitaj_plan()
    except Exception as e:  # noqa: BLE001
        st.warning(f"Ne mogu učitati postojeće nazive/redoslijed: {e}")
        spremljeno = {"naslovi": {}, "redoslijed": {}, "odabir": {}}

    stanje_kljuc = f"skripta_knjiga_plan_{PREDMET}_{knjiga}"
    if stanje_kljuc not in st.session_state:
        st.session_state[stanje_kljuc] = _pocetni_plan(grupe, spremljeno)
    plan = st.session_state[stanje_kljuc]

    # Novo uvezeno poglavlje (npr. Caki je upravo dodao Poglavlje2.15) - dodaj na kraj,
    # bez brisanja onoga sto je Caki vec podesio.
    postojeci_kljucevi = {p["kljuc"] for p in plan}
    novi = [k for k in grupe if k not in postojeci_kljucevi]
    if novi:
        for k in sorted(novi, key=lambda x: _kljuc_za_poredak(x, spremljeno["redoslijed"])):
            plan.append({"kljuc": k, "naslov": spremljeno["naslovi"].get(k, ""),
                         "redoslijed": float((len(plan) + 1) * 10), "ukljuceno": True,
                         "primjeri": None, "zadaci": None, "tipovi": {}})
        st.info(f"Novo u bazi: {len(novi)} poglavlje(a) dodano na kraj popisa.")

    # 30.10.2026.: brojevi idu po EFEKTIVNOM tipu (lokalna promjena primjer <-> zadatak).
    _po_tipu = {p["kljuc"]: _podijeli_po_tipu(grupe.get(p["kljuc"], {}), p["tipovi"])
                for p in plan}
    ukupno_p = sum(len(v[0]) for v in _po_tipu.values())
    ukupno_z = sum(len(v[1]) for v in _po_tipu.values())
    m1, m2, m3 = st.columns(3)
    m1.metric("Poglavlja", len(grupe))
    m2.metric("Primjera", ukupno_p)
    m3.metric("Zadataka", ukupno_z)

    st.markdown("###### 1. Poredaj poglavlja i upiši nazive")
    st.caption(
        "**Redoslijed**: manji broj = ranije u skripti. Najbrže: promijeni broj samo onom "
        "poglavlju koje mijenja mjesto (decimalno je dopušteno, npr. 15 ide između 10 i 20). "
        "**Naziv**: ono što piše u PDF-u; prazno = sirovi ključ (npr. „Poglavlje2.14”). "
        "**Uključi**: isključeno poglavlje ne ide u PDF."
    )

    tablica = pd.DataFrame([{
        "Uključi": bool(p["ukljuceno"]),
        "Poglavlje": p["kljuc"],
        "Naziv u PDF-u": p["naslov"],
        "Primjeri": f"{_odabrani_broj(_po_tipu[p['kljuc']][0], p['primjeri'])}"
                    f" / {len(_po_tipu[p['kljuc']][0])}",
        "Zadaci": f"{_odabrani_broj(_po_tipu[p['kljuc']][1], p['zadaci'])}"
                  f" / {len(_po_tipu[p['kljuc']][1])}",
        "Redoslijed": float(p["redoslijed"]),
    } for p in plan])

    verzija_tablice = st.session_state.get(f"{stanje_kljuc}_v", 0)
    uredeno = st.data_editor(
        tablica, hide_index=True, use_container_width=True,
        key=f"skripta_knjiga_tablica_{PREDMET}_{knjiga}_{verzija_tablice}",
        column_config={
            "Uključi": st.column_config.CheckboxColumn("Uključi", width="small"),
            "Poglavlje": st.column_config.TextColumn("Poglavlje", disabled=True, width="small"),
            "Naziv u PDF-u": st.column_config.TextColumn("Naziv u PDF-u", width="large"),
            "Primjeri": st.column_config.TextColumn("Primjeri", disabled=True, width="small",
                                                    help="odabrano / ukupno"),
            "Zadaci": st.column_config.TextColumn("Zadaci", disabled=True, width="small",
                                                  help="odabrano / ukupno"),
            "Redoslijed": st.column_config.NumberColumn(
                "Redoslijed", step=1, format="%g", width="small",
                help="Manji broj = ranije. Decimalno dopušteno (npr. 15 između 10 i 20)."),
        },
    )
    if isinstance(uredeno, pd.DataFrame) and len(uredeno) == len(plan):
        for p, (_, redak) in zip(plan, uredeno.iterrows()):
            p["ukljuceno"] = bool(redak.get("Uključi", True))
            p["naslov"] = str(redak.get("Naziv u PDF-u") or "")
            try:
                p["redoslijed"] = float(redak.get("Redoslijed"))
            except (TypeError, ValueError):
                pass

    k1, k2 = st.columns([1, 2])
    with k1:
        if st.button("🔀 Primijeni redoslijed", use_container_width=True,
                     help="Sortiraj tablicu po stupcu Redoslijed."):
            plan.sort(key=lambda p: (float(p["redoslijed"]), _poglavlje_sort_key(p["kljuc"])))
            st.session_state[f"{stanje_kljuc}_v"] = verzija_tablice + 1
            st.rerun()
    with k2:
        if st.button("💾 Spremi plan i tipove u bazu", use_container_width=True):
            if _spremi_sve(plan, spremljeno):
                st.success("✅ Spremljeno (plan u 'Sifrarnik_poglavlja_knjige', tipovi u 'Zadaci').")

    # ---------------- 2. pojedinačni odabir primjera/zadataka ----------------
    st.markdown("###### 2. Označi što ide u skriptu (pojedinačno)")
    kljucevi = [p["kljuc"] for p in sorted(plan, key=lambda p: (float(p["redoslijed"]),
                                                                _poglavlje_sort_key(p["kljuc"])))]
    if not kljucevi:
        return

    def _po_tipu_za(k):
        p = next((x for x in plan if x["kljuc"] == k), None)
        return _podijeli_po_tipu(grupe.get(k, {}), (p or {}).get("tipovi") or {})

    odabrano = st.selectbox(
        "Poglavlje", kljucevi, key=f"skripta_knjiga_detalj_{PREDMET}_{knjiga}",
        format_func=lambda k: (
            f"{(next((p['naslov'] for p in plan if p['kljuc'] == k), '') or k)} "
            f"— {len(_po_tipu_za(k)[0])} primjera, {len(_po_tipu_za(k)[1])} zadataka"))
    pogl = next(p for p in plan if p["kljuc"] == odabrano)
    grupa = grupe.get(odabrano, {"primjeri": [], "zadaci": []})
    svi_redovi = (grupa.get("primjeri") or []) + (grupa.get("zadaci") or [])
    if not svi_redovi:
        st.info("Ovo poglavlje nema nijedan redak u bazi.")
        return

    # 30.10.2026.: redak ima EFEKTIVNI tip (plan može promijeniti primjer <-> zadatak).
    # Tablica je poredana po efektivnom tipu (prvo primjeri, pa zadaci), a unutar skupine
    # ostaje redoslijed iz baze; kad Caki promijeni Tip, redak se premjesti na sljedećem
    # rerunu. "_tip_baza" pamti tip iz baze da se zna je li promjena uopće potrebna.
    opisani = []
    for idx, r in enumerate(svi_redovi):
        tip_ef = _tip_efektivni(r, pogl["tipovi"])
        tip_baza = "primjer" if _je_primjer_na_satu(r) else "zadatak"
        opisani.append((0 if tip_ef == "primjer" else 1, idx, r, tip_ef, tip_baza))
    opisani.sort(key=lambda x: (x[0], x[1]))

    izbor_p = set(_lista_odabranih([x[2] for x in opisani if x[3] == "primjer"], pogl["primjeri"]))
    izbor_z = set(_lista_odabranih([x[2] for x in opisani if x[3] == "zadatak"], pogl["zadaci"]))

    stavke = []
    for poz, (_, _, r, tip_ef, tip_baza) in enumerate(opisani, start=1):
        rid = str(r.get("id", ""))
        ima_rjesenje = bool(str(r.get("rjesenje") or r.get("konacan_odgovor") or "").strip())
        stavke.append({
            "Uključi": rid in (izbor_p if tip_ef == "primjer" else izbor_z),
            "Tip": "Primjer" if tip_ef == "primjer" else "Zadatak",
            "#": _serija_broj(rid) or poz,
            "Tekst": _preview(r.get("tekst_zadatka_latex")),
            "Rješenje": "da" if ima_rjesenje else "—",
            "_id": rid,
            "_tip_ef": tip_ef,
            "_tip_baza": tip_baza,
        })

    st.caption("Označeno ulazi u PDF. **Tip** mijenjaš padajućim izborom (Primjer / Zadatak); "
               "**Spremi** ili **Generiraj** upisuje promjenu u bazu (`koristi_kao_primjer_na_"
               "satu`) pa vrijedi i za buduće skripte. Redoslijed u PDF-u je primjeri pa "
               "zadaci, kako su unešeni.")
    df_stavke = pd.DataFrame(stavke)
    verzija_stavke = st.session_state.get(f"{stanje_kljuc}_stavke_v_{odabrano}", 0)
    uredeno_stavke = st.data_editor(
        df_stavke.drop(columns=["_id", "_tip_ef", "_tip_baza"]), hide_index=True,
        use_container_width=True,
        key=f"skripta_knjiga_stavke_{PREDMET}_{knjiga}_{odabrano}_{verzija_stavke}",
        column_config={
            "Uključi": st.column_config.CheckboxColumn("Uključi", width="small"),
            "Tip": st.column_config.SelectboxColumn(
                "Tip", options=["Primjer", "Zadatak"], required=True, width="small",
                help="Sprema se u bazu (koristi_kao_primjer_na_satu) i vrijedi za buduće skripte."),
            "#": st.column_config.NumberColumn("#", disabled=True, width="small"),
            "Tekst": st.column_config.TextColumn("Zadatak (početak)", disabled=True, width="large"),
            "Rješenje": st.column_config.TextColumn("Rješenje", disabled=True, width="small"),
        },
    )
    if isinstance(uredeno_stavke, pd.DataFrame) and len(uredeno_stavke) == len(stavke):
        oznaceno_p, oznaceno_z = [], []
        ukupno_p = ukupno_z = 0
        promijenjen_tip = False
        for osnovni, (_, redak) in zip(stavke, uredeno_stavke.iterrows()):
            novi_tip = ("primjer" if str(redak.get("Tip", "")).strip().lower().startswith("primjer")
                        else "zadatak")
            ukupno_p += 1 if novi_tip == "primjer" else 0
            ukupno_z += 1 if novi_tip == "zadatak" else 0
            rid = osnovni["_id"]
            if novi_tip != osnovni["_tip_ef"]:
                promijenjen_tip = True
            if novi_tip != osnovni["_tip_baza"]:
                pogl["tipovi"][rid] = novi_tip
            else:
                pogl["tipovi"].pop(rid, None)
            if bool(redak.get("Uključi", False)):
                (oznaceno_p if novi_tip == "primjer" else oznaceno_z).append(rid)
        pogl["primjeri"] = (None if len(oznaceno_p) == ukupno_p else oznaceno_p)
        pogl["zadaci"] = (None if len(oznaceno_z) == ukupno_z else oznaceno_z)
        if promijenjen_tip:
            # redak se mora premjestiti u drugu skupinu -> svjez editor s novim poretkom
            st.session_state[f"{stanje_kljuc}_stavke_v_{odabrano}"] = verzija_stavke + 1
            st.rerun()

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        postavi_sve = st.button("✅ Sve", use_container_width=True)
    with b2:
        postavi_nista = st.button("⬜ Ništa", use_container_width=True)
    with b3:
        samo_primjeri = st.button("📝 Samo primjeri", use_container_width=True)
    with b4:
        samo_zadaci = st.button("🧮 Samo zadaci", use_container_width=True)
    if postavi_sve or postavi_nista or samo_primjeri or samo_zadaci:
        if postavi_sve:
            pogl["primjeri"], pogl["zadaci"] = None, None
        elif postavi_nista:
            pogl["primjeri"], pogl["zadaci"] = [], []
        elif samo_primjeri:
            pogl["primjeri"], pogl["zadaci"] = None, []
        else:
            pogl["primjeri"], pogl["zadaci"] = [], None
        st.session_state[f"{stanje_kljuc}_stavke_v_{odabrano}"] = verzija_stavke + 1
        st.rerun()

    # ---------------- 3. naslov i gradnja ----------------
    st.divider()
    st.markdown("###### 3. Naslov i gradnja")
    n1, n2 = st.columns([1, 1])
    with n1:
        naslov = st.text_input("Naslov skripte", value="Skripta za maturu",
                               key=f"skripta_knjiga_naslov_{PREDMET}",
                               help="Verzija za profesora dobiva dodatak „— rješenja”.")
    with n2:
        podnaslov = st.text_input("Podnaslov (neobavezno)", value="",
                                  key=f"skripta_knjiga_podnaslov_{PREDMET}",
                                  placeholder="npr. Priprema za maturu · šk. god. 2026./2027.")

    ukljucena = [p for p in plan if p["ukljuceno"]]
    broj_stavki = sum(
        _odabrani_broj(grupe.get(p["kljuc"], {}).get("primjeri", []), p["primjeri"])
        + _odabrani_broj(grupe.get(p["kljuc"], {}).get("zadaci", []), p["zadaci"])
        for p in ukljucena)
    st.caption(f"U skriptu ulazi **{len(ukljucena)} poglavlja** i **{broj_stavki}** "
               f"primjera/zadataka.")

    token = st.secrets.get("GITHUB_DISPATCH_TOKEN")
    ima_tokena = (bool(token) and bool(st.secrets.get("SKRIPTE_FOLDER_ID"))
                  and PREDMET == predmet_config.ZADANI_PREDMET)
    if not ima_tokena:
        if PREDMET != predmet_config.ZADANI_PREDMET:
            st.warning("Automatska gradnja zasad radi samo za matematiku (GitHub radnik čita "
                       "matematički Sheet). U bočnoj traci odaberi „Matematika”.")
        else:
            st.warning("Automatska gradnja nije uključena (u Streamlit Secrets nedostaje "
                       "`GITHUB_DISPATCH_TOKEN` ili `SKRIPTE_FOLDER_ID`). Dodaj ih pa se gumb aktivira.")

    sto = st.radio("Što generirati", ["Obje verzije", "Samo za učenike", "Samo s rješenjima"],
                   horizontal=True, key="skripta_knjiga_sto")
    verzije = {"Obje verzije": ["ucenik", "profesor"],
               "Samo za učenike": ["ucenik"],
               "Samo s rješenjima": ["profesor"]}[sto]

    if st.button("📄 Generiraj PDF", type="primary", disabled=not ima_tokena or not broj_stavki):
        if not _spremi_sve(plan, spremljeno):
            return
        poslano, greske = [], []
        for verzija in verzije:
            try:
                naslov_v = _cist_tekst(naslov) or "Skripta za maturu"
                if verzija == "profesor":
                    naslov_v += " — rješenja"
                zahtjev_id = spremi_zahtjev_skripte(
                    init_sheet(), verzija_teorije=verzija,
                    filtri={"biblioteke": [knjiga], "grupiraj_po_poglavlju": True},
                    naslov=naslov_v, podnaslov=podnaslov, verzija_sadrzaja=verzija)
                ok, poruka = pokreni_github_build_skripte(token, zahtjev_id)
                if ok:
                    poslano.append((verzija, zahtjev_id))
                else:
                    greske.append(f"{verzija}: {poruka}")
            except Exception as e:  # noqa: BLE001
                greske.append(f"{verzija}: {type(e).__name__}: {e}")
        if poslano:
            st.success("✅ Gradnja pokrenuta: " + ", ".join(f"{v} ({i})" for v, i in poslano)
                       + ". Za 2–4 minute klikni „Osvježi status” i preuzmi PDF.")
        for g in greske:
            st.error(g)
        if poslano:
            st.cache_data.clear()

    with st.expander("🔎 Dijagnostika (ako popis poglavlja ne izgleda kako treba)"):
        redovi_knjige = [r for r in svi
                         if _cist_tekst(r.get("biblioteka_izvora")).lower() == knjiga.lower()]
        bez_poglavlja = [r for r in redovi_knjige
                         if not _cist_tekst(parsiraj_poglavlje_iz_izvora(r.get("izvor_naziv", "")))]
        st.write(f"Redaka za „{knjiga}”: **{len(redovi_knjige)}** · poglavlja: **{len(grupe)}** · "
                 f"bez prepoznatog poglavlja: **{len(bez_poglavlja)}**")
        primjeri_flag = sum(1 for r in redovi_knjige
                            if _cist_tekst(r.get("koristi_kao_primjer_na_satu")).lower() == "da")
        st.write(f"Primjeri prema kvačici: **{primjeri_flag}** · prema kvačici ILI nazivu serije: "
                 f"**{sum(len(g['primjeri']) for g in grupe.values())}**")
        if bez_poglavlja:
            st.caption("Primjeri redaka bez prepoznatog poglavlja (izvor_naziv):")
            st.dataframe(pd.DataFrame({"izvor_naziv": sorted(
                {_cist_tekst(r.get("izvor_naziv")) for r in bez_poglavlja})}), hide_index=True)


# ---------------------------------------------------------------
# 2. NAPREDNI FILTRI (stariji način - ostaje nepromijenjen)
# ---------------------------------------------------------------

def _napredni_filtri():
    st.subheader("⚙️ Napredni filtri")
    st.info(
        "Ova kartica NE generira PDF odmah - bilježi ŠTO GitHub radnik treba izgraditi. "
        "Nazivi i redoslijed poglavlja te pojedinačni odabir uređuju se u kartici "
        "„📗 Skripta iz knjige” i vrijede i ovdje kad je uključena kvačica za kronološki build."
    )

    if st.button("🔄 Osvježi popis cjelina", key="skripta_osvjezi_cjeline"):
        _ucitaj_cjeline_za.clear()

    cjeline = ucitaj_cjeline()
    if not cjeline:
        st.warning("Šifrarnik cjelina je prazan - popuni tab 'Sifrarnik_cjelina' prvo.")
        st.stop()

    verzija = st.radio(
        "Verzija teorije", ["ucenik", "profesor"], horizontal=True,
        format_func=lambda v: "Učenik (bez rješenja iz primjera)" if v == "ucenik" else "Profesor (s rješenjima)",
        key="skripta_verzija",
    )

    st.markdown("**Filtri zadataka**")
    st.caption("Prazno = bez ograničenja po tom kriteriju. Kriteriji se kombiniraju s I; "
               "više vrijednosti unutar jednog kriterija s ILI.")

    try:
        svi = ucitaj_zadatke()
    except Exception as e:  # noqa: BLE001
        st.error(f"Ne mogu učitati zadatke za brojač: {e}")
        svi = []

    def _vrijednosti(stupac, velika=False):
        v = {str(r.get(stupac, "")).strip() for r in svi}
        v = {x.upper() if velika else x for x in v if x}
        return sorted(v)

    godine = sorted({int(str(r.get("godina", ""))[:4]) for r in svi
                     if str(r.get("godina", ""))[:4].isdigit()})

    k1, k2 = st.columns(2)
    with k1:
        razine = st.multiselect("Razina mature", ["A", "B"], key="skripta_razine")
        cjeline_odabrane = st.multiselect("Cjelina", cjeline, key="skripta_cjeline")
    with k2:
        izvori = st.multiselect(
            "Vrsta izvora", _vrijednosti("izvor_tip") or ["matura", "zbirka", "vlastiti_materijal", "udzbenik"],
            key="skripta_izvori",
            help="matura = državna matura; zbirka = zbirke zadataka; vlastiti_materijal = tvoji zadaci; udžbenik.")
        biblioteke = st.multiselect("Zbirka / biblioteka izvora", _vrijednosti("biblioteka_izvora"),
                                     key="skripta_biblioteke")

    if godine:
        g_od, g_do = st.select_slider("Godina (od - do)", options=godine,
                                      value=(godine[0], godine[-1]), key="skripta_godine")
        godina_od = None if (g_od == godine[0] and g_do == godine[-1]) else g_od
        godina_do = None if (g_od == godine[0] and g_do == godine[-1]) else g_do
    else:
        godina_od = godina_do = None

    filtriraj = st.checkbox(
        "Samo zadaci označeni za skriptu (u_skriptu = DA)", value=False,
        key="skripta_filtriraj",
        help="Uključi ako želiš samo fiksni skup 'zadaci za rad na satu' koje si ručno označila.")

    grupiraj_po_poglavlju = st.checkbox(
        "📖 Kronološki po poglavlju knjige (umjesto po cjelini)", value=False,
        key="skripta_grupiraj_po_poglavlju",
        help="Za materijal unesen preko 'Uvoz iz foldera' (PoglavljeX.Y_Primjeri / "
             "PoglavljeX.Y_zadaci): poglavlja idu po tvom redoslijedu iz kartice "
             "„📗 Skripta iz knjige”, Primjeri prije Zadataka, bez sortiranja po težini.")

    filtri = {
        "razine": razine, "cjeline": cjeline_odabrane, "izvori": izvori, "biblioteke": biblioteke,
        "godina_od": godina_od, "godina_do": godina_do, "samo_u_skriptu": filtriraj,
        "grupiraj_po_poglavlju": grupiraj_po_poglavlju,
    }
    pogodaka = filtriraj_zadatke(svi, filtri)
    st.metric("Zadataka koji zadovoljavaju filtre", len(pogodaka),
              help="Broj prije gradnje - isti filtar koristi GitHub radnik.")
    st.caption(f"Opis: {opis_filtara(filtri)}")
    if pogodaka:
        po = {}
        for r in pogodaka:
            c = str(r.get("cjelina", "")).strip() or "Nekategorizirano"
            po[c] = po.get(c, 0) + 1
        st.dataframe([{"cjelina": c, "zadataka": n} for c, n in sorted(po.items())],
                     hide_index=True)

    st.subheader("Naslov i podnaslov")
    n1, n2 = st.columns(2)
    with n1:
        naslov = st.text_input("Naslov dokumenta", key="skripta_naslov", max_chars=150,
                               placeholder="npr. Vektori – matura A razina",
                               help="Prazno = automatski naslov iz filtara (npr. „Skripta - Vektori“).")
    with n2:
        podnaslov = st.text_input("Podnaslov (neobavezno)", key="skripta_podnaslov",
                                  max_chars=200,
                                  placeholder="npr. Zadaci za pripremu · šk. god. 2026./2027.")

    st.divider()
    token = st.secrets.get("GITHUB_DISPATCH_TOKEN")
    pdf_spreman = bool(token) and bool(st.secrets.get("SKRIPTE_FOLDER_ID")) and \
        PREDMET == predmet_config.ZADANI_PREDMET
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📄 Izgradi PDF (automatski, ~3 min)", type="primary",
                     disabled=not pogodaka or not pdf_spreman,
                     help=None if pdf_spreman else
                     ("Automatska gradnja zasad radi samo za matematiku - za ovaj predmet "
                      "koristi „Samo zapiši zahtjev (za Colab)“."
                      if PREDMET != predmet_config.ZADANI_PREDMET else
                      "Automatska gradnja još nije uključena (nedostaju tajne "
                      "GITHUB_DISPATCH_TOKEN / SKRIPTE_FOLDER_ID).")):
            zid = spremi_zahtjev_skripte(init_sheet(), verzija_teorije=verzija, filtri=filtri,
                                          naslov=naslov, podnaslov=podnaslov,
                                          verzija_sadrzaja=verzija if grupiraj_po_poglavlju else "")
            ok, poruka = pokreni_github_build_skripte(token, zid)
            if ok:
                st.success(f"✅ Gradnja pokrenuta (zahtjev {zid}, {len(pogodaka)} zadataka). "
                           "Za ~3 minute klikni „Osvježi status” dolje i preuzmi PDF.")
            else:
                st.error(f"❌ {poruka}")
            st.cache_data.clear()
    with c2:
        if st.button("💾 Samo zapiši zahtjev (za Colab)", disabled=not pogodaka):
            spremi_zahtjev_skripte(init_sheet(), verzija_teorije=verzija, filtri=filtri,
                                    naslov=naslov, podnaslov=podnaslov,
                                    verzija_sadrzaja=verzija if grupiraj_po_poglavlju else "")
            st.success(
                f"✅ Zahtjev spremljen: **{opis_filtara(filtri)}** / "
                f"**{'učenik' if verzija == 'ucenik' else 'profesor'}** / {len(pogodaka)} zadataka. "
                "Sad pokreni Korak 3.1s u Colabu - pročitat će ovaj zahtjev.")
            st.cache_data.clear()

    st.divider()
    st.subheader("Posljednji zapisan zahtjev")
    zadnji = ucitaj_zadnji_zahtjev_skripte(init_sheet())
    if zadnji:
        st.json(zadnji)
    else:
        st.caption("Još nema nijednog zahtjeva.")


# ---------------------------------------------------------------
# Zajednički prikaz izgradnji (obje kartice)
# ---------------------------------------------------------------

def _prikazi_izgradnje():
    st.divider()
    st.subheader("📥 Zadnje izgradnje")
    if st.button("🔄 Osvježi status", key="skripta_osvjezi_status"):
        st.cache_data.clear()

    try:
        popis = [z for z in popis_zahtjeva_skripte(init_sheet()) if z.get("zahtjev_id")]
    except Exception as e:  # noqa: BLE001
        st.warning(f"Popis izgradnji se ne može učitati: {e}")
        return
    if not popis:
        st.caption("Još nema automatskih izgradnji.")
        return

    for z in popis:
        verzija = (z.get("verzija_sadrzaja") or "").strip().lower()
        oznaka = {"ucenik": "👩‍🎓 učenik", "profesor": "🧑‍🏫 profesor"}.get(verzija, "")
        st.markdown(f"**{z.get('vrijeme') or '—'}** · {z.get('naslov') or opis_filtara(z.get('filtri'))}"
                    + (f" · {oznaka}" if oznaka else "")
                    + f" · {_STATUS_OZNAKA.get(z.get('status'), z.get('status') or '—')}"
                    + (f" · _{z['poruka']}_" if z.get("poruka") else ""))
        if z.get("status") == "gotovo" and z.get("pdf_drive_id"):
            kljuc = f"skripta_pdf_{z['pdf_drive_id']}"
            if kljuc in st.session_state:
                st.download_button(
                    "⬇️ Preuzmi PDF", st.session_state[kljuc],
                    file_name=f"skripta_{z['zahtjev_id']}.pdf", mime="application/pdf",
                    key=f"dl_{z['zahtjev_id']}")
            elif st.button("⬇️ Pripremi PDF za preuzimanje", key=f"prip_{z['zahtjev_id']}"):
                try:
                    st.session_state[kljuc] = preuzmi_datoteku_iz_drivea(
                        init_drive(), z["pdf_drive_id"])
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.warning(f"PDF se ne može dohvatiti ({type(e).__name__}).")


# ---------------------------------------------------------------
# Glavni tok
# ---------------------------------------------------------------

st.title("📘 Skripta")
st.caption("PDF skripta za maturu - iz jedne knjige, s tvojim redoslijedom poglavlja i "
           "pojedinačno odabranim zadacima. Gradnja ide preko GitHub Actions (~2–4 min).")

nacin = st.radio(
    "Način rada", ["📗 Iz knjige (jednostavno)", "⚙️ Napredni filtri"],
    horizontal=True, key="skripta_nacin",
    help="„Iz knjige” je novi, jednostavni tok. „Napredni filtri” je stari način po "
         "kurikulumskim cjelinama - ostaje za posebne slučajeve.")

if nacin.startswith("📗"):
    _skripta_iz_knjige()
else:
    _napredni_filtri()

_prikazi_izgradnje()
