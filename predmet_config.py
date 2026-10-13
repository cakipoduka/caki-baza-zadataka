"""
CAKI - predmet_config.py (12.10.2026.)

Jedno mjesto koje zna KOJI PREDMET je aktivan (matematika, fizika, ...) i koji Google Sheet,
koji Drive folder sa slikama i koje postavke pripadaju tom predmetu.

Odluka (Caki, 12.10.2026.): JEDAN kod i JEDNA Streamlit aplikacija, a svaki predmet ima
SVOJ Google Sheet (isti tabovi i isti stupci kao matematika) i SVOJ folder sa slikama.
Predmet se bira u bočnoj traci ("Predmet"), a može se unaprijed postaviti u linku:
    https://<aplikacija>/?predmet=fizika

Kako se predmet uključuje: u Streamlit Secrets dodaj dva retka (vrijednosti su ID-ovi,
ne nazivi):
    SHEET_ID_FIZIKA = "XXXX"
    SLIKE_FOLDER_ID_FIZIKA = "XXXX"
Dok tih redaka nema, predmet "fizika" se uopće ne nudi i aplikacija radi točno kao prije
(samo matematika). Matematika i dalje koristi postojeće SHEET_ID i SLIKE_FOLDER_ID.

Ovaj modul NE uvozi streamlit na vrhu (da ga mogu koristiti i skripte/testovi bez njega);
funkcija odaberi_predmet() ga uvozi tek kad se pozove.
"""

ZADANI_PREDMET = "matematika"

# Kategorije vrednovanja (UZV/RP/MK) postoje samo u kurikulumu matematike. Za ostale
# predmete lista je prazna pa se u Test Builderu ne prikazuju.
_KATEGORIJE_MATEMATIKA = [
    ("UZV", "Usvojenost znanja i vještina"),
    ("RP", "Rješavanje problema"),
    ("MK", "Matematička komunikacija"),
]

PREDMETI = {
    "matematika": {
        "naziv": "Matematika",
        "naslov_aplikacije": "CAKI Matematika",
        "zaglavlje_pdf": "MATEMATIKA",       # lijevo gore na svakoj stranici PDF-a (Test Builder)
        "sheet_kljuc": "SHEET_ID",
        "slike_kljuc": "SLIKE_FOLDER_ID",
        "razine": ["A", "B", "-"],            # državna matura iz matematike ima razine A i B
        "kategorije_vrednovanja": _KATEGORIJE_MATEMATIKA,
        "slug": "matematika",
    },
    "fizika": {
        "naziv": "Fizika",
        "naslov_aplikacije": "CAKI Fizika",
        "zaglavlje_pdf": "FIZIKA",
        "sheet_kljuc": "SHEET_ID_FIZIKA",
        "slike_kljuc": "SLIKE_FOLDER_ID_FIZIKA",
        "razine": ["-"],                      # državna matura iz fizike ima jednu razinu
        "kategorije_vrednovanja": [],
        "slug": "fizika",
    },
}


def _secret(secrets, kljuc):
    """Vrijednost iz st.secrets (ili običnog dicta) kao string; prazan string ako nema."""
    try:
        v = secrets[kljuc]
    except Exception:
        return ""
    return str(v).strip() if v else ""


def normaliziraj_predmet(vrijednost):
    """'Fizika ' -> 'fizika'. Nepoznato/prazno -> None."""
    if not vrijednost:
        return None
    v = str(vrijednost).strip().lower()
    return v if v in PREDMETI else None


def postavke(predmet):
    return PREDMETI[normaliziraj_predmet(predmet) or ZADANI_PREDMET]


def predmet_dostupan(predmet, secrets):
    """Matematika je uvijek dostupna (postojeći SHEET_ID). Ostali predmeti samo ako su u
    Secrets postavljena OBA ID-a (Sheet i folder sa slikama)."""
    p = normaliziraj_predmet(predmet)
    if not p:
        return False
    if p == ZADANI_PREDMET:
        return True
    cfg = PREDMETI[p]
    return bool(_secret(secrets, cfg["sheet_kljuc"]) and _secret(secrets, cfg["slike_kljuc"]))


def dostupni_predmeti(secrets):
    return [p for p in PREDMETI if predmet_dostupan(p, secrets)]


def sheet_id(predmet, secrets):
    cfg = postavke(predmet)
    v = _secret(secrets, cfg["sheet_kljuc"])
    if not v:
        raise KeyError(f"U Streamlit Secrets nedostaje {cfg['sheet_kljuc']} (Sheet za predmet "
                       f"'{cfg['naziv']}').")
    return v


def slike_folder_id(predmet, secrets):
    cfg = postavke(predmet)
    v = _secret(secrets, cfg["slike_kljuc"])
    if not v:
        raise KeyError(f"U Streamlit Secrets nedostaje {cfg['slike_kljuc']} (folder sa slikama za "
                       f"predmet '{cfg['naziv']}').")
    return v


def kategorije_vrednovanja(predmet):
    return list(postavke(predmet)["kategorije_vrednovanja"])


def razine(predmet):
    return list(postavke(predmet)["razine"])


def odaberi_predmet(st=None):
    """Vraća aktivni predmet (slug) i, ako je dostupno više predmeta, crta izbornik
    "Predmet" u bočnoj traci. Vrijednost se čuva u st.session_state["predmet"], koji dijele
    SVE stranice aplikacije - dovoljno je odabrati jednom.

    Redoslijed: već odabrano u ovoj sesiji -> ?predmet= iz linka -> matematika."""
    if st is None:
        import streamlit as st  # noqa: PLC0415 - namjerno lijeni uvoz

    dostupni = dostupni_predmeti(st.secrets)

    trenutni = normaliziraj_predmet(st.session_state.get("predmet"))
    if trenutni is None:
        try:
            iz_linka = normaliziraj_predmet(st.query_params.get("predmet"))
        except Exception:
            iz_linka = None
        trenutni = iz_linka if iz_linka in dostupni else ZADANI_PREDMET
    if trenutni not in dostupni:
        trenutni = ZADANI_PREDMET
    st.session_state["predmet"] = trenutni

    if len(dostupni) > 1:
        def _na_promjenu():
            novi = normaliziraj_predmet(st.session_state.get("predmet_izbornik"))
            if novi in dostupni:
                st.session_state["predmet"] = novi
                try:
                    st.query_params["predmet"] = novi
                except Exception:
                    pass

        st.sidebar.selectbox(
            "Predmet", dostupni, index=dostupni.index(trenutni),
            format_func=lambda p: PREDMETI[p]["naziv"],
            key="predmet_izbornik", on_change=_na_promjenu,
        )
    return st.session_state["predmet"]


def zahtijevaj_matematiku(st, naziv_stranice):
    """Za stranice koje zasad rade samo za matematiku (WP alati, AI kontrola): ako je u bočnoj
    traci odabran drugi predmet, prikaže obavijest i zaustavi stranicu - tako se nikad ne
    piše po krivom Sheetu. Vraća aktivni predmet (uvijek 'matematika' ako ide dalje)."""
    predmet = odaberi_predmet(st)
    if predmet != ZADANI_PREDMET:
        st.info(f"Stranica „{naziv_stranice}” zasad radi samo za matematiku. "
                f"U bočnoj traci odaberi predmet „{PREDMETI[ZADANI_PREDMET]['naziv']}”.")
        st.stop()
    return predmet
