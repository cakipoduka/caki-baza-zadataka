"""CAKI — odgovori_posao.py  (25.10.2026.)

POSAO `kratki_odgovor`: iz službenog rješenja izvuci **konačni odgovor** koji učenik upisuje,
za stavke/zadatke koje ga još nemaju. Cilj: baza spremna za automatsko ocjenjivanje.

Redoslijed (jeftino → skupo, sigurno → nesigurno):
  1. **deterministički** (`podjela_zadataka.kratki_odgovor`) — uzima odgovor samo kad je očit
     (npr. lanac `2^3·2^4=2^7` → `2^7`). Ako uspije, AI se NE poziva.
  2. **AI** — model iz rješenja predloži konačni odgovor ili vrati "" kad rješenje ne daje
     jednoznačan odgovor (postupak, crtež, više mogućih rješenja).
  3. **provjera** — odgovor MORA postojati u izvornom rješenju (normalizirano); ako ga SymPy
     može pročitati, provjeri se i ekvivalencija sa zadnjim izrazom rješenja.

Nijedan odgovor se ne upisuje bez prolaska provjere — bolje prazno nego izmišljeno.
Modul ne dira Sheet: vraća promjene, a upisuje ih `radnik.py`.
"""
from __future__ import annotations

import os
import re

KI_NIJE_SIGURNO = ("RJESENJE", "NEJASNO", "SLIKA")


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _norm(tekst: str) -> str:
    """Za usporedbu: bez razmaka, oznaka `)` i LaTeX prijeloma (isto kao drugdje u projektu)."""
    t = _s(tekst).lower()
    t = t.replace("\\newline", "").replace("\\\\", "").replace("<br>", "")
    t = t.replace(")", "").replace("\\", "")
    return re.sub(r"\s+", "", t)


def _dodaj_napomenu(tekst: str, napomena: str) -> str:
    t = _s(tekst)
    return f"{t}; {napomena}" if t else napomena


AI_SISTEM = """Iz zadanog SLUŽBENOG RJEŠENJA izvuci KONAČNI ODGOVOR koji učenik upisuje.

PRAVILA:
1. Vrati ISKLJUČIVO JSON: {"odgovor": "..."}.
2. "odgovor" mora biti DOSLOVNO iz rješenja (isti zapis, isti LaTeX) — bez prepričavanja,
   bez računanja, bez izmišljanja.
3. Ako rješenje daje više dijelova, vrati odgovor samo za dio koji je u pitanju.
4. Ako rješenje NE daje jednoznačan konačni odgovor (postupak, opis, crtež, više mogućih
   rješenja, "više točnih odgovora"), vrati {"odgovor": ""}.
5. Ako nisi siguran — vrati prazno. Bolje prazno nego pogrešno."""


def _json_iz_odgovora(tekst: str):
    import json

    t = re.sub(r"^```(?:json)?", "", _s(tekst)).strip()
    t = re.sub(r"```$", "", t).strip()
    i = t.find("{")
    if i == -1:
        return None
    try:
        return json.loads(t[i:])
    except ValueError:
        return None


def _zadnji_izraz(rjesenje: str) -> str:
    """Zadnji član lanca jednakosti (npr. '... =2^{12}' -> '2^{12}'), ili ""."""
    dijelovi = [d.strip() for d in _s(rjesenje).split("=")]
    return dijelovi[-1] if len(dijelovi) > 1 else ""


def provjeri_odgovor(odgovor: str, rjesenje: str) -> tuple[bool, str]:
    """(prolazi, napomena). Odgovor mora postojati u rješenju; SymPy (ako radi) daje jaču ocjenu."""
    a, rj = _s(odgovor), _s(rjesenje)
    if not a or not rj:
        return False, "prazno"
    if len(a) > 80:
        return False, "predugačko"
    if _norm(a) not in _norm(rj):
        return False, "nije u rješenju"

    napomena = "ODGOVOR: iz rješenja (AI)"
    try:
        import rjesavac as rj_mod

        if rj_mod.DOSTUPAN:
            zadnji = _zadnji_izraz(rj)
            if zadnji:
                stanje = rj_mod.ekvivalentno(zadnji, a)
                if stanje is True:
                    napomena += ", provjereno SymPy"
                elif stanje is False:
                    return False, "SymPy: nije ekvivalentno zadnjem izrazu"
                else:
                    napomena += ", SymPy ne može provjeriti"
    except Exception:                                     # noqa: BLE001 - SymPy nije obavezan
        pass
    return True, napomena


