"""CAKI — popravci_posao.py  (26.10.2026.)

Dva POPRAVKA postojećih podataka u bazi (ne diraju strukturu):

1. `popravi_cjeline` — zadaci kojima `potpoglavlje` pripada drugoj cjelini ili ga nema u
   šifrarniku. Primjenjuje SAMO jednoznačne slučajeve:
     - potpoglavlje postoji u šifrarniku pod TOČNO JEDNOM cjelinom → ispravi `cjelina`,
     - potpoglavlje ne postoji, ali postoji TOČNO JEDAN dovoljno sličan naziv → ispravi
       `potpoglavlje` (npr. „Grafički prikaz funkcije" → „Grafički prikaz funkcija").
   Dvoznačno (npr. „Domena i slika funkcije" pod dvije cjeline) se PRESKAČE i ostaje za ručno.

2. `popravi_tezinu` — normalizira `tezina` na tri dopuštene vrijednosti: `lako`, `srednje`,
   `teško`. U bazi su bila DVA zapisa za isto: `tesko` (266) i `teško` (10) → sada samo `teško`.

Oba vraćaju promjene u istom obliku kao ostali poslovi; upis i undo radi `radnik.py`.
"""
from __future__ import annotations

import difflib
import re

TEZINE = {"lako": "lako", "srednje": "srednje", "srednje teško": "srednje", "tesko": "teško",
          "teško": "teško", "tezak": "teško", "težak": "teško", "lako/teško": "teško"}

_SIFRARNIK_CACHE: dict = {}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _dodaj_napomenu(tekst: str, napomena: str) -> str:
    t = _s(tekst)
    return f"{t}; {napomena}" if t else napomena


def _sifrarnik(sheet):
    """{cjelina: {potpoglavlja}} i {potpoglavlje: {cjeline}} iz taba `Sifrarnik_potpoglavlja`."""
    if "mapa" in _SIFRARNIK_CACHE:
        return _SIFRARNIK_CACHE["mapa"], _SIFRARNIK_CACHE["po_pp"]
    mapa: dict[str, set] = {}
    if sheet is not None:
        try:
            ws = sheet.worksheet("Sifrarnik_potpoglavlja")
            for r in ws.get_all_records():
                c, p = _s(r.get("cjelina")), _s(r.get("potpoglavlje"))
                if c and p:
                    mapa.setdefault(c, set()).add(p)
        except Exception:                                  # noqa: BLE001 — tab ne postoji
            mapa = {}
    po_pp: dict[str, set] = {}
    for c, ps in mapa.items():
        for p in ps:
            po_pp.setdefault(p, set()).add(c)
    _SIFRARNIK_CACHE["mapa"], _SIFRARNIK_CACHE["po_pp"] = mapa, po_pp
    return mapa, po_pp


# ---------------------------------------------------------------------------------------------
# 1) cjeline / potpoglavlja
# ---------------------------------------------------------------------------------------------

def predlozi_cjeline(redak: dict, sheet=None) -> dict | None:
    mapa, po_pp = _sifrarnik(sheet)
    if not mapa:
        return None
    cjelina, potp = _s(redak.get("cjelina")), _s(redak.get("potpoglavlje"))
    if not potp:
        return None
    if potp in mapa.get(cjelina, set()):
        return None                                        # već je ispravno

    novo_polje, nova_vrijednost, opis = None, "", ""
    if potp in po_pp:
        opcije = sorted(po_pp[potp])
        if len(opcije) == 1 and cjelina != opcije[0]:
            novo_polje, nova_vrijednost = "cjelina", opcije[0]
            opis = f"CJELINA: {cjelina!r} -> {opcije[0]!r} (potpoglavlje pripada tamo)"
    else:
        blizu = difflib.get_close_matches(potp, sorted(po_pp), n=2, cutoff=0.85)
        if len(blizu) == 1:
            novo_polje, nova_vrijednost = "potpoglavlje", blizu[0]
            opis = f"POTPOGLAVLJE: {potp!r} -> {blizu[0]!r} (nije bilo u šifrarniku)"
    if not novo_polje:
        return None                                        # dvoznačno ili nema dovoljno sličnog - ručno

    novo_status = _dodaj_napomenu(redak.get("status_provjere"), "POPRAVLJENO: " + opis)
    return {
        "polja": {novo_polje: nova_vrijednost, "status_provjere": novo_status},
        "novi_redci": [],
        "log": [{"id": _s(redak.get("id")), "polje": novo_polje,
                 "staro": _s(redak.get(novo_polje)), "novo": nova_vrijednost},
                {"id": _s(redak.get("id")), "polje": "status_provjere",
                 "staro": _s(redak.get("status_provjere")), "novo": novo_status}],
    }


def vec_obradjeno_cjeline(redak: dict) -> bool:
    """Preskoči ako je već popravljano (oznaka POPRAVLJENO) — da ponovni prolaz ne piše opet."""
    return "POPRAVLJENO: CJELINA" in _s(redak.get("status_provjere")) or \
           "POPRAVLJENO: POTPOGLAVLJE" in _s(redak.get("status_provjere"))


def provjeri_cjeline(redak: dict, promjene: dict) -> bool:
    polja = promjene.get("polja", {})
    return bool(_s(polja.get("cjelina")) or _s(polja.get("potpoglavlje")))


# ---------------------------------------------------------------------------------------------
# 2) težina
# ---------------------------------------------------------------------------------------------

def normaliziraj_tezinu(vrijednost: str) -> str:
    """'tesko' / 'Teško' / ' teško ' -> 'teško'; 'srednje' ostaje; nepoznato -> ''."""
    t = _s(vrijednost).lower()
    t = re.sub(r"\s+", " ", t)
    return TEZINE.get(t, "")


def predlozi_tezinu(redak: dict, sheet=None) -> dict | None:
    staro = _s(redak.get("tezina"))
    novo = normaliziraj_tezinu(staro)
    if not novo or novo == staro:
        return None
    return {
        "polja": {"tezina": novo},
        "novi_redci": [],
        "log": [{"id": _s(redak.get("id")), "polje": "tezina", "staro": staro, "novo": novo}],
    }


def vec_obradjeno_tezina(redak: dict) -> bool:
    return normaliziraj_tezinu(redak.get("tezina")) == _s(redak.get("tezina"))


def provjeri_tezinu(redak: dict, promjene: dict) -> bool:
    novo = _s(promjene.get("polja", {}).get("tezina"))
    return novo in ("lako", "srednje", "teško")
