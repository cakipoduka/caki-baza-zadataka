"""
CAKI — ocjenjivanje_pretpregled.py  (21.10.2026.)

Ocjenjivanje zadataka SAMO za Pretpregled testa (pages/10_pretpregled_testa.py) —
Caki sam rjesava objavljeni test unutar Test Buildera da provjeri izgled i bodovanje,
bez upisa u Rezultati_testova.

POZNATA DUPLIKACIJA (isto kao pipeline_upisi.py u MASTER CRM -- v. TRACKER 21.10.2026.):
ove funkcije su NAMJERNO identicna kopija stvarne logike ocjenjivanja iz
`caki-booking-termina/testovi_online.py` (normalizuj/kratki_tocan/je_tocan/ocjeni).
Razlog kopiranja: Streamlit Cloud deploya SAMO repozitorij u kojem se nalazi app -- ova
app (`caki-baza-zadataka`) nema pristup kodu iz `caki-booking-termina` u produkciji,
pa cross-repo import ovdje ne bi radio na Cloudu (lokalno bi "radio" jer je mapa
fizicki tu, ali bi pucalo nakon pusha).

AKO SE PROMIJENI LOGIKA OCJENJIVANJA (npr. novi oblik kratkog odgovora), MORA SE
PROMIJENITI NA OBA MJESTA -- ovdje i u caki-booking-termina/testovi_online.py -- inace
pretpregled pocne davati drugaciju ocjenu nego stvarni portal, sto je gore nego da
pretpregled ne postoji. Ako ovo postane bolno (cest izvor gresaka), razmisliti o
zasebnom shared paketu -- nije ucinjeno sada (YAGNI).
"""
from __future__ import annotations

import re


def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def _broj(vrijednost, zadano: float = 1.0) -> float:
    try:
        b = float(str(vrijednost).replace(",", ".").strip())
    except (TypeError, ValueError):
        return zadano
    return b if b > 0 else zadano


def normalizuj(tex) -> str:
    """LaTeX/tekst u oblik pogodan za usporedbu: bez $, \\left, razmaka, s razlomkom kao (a)/(b)."""
    t = _tekst(tex)
    if not t:
        return ""
    t = t.replace("$", "")
    t = t.replace("\\left", "").replace("\\right", "")
    t = t.replace("\\displaystyle", "")
    t = re.sub(r"\\[,;!:]", "", t)
    t = t.replace("~", "")
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = (t.replace("\\leq", "<=").replace("\\geq", ">=")
         .replace("\\le", "<=").replace("\\ge", ">="))
    t = t.replace("\\sqrt", "sqrt").replace("\u221a", "sqrt")
    t = t.replace("\\pi", "pi")
    t = t.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    t = t.replace("{,}", ".")
    for _ in range(4):
        novi = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
        if novi == t:
            break
        t = novi
    t = re.sub(r"\s+", "", t)
    return t.rstrip(".").lower()


def _bez_varijable(izraz: str) -> str:
    """'x=2' -> '2', 'n:5' -> '5' -- ucenik cesto napise ime nepoznanice."""
    return re.sub(r"^[a-z]=|^[a-z]:", "", izraz.strip())


def _kao_broj(izraz: str):
    s = izraz.strip()
    if "," in s:
        s = s.replace(",", ".")
    m = re.fullmatch(r"\(?(-?\d+(?:\.\d+)?)\)?/\(?(-?\d+(?:\.\d+)?)\)?", s)
    if m:
        nazivnik = float(m.group(2))
        return float(m.group(1)) / nazivnik if nazivnik else None
    try:
        return float(s)
    except ValueError:
        return None


def _vrijednost_izraza(tekst):
    """Brojevna vrijednost izraza iz odgovora — za EKVIVALENTNE OBLIKE (22.10.2026.).

    Ista kopija kao u `caki-booking-termina/testovi_online.py` (portal) — vidi zaglavlje modula:
    logika ocjenjivanja MORA biti ista na oba mjesta, inače pretpregled daje drugu ocjenu.
    Učenik smije napisati drugi oblik istog rješenja: `2^{12}` = `4096`, `\\sqrt{8}` = `2\\sqrt{2}`.
    """
    t = _tekst(tekst)
    if not t:
        return None
    t = t.replace("$", "").replace("\\left", "").replace("\\right", "").replace("\\displaystyle", "")
    t = re.sub(r"\\[,;!:]", "", t)
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = t.replace("\u2212", "-").replace("\u00b7", "*")
    for _ in range(3):
        try:
            novi = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"((\1)/(\2))", t)
        except re.error:
            return None
        if novi == t:
            break
        t = novi
    t = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"((\1)**0.5)", t)
    t = re.sub(r"\^\{([^{}]*)\}", r"**(\1)", t)
    t = re.sub(r"\^(\d+)", r"**\1", t)
    t = t.replace("{,}", ".").replace(",", ".").replace("%", "")
    t = re.sub(r"(?<=[\d)])\s*\(", "*(", t)          # implicitno množenje: 2(3) -> 2*(3)
    t = re.sub(r"\)\s*\(", ")*(", t)
    t = t.replace(" ", "")
    if not re.fullmatch(r"[0-9+\-*/().]+", t or ""):
        return None
    try:
        return float(eval(t, {"__builtins__": {}}, {}))   # noqa: S307 — samo brojke i operatori
    except Exception:                                     # noqa: BLE001
        return None