def predlozi(redak: dict, pozovi_ai=None) -> dict | None:
    """Vrati {"polja": {...}} za upis ili None (nema što / provjera nije prošla)."""
    import podjela_zadataka as pz

    if _s(redak.get("uloga")).lower() == "skupina":
        return None
    if _s(redak.get("konacan_odgovor")):
        return None                                        # već ima
    rjesenje = _s(redak.get("rjesenje"))
    if not rjesenje:
        return None                                        # nema iz čega izvući

    odgovor = pz.kratki_odgovor(rjesenje)                  # 1) deterministicki, besplatno
    if not odgovor:
        if pozovi_ai is None:
            from radnik_poslovi import _pozovi_ai as pozovi_ai
        model = _s(os.environ.get("AI_MODEL")) or "claude-sonnet-5"
        korisnik = ("RJEŠENJE:\n" + rjesenje + "\n\nTEKST ZADATKA:\n"
                    + _s(redak.get("tekst_zadatka_latex")) + "\n\nVrati JSON po pravilima.")
        try:
            sirovo = pozovi_ai(AI_SISTEM, korisnik, model)
        except Exception as e:                             # noqa: BLE001
            print(f"AI nije odgovorio ({type(e).__name__}); preskačem.")
            return None
        podaci = _json_iz_odgovora(sirovo) or {}
        odgovor = _s(podaci.get("odgovor"))
        if not odgovor:
            return None                                    # AI kaže: nema jednoznačnog odgovora
        prolazi, napomena = provjeri_odgovor(odgovor, rjesenje)
        if not prolazi:
            return None                                    # izmišljeno / neprovjerljivo - ne upisuj
        return {"polja": {"konacan_odgovor": odgovor,
                          "status_provjere": _dodaj_napomenu(redak.get("status_provjere"), napomena)},
                "novi_redci": [],
                "log": [{"id": _s(redak.get("id")), "polje": "konacan_odgovor",
                         "staro": "", "novo": odgovor},
                        {"id": _s(redak.get("id")), "polje": "status_provjere",
                         "staro": _s(redak.get("status_provjere")),
                         "novo": _dodaj_napomenu(redak.get("status_provjere"), napomena)}]}

    # deterministicki odgovor: dodatna provjera (mora biti iz rješenja)
    prolazi, napomena = provjeri_odgovor(odgovor, rjesenje)
    if not prolazi:
        return None
    return {"polja": {"konacan_odgovor": odgovor,
                      "status_provjere": _dodaj_napomenu(redak.get("status_provjere"), napomena)},
            "novi_redci": [],
            "log": [{"id": _s(redak.get("id")), "polje": "konacan_odgovor", "staro": "", "novo": odgovor},
                    {"id": _s(redak.get("id")), "polje": "status_provjere",
                     "staro": _s(redak.get("status_provjere")),
                     "novo": _dodaj_napomenu(redak.get("status_provjere"), napomena)}]}


def vec_obradjeno(redak: dict) -> bool:
    """Preskoči ako odgovor već postoji (idempotencija ponovnog pokretanja)."""
    return bool(_s(redak.get("konacan_odgovor")))


def provjeri(redak: dict, promjene: dict) -> bool:
    """Tvrda provjera prije upisa."""
    odgovor = _s(promjene.get("polja", {}).get("konacan_odgovor"))
    prolazi, _ = provjeri_odgovor(odgovor, _s(redak.get("rjesenje")))
    return bool(prolazi)
