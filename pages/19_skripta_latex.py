"""
CAKI Matematika - pages/19_skripta_latex.py (4.11.2026.)

📕 SKRIPTA (LaTeX) — NOVA, PARALELNA staza za PDF skriptu.

ODNOS PREMA POSTOJEĆOJ STRANICI „📘 Skripta" (Cakijeva odluka 4.11.2026.):
postojeća stranica (pages/4_skripta.py) i njezin PreTeXt build (skripta_build.py +
GitHub Actions) OSTAJU NEDIRNUTI i rade kao prije. Ova stranica je zasebna i ne piše
ni u jedan tab koji ta staza koristi — samo ČITA:
  - tab `Zadaci`                      (zadaci i primjeri)
  - tab `Sifrarnik_poglavlja_knjige`  (redoslijed, nazivi, odabir — uređuje se na 📘 Skripta)
  - tab `Teorija_potpoglavlja`        (teorija, uređuje se na ✍️ Teorija)
  - tab `Formule`                     (formule, uređuju se na 📐 Formule)
SVOJE postavke (oznaka cjeline, koja teorija, koje formule) piše u VLASTITI tab
`Skripta_latex_postavke` (v. skripta_latex_postavke.py).

ŠTO JE DRUGAČIJE U PDF-u (sve na Cakijev izričit zahtjev):
  - stilizacija kao kod testova iz Test Buildera (pages/caki-skripta.sty nadograđuje
    caki-style.sty): POVEĆANE matematičke formule, uske margine, crn tekst,
    ponuđeni odgovori A-D u JEDNOM REDU kad stanu
  - naslov cjeline CENTRIRAN, uvećan, istaknut, na novoj stranici
  - zadržane oznake težine L/S/T i podaci o firmi (letterhead + podnožje)
  - TEORIJA i FORMULE ispod naslova cjeline
  - razdjelni simbol (◇ ◇ ◇) između primjera i zadataka
  - RJEŠENJA NA KRAJU SVAKOG POGLAVLJA (ne na kraju dokumenta)

PDF se kompajlira pdflatexom IZRAVNO u Streamlitu — isto kao Test Builder (packages.txt
već sadrži texlive pakete koji za to trebaju). Za razliku od PreTeXt staze, ne treba
GitHub Actions ni čekanje od ~3 min.
"""
import datetime
import os
import subprocess
import tempfile

import streamlit as st

import predmet_config
import secrets_json as _sj
import formule as formule_modul
import skripta_latex as sl
import skripta_latex_postavke as postavke_modul
from latex_tekst import escape_outside_math
from baza_zadataka_pipeline import (
    TEZINA_LEGENDA,
    get_drive_service,
    get_gspread_client,
    get_naslovi_poglavlja,
    get_odabir_poglavlja,
    get_redoslijed_poglavlja,
    get_teorija_po_potpoglavlju,
)
from caki_stabilnost import DRIVE_LOCK

st.set_page_config(page_title="CAKI Skripta (LaTeX)", page_icon="📕", layout="wide")
import caki_stil as stil  # noqa: E402  (31.10.2026.: CAKI tema)
stil.primijeni()

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
ZADANA_KNJIGA = "ŠK-Matematika na maturi"


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao app.py, 2_test_builder.py, 4_skripta.py)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_skripta_tex"] = (
            st.session_state.get("lozinka_unos_skripta_tex") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_skripta_tex"):
        return True
    st.title("📕 CAKI Skripta (LaTeX)")
    st.text_input("Lozinka", type="password", key="lozinka_unos_skripta_tex", on_change=na_unos)
    if st.session_state.get("autoriziran_skripta_tex") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

PREDMET = predmet_config.odaberi_predmet(st)


# ---------------------------------------------------------------
# Google Sheets / Drive
# ---------------------------------------------------------------

