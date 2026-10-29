"""
CAKI Matematika - pages/4_skripta.py

Streamlit stranica za PRIPREMU zahtjeva za "skriptu" (§27.5, 15.9.2026.) - bira SAMO
parametre (razina, cjelina, vrsta izvora, biblioteka, godina, u_skriptu + učenik/profesor). NE gradi PDF ovdje - stvarni PreTeXt/xelatex build i dalje radi Colab
(Korak 3.1 -> 3.3 -> 5), NAMJERNO: xelatex/TeX Live je pretežak/presporo za ovaj lagani
Streamlit Cloud hosting koji SVAKODNEVNO koriste i profesori (Test Builder) i Caki
(unos zadataka) - ubacivanje LaTeX buildanja u tu istu aplikaciju bi riskiralo usporiti
ili srušiti je za sve, za značajku koja se koristi rijetko (par puta godišnje).

Ova stranica samo zapisuje zahtjev u tab 'Skripta_zahtjevi' (poštanski sandučić) -
Colab (Korak 3.1) čita POSLJEDNJI zahtjev preko ucitaj_zadnji_zahtjev_skripte() PRIJE
poziva build_pretext_article. Ovo NE pokreće build samo od sebe - Caki i dalje ručno
pokreće Colab kad želi, isto kao dosad za običan build. Vidi
UPUTA_skripta_streamlit_colab.md za točan redak koji treba dodati u tu Colab ćeliju.
"""
import json

import streamlit as st

import predmet_config
from baza_zadataka_pipeline import (
    get_drive_service,
    get_gspread_client,
    get_naslovi_poglavlja,
    get_redoslijed_poglavlja,
    get_sifrarnik_cjelina,
    parsiraj_poglavlje_iz_izvora,
    pokreni_github_build_skripte,
    popis_zahtjeva_skripte,
    preuzmi_datoteku_iz_drivea,
    spremi_naslove_poglavlja,
    spremi_zahtjev_skripte,
    ucitaj_zadnji_zahtjev_skripte,
)
from baza_zadataka_pipeline import _poglavlje_sort_key  # noqa: E402 - interni helper, isti obrazac kao _izgleda_kao_recenica u pages/8_uvoz_iz_foldera.py
from filtriraj_zadatke_za_skriptu import filtriraj_zadatke, opis_filtara

import secrets_json as _sj  # 21.10.2026.: tolerantno čitanje JSON-a iz Secrets
st.set_page_config(page_title="CAKI Skripta", page_icon="📘", layout="wide")


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
# Google Sheets
# ---------------------------------------------------------------

# Predmet (12.10.2026.) - svaki predmet ima svoj Sheet (v. predmet_config.py).
PREDMET = predmet_config.odaberi_predmet(st)


@st.cache_resource
def _init_sheet_za(predmet):
    sa_info = _sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(predmet_config.sheet_id(predmet, st.secrets))


def init_sheet():
    return _init_sheet_za(PREDMET)


@st.cache_data(ttl=3600)
def _ucitaj_cjeline_za(predmet):
    return sorted(get_sifrarnik_cjelina(_init_sheet_za(predmet)).keys())


def _ucitaj_cjeline():
    return _ucitaj_cjeline_za(PREDMET)


@st.cache_data(ttl=600)
def _ucitaj_zadatke_za(predmet):
    """Svi retci taba Zadaci (samo za brojac i popis vrijednosti filtara - build radi Colab)."""
    return _init_sheet_za(predmet).worksheet("Zadaci").get_all_records()


def _ucitaj_zadatke():
    return _ucitaj_zadatke_za(PREDMET)


# ---------------------------------------------------------------
# UI
# ---------------------------------------------------------------

st.title("📘 Priprema skripte")
st.info(
    "Ova stranica NE generira PDF - samo bilježi ŠTO Colab treba izgraditi sljedeći put "
    "kad ručno pokreneš Korak 3.1. Sam PDF build ostaje u Colabu (xelatex je pretežak za "
    "ovaj hosting) - klikom ovdje ništa se odmah ne događa na webu ni kod studenata."
)

if st.button("🔄 Osvježi popis cjelina"):
    _ucitaj_cjeline_za.clear()  # 29.10.2026.: FIX - _ucitaj_cjeline (plain wrapper) nema .clear(), prava keš funkcija je _ucitaj_cjeline_za

