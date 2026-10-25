"""CAKI — radnik_poslovi.py  (22.10.2026.)

POPIS POSLOVA koje `radnik.py` zna odraditi. Svaki posao je mali rječnik s 4 funkcije:

    predlozi(redak, sheet=None)  -> {"polja": {...}, "novi_redci": [...], "log": [...]} ili None
    vec_obradjeno(redak)         -> bool   (preskoči ako je već obrađeno)
    provjeri(redak, promjene)    -> bool   (tvrda provjera PRIJE upisa; False = ne diraj)
    naziv                        -> str

Dodavanje novog posla (kratki odgovori, prijevodi, kontrole) = ~100–150 linija ovdje; radnik,
stanje, log i undo ostaju isti. AI, ako ga posao koristi, dobiva se kao funkcija `pozovi` — isti
obrazac kao `raspodjela_cjelina.py`, pa testovi rade bez mreže.
"""
from __future__ import annotations

import re

import podjela_zadataka as pz


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _dodaj_napomenu(tekst: str, napomena: str) -> str:
    t = _s(tekst)
    return f"{t}; {napomena}" if t else napomena


def _redak_stavke(redak: dict, oznaka: str, tekst: str, rjesenje: str, odgovor: str,
                  bodovi, roditelj_id: str, napomena: str = "") -> dict:
    """Novi redak stavke: kopija roditeljevih podataka + vlastiti tekst, rješenje i oznaka."""
    novi = dict(redak)
    novi.update({
        "id": pz.id_stavke(roditelj_id, oznaka),
        "tekst_zadatka_latex": tekst,
        "tekst_zadatka_mathjax": tekst.replace("\\\\", "<br>"),
        "rjesenje": rjesenje,
        "rjesenje_status": "sluzbeno" if rjesenje else "nedostaje",
        "tip_rjesenja_izvor": _s(redak.get("tip_rjesenja_izvor")) if rjesenje else "",
        "konacan_odgovor": odgovor,
        "max_bodovi": "" if not bodovi else (f"{bodovi:g}"),
        "uloga": "stavka",
        "roditelj_id": roditelj_id,
        "oznaka_stavke": oznaka,
        # slika ostaje na skupini (uvodu) - vidi napomenu u podjeli
        "slika_zadana": "ne",
        "slika_putanja": "",
        "slika_rjesenje_putanja": "",
        "status_provjere": _dodaj_napomenu(redak.get("status_provjere"), napomena) if napomena
                           else _s(redak.get("status_provjere")),
    })
    return novi


# ---------------------------------------------------------------------------------------------
# POSAO: cijepanje zadatka na podpitanja (deterministički)
# ---------------------------------------------------------------------------------------------

def _predlozi_cijepanje(redak: dict, sheet=None):
    p = pz.podijeli(redak)
    if not p:
        return None
    roditelj_id = p["id"]
    uvod = p["uvod"]
    polja = {
        "uloga": "skupina",
        "tekst_zadatka_latex": uvod,
        "tekst_zadatka_mathjax": uvod.replace("\\\\", "<br>"),
        # 22.10.2026.: rješenje i konačni odgovor NE brišu se s roditelja (prvi pravi prolaz je
        # pokazao da se time gubi podatak, npr. "19.7907 km" kod B2010_jesenski_021). Ostaju na
        # skupini kao zapis; stavke nose svoje dijelove, a Test Builder rješenje skupine ionako
        # ne prikazuje (dodaj_jedinicu ga čisti u kopiji testa).
        "status_provjere": _dodaj_napomenu(
            redak.get("status_provjere"),
            "RAZDVOJENO: " + ", ".join(f"{o})" for o in p["oznake"])
            + ("; RJESENJE: cijelo ostaje na skupini" if _s(redak.get("rjesenje")) else ""),
        ),
    }
    novi_redci = [_redak_stavke(redak, s["oznaka"], s["tekst"], s["rjesenje"],
                                s["konacan_odgovor"], s["max_bodovi"], roditelj_id,
                                napomena=s.get("napomena", ""))
                  for s in p["stavke"]]
    log = [{"id": roditelj_id, "polje": k, "staro": _s(redak.get(k)), "novo": _s(v)}
           for k, v in polja.items()]
    log += [{"id": r["id"], "polje": "+redak", "staro": "", "novo": ""} for r in novi_redci]
    return {"polja": polja, "novi_redci": novi_redci, "log": log}


def _vec_obradjeno_cijepanje(redak: dict) -> bool:
    return _s(redak.get("uloga")).lower() in ("skupina", "stavka") or bool(_s(redak.get("roditelj_id")))


def _provjeri_cijepanje(redak: dict, promjene: dict) -> bool:
    """Tvrda provjera prije upisa: stavke imaju tekst, ID-evi su novi, bodovi se zbrajaju."""
    stavke = promjene["novi_redci"]
    if len(stavke) < 2:
        return False
    if any(not _s(s.get("tekst_zadatka_latex")) for s in stavke):
        return False
    if any(_s(s.get("id")) == _s(redak.get("id")) for s in stavke):
        return False
    try:
        ukupno = float(_s(redak.get("max_bodovi")).replace(",", ".") or 0)
    except ValueError:
        ukupno = 0.0
    if ukupno:
        try:
            zbroj = sum(float(_s(s.get("max_bodovi")).replace(",", ".") or 0) for s in stavke)
        except ValueError:
            return False
        if abs(zbroj - ukupno) > 0.01:
            return False
    return True


POSLOVI = {
    "cijepanje": {
        "naziv": "Cijepanje zadatka na podpitanja (uvod + a)/b)/…)",
        "predlozi": _predlozi_cijepanje,
        "vec_obradjeno": _vec_obradjeno_cijepanje,
        "provjeri": _provjeri_cijepanje,
    },
}


def dohvati(naziv: str):
    return POSLOVI.get(_s(naziv))


def dostupni() -> list[str]:
    return list(POSLOVI)