@st.cache_resource
def _init_sheet_za(predmet):
    gc = get_gspread_client(_sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON"))
    return gc.open_by_key(predmet_config.sheet_id(predmet, st.secrets))


def init_sheet():
    return _init_sheet_za(PREDMET)


@st.cache_resource
def _init_drive_za(predmet):
    return get_drive_service(_sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON"))


@st.cache_data(ttl=600)
def _ucitaj_zadatke_za(predmet):
    return _init_sheet_za(predmet).worksheet("Zadaci").get_all_records()


@st.cache_data(ttl=60)
def _ucitaj_plan_za(predmet):
    sheet = _init_sheet_za(predmet)
    return {"naslovi": get_naslovi_poglavlja(sheet),
            "redoslijed": get_redoslijed_poglavlja(sheet),
            "odabir": get_odabir_poglavlja(sheet)}


@st.cache_data(ttl=300)
def _ucitaj_teoriju_za(predmet):
    """{(cjelina, potpoglavlje): redak} -> {"cjelina||potpoglavlje": tekst_teorije_latex}."""
    izlaz = {}
    for (cjelina, potpoglavlje), redak in get_teorija_po_potpoglavlju(_init_sheet_za(predmet)).items():
        tekst = str(redak.get("tekst_teorije_latex") or "").strip()
        if tekst:
            izlaz[postavke_modul.kljuc_teorije(cjelina, potpoglavlje)] = tekst
    return izlaz


@st.cache_data(ttl=300)
def _ucitaj_formule_za(predmet):
    return formule_modul.aktivne(formule_modul.load_formule(_init_sheet_za(predmet)))


@st.cache_data(ttl=60)
def _ucitaj_postavke_za(predmet):
    return postavke_modul.ucitaj(_init_sheet_za(predmet))


@st.cache_data(ttl=3600, max_entries=800, show_spinner=False)
def _sliku_bytes_za(naziv_datoteke, predmet):
    """Bajtovi slike iz 02_SLIKE Drive foldera. None ako nije pronađena (NE baca grešku —
    referenciranje nepostojeće datoteke u .tex-u srušilo bi cijelo kompajliranje, pa
    skripta_latex.py takve slike preskače).

    DRIVE_LOCK: Drive servis (httplib2) nije siguran za istodobne pozive iz više dretvi
    (v. caki_stabilnost.py) — pozivi za slike idu jedan po jedan."""
    if not naziv_datoteke:
        return None
    drive = _init_drive_za(predmet)
    folder_id = predmet_config.slike_folder_id(predmet, st.secrets)
    naziv_q = str(naziv_datoteke).replace("\\", "\\\\").replace("'", "\\'")
    try:
        with DRIVE_LOCK:
            rezultat = drive.files().list(
                q=f"name='{naziv_q}' and '{folder_id}' in parents and trashed=false",
                fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
            datoteke = rezultat.get("files", [])
            if not datoteke:
                return None
            return drive.files().get_media(fileId=datoteke[0]["id"],
                                           supportsAllDrives=True).execute()
    except Exception:  # noqa: BLE001 — slika koja se ne da dohvatiti ne smije srušiti stranicu
        return None


def _cist(tekst) -> str:
    return " ".join(str(tekst or "").split()).strip()


def osvjezi_kes():
    """Prazni SVE keševe ove stranice.

    5.11.2026. (Cakijev nalaz „ispravio sam i spremio, ali nije odmah povuklo"): tab `Zadaci`
    se drži 10 minuta (`ttl=600`), pa se ispravak u Sheetu ne vidi odmah i stranica ponavlja
    istu grešku. Bez ovoga bi Caki morao čekati da keš istekne."""
    for funkcija in (_ucitaj_zadatke_za, _ucitaj_plan_za, _ucitaj_teoriju_za,
                     _ucitaj_formule_za, _ucitaj_postavke_za):
        try:
            funkcija.clear()
        except Exception:  # noqa: BLE001 — čišćenje keša ne smije srušiti stranicu
            pass


def _csv_problema(problemi) -> str:
    """Popis problema kao CSV (za „Preuzmi popis") — da Caki može ispravljati u Sheetu
    gledajući cijeli popis, bez skrolanja po stranici."""
    import csv
    import io as _io
    izlaz = _io.StringIO()
    pisac = csv.writer(izlaz, delimiter=";")
    pisac.writerow(["poglavlje", "vrsta", "id", "polje", "problem", "tekst"])
    for p in problemi:
        pisac.writerow([p["poglavlje"], p["vrsta"], p["id"], p["polje"], p["problem"],
                        " ".join(str(p["tekst"]).split())])
    return izlaz.getvalue()


def _prikazi_problema(problemi, naslov_poruke):
    """Jedna tablica sa SVIM nalazima + preuzimanje popisa + gumb za osvježavanje keša."""
    st.markdown(f"**{naslov_poruke}**")
    st.dataframe(
        [{"poglavlje": p["poglavlje"], "vrsta": p["vrsta"], "id": p["id"],
          "polje": p["polje"], "problem": p["problem"],
          "tekst": " ".join(str(p["tekst"]).split())[:300]} for p in problemi],
        width="stretch", hide_index=True)
    d1, d2 = st.columns([1, 1])
    d1.download_button("⬇️ Preuzmi popis (CSV)", data=_csv_problema(problemi).encode("utf-8-sig"),
                       file_name="skripta_latex_greske.csv", mime="text/csv",
                       key=f"tex_csv_{abs(hash(naslov_poruke)) % 10**8}")
    if d2.button("🔄 Osvježi podatke iz baze", key=f"tex_osv_{abs(hash(naslov_poruke)) % 10**8}",
                 help="Nakon ispravka u Google Sheetu — stranica inače drži podatke do 10 minuta."):
        osvjezi_kes()
        st.rerun()


# ---------------------------------------------------------------
# Učitavanje podataka
# ---------------------------------------------------------------

st.title("📕 Skripta (LaTeX)")
st.caption(
    "Nova staza: PDF se gradi **izravno pdflatexom** (isti stil kao testovi iz Test Buildera), "
    "bez PreTeXt-a i bez GitHub Actions. Postojeća stranica **📘 Skripta** radi nepromijenjeno. "
    "Redoslijed poglavlja, nazive i odabir zadataka i dalje uređuješ ondje — ovdje se samo koriste."
)

if st.button("🔄 Osvježi podatke iz baze", key="tex_osvjezi_gore",
             help="Klikni nakon što si nešto ispravio u Google Sheetu — stranica inače drži "
                  "zadatke, teoriju i formule u kešu do 10 minuta."):
    osvjezi_kes()
    st.rerun()

try:
    svi_zadaci = _ucitaj_zadatke_za(PREDMET)
except Exception as e:  # noqa: BLE001
    st.error(f"Ne mogu učitati tab Zadaci: {e}")
    st.stop()

knjige = sorted({_cist(r.get("biblioteka_izvora")) for r in svi_zadaci
                 if _cist(r.get("biblioteka_izvora"))})
if not knjige:
    st.warning("U tabu `Zadaci` nema nijedne vrijednosti u stupcu `biblioteka_izvora`.")
    st.stop()

zadana = next((k for k in knjige if k.lower() == ZADANA_KNJIGA.lower()), knjige[0])
knjiga = st.selectbox("Knjiga / biblioteka izvora", knjige, index=knjige.index(zadana),
                      key="skripta_tex_knjiga")

redovi_knjige = [r for r in svi_zadaci if _cist(r.get("biblioteka_izvora")).lower() == knjiga.lower()]

try:
    plan = _ucitaj_plan_za(PREDMET)
except Exception as e:  # noqa: BLE001
    st.warning(f"Ne mogu učitati plan poglavlja: {e}")
    plan = {"naslovi": {}, "redoslijed": {}, "odabir": {}}

sva_poglavlja = sl.grupiraj_po_poglavljima(
    redovi_knjige, naslovi_poglavlja=plan["naslovi"],
    redoslijed_poglavlja=plan["redoslijed"], odabir_poglavlja=plan["odabir"])

if not sva_poglavlja:
    st.warning(f"Za knjigu „{knjiga}” nema uključenih poglavlja s odabranim zadacima. "
               "Provjeri plan na stranici 📘 Skripta → Iz knjige.")
    st.stop()

try:
    teorije = _ucitaj_teoriju_za(PREDMET)
except Exception as e:  # noqa: BLE001
    st.warning(f"Ne mogu učitati tab Teorija_potpoglavlja: {e}")
    teorije = {}

try:
    sve_formule = _ucitaj_formule_za(PREDMET)
except Exception as e:  # noqa: BLE001
    st.warning(f"Ne mogu učitati tab Formule: {e}")
    sve_formule = []

try:
    spremljene_postavke = _ucitaj_postavke_za(PREDMET)
except Exception as e:  # noqa: BLE001
    st.warning(f"Ne mogu učitati spremljene postavke: {e}")
    spremljene_postavke = {}

formule_po_id = {str(f.get("formula_id")): f for f in sve_formule}
teorija_opcije = [""] + sorted(teorije.keys())
formula_opcije = [str(f.get("formula_id")) for f in sve_formule]


def _naziv_formule(fid):
    f = formule_po_id.get(str(fid)) or {}
    paket = _cist(f.get("paket"))
    return f"{_cist(f.get('naslov')) or fid}" + (f"  ·  {paket}" if paket else "")


# Spremljene postavke se upisuju na SVA poglavlja, ne samo na odabrana — tako provjera
# „cijele knjige" (niže) vidi i teoriju poglavlja koja trenutno nisu u ispisu. Za odabrana
# poglavlja ove vrijednosti kasnije prepisuju widgeti u sklopivim blokovima.
for _p in sva_poglavlja:
    _s = spremljene_postavke.get(_p["kljuc"], {})
    _p["oznaka"] = _s.get("oznaka", "")
    _p["teorija"] = teorije.get(_s.get("teorija_kljuc", ""), "")
    _p["formule"] = [formule_po_id[x] for x in _s.get("formule_ids", []) if x in formule_po_id]
    _p["formule_rucno"] = _s.get("formule_rucno", "")


# ---------------------------------------------------------------
# Postavke po poglavlju
# ---------------------------------------------------------------

st.divider()
st.subheader("✅ Koja poglavlja idu u OVU skriptu")
st.caption(
    "Dok tipkaš knjigu, ovdje odabereš samo gotova poglavlja i ispišeš njih. "
    "Ovo je **odvojeno** od uključenosti poglavlja u glavnom planu na 📘 Skripta — tamo se "
    "ništa ne mijenja. Izbor se pamti gumbom „Spremi postavke poglavlja” niže."
)

_kljuc_odabira = f"tex_odabir_poglavlja_{PREDMET}_{knjiga}"
_svi_kljucevi = [p["kljuc"] for p in sva_poglavlja]
if _kljuc_odabira not in st.session_state:
    st.session_state[_kljuc_odabira] = [
        k for k in _svi_kljucevi
        if spremljene_postavke.get(k, {}).get("u_skripti", True)]
else:
    # Plan se u međuvremenu mogao promijeniti (novo/izbačeno poglavlje) — multiselect pada
    # ako u stanju ostane vrijednost koje više nema među opcijama.
    st.session_state[_kljuc_odabira] = [k for k in st.session_state[_kljuc_odabira]
                                        if k in _svi_kljucevi]

_b1, _b2, _b3 = st.columns([1, 1, 5])
if _b1.button("✅ Sva", key="tex_sva_poglavlja", width="stretch"):
    st.session_state[_kljuc_odabira] = list(_svi_kljucevi)
    st.rerun()
if _b2.button("⬜ Nijedno", key="tex_nijedno_poglavlje", width="stretch"):
    st.session_state[_kljuc_odabira] = []
    st.rerun()

_opis = {p["kljuc"]: f"{p['naslov']}  ·  {len(p['primjeri'])}P / {len(p['zadaci'])}Z"
         for p in sva_poglavlja}
odabrani_kljucevi = st.multiselect(
    "Poglavlja u skripti", _svi_kljucevi, key=_kljuc_odabira,
    format_func=lambda k: _opis.get(k, k),
    help="Redoslijed u PDF-u je uvijek redoslijed iz plana, bez obzira kojim ih redom ovdje "
         "dodaš. P = primjeri, Z = zadaci.")

poglavlja = [p for p in sva_poglavlja if p["kljuc"] in set(odabrani_kljucevi)]
if not poglavlja:
    st.warning("Nijedno poglavlje nije odabrano — odaberi barem jedno da bi mogao generirati PDF.")
    st.stop()

st.divider()
st.subheader("📑 Odabrana poglavlja — teorija, formule i oznaka cjeline")
st.caption(
    "Za svako poglavlje možeš dodati **oznaku** (npr. `3.1` — po njoj se numeriraju zadaci), "
    "**teoriju** iz taba `Teorija_potpoglavlja` i **formule** iz taba `Formule` ili ručno "
    "upisan LaTeX. Sve je neobavezno — poglavlje bez toga ispisuje samo primjere i zadatke."
)

if not teorije:
    st.info("Tab `Teorija_potpoglavlja` je prazan ili nedostupan — ponuda teorije je prazna. "
            "Teoriju unosiš na stranici ✍️ Teorija.")
if not sve_formule:
    st.info("Tab `Formule` je prazan ili nedostupan — ponuda formula je prazna. Formule unosiš "
            "na stranici 📐 Formule. Ručni LaTeX blok radi i bez toga.")

for pog in poglavlja:
    kljuc = pog["kljuc"]
    spremljeno = spremljene_postavke.get(kljuc, {})
    with st.expander(
        f"**{pog['naslov']}**  ·  {len(pog['primjeri'])} primjera, {len(pog['zadaci'])} zadataka",
        expanded=False,
    ):
        k1, k2 = st.columns([1, 3])
        pog["oznaka"] = k1.text_input(
            "Oznaka cjeline", value=spremljeno.get("oznaka", ""),
            key=f"tex_oznaka_{kljuc}",
            help="Npr. 3.1 — zadaci se tada zovu „Zadatak 3.1.1.”. Prazno = redni broj cjeline.")
        izbor_teorije = k2.selectbox(
            "Teorija ispod naslova", teorija_opcije,
            index=(teorija_opcije.index(spremljeno.get("teorija_kljuc"))
                   if spremljeno.get("teorija_kljuc") in teorija_opcije else 0),
            key=f"tex_teorija_{kljuc}",
            format_func=lambda x: "— bez teorije —" if not x else x.replace(
                postavke_modul.TEORIJA_RAZDJELNIK, "  →  "))
        pog["teorija"] = teorije.get(izbor_teorije, "")
        pog["_teorija_kljuc"] = izbor_teorije

        izbor_formula = st.multiselect(
            "Formule iz baze", formula_opcije,
            default=[x for x in spremljeno.get("formule_ids", []) if x in formula_opcije],
            key=f"tex_formule_{kljuc}", format_func=_naziv_formule)
        pog["formule"] = [formule_po_id[x] for x in izbor_formula if x in formule_po_id]
        pog["_formule_ids"] = izbor_formula

        pog["formule_rucno"] = st.text_area(
            "Dodatne formule — ručno (LaTeX)", value=spremljeno.get("formule_rucno", ""),
            key=f"tex_rucno_{kljuc}", height=90,
            help=r"Piše se kao LaTeX, npr. \[\sin^2 x+\cos^2 x=1\]. Ide doslovno u dokument.")

        if pog["teorija"]:
            st.caption(f"Teorija: {len(pog['teorija'])} znakova.")

if st.button("💾 Spremi postavke poglavlja u bazu", key="tex_spremi_postavke"):
    novo = dict(spremljene_postavke)
    odabrano = set(odabrani_kljucevi)
    for pog in sva_poglavlja:
        kljuc = pog["kljuc"]
        if kljuc in odabrano:
            novo[kljuc] = {
                "oznaka": pog.get("oznaka", ""),
                "teorija_kljuc": pog.get("_teorija_kljuc", ""),
                "formule_ids": pog.get("_formule_ids", []),
                "formule_rucno": pog.get("formule_rucno", ""),
                "u_skripti": True,
            }
        else:
            # Neodabrano poglavlje: njegove postavke (teorija, formule…) se ČUVAJU — mijenja
            # se samo zastavica, da se pri idućem otvaranju stranice ne vrati uključeno.
            novo[kljuc] = {**novo.get(kljuc, {}), "u_skripti": False}
    try:
        postavke_modul.spremi(init_sheet(), novo)
        _ucitaj_postavke_za.clear()
        st.success(f"Spremljeno u tab `{postavke_modul.POSTAVKE_TAB}`.")
    except Exception as e:  # noqa: BLE001
        st.error(f"Spremanje nije uspjelo: {e}")


# ---------------------------------------------------------------
# Naslov i opcije dokumenta
# ---------------------------------------------------------------

st.divider()
st.subheader("📄 Dokument")

s1, s2 = st.columns(2)
naslov = s1.text_input("Naslov skripte", value="Skripta za maturu", key="tex_naslov", max_chars=150)
podnaslov = s2.text_input("Podnaslov (neobavezno)", value="", key="tex_podnaslov", max_chars=150)

o1, o2, o3 = st.columns(3)
verzija = o1.radio("Verzija", ["ucenik", "profesor"], key="tex_verzija",
                   format_func=lambda x: "Za učenike" if x == "ucenik" else "Za profesora",
                   help="Za profesora: u teoriji ostaju [RJESENJE] blokovi, a među rješenjima su "
                        "i konačni odgovori primjera.")
rjesenja = o2.radio("Rješenja na kraju poglavlja",
                    [sl.RJESENJA_POSTUPAK, sl.RJESENJA_ODGOVOR, sl.RJESENJA_BEZ],
                    key="tex_rjesenja",
                    format_func=lambda x: {"postupak": "Puni postupak",
                                           "odgovor": "Samo konačan odgovor (2 stupca)",
                                           "bez": "Bez rješenja"}[x])
dvostrano = o3.checkbox(
    "Obostrani ispis s uvezom", value=True, key="tex_dvostrano",
    help="Unutarnja margina veća od vanjske (1.9/1.0 cm) — uvez ne pojede tekst. "
         "Isključeno = simetrične margine 1.3 cm, kao kod testova.")

# --- Gdje su rješenja i prijelom stranice: oboje utječe na broj polupraznih stranica ---
m1, m2, m3 = st.columns(3)
mjesto_rjesenja = m1.radio(
    "Gdje su rješenja", [sl.MJESTO_KRAJ, sl.MJESTO_POGLAVLJE], key="tex_mjesto_rjesenja",
    format_func=lambda x: {"kraj": "Sva na kraju skripte",
                           "poglavlje": "Iza svakog poglavlja"}[x],
    help="Sva na kraju: jedna cjelina „Rješenja” s numeracijom po poglavljima "
         "(3.1.1., 3.1.2., …) — manje polupraznih stranica. Oznake su iste u oba slučaja.")
nova_stranica = m2.checkbox(
    "Svaka cjelina na novoj stranici", value=True, key="tex_nova_stranica",
    help="Isključi ako želiš još manje praznog papira — cjeline se tada nižu jedna za "
         "drugom, s većim razmakom umjesto prijeloma.")
sa_sadrzajem = m3.checkbox(
    "Ispiši sadržaj (s brojevima stranica)", value=False, key="tex_sadrzaj",
    help="Popis cjelina s brojevima stranica, odmah iza naslova. Traži treći prolaz "
         "pdflatexa, pa gradnja traje malo dulje.")
sa_slikama = st.checkbox(
    "Uključi slike uz zadatke", value=True, key="tex_slike",
    help="Isključi za brzu probu izgleda — slike se dohvaćaju s Drivea i to je najsporiji dio.")
dopusti_neispravne = st.checkbox(
    "Nastavi i kad neki zadatak ima neispravan LaTeX", value=False, key="tex_dopusti",
    help="Zadatak ostaje na svom mjestu (numeracija se ne mijenja), ali umjesto teksta piše "
         "vidljiva oznaka NEISPRAVAN LaTeX, s id-om i poljem. Korisno da jedna pokvarena "
         "ćelija ne blokira ispis cijele skripte.")

ukupno_p = sum(len(p["primjeri"]) for p in poglavlja)
ukupno_z = sum(len(p["zadaci"]) for p in poglavlja)
st.info(f"U skriptu ide **{len(poglavlja)}** od **{len(sva_poglavlja)}** poglavlja: "
        f"**{ukupno_p}** primjera i **{ukupno_z}** zadataka.")


# ---------------------------------------------------------------
# Provjera LaTeXa — SVI nalazi odjednom
# ---------------------------------------------------------------

with st.expander("🔍 Provjera LaTeXa (sve greške odjednom)", expanded=False):
    st.caption(
        "Nađe SVA polja koja bi srušila kompajliranje i ispiše ih u jednoj tablici — ne jedno "
        "po jedno. Provjerava neparan broj `$` i neuravnotežene `{ }` unutar matematike; to su "
        "greške koje se mogu naći bez pokretanja LaTeXa. Ostalo javi pdflatex pri gradnji."
    )
    cijela_knjiga = st.checkbox(
        "Provjeri CIJELU knjigu (sva poglavlja, ne samo odabrana)", value=True,
        key="tex_provjeri_sve",
        help="Da odjednom vidiš sve što treba popraviti, a ne samo u poglavljima koja sad ispisuješ.")
    if st.button("🔍 Provjeri sada", key="tex_provjeri_gumb"):
        _za_provjeru = sva_poglavlja if cijela_knjiga else poglavlja
        _nalazi = sl.provjeri_latex(_za_provjeru)
        if not _nalazi:
            st.success(f"Nema nijedne greške u {len(_za_provjeru)} poglavlja. Možeš generirati PDF.")
        else:
            _redaka = len({(p["poglavlje_kljuc"], p["id"]) for p in _nalazi})
            st.error(f"❌ {len(_nalazi)} nalaza u {_redaka} redaka baze "
                     f"(provjereno {len(_za_provjeru)} poglavlja).")
            _prikazi_problema(_nalazi, "Sve greške:")


# ---------------------------------------------------------------
# Gradnja PDF-a
# ---------------------------------------------------------------

def _pripremi_main_tex():
    """Popunjava predložak (v. pages/main_skripta_template.tex). Naslov/podnaslov prolaze
    kroz escape_outside_math jer ih Caki tipka slobodno (& ili % u naslovu inače ruši build)."""
    with open(os.path.join(TEMPLATE_DIR, "main_skripta_template.tex"), encoding="utf-8") as f:
        main_tex = f.read()
    return (main_tex
            .replace("{{DVOSTRANO}}", ", twoside" if dvostrano else "")
            .replace("{{PREDMET_ZAGLAVLJE}}", predmet_config.postavke(PREDMET)["zaglavlje_pdf"])
            .replace("{{GEOMETRIJA}}", "\\cakiuvez" if dvostrano else "\\cakibezuveza")
            .replace("{{PRIJELOM}}", "" if nova_stranica else "\\cakicjelinebezprijeloma")
            .replace("{{SADRZAJ}}", "\\cakisadrzaj" if sa_sadrzajem else "")
            .replace("{{NASLOV_ZAGLAVLJE}}", escape_outside_math(naslov))
            .replace("{{NASLOV}}", escape_outside_math(naslov))
            .replace("{{PODNASLOV}}", escape_outside_math(podnaslov))
            .replace("{{DATUM}}", datetime.date.today().strftime("%d.%m.%Y."))
            .replace("{{LEGENDA}}", escape_outside_math(TEZINA_LEGENDA)))


if st.button("🖨️ Generiraj PDF", type="primary", key="tex_generiraj"):
    # Provjera prije kompajliranja: SVI nalazi odjednom (ne jedan po jedan), jer pdflatex s
    # -halt-on-error staje na prvoj grešci pa bi inače slijedilo desetke krugova.
    problemi = sl.provjeri_latex(poglavlja)
    if problemi and not dopusti_neispravne:
        redaka = len({(p["poglavlje_kljuc"], p["id"]) for p in problemi})
        st.error(
            f"❌ {len(problemi)} nalaza u {redaka} redaka baze razbilo bi kompajliranje. "
            "Ispravi ih u Sheetu pa klikni gumb za osvježavanje ispod tablice — ili uključi "
            "kvačicu „Nastavi i kad neki zadatak ima neispravan LaTeX” gore i ispiši skriptu "
            "odmah, s označenim mjestima.")
        _prikazi_problema(problemi, "Sve greške u odabranim poglavljima:")
        st.stop()
    if problemi:
        st.warning(f"⚠️ {len(problemi)} nalaza — ta mjesta će u PDF-u biti označena kao "
                   "NEISPRAVAN LaTeX, ostalo se ispisuje normalno.")
        _prikazi_problema(problemi, "Označeno u PDF-u:")

    # Slike se dohvaćaju PRIJE gradnje .tex-a, da se u dokument upišu samo one koje stvarno
    # postoje (isti razlog kao u Test Builderu).
    slike_bytes = {}
    if sa_slikama:
        potrebne = sl.sve_slike(poglavlja)
        if potrebne:
            traka = st.progress(0.0, text=f"Dohvaćam slike (0/{len(potrebne)})…")
            for i, naziv in enumerate(potrebne, start=1):
                b = _sliku_bytes_za(naziv, PREDMET)
                if b:
                    slike_bytes[naziv] = b
                traka.progress(i / len(potrebne), text=f"Dohvaćam slike ({i}/{len(potrebne)})…")
            traka.empty()
            nedostaju = [x for x in potrebne if x not in slike_bytes]
            if nedostaju:
                st.warning(f"⚠️ {len(nedostaju)} slika nije pronađeno na Driveu (nastavljam bez "
                           f"njih): {', '.join(nedostaju[:15])}"
                           + ("…" if len(nedostaju) > 15 else ""))

    tijelo, broj_p, broj_z = sl.izgradi_tijelo(
        poglavlja, verzija=verzija, rjesenja=rjesenja, slike_dostupne=set(slike_bytes),
        preskoci_neispravne=bool(problemi), mjesto_rjesenja=mjesto_rjesenja)
    if not tijelo.strip():
        st.error("Nema sadržaja za PDF.")
        st.stop()

    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "generated"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "images"), exist_ok=True)
        with open(os.path.join(tmpdir, "main.tex"), "w", encoding="utf-8") as f:
            f.write(_pripremi_main_tex())
        with open(os.path.join(tmpdir, "generated", "skripta_body.tex"), "w", encoding="utf-8") as f:
            f.write(tijelo)
        for sty in ("caki-style.sty", "caki-skripta.sty"):
            with open(os.path.join(TEMPLATE_DIR, sty), encoding="utf-8") as f:
                sadrzaj = f.read()
            with open(os.path.join(tmpdir, sty), "w", encoding="utf-8") as f:
                f.write(sadrzaj)
        for naziv, b in slike_bytes.items():
            with open(os.path.join(tmpdir, "images", naziv), "wb") as f:
                f.write(b)

        with st.spinner(f"Kompajliram PDF ({broj_p} primjera, {broj_z} zadataka)…"):
            ok, log_tail = True, ""
            # Dva prolaza: breakable tcolorbox okviri i fancyhdr trebaju drugi prolaz da
            # se prijelomi/brojevi stranica slegnu (isto kao Test Builder).
            # TRI prolaza kad je uključen sadržaj: 1. skupi stavke u .toc, 2. ubaci sadržaj
            # (čime se sav sadržaj pomakne za koju stranicu), 3. ispravi brojeve stranica.
            for _ in range(3 if sa_sadrzajem else 2):
                r = subprocess.run(
                    ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode",
                     "-halt-on-error", "main.tex"],
                    cwd=tmpdir, capture_output=True, text=True, timeout=240,
                    encoding="utf-8", errors="replace")
                if r.returncode != 0:
                    ok = False
                    log_tail = "\n".join((r.stdout or "").splitlines()[-45:])
                    break

        if not ok:
            st.error("Kompajliranje nije uspjelo. Najčešći uzroci: neuparen `$`, pogrešan LaTeX "
                     "u ručnom bloku formula ili u tekstu teorije.")
            st.code(log_tail, language="text")
            with st.expander("Prikaži generirani .tex (za dijagnostiku)"):
                st.code(tijelo[:20000], language="latex")
        else:
            with open(os.path.join(tmpdir, "main.pdf"), "rb") as f:
                pdf_bytes = f.read()
            st.success(f"PDF generiran ({len(pdf_bytes) // 1024} kB).")
            ime = f"{naslov.replace(' ', '_')}_{verzija}.pdf"
            st.download_button("⬇️ Preuzmi PDF", data=pdf_bytes, file_name=ime,
                               mime="application/pdf")
