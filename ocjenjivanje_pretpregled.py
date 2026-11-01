r"""
CAKI — ocjenjivanje_pretpregled.py  (21.10.2026., prepravljen 1.11.2026.)

Ocjenjivanje zadataka SAMO za Pretpregled testa (pages/10_pretpregled_testa.py) —
Caki sam rjesava objavljeni test unutar Test Buildera da provjeri izgled i bodovanje,
bez upisa u Rezultati_testova.

1.11.2026. — LOGIKA JE SADA U JEDNOM MODULU (`provjera_odgovora.py`)
    Prije je ovo bila NAMJERNA kopija funkcija iz `caki-booking-termina/testovi_online.py`
    (Streamlit Cloud deploya samo repo u kojem je aplikacija, pa cross-repo import ne radi).
    Kopija se razišla tek toliko da je Pretpregled davao drugu ocjenu od portala — a upravo je
    to ono što Pretpregled čini beskorisnim. Zato je 1.11.2026. usporedba izdvojena u
    `provjera_odgovora.py`, koji je BAJT-IDENTIČAN u `caki-baza-zadataka/` i
    `caki-booking-termina/`. Ovdje su ostale samo tanke omotnice (imena se ne mijenjaju, jer ih
    zove `pages/10_pretpregled_testa.py` i niz testova).

    Ako se mijenja logika ocjenjivanja — mijenja se `provjera_odgovora.py` i kopira u drugi repo;
    test `testovi/test_provjera_odgovora.py` provjerava da su kopije iste (md5).

    AI provjera (`pozovi`) u Pretpregledu je isključena po defaultu: ovo je Cakijev vlastiti
    pregled i nema smisla trošiti pozive. `ocjeni(..., pozovi=..., dopusti_ai=True)` radi ako
    se ikad uključi.
"""
from __future__ import annotations

import re

import provjera_odgovora as _provjera


def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def _broj(vrijednost, zadano: float = 1.0) -> float:
    try:
        b = float(str(vrijednost).replace(",", ".").strip())
    except (TypeError, ValueError):
        return zadano
    return b if b > 0 else zadano


def normalizuj(tex) -> str:
    """LaTeX/tekst u oblik pogodan za usporedbu (tijelo: `provjera_odgovora.normalizuj`)."""
    return _provjera.normalizuj(tex)


def _bez_varijable(izraz: str) -> str:
    """'x=2' -> '2', 'n:5' -> '5' -- ucenik cesto napise ime nepoznanice."""
    return _provjera._bez_varijable(izraz)


def _kao_broj(izraz: str):
    return _provjera._kao_broj(izraz)


def _vrijednost_izraza(tekst):
    """Brojevna vrijednost izraza (`2^{12}` = `4096`, `\\sqrt{8}` = `2\\sqrt{2}`)."""
    return _provjera._vrijednost_izraza(tekst)


def _alt_kljucevi(kljuc) -> list:
    """`3|4|5` -> ["3","4","5"], `65°50' ili 114°10'` -> dva oblika -- VIŠE PRIHVAĆENIH RJEŠENJA."""
    return _provjera._alt_kljucevi(kljuc)


def _kratki_tocan_jedan(kljuc, odgovor) -> bool:
    return _provjera._uporedi_jedan(kljuc, odgovor)[0] == _provjera.STATUS_TOCNO


def kratki_tocan(kljuc, odgovor) -> bool:
    """Kratki odgovor: više prihvaćenih rješenja (`a|b|c`, `a ili b`) i ekvivalentni brojevni oblici."""
    return _provjera.tocno(kljuc, odgovor)


def _slovo_iz_kljuca(kljuc, opcije) -> str:
    """Konacan odgovor visestrukog izbora -> 'A'/'B'/'C'/'D' (ili '' ako se ne prepozna)."""
    k = _tekst(kljuc)
    if not k:
        return ""
    m = re.match(r"^([A-Za-zČĆŽŠĐ])\s*[\)\.:\-–]", k)
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


def je_tocan_izbor(zadatak, odgovor) -> bool:
    """Višestruki izbor: uspoređuje se SLOVO (ako ključ nema slovo, tekst odabrane opcije)."""
    tocno = _slovo_iz_kljuca(zadatak.get("odgovor"), opcije_zadatka(zadatak))
    if tocno:
        return _tekst(odgovor).upper()[:1] == tocno
    opcije = opcije_zadatka(zadatak)
    slovo = _tekst(odgovor).upper()[:1]
    if "A" <= slovo <= "Z" and 0 <= ord(slovo) - 65 < len(opcije):
        return kratki_tocan(zadatak.get("odgovor"), opcije[ord(slovo) - 65])
    return False


def je_tocan(zadatak, odgovor) -> bool:
    if not _tekst(odgovor):
        return False
    if _tekst(zadatak.get("tip")) == "visestruki_izbor" and zadatak.get("opcije"):
        return je_tocan_izbor(zadatak, odgovor)
    return kratki_tocan(zadatak.get("odgovor"), odgovor)


def je_tocan_detaljno(zadatak, odgovor, *, pozovi=None, dopusti_ai=False) -> dict:
    """`{"status", "izvor", "zasto"}` za JEDAN zadatak (1.11.2026.)."""
    odgovor = _tekst(odgovor)
    if not odgovor:
        return {"status": "prazno", "izvor": "", "zasto": "nema odgovora"}
    if _tekst(zadatak.get("tip")) == "visestruki_izbor" and zadatak.get("opcije"):
        return {"status": "tocno" if je_tocan_izbor(zadatak, odgovor) else "netocno",
                "izvor": "slovo", "zasto": ""}
    return _provjera.odluci(zadatak.get("odgovor"), odgovor,
                            tekst=_tekst(zadatak.get("tekst")),
                            pozovi=pozovi, dopusti_ai=dopusti_ai)


def ocjeni(zadaci, odgovori, *, pozovi=None, dopusti_ai: bool = False) -> tuple[float, float, list]:
    """Vraca (bodovi, bodovi_max, detalji). `odgovori` je dict {redni_broj: odgovor}.

    25.10.2026.: svaki zadatak dobiva `status` — `tocno`, `netocno`, `prazno`, **`ceka`**
    (nema ključa ili je postupak) ili **`sumnja`** (1.11.2026. — sličan zapis, čeka Cakijevu
    odluku). Takav zadatak NE dobiva 0 kao konačno — vidljiv je u 🧑‍🏫 Provjeri rješenja.
    """
    bodovi = 0.0
    maks = 0.0
    detalji = []
    for i, z in enumerate(zadaci or []):
        m = _broj(z.get("bodovi"))
        maks += m
        odgovor = _tekst((odgovori or {}).get(i))
        ocekivano = _tekst(z.get("odgovor"))
        rez = je_tocan_detaljno(z, odgovor, pozovi=pozovi, dopusti_ai=dopusti_ai)
        status = rez["status"]
        if status == "netocno" and _tekst(z.get("tip")) == "prosireni_odgovor":
            status = "ceka"
        b = m if status == "tocno" else 0.0
        bodovi += b
        detalji.append({
            "id": _tekst(z.get("id")),
            "tocno": status == "tocno",
            "status": status,
            "bodovi": round(b, 2),
            "max": round(m, 2),
            "odgovor": odgovor,
            "ocekivano": ocekivano,
            "izvor": rez.get("izvor", ""),
            "zasto": rez.get("zasto", ""),
        })
    return round(bodovi, 2), round(maks, 2), detalji
