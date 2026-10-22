"""
CAKI — radovi_admin.py  (22.10.2026.)

📸 Pomoćne funkcije za **pregled radova učenika** u bazi zadataka (stranica `15_radovi.py`).

Zašto zasebna kopija: portal (`caki-booking-termina/radovi.py`) piše u isti tab `Radovi`, ali
Streamlit Cloud deploya svaki repo zasebno — dijeljeni import nije moguć. Zato su ovdje samo
**čiste funkcije za čitanje i označavanje**, bez uploada.

Tvrdi podaci (tab `Radovi` u CRM Sheetu): rad_id, test_id, ucenik_id, file_id, naziv, vrsta,
velicina, kreirano, status, link.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

RADOVI_TAB = "Radovi"
RADOVI_HEADERS = ["rad_id", "test_id", "ucenik_id", "file_id", "naziv", "vrsta",
                  "velicina", "kreirano", "status", "link"]
DANI_CUVANJA = 7
DRIVE_WEB = "https://drive.google.com/file/d/{file_id}/view"


def _tekst(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def load_radovi(sheet) -> list[dict]:
    try:
        ws = sheet.worksheet(RADOVI_TAB)
    except Exception:                                   # noqa: BLE001
        return []
    try:
        return [r for r in ws.get_all_records() if _tekst(r.get("rad_id"))]
    except Exception:                                   # noqa: BLE001
        return []


def za_test(radovi, test_id: str) -> list[dict]:
    return [r for r in radovi or [] if _tekst(r.get("test_id")) == _tekst(test_id)]


def stariji_od(radovi, dana: int = DANI_CUVANJA, danas=None) -> list[dict]:
    """Radovi stariji od `dana` (za brisanje); neispravan datum se preskače."""
    granica = (danas or date.today()) - timedelta(days=max(0, int(dana)))
    izlaz = []
    for r in radovi or []:
        try:
            kad = datetime.fromisoformat(_tekst(r.get("kreirano")).replace(" ", "T")).date()
        except ValueError:
            continue
        if kad < granica and _tekst(r.get("status")) != "Obrisano":
            izlaz.append(r)
    return izlaz


def oznaci_obrisano(sheet, rad_id: str) -> bool:
    """Označi radak kao Obrisano (zapis ostaje za evidenciju)."""
    try:
        ws = sheet.worksheet(RADOVI_TAB)
        zaglavlje = [_tekst(h) for h in ws.row_values(1)]
        if "status" not in zaglavlje:
            return False
        kolona = zaglavlje.index("status") + 1
        for i, vrijednost in enumerate(ws.col_values(1), start=1):
            if _tekst(vrijednost) == _tekst(rad_id):
                ws.update_cell(i, kolona, "Obrisano")
                return True
    except Exception:                                   # noqa: BLE001
        return False
    return False


def tablica(radovi):
    import pandas as pd

    return pd.DataFrame([{
        "ID": _tekst(r.get("rad_id")),
        "Test": _tekst(r.get("test_id")),
        "Učenik": _tekst(r.get("ucenik_id")).upper(),
        "Datoteka": _tekst(r.get("naziv")),
        "Vrsta": _tekst(r.get("vrsta")),
        "KB": round(int(r.get("velicina") or 0) / 1024, 1),
        "Kreirano": _tekst(r.get("kreirano")),
        "Status": _tekst(r.get("status")),
        "Otvori": _tekst(r.get("link")),
    } for r in radovi or []])


__all__ = [
    "RADOVI_TAB", "RADOVI_HEADERS", "DANI_CUVANJA", "DRIVE_WEB", "load_radovi", "za_test",
    "stariji_od", "oznaci_obrisano", "tablica",
]
