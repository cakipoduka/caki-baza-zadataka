"""
CAKI — formule.py  (22.10.2026.)

📐 Baza **formula** za ispite (matura, razredni ispiti) — Caki ih unosi u LaTeXu, slaže u
**pakete** (npr. „Matura 2026 — službene") i pri objavi testa odabere što učenik smije vidjeti
u desnoj koloni portala.

Model (Cakijeva odluka 22.10.2026.): formule žive u **bazi zadataka** (tab `Formule`), a u test
se pri objavi **zamrzne kopija teksta** (`formule_json` u retku testa). Zašto kopija: portal čita
samo CRM Sheet i nema pristup bazi — ovako ne treba ništa dodatno, a učenik vidi isto što je
Caki vidio u trenutku objave.

Tvrdi podaci (tab `Formule`): formula_id, naslov, cjelina, paket, tekst_latex, opis, aktivno,
kreirano.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

FORMULE_TAB = "Formule"
FORMULE_HEADERS = ["formula_id", "naslov", "cjelina", "paket", "tekst_latex",
                   "datoteka", "opis", "aktivno", "kreirano"]

MAX_FORMULA_ZNAKOVA = 4000      # zaštita od jedne divovske formule (Sheets ćelija ~45k)


def _tekst(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _cjeline(vrijednost) -> str:
    """Cjelina može biti jedna ili VIŠE (lista) — čuva se kao „A; B; C"."""
    if isinstance(vrijednost, (list, tuple, set)):
        dijelovi = [_tekst(x) for x in vrijednost if _tekst(x)]
    else:
        dijelovi = [_tekst(x) for x in str(vrijednost or "").split(";") if _tekst(x)]
    vidjeno, izlaz = set(), []
    for d in dijelovi:
        if d not in vidjeno:
            vidjeno.add(d)
            izlaz.append(d)
    return "; ".join(izlaz)


def cjeline(formula) -> list[str]:
    """Popis cjelina iz retka formule (prazna lista ako nema)."""
    return [_tekst(x) for x in _tekst((formula or {}).get("cjelina")).split(";")
            if _tekst(x)]


# ============================================================
# Tab i CRUD
# ============================================================

def osiguraj_tab(sheet):
    """Otvori tab `Formule` — i **dopuni zaglavlje** ako su dodani novi stupci.

    22.10.2026. (Cakijev nalaz „dodao sam PDF, ali ništa se ne vidi"): tab je mogao nastati prije
    stupca `datoteka`, pa su se vrijednosti pisale pod pogrešna imena. Sada se nedostajući stupci
    dopisuju, pa zapis uvijek sjedne pod svoje ime.
    """
    try:
        ws = sheet.worksheet(FORMULE_TAB)
    except Exception:                                   # noqa: BLE001 — tab još ne postoji
        ws = sheet.add_worksheet(title=FORMULE_TAB, rows=300, cols=len(FORMULE_HEADERS))
        ws.append_row(FORMULE_HEADERS, value_input_option="RAW")
        return ws

    try:
        zaglavlje = [_tekst(h) for h in ws.row_values(1)]
        fali = [h for h in FORMULE_HEADERS if h not in zaglavlje]
        if fali:
            if len(zaglavlje) + len(fali) > getattr(ws, "col_count", 0):
                try:
                    ws.add_cols(len(zaglavlje) + len(fali) - getattr(ws, "col_count", 0))
                except Exception:                       # noqa: BLE001 — neke kopije nemaju
                    pass
            for i, naziv in enumerate(fali, start=len(zaglavlje) + 1):
                try:
                    ws.update_cell(1, i, naziv)
                except Exception:                       # noqa: BLE001
                    break
    except Exception:                                   # noqa: BLE001 — čitanje zaglavlja
        pass
    return ws


def load_formule(sheet) -> list[dict]:
    try:
        ws = sheet.worksheet(FORMULE_TAB)
    except Exception:                                   # noqa: BLE001
        return []
    try:
        redci = ws.get_all_records()
    except Exception:                                   # noqa: BLE001
        return []
    return [r for r in redci if _tekst(r.get("formula_id"))]


def novi_id(postojeci=()) -> str:
    danas = datetime.now().strftime("%y%m%d")
    postojeci = {_tekst(x) for x in (postojeci or ()) if _tekst(x)}
    for _ in range(200):
        kandidat = f"F{danas}-{len(postojeci) + 1}"
        if kandidat not in postojeci:
            return kandidat
        postojeci.add(kandidat)
    raise RuntimeError("Ne mogu složiti jedinstven ID formule.")


