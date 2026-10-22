"""CAKI — rjesavac.py  (22.10.2026.)

EGZAKTNA PROVJERA kratkih odgovora (SymPy) — „verifikator prije svega".

Zašto ovako, a ne „skripta rješava sve": većina zadataka u bazi je `prosireni_odgovor`
(postupak), gdje konačnog odgovora ni nema. Ondje gdje konačni odgovor POSTOJI, posao je
provjeriti je li predloženi odgovor ekvivalentan očekivanom — i to egzaktno, simbolički, a ne
„po izgledu". Time AI smije predlagati, a odluku nosi provjera:

    provjeri_ocekivano(ocekivano="2\\sqrt{2}", odgovor="\\sqrt{8}")  -> True   (ekvivalentno)

Pravilo: kad nismo sigurni, vraća **None** (nepoznato) — nikad ne pogađa i nikad ne proglašava
netočnim nešto što nije moglo pročitati. `None` znači „ovaj zadatak ide na ručnu provjeru".

Nema mreže i ne dira Sheet. `sympy` se uvozi lijeno (app i testovi rade i bez njega).
"""
from __future__ import annotations

import re

try:                                        # sympy je u requirements.txt; bez njega modul i dalje radi
    import sympy as _sp
    DOSTUPAN = True
except Exception:                           # noqa: BLE001
    _sp = None
    DOSTUPAN = False


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def ocisti_latex(tekst: str) -> str:
    """LaTeX -> oblik koji SymPy razumije (bez $, \\left, \\displaystyle, \\text{…}, \\frac{a}{b}->(a)/(b))."""
    t = _s(tekst)
    if not t:
        return ""
    t = t.replace("$", "").replace("\\left", "").replace("\\right", "").replace("\\displaystyle", "")
    t = re.sub(r"\\[,;!:]", "", t)
    t = re.sub(r"\\(?:text|mathrm|operatorname)\{([^{}]*)\}", r"\1", t)
    t = (t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
         .replace("\\pi", "pi").replace("\\leq", "<=").replace("\\geq", ">="))
    t = t.replace("\u2212", "-").replace("\u221a", "sqrt")
    for _ in range(4):                                   # \frac{a}{b} -> (a)/(b), i ugniježđeno
        novi = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"((\1)/(\2))", t)
        if novi == t:
            break
        t = novi
    t = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"sqrt(\1)", t)
    t = re.sub(r"\\sqrt\s*(\d+|[a-zA-Z])", r"sqrt(\1)", t)
    t = t.replace("{,}", ".").replace(",", ".")
    t = re.sub(r"\s+", "", t)
    return t.strip().rstrip(".")


def _kao_izraz(tekst: str):
    """Tekst -> SymPy izraz ili None. Skida i "x=" / "A=" (odgovor je desna strana)."""
    if not DOSTUPAN:
        return None
    t = ocisti_latex(tekst)
    if not t:
        return None
    m = re.fullmatch(r"[a-zA-Z]=(.+)", t)
    if m:
        t = m.group(1)
    t = t.rstrip("%")
    try:
        return _sp.sympify(t, evaluate=True)
    except Exception:                                    # noqa: BLE001 — nije izraz koji znamo
        return None


def ekvivalentno(ocekivano: str, odgovor: str):
    """True/False ako se može odlučiti, inače None (npr. različit oblik skupa ili nejednadžba)."""
    a, b = _kao_izraz(ocekivano), _kao_izraz(odgovor)
    if a is None or b is None:
        return None
    try:
        razlika = _sp.simplify(a - b)
        if razlika == 0:
            return True
        return bool(abs(complex(_sp.N(razlika, 30))) < 1e-20)
    except Exception:                                     # noqa: BLE001
        return None


def provjeri_ocekivano(ocekivano: str, odgovor: str, normalizuj=None):
    """Konačna odluka za kratki odgovor: True (točno), False (netočno), None (ne zna se).

    Redoslijed:
      1. `normalizuj` (ako ga pozivatelj preda) — postojeća usporedba iz ocjenjivanja;
      2. SymPy simbolička ekvivalencija (hvata `\\sqrt{8}` = `2\\sqrt{2}`, `0,5` = `\\frac{1}{2}`);
      3. inače None — ide na ručnu provjeru, NIKAD se ne upisuje kao netočno.
    """
    if not _s(odgovor):
        return False
    if normalizuj is not None:
        try:
            if normalizuj(ocekivano, odgovor):
                return True
        except Exception:                                 # noqa: BLE001
            pass
    rezultat = ekvivalentno(ocekivano, odgovor)
    return rezultat


def izracunaj(izraz: str):
    """Vrijednost izraza kao SymPy (npr. '\\frac{3}{4}+\\frac{1}{4}' -> 1), ili None."""
    return _kao_izraz(izraz)