def _alt_kljucevi(kljuc) -> list:
    """`3|4|5` -> ["3","4","5"] — VIŠE PRIHVAĆENIH RJEŠENJA; inače [kljuc]."""
    dijelovi = [d.strip() for d in _tekst(kljuc).split("|") if d.strip()]
    return dijelovi if len(dijelovi) > 1 else [_tekst(kljuc)]


def _kratki_tocan_jedan(kljuc, odgovor) -> bool:
    """Usporedba kratkog odgovora: jednak zapis, jednak broj ili jednak razlomak."""
    a, b = normalizuj(kljuc), normalizuj(odgovor)
    if not a or not b:
        return False
    if a == b:
        return True
    va, vb = _bez_varijable(a), _bez_varijable(b)
    if va == vb:
        return True
    if va.rstrip("%") == vb.rstrip("%"):
        return True
    x, y = _kao_broj(va), _kao_broj(vb)
    if x is not None and y is not None:
        return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))
    return False


def kratki_tocan(kljuc, odgovor) -> bool:
    """Kratki odgovor: isto kao prije + (22.10.2026.) VIŠE PRIHVAĆENIH RJEŠENJA (`a|b|c`) i
    ekvivalentni brojevni oblici (`2^{12}` = `4096`, `\\sqrt{8}` = `2\\sqrt{2}`)."""
    if not _tekst(odgovor):
        return False
    alternative = _alt_kljucevi(kljuc)
    if any(_kratki_tocan_jedan(alt, odgovor) for alt in alternative):
        return True
    y = _vrijednost_izraza(odgovor)
    if y is None:
        return False
    for alt in alternative:
        x = _vrijednost_izraza(alt)
        if x is not None and abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y)):
            return True
    return False


def _slovo_iz_kljuca(kljuc, opcije) -> str:
    """Konacan odgovor visestrukog izbora -> 'A'/'B'/'C'/'D' (ili '' ako se ne prepozna)."""
    k = _tekst(kljuc)
    if not k:
        return ""
    m = re.match(r"^([A-Za-z\u010c\u0106\u017d\u0160\u0110])\s*[\)\.:\-\u2013]", k)
    if m:
        return m.group(1).upper()
    if len(k) == 1 and k.isalpha():
        return k.upper()
    nk = normalizuj(k)
    for i, opcija in enumerate(opcije or []):
        if normalizuj(opcija) and normalizuj(opcija) == nk:
            return chr(65 + i)
    for i, opcija in enumerate(opcije or []):
        if normalizuj(opcija) and normalizuj(opcija) in nk:
            return chr(65 + i)
    return ""


def opcije_zadatka(zadatak) -> list:
    opcije = zadatak.get("opcije") or []
    return [o for o in opcije if _tekst(o)]


def je_tocan(zadatak, odgovor) -> bool:
    if not _tekst(odgovor):
        return False
    if _tekst(zadatak.get("tip")) == "visestruki_izbor" and zadatak.get("opcije"):
        tocno = _slovo_iz_kljuca(zadatak.get("odgovor"), opcije_zadatka(zadatak))
        if tocno:
            return _tekst(odgovor).upper()[:1] == tocno
        opcije = opcije_zadatka(zadatak)
        slovo = _tekst(odgovor).upper()[:1]
        if "A" <= slovo <= "Z" and 0 <= ord(slovo) - 65 < len(opcije):
            return kratki_tocan(zadatak.get("odgovor"), opcije[ord(slovo) - 65])
        return False
    return kratki_tocan(zadatak.get("odgovor"), odgovor)


def ocjeni(zadaci, odgovori) -> tuple[float, float, list]:
    """Vraca (bodovi, bodovi_max, detalji). `odgovori` je dict {redni_broj: odgovor}."""
    bodovi = 0.0
    maks = 0.0
    detalji = []
    for i, z in enumerate(zadaci or []):
        m = _broj(z.get("bodovi"))
        maks += m
        odgovor = _tekst((odgovori or {}).get(i))
        tocno = je_tocan(z, odgovor)
        b = m if tocno else 0.0
        bodovi += b
        detalji.append({
            "id": _tekst(z.get("id")),
            "tocno": tocno,
            "bodovi": round(b, 2),
            "max": round(m, 2),
            "odgovor": odgovor,
            "ocekivano": _tekst(z.get("odgovor")),
        })
    return round(bodovi, 2), round(maks, 2), detalji