def dodaj_formulu(sheet, *, naslov: str, tekst_latex: str = "", cjelina: str = "", paket: str = "",
                  datoteka: str = "", opis: str = "", aktivno: bool = True) -> dict:
    naslov = _tekst(naslov)
    tekst_latex = _tekst(tekst_latex)
    datoteka = _tekst(datoteka)
    if not naslov:
        raise ValueError("Formula treba naziv.")
    if not tekst_latex and not datoteka:
        raise ValueError("Formula treba sadržaj — LaTeX ILI datoteku (PDF/slika) iz Drivea.")
    if len(tekst_latex) > MAX_FORMULA_ZNAKOVA:
        raise ValueError(f"Formula je predugačka (>{MAX_FORMULA_ZNAKOVA} znakova).")
    ws = osiguraj_tab(sheet)
    try:
        postojeci = [_tekst(v) for v in ws.col_values(1)]
    except Exception:                                   # noqa: BLE001
        postojeci = []
    redak = {
        "formula_id": novi_id(postojeci),
        "naslov": naslov,
        "cjelina": _cjeline(cjelina),
        "paket": _tekst(paket),
        "tekst_latex": tekst_latex,
        "datoteka": datoteka,
        "opis": _tekst(opis)[:300],
        "aktivno": "Da" if aktivno else "Ne",
        "kreirano": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # Piše se po STVARNOM zaglavlju taba: ako je stupac dopisan na kraj, vrijednosti i dalje
    # sjedaju pod svoje ime (22.10.2026., Cakijev nalaz s PDF-om koji „nestane”).
    _zaglavlje = [_tekst(h) for h in ws.row_values(1)] or list(FORMULE_HEADERS)
    ws.append_row([redak.get(h, "") for h in _zaglavlje], value_input_option="RAW")
    return redak


def _redak_broj(ws, formula_id: str):
    try:
        idovi = [_tekst(v) for v in ws.col_values(1)]
    except Exception:                                   # noqa: BLE001
        return None
    for i, vrijednost in enumerate(idovi, start=1):
        if vrijednost == _tekst(formula_id):
            return i
    return None


def azuriraj_formulu(sheet, formula_id: str, polja: dict) -> bool:
    ws = osiguraj_tab(sheet)
    redak = _redak_broj(ws, formula_id)
    if redak is None:
        raise ValueError(f"Formule `{formula_id}` nema u tabu.")
    dopusteno = {h: True for h in FORMULE_HEADERS}
    izmjene = {k: v for k, v in (polja or {}).items() if k in dopusteno and k != "formula_id"}
    if not izmjene:
        return False
    zaglavlje = [_tekst(h) for h in ws.row_values(1)]
    for kljuc, vrijednost in izmjene.items():
        if kljuc == "aktivno":
            vrijednost = "Da" if _tekst(vrijednost) in ("Da", "da", "True", "1") else "Ne"
        if kljuc in zaglavlje:
            ws.update_cell(redak, zaglavlje.index(kljuc) + 1, vrijednost)
    return True


def obrisi_formulu(sheet, formula_id: str) -> bool:
    ws = osiguraj_tab(sheet)
    redak = _redak_broj(ws, formula_id)
    if redak is None:
        return False
    ws.delete_rows(redak)
    return True


# ============================================================
# Paketi i odabir za test
# ============================================================

def paketi(formule) -> list[str]:
    """Nazivi paketa koji imaju barem jednu formulu (prazan paket se ne nudi)."""
    return sorted({_tekst(f.get("paket")) for f in formule or [] if _tekst(f.get("paket"))})


def aktivne(formule) -> list[dict]:
    return [f for f in formule or [] if _tekst(f.get("aktivno")) in ("Da", "da", "")]


def izbor_za_test(formule, paketi_odabrani=(), idovi_odabrani=(), sve: bool = False) -> list[dict]:
    """Odabir formule za JEDAN test — vraća zamrznute retke (naslov, cjelina, latex, opis).

    Redoslijed: sve (ako je označeno) → paketi → pojedinačne. Duplikati se preskaču.
    """
    izvor = aktivne(formule)
    zele = {_tekst(p) for p in paketi_odabrani or [] if _tekst(p)}
    idovi = {_tekst(i) for i in idovi_odabrani or [] if _tekst(i)}
    izlaz, vidjeno = [], set()
    for f in izvor:
        fid = _tekst(f.get("formula_id"))
        if not (sve or _tekst(f.get("paket")) in zele or fid in idovi):
            continue
        if fid in vidjeno:
            continue
        vidjeno.add(fid)
        izlaz.append({
            "formula_id": fid,
            "naslov": _tekst(f.get("naslov")),
            "cjelina": _tekst(f.get("cjelina")),
            "paket": _tekst(f.get("paket")),
            "tekst_latex": _tekst(f.get("tekst_latex")),
            "datoteka": _tekst(f.get("datoteka")),
            "opis": _tekst(f.get("opis")),
        })
    return izlaz


def u_json(formule) -> str:
    return json.dumps(list(formule or []), ensure_ascii=False) if formule else ""


def iz_retka(redak) -> list[dict]:
    """Zamrznute formule iz retka testa (`formule_json`)."""
    sirovo = _tekst((redak or {}).get("formule_json")) or _tekst((redak or {}).get("formule"))
    if not sirovo:
        return []
    try:
        podaci = json.loads(sirovo)
    except ValueError:
        return []
    return [f for f in podaci if isinstance(f, dict)
            and (_tekst(f.get("tekst_latex")) or _tekst(f.get("datoteka")))] \
        if isinstance(podaci, list) else []


# ============================================================
# Prikaz
# ============================================================

def tekst_formule(formula) -> str:
    """Markdown za prikaz formule (Streamlit renderira $…$ preko KaTeX-a)."""
    latex = _tekst((formula or {}).get("tekst_latex"))
    if not latex:
        return ""
    if "$" in latex:
        return latex
    return f"$${latex}$$"


def tablica(formule):
    import pandas as pd

    return pd.DataFrame([{
        "ID": _tekst(f.get("formula_id")),
        "Naziv": _tekst(f.get("naslov")),
        "Cjelina": _tekst(f.get("cjelina")),
        "Paket": _tekst(f.get("paket")),
        "Aktivna": _tekst(f.get("aktivno")),
        "Opis": _tekst(f.get("opis")),
    } for f in formule or []])


__all__ = [
    "FORMULE_TAB", "FORMULE_HEADERS", "MAX_FORMULA_ZNAKOVA", "osiguraj_tab", "load_formule",
    "novi_id", "dodaj_formulu", "azuriraj_formulu", "obrisi_formulu", "paketi", "aktivne",
    "izbor_za_test", "u_json", "iz_retka", "tekst_formule", "tablica",
    "cjeline", "_cjeline",
]
