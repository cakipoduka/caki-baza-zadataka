"""
CAKI — pomoc_admin.py  (22.10.2026.)

Pregled **💡 Pomoći pri učenju** za Cakija — čita tab `AI_pomoc_log` koji portal puni
kad učenik pita bota tijekom rješavanja testa.

Dvije stvari koje Caki dobije:
    1. **Pitanja** — što su učenici pitali, je li filter spriječio curenje rješenja.
    2. **Video kandidati** — zadaci o kojima se najviše pita = najbolji kandidati za
       snimanje video rješenja i embed u bazu.

Namjerno zaseban modul (ne u `testovi_admin.py`): pregled je neovisan o panelu testova i
tako se ne sudara s drugim izmjenama istog dana.

Tabovi koje čita: `AI_pomoc_log` (CRM Sheet). Ništa se ovdje ne piše.
"""
from __future__ import annotations

LOG_TAB = "AI_pomoc_log"
LOG_HEADERS = ["pitanje_id", "test_id", "ucenik_id", "zadatak_id", "zadatak",
               "razina", "pitanje", "odgovor", "model", "filtrirano", "kreirano"]

MAX_PITANJA = 5          # koliko pitanja učenik smije postaviti po testu (portal)


def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def load_log(sheet) -> list[dict]:
    """Sva pitanja (prazna lista ako tab još ne postoji)."""
    try:
        ws = sheet.worksheet(LOG_TAB)
    except Exception:                                   # noqa: BLE001 — tab još ne postoji
        return []
    try:
        return [r for r in ws.get_all_records() if _tekst(r.get("pitanje_id"))]
    except Exception:                                   # noqa: BLE001 — Google ne odgovara
        return []


def sazetak(log) -> dict:
    """Brojevi za vrh stranice."""
    redci = list(log or [])
    filtrirano = sum(1 for r in redci if _tekst(r.get("filtrirano")) == "Da")
    return {
        "pitanja": len(redci),
        "ucenika": len({_tekst(r.get("ucenik_id")).upper() for r in redci if _tekst(r.get("ucenik_id"))}),
        "testova": len({_tekst(r.get("test_id")) for r in redci if _tekst(r.get("test_id"))}),
        "filtrirano": filtrirano,
        "zadataka": len({_tekst(r.get("zadatak_id")) for r in redci if _tekst(r.get("zadatak_id"))}),
    }


def video_kandidati(log, min_pitanja: int = 2) -> list[dict]:
    """Zadaci o kojima se najviše pita — kandidati za video rješenje.

    Jedan zadatak = jedan redak; broji se koliko je različitih učenika pitalo (ne samo
    koliko pitanja, da jedan učenik ne „napumpa” broj).
    """
    po_zadatku: dict[str, dict] = {}
    for r in log or []:
        zid = _tekst(r.get("zadatak_id"))
        if not zid:
            continue
        stavka = po_zadatku.setdefault(zid, {
            "zadatak_id": zid,
            "zadatak": _tekst(r.get("zadatak")),
            "pitanja": 0,
            "ucenici": set(),
            "testovi": set(),
        })
        stavka["pitanja"] += 1
        uid = _tekst(r.get("ucenik_id")).upper()
        if uid:
            stavka["ucenici"].add(uid)
        tid = _tekst(r.get("test_id"))
        if tid:
            stavka["testovi"].add(tid)
        if not stavka["zadatak"]:
            stavka["zadatak"] = _tekst(r.get("zadatak"))

    izlaz = []
    for s in po_zadatku.values():
        if s["pitanja"] < max(1, int(min_pitanja)):
            continue
        izlaz.append({
            "zadatak_id": s["zadatak_id"],
            "zadatak": s["zadatak"],
            "pitanja": s["pitanja"],
            "ucenika": len(s["ucenici"]),
            "testova": len(s["testovi"]),
        })
    izlaz.sort(key=lambda z: (-z["ucenika"], -z["pitanja"], z["zadatak_id"]))
    return izlaz


def tablica_loga(log, limit: int = 200):
    import pandas as pd

    redci = sorted(log or [], key=lambda r: _tekst(r.get("kreirano")), reverse=True)[:limit]
    return pd.DataFrame([{
        "Kad": _tekst(r.get("kreirano")),
        "Učenik": _tekst(r.get("ucenik_id")).upper(),
        "Test": _tekst(r.get("test_id")),
        "Zadatak": _tekst(r.get("zadatak_id")),
        "Razina": _tekst(r.get("razina")),
        "Pitanje": _tekst(r.get("pitanje")),
        "Odgovor": _tekst(r.get("odgovor")),
        "Filtrirano": _tekst(r.get("filtrirano")),
    } for r in redci])


def tablica_kandidata(kandidati):
    import pandas as pd

    return pd.DataFrame([{
        "Zadatak": k["zadatak_id"],
        "Tekst": k["zadatak"],
        "Pitalo učenika": k["ucenika"],
        "Pitanja": k["pitanja"],
        "U testova": k["testova"],
    } for k in kandidati or []])


def csv_loga(log) -> str:
    df = tablica_loga(log, limit=10_000)
    return df.to_csv(index=False, sep=";", lineterminator="\n") if not df.empty else ""


def csv_kandidata(kandidati) -> str:
    df = tablica_kandidata(kandidati)
    return df.to_csv(index=False, sep=";", lineterminator="\n") if not df.empty else ""


__all__ = [
    "LOG_TAB", "LOG_HEADERS", "MAX_PITANJA", "load_log", "sazetak", "video_kandidati",
    "tablica_loga", "tablica_kandidata", "csv_loga", "csv_kandidata",
]
