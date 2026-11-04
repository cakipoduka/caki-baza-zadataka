"""
CAKI — skripta_latex_postavke.py (4.11.2026.)

Postavke PO POGLAVLJU za novu stazu „Skripta (LaTeX)": oznaka cjeline, koja teorija ide
ispod naslova, koje formule i ručno upisan LaTeX blok formula.

ZAŠTO ZASEBAN TAB (`Skripta_latex_postavke`): tab `Sifrarnik_poglavlja_knjige` dijeli
PreTeXt staza (pages/4_skripta.py + skripta_build.py) i ondje se NIŠTA ne dira — nova
staza samo ČITA odatle redoslijed, nazive i odabir zadataka. Sve što je novo (teorija,
formule, oznaka) živi u vlastitom tabu, pa dodavanje stupca ovdje ne može srušiti
postojeću skriptu. Tab se, kao i ostali šifrarnici u projektu, sam kreira pri prvom
spremanju; dok ga nema, `ucitaj` vraća prazno i ništa ne puca.

Redci bez `poglavlje_kljuc` se preskaču. Spremanje PREPISUJE cijeli tab (desetci redaka,
isti pristup kao bp.spremi_naslove_poglavlja — sigurnije nego upsert po retku).
"""
from __future__ import annotations

import baza_zadataka_pipeline as bp

POSTAVKE_TAB = "Skripta_latex_postavke"
POSTAVKE_HEADERS = ["poglavlje_kljuc", "oznaka", "teorija_kljuc", "formule_ids", "formule_rucno",
                    # 4.11.2026. (Caki): „da"/„ne" — ide li poglavlje u OVU skriptu. Odvojeno od
                    # stupca `ukljuceno` u tabu Sifrarnik_poglavlja_knjige, koji je dio plana za
                    # PreTeXt stazu: Caki tipka cijelu knjigu, a usput ispisuje samo gotova
                    # poglavlja — ne smije zbog toga mijenjati glavni plan. Prazno = da.
                    "u_skripti"]

# Razdjelnik u `teorija_kljuc` — (cjelina, potpoglavlje) spljošteno u jednu ćeliju.
TEORIJA_RAZDJELNIK = "||"


def _t(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def kljuc_teorije(cjelina: str, potpoglavlje: str) -> str:
    return f"{_t(cjelina)}{TEORIJA_RAZDJELNIK}{_t(potpoglavlje)}"


def razdvoji_kljuc_teorije(kljuc: str) -> tuple:
    """'Algebra||Kvadratna jednadžba' -> ('Algebra', 'Kvadratna jednadžba'); prazno -> ('','')."""
    dijelovi = _t(kljuc).split(TEORIJA_RAZDJELNIK)
    if len(dijelovi) != 2:
        return "", ""
    return dijelovi[0].strip(), dijelovi[1].strip()


def ucitaj(sheet) -> dict:
    """{poglavlje_kljuc: {"oznaka", "teorija_kljuc", "formule_ids": [...], "formule_rucno"}}.
    Tab koji ne postoji -> prazan rječnik (bez greške, bez kreiranja — kreira se tek pri
    prvom spremanju, da se Sheet ne zatrpa praznim tabovima)."""
    try:
        ws = sheet.worksheet(POSTAVKE_TAB)
    except Exception:                                   # noqa: BLE001 — tab još ne postoji
        return {}
    try:
        redovi = ws.get_all_values()
    except Exception:                                   # noqa: BLE001
        return {}
    if len(redovi) < 2:
        return {}
    zaglavlje = [_t(h) for h in redovi[0]]
    idx = {h: i for i, h in enumerate(zaglavlje)}

    def _celija(r, ime):
        i = idx.get(ime)
        return _t(r[i]) if i is not None and i < len(r) else ""

    izlaz = {}
    for r in redovi[1:]:
        kljuc = _celija(r, "poglavlje_kljuc")
        if not kljuc:
            continue
        ids = [x.strip() for x in _celija(r, "formule_ids").split(",") if x.strip()]
        izlaz[kljuc] = {
            "oznaka": _celija(r, "oznaka"),
            "teorija_kljuc": _celija(r, "teorija_kljuc"),
            "formule_ids": ids,
            "formule_rucno": _celija(r, "formule_rucno"),
            # Prazno/nepoznato = DA (poglavlje ide u skriptu) — tako stari redci, zapisani
            # prije nego je ovaj stupac postojao, ostaju uključeni.
            "u_skripti": _celija(r, "u_skripti").lower() not in ("ne", "no", "false", "0"),
        }
    return izlaz


def spremi(sheet, postavke: dict) -> None:
    """Prepisuje CIJELI tab. postavke: isti oblik kakav vraća `ucitaj`.

    Redak se izostavlja samo ako NEMA ničega za zapamtiti — dakle ako su sva polja prazna
    I poglavlje je uključeno (to je ionako zadano stanje). Isključeno poglavlje se MORA
    zapisati i kad je sve ostalo prazno, inače bi se pri sljedećem učitavanju vratilo kao
    uključeno."""
    ws = bp.get_or_create_worksheet(sheet, POSTAVKE_TAB, POSTAVKE_HEADERS)
    redci = [POSTAVKE_HEADERS]
    for kljuc, p in (postavke or {}).items():
        kljuc = _t(kljuc)
        if not kljuc:
            continue
        oznaka = _t((p or {}).get("oznaka"))
        teorija = _t((p or {}).get("teorija_kljuc"))
        ids = ", ".join(_t(x) for x in ((p or {}).get("formule_ids") or []) if _t(x))
        rucno = _t((p or {}).get("formule_rucno"))
        u_skripti = (p or {}).get("u_skripti", True)
        if not (oznaka or teorija or ids or rucno) and u_skripti:
            continue
        redci.append([kljuc, oznaka, teorija, ids, rucno, "da" if u_skripti else "ne"])
    ws.clear()
    ws.update(values=redci, range_name="A1", value_input_option="RAW")