cjeline = _ucitaj_cjeline()
if not cjeline:
    st.warning("Šifrarnik cjelina je prazan - popuni tab 'Sifrarnik_cjelina' prvo.")
    st.stop()

verzija = st.radio(
    "Verzija teorije",
    ["ucenik", "profesor"],
    horizontal=True,
    format_func=lambda v: "Učenik (bez rješenja iz primjera)" if v == "ucenik" else "Profesor (s rješenjima)",
    key="skripta_verzija",
)

st.subheader("Filtri zadataka")
st.caption("Prazno = bez ograničenja po tom kriteriju. Kriteriji se kombiniraju s I; "
           "više vrijednosti unutar jednog kriterija s ILI.")

try:
    _svi = _ucitaj_zadatke()
except Exception as e:  # noqa: BLE001 - prikaži, ali ne ruši stranicu
    st.error(f"Ne mogu učitati zadatke za brojač: {e}")
    _svi = []


def _vrijednosti(stupac, velika=False):
    v = {str(r.get(stupac, "")).strip() for r in _svi}
    v = {x.upper() if velika else x for x in v if x}
    return sorted(v)


_godine = sorted({int(str(r.get("godina", ""))[:4]) for r in _svi if str(r.get("godina", ""))[:4].isdigit()})

k1, k2 = st.columns(2)
with k1:
    razine = st.multiselect("Razina mature", ["A", "B"], key="skripta_razine")
    cjeline_odabrane = st.multiselect("Cjelina", cjeline, key="skripta_cjeline")
with k2:
    izvori = st.multiselect(
        "Vrsta izvora", _vrijednosti("izvor_tip") or ["matura", "zbirka", "vlastiti_materijal", "udzbenik"],
        key="skripta_izvori",
        help="matura = državna matura; zbirka = zbirke zadataka; vlastiti_materijal = tvoji zadaci; udzbenik.")
    biblioteke = st.multiselect("Zbirka / biblioteka izvora", _vrijednosti("biblioteka_izvora"),
                                key="skripta_biblioteke")

if _godine:
    g_od, g_do = st.select_slider("Godina (od - do)", options=_godine,
                                   value=(_godine[0], _godine[-1]), key="skripta_godine")
    # cijeli raspon = bez filtra po godini (zadaci bez godine tada ne ispadaju)
    godina_od = None if (g_od == _godine[0] and g_do == _godine[-1]) else g_od
    godina_do = None if (g_od == _godine[0] and g_do == _godine[-1]) else g_do
else:
    godina_od = godina_do = None

filtriraj = st.checkbox(
    "Samo zadaci označeni za skriptu (u_skriptu = DA)",
    value=False,
    key="skripta_filtriraj",
    help="Uključi ako želiš samo fiksni skup 'zadaci za rad na satu' koje si ručno označila.",
)

grupiraj_po_poglavlju = st.checkbox(
    "📖 Kronološki po poglavlju knjige (umjesto po cjelini)",
    value=False,
    key="skripta_grupiraj_po_poglavlju",
    help="Za materijal unesen preko 'Uvoz iz foldera' (PoglavljeX.Y_Primjeri / "
         "PoglavljeX.Y_zadaci) - poglavlja idu redom 1→30 kako su u knjizi (ili po ručnom "
         "poretku, v. tablicu ispod), Primjeri prije Zadataka unutar svakog poglavlja, BEZ "
         "sortiranja po težini (čuva redoslijed skeniranja). Naziv i redoslijed svakog "
         "poglavlja upisuješ u tablici ispod (čim uključiš ovu kvačicu) - sprema se u tab "
         "'Sifrarnik_poglavlja_knjige' u Google Sheetu, isto vrijedi i ako ga uredite izravno "
         "tamo.",
)

filtri = {
    "razine": razine, "cjeline": cjeline_odabrane, "izvori": izvori, "biblioteke": biblioteke,
    "godina_od": godina_od, "godina_do": godina_do, "samo_u_skriptu": filtriraj,
    "grupiraj_po_poglavlju": grupiraj_po_poglavlju,
}
_pogodaka = filtriraj_zadatke(_svi, filtri)
st.metric("Zadataka koji zadovoljavaju filtre", len(_pogodaka), help="Broj prije gradnje - isti filtar koristi Colab.")
st.caption(f"Opis: {opis_filtara(filtri)}")
if _pogodaka:
    _po = {}
    for r in _pogodaka:
        c = str(r.get("cjelina", "")).strip() or "Nekategorizirano"
        _po[c] = _po.get(c, 0) + 1
    st.dataframe([{"cjelina": c, "zadataka": n} for c, n in sorted(_po.items())], hide_index=True)

if grupiraj_po_poglavlju:
    st.markdown("###### 📖 Nazivi i redoslijed poglavlja")
    st.caption(
        "Poglavlja prepoznata iz trenutno filtriranih zadataka (iz 'izvor_naziv', npr. "
        "'Poglavlje2.11_zadaci' i 'Poglavlje2.11_Primjeri' postaju JEDNO poglavlje "
        "'Poglavlje2.11'). Suzi filtre iznad (npr. biblioteka = jedna knjiga) da ovdje vidiš "
        "SAMO poglavlja te knjige. **Redoslijed**: manji broj ide prije u skripti - po "
        "defaultu popunjen prirodnim poretkom (1.1, 1.2, ... 1.10), promijeni SAMO retke "
        "gdje želiš drugačiji poredak (decimale su ok, npr. 2.5 da umetneš između 2 i 3 bez "
        "pretipkavanja svih ostalih). **Naziv**: prazno = u PDF-u ide sirovi ključ."
    )
    _poglavlja_kljucevi = sorted(
        {parsiraj_poglavlje_iz_izvora(r.get("izvor_naziv", "")) for r in _pogodaka
         if parsiraj_poglavlje_iz_izvora(r.get("izvor_naziv", "")).strip()},
        key=_poglavlje_sort_key,
    )
    if not _poglavlja_kljucevi:
        st.caption("Nijedan trenutno filtrirani zadatak nema prepoznatljiv 'PoglavljeX.Y' ključ "
                   "u izvor_naziv - ova tablica se puni samo za materijal unesen preko 'Uvoz iz "
                   "foldera'.")
    else:
        try:
            _sheet_za_poglavlja = init_sheet()
            _postojeci_naslovi = get_naslovi_poglavlja(_sheet_za_poglavlja)
            _postojeci_redoslijed = get_redoslijed_poglavlja(_sheet_za_poglavlja)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Ne mogu učitati postojeće nazive/redoslijed: {e}")
            _postojeci_naslovi, _postojeci_redoslijed = {}, {}
        _poglavlja_tablica = [
            {
                "poglavlje_kljuc": k,
                "redoslijed": _postojeci_redoslijed.get(k, float(_i + 1)),
                "naziv_cjeline": _postojeci_naslovi.get(k, ""),
            }
            for _i, k in enumerate(_poglavlja_kljucevi)
        ]
        _poglavlja_uredeno = st.data_editor(
            _poglavlja_tablica, hide_index=True, use_container_width=True,
            key="skripta_poglavlja_editor",
            column_config={
                "poglavlje_kljuc": st.column_config.TextColumn("Poglavlje (ključ)", disabled=True),
                "redoslijed": st.column_config.NumberColumn(
                    "Redoslijed", help="Manji broj = ranije u skripti.", step=1, format="%.2f"),
                "naziv_cjeline": st.column_config.TextColumn("Naziv cjeline (u PDF-u)"),
            },
        )
        if st.button("💾 Spremi nazive i redoslijed poglavlja", key="skripta_spremi_poglavlja"):
            try:
                spremi_naslove_poglavlja(init_sheet(), [
                    {"poglavlje_kljuc": r.get("poglavlje_kljuc"), "redoslijed": r.get("redoslijed"),
                     "naslov_prikaz": r.get("naziv_cjeline")}
                    for r in _poglavlja_uredeno
                ])
                st.success(f"✅ Spremljeno {len(_poglavlja_uredeno)} poglavlja u "
                          "'Sifrarnik_poglavlja_knjige'.")
                st.cache_data.clear()
            except Exception as e:  # noqa: BLE001
                st.error(f"Greška: {e}")

st.subheader("Naslov i podnaslov")
n1, n2 = st.columns(2)
with n1:
    naslov = st.text_input("Naslov dokumenta", key="skripta_naslov", max_chars=150,
                           placeholder="npr. Vektori – matura A razina",
                           help="Prazno = automatski naslov iz filtara (npr. „Skripta - Vektori“).")
with n2:
    podnaslov = st.text_input("Podnaslov (neobavezno)", key="skripta_podnaslov", max_chars=200,
                              placeholder="npr. Zadaci za pripremu · šk. god. 2026./2027.")

st.divider()
_token = st.secrets.get("GITHUB_DISPATCH_TOKEN")
# Automatska gradnja (GitHub radnik) zasad čita samo matematički Sheet; za ostale predmete koristi Colab (Korak 3.1s).
_pdf_spreman = bool(_token) and bool(st.secrets.get("SKRIPTE_FOLDER_ID")) and PREDMET == predmet_config.ZADANI_PREDMET
c1, c2 = st.columns(2)
with c1:
    if st.button("📄 Izgradi PDF (automatski, ~5 min)", type="primary",
                 disabled=not _pogodaka or not _pdf_spreman,
                 help=None if _pdf_spreman else ("Automatska gradnja zasad radi samo za matematiku - za ovaj predmet koristi „Samo zapiši zahtjev (za Colab)“." if PREDMET != predmet_config.ZADANI_PREDMET else "Automatska gradnja još nije uključena (nedostaju tajne GITHUB_DISPATCH_TOKEN / SKRIPTE_FOLDER_ID).")):
        _zid = spremi_zahtjev_skripte(init_sheet(), verzija_teorije=verzija, filtri=filtri,
                                   naslov=naslov, podnaslov=podnaslov)
        _ok, _poruka = pokreni_github_build_skripte(_token, _zid)
        if _ok:
            st.success(f"✅ Gradnja pokrenuta (zahtjev {_zid}, {len(_pogodaka)} zadataka). "
                       "Za ~5 minuta klikni „Osvježi status“ dolje i preuzmi PDF.")
        else:
            st.error(f"❌ {_poruka}")
        st.cache_data.clear()
with c2:
    if st.button("💾 Samo zapiši zahtjev (za Colab)", disabled=not _pogodaka):
        spremi_zahtjev_skripte(init_sheet(), verzija_teorije=verzija, filtri=filtri,
                                   naslov=naslov, podnaslov=podnaslov)
        st.success(
            f"✅ Zahtjev spremljen: **{opis_filtara(filtri)}** / "
            f"**{'učenik' if verzija == 'ucenik' else 'profesor'}** / {len(_pogodaka)} zadataka. "
            "Sad pokreni Korak 3.1s u Colabu - pročitat će ovaj zahtjev."
        )
        st.cache_data.clear()

st.divider()
st.subheader("Zadnje izgradnje")
if st.button("🔄 Osvježi status"):
    st.cache_data.clear()
_STATUS = {"cekanje": "⏳ čeka", "u_radu": "🛠️ u izradi", "gotovo": "✅ gotovo", "greska": "❌ greška"}
_zadnji_popis = [z for z in popis_zahtjeva_skripte(init_sheet()) if z.get("zahtjev_id")]
if not _zadnji_popis:
    st.caption("Još nema automatskih izgradnji.")
for z in _zadnji_popis:
    st.markdown(f"**{z['vrijeme']}** · {opis_filtara(z['filtri'])} · {_STATUS.get(z['status'], z['status'] or '—')}"
                + (f" · _{z['poruka']}_" if z.get("poruka") else ""))
    if z["status"] == "gotovo" and z.get("pdf_drive_id"):
        try:
            _bytes = preuzmi_datoteku_iz_drivea(get_drive_service(_sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON")), z["pdf_drive_id"])
            st.download_button("⬇️ Preuzmi PDF", _bytes, file_name=f"skripta_{z['zahtjev_id']}.pdf",
                               mime="application/pdf", key=f"pdf_{z['zahtjev_id']}")
        except Exception as e:  # noqa: BLE001
            st.warning(f"PDF se ne može dohvatiti ({type(e).__name__}).")

st.divider()
st.subheader("Posljednji zapisan zahtjev")
zadnji = ucitaj_zadnji_zahtjev_skripte(init_sheet())
if zadnji:
    st.json(zadnji)
else:
    st.caption("Još nema nijednog zahtjeva.")
