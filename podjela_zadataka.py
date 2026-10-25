"""CAKI — podjela_zadataka.py  (22.10.2026.)

DETERMINISTIČKA podjela jednog zadatka s više podpitanja na:

  - SKUPINU (redak `uloga="skupina"`) — zajednički UVOD (tekst prije prve oznake),
  - STAVKE (redci `uloga="stavka"`, `roditelj_id` = ID skupine, `oznaka_stavke` = "a"/"b"/…)

pri čemu svaka stavka zadrži **svoj dio rješenja** (i kratki odgovor kad se iz njega može
izvući jednoznačno).

ZAŠTO BEZ AI-JA: mjereno ovim modulom na stvarnoj bazi (CAKI_Matematika_Baza, 9.724 retka,
22.10.2026.) — kandidata je **1.743**, a **1.581 (91 %) dijeli se deterministički**; 73 prolazi
bez rješenja (označeno, nije „sigurno"), 162 traži AI (neusklađene oznake), 128 ima sliku.
(Procjena od 84 % prije pisanja modula bila je preblaga: brojala je i lažne oznake poput `g)`
iz mjernih jedinica — maskiranje matematike to ispravlja.) Za takve je dijeljenje čisto rezanje
teksta: nema halucinacije, nema troška, a rezultat je jednak izvoru. AI ostaje samo za ostatak.

Kako se izbjegava lažna oznaka:
  - sadržaj unutar `$…$` i `$$…$$` se MASKIRA prije traženja oznaka (inače npr. `$g(x)$` izgleda
    kao oznaka `g)`),
  - prihvaća se samo NIZ oznaka koje idu redom (`a, b, c…` ili `1, 2, 3…`) i počinju od `a`/`1`,
  - tekst i rješenje moraju imati ISTI niz oznaka — inače funkcija javlja da treba AI/pregled.

Modul ne dira Sheet, ne zove mrežu i ne zna za Streamlit — koriste ga i stranica i radnik
(vidi `upute/ARHITEKTURA_RADNIK.md`).
"""
from __future__ import annotations

import re
from collections import Counter

# Oznake podpitanja: "a)" … "h)" ili "1)" … "20)". Prihvaća se samo na granici (početak retka,
# razmak, ; : . , ( [ ), da se ne hvata npr. "f(x)" — i uz maskiranje matematike ni "g(x)".
_OZNAKA = re.compile(r"(?:(?<=^)|(?<=[\s;:.,(\[]))([a-h]|\d{1,2})\)")

_ABECEDA = "abcdefgh"


def _maskiraj_matematiku(tekst: str) -> str:
    """Zamijeni sadržaj $…$ / $$…$$ razmacima iste duljine (pozicije ostaju točne)."""
    if not tekst:
        return ""
    izlaz = list(tekst)
    i, n = 0, len(tekst)
    while i < n:
        if tekst[i] != "$":
            i += 1
            continue
        dvostruki = tekst.startswith("$$", i)
        otvarac = "$$" if dvostruki else "$"
        kraj = tekst.find(otvarac, i + len(otvarac))
        if kraj == -1:
            break                       # nezatvorena matematička oznaka - ostavi kako je
        for j in range(i, kraj + len(otvarac)):
            if izlaz[j] != "\n":
                izlaz[j] = " "
        i = kraj + len(otvarac)
    return "".join(izlaz)


def nadi_oznake(tekst: str) -> list[tuple[str, int]]:
    """Vrati [(oznaka, pozicija_početka_markera), …] za NIZ oznaka koje idu redom.

    Prihvaća samo oznake koje počinju od "a" ili "1" i nastavljaju se redom (a→b→c, 1→2→3),
    tako da obični tekst poput "vidi sliku b) i zatim c)" ne prolazi slučajno. Ako niza nema,
    vraća [].
    """
    maska = _maskiraj_matematiku(tekst or "")
    kandidati = [(m.group(1), m.start()) for m in _OZNAKA.finditer(maska)]
    if len(kandidati) < 2:
        return []

    for pocetak in ("a", "1"):
        niz: list[tuple[str, int]] = []
        cekana = pocetak
        for oznaka, pozicija in kandidati:
            if oznaka != cekana:
                continue
            niz.append((oznaka, pozicija))
            if cekana.isdigit():
                cekana = str(int(cekana) + 1)
            else:
                sledeca = _ABECEDA.find(cekana) + 1
                cekana = _ABECEDA[sledeca] if sledeca < len(_ABECEDA) else "?"
        if len(niz) >= 2:
            return niz
    return []


def _razdvoji_po_oznakama(tekst: str, oznake: list[tuple[str, int]]) -> tuple[str, list[tuple[str, str]]]:
    """(uvod, [(oznaka, sadržaj), …]) — sadržaj je tekst IZA "x)" do sljedeće oznake."""
    uvod = (tekst[:oznake[0][1]] if oznake else tekst or "").strip()
    dijelovi = []
    for i, (oznaka, pozicija) in enumerate(oznake):
        kraj = oznake[i + 1][1] if i + 1 < len(oznake) else len(tekst)
        sadrzaj = tekst[pozicija:kraj].strip()
        # skini sam marker "a)" s početka
        sadrzaj = re.sub(r"^[a-h\d]{1,2}\)\s*", "", sadrzaj).strip()
        dijelovi.append((oznaka, sadrzaj))
    return uvod, dijelovi


# ---------------------------------------------------------------------------------------------
# Kratki odgovor iz dijela rješenja — samo kad je JEDNOZNAČAN, inače prazno (nikad se ne pogađa)
# ---------------------------------------------------------------------------------------------

_RUBOVI = re.compile(r"(?:\s|\\newline|\\par|\\\\|<br\s*/?>|~)+", re.I)


def ocisti_rubove(tekst: str) -> str:
    """Skini s početka i kraja ostatke prijeloma retka (`\\newline`, `\\\\`, `<br>`, `~`).

    Zašto: uvezeni zadaci (npr. matura `B2010_jesenski_...`) dijelove odvajaju s `\\newline`, pa
    nakon rezanja uvodu i dijelovima ostane taj rep i u aplikaciji se vidi kao doslovan tekst.
    22.10.2026.: uočeno na prvom pravom prolazu radnika.
    """
    t = tekst or ""
    for _ in range(3):
        novi = t.strip()
        for rep in ("\\newline", "\\par", "\\\\", "<br>", "<br/>", "<br />", "~"):
            if novi.lower().endswith(rep):
                novi = novi[: -len(rep)]
            if novi.lower().startswith(rep):
                novi = novi[len(rep):]
        novi = novi.strip()
        novi = novi.rstrip("\\").rstrip()      # ostatak prekinutog `\newline` (npr. "\n\")
        if novi == t:
            break
        t = novi
    return t


def _bez_latex_kratica(tekst: str) -> str:
    """Ukloni LaTeX kratice (\\cdot, \\dfrac, \\left…) — ostaju samo 'prave' riječi."""
    t = re.sub(r"\\[a-zA-Z]+", " ", tekst or "")
    t = re.sub(r"\\.", " ", t)
    return t


def _ima_rijeci(tekst: str) -> bool:
    """Ima li u tekstu riječ od 3+ slova (hrvatski/engleski), tj. opis postupka?"""
    return bool(re.search(r"[A-Za-zčćžšđČĆŽŠĐ]{3,}", _bez_latex_kratica(tekst)))


def kratki_odgovor(dio_rjesenja: str) -> str:
    """Iz dijela rješenja izvuci konačni odgovor SAMO kad je očit; inače "".

    Prihvaća se:
      1. JEDAN izraz, eventualno s "x=" ispred — "$x=-\\frac{8}{5}$", "$A=\\{10,12,14\\}$";
      2. (22.10.2026.) LANAC JEDNAKOSTI bez teksta — "$2^3\\cdot2^4\\cdot2^5=2^{3+4+5}=2^{12}$"
         daje **zadnji** član ("$2^{12}$"), jer je to konačni oblik koji učenik treba napisati.
    Ako dio rješenja sadrži postupak (riječi, dvije rečenice, nejednakost), vraća "" — takav
    zadatak ide na ručnu provjeru, nikad u automatsku ocjenu. Zapis ostaje kakav je u bazi.
    """
    t = (dio_rjesenja or "").strip().strip(".").strip()
    if not t or len(t) > 120:
        return ""
    if _ima_rijeci(t):
        return ""
    if t.count(";") > 0 or "\n" in t or re.search(r"\.\s", t):
        return ""

    # 2) lanac jednakosti: uzmi zadnji član — ali SAMO ako je lanac "račun", ne popis tvrdnji
    #    (npr. "$A\cup B=\{1,2\}$, $A\cap B=\{1\}$" je DVIJE tvrdnje, ne lanac — ne diraj).
    if t.count("=") >= 2:
        if re.search(r"\\(cup|cap|setminus|in|notin|subset)", t):
            return ""
        if re.search(r",", re.sub(r"\{[^{}]*\}", "", t)):      # zarez IZVAN zagrada = nova tvrdnja
            return ""
        zadnji = t.split("=")[-1].strip().strip("$").strip().rstrip(".")
        if zadnji and len(zadnji) <= 80 and not _ima_rijeci(zadnji) and "=" not in zadnji:
            return zadnji
        return ""

    if t.count("=") > 1:
        return ""
    t = re.sub(r"^(odgovor|rješenje|rezultat)\s*:?\s*", "", t, flags=re.I)
    return t.strip()


# ---------------------------------------------------------------------------------------------
# Podjela jednog retka (dict s poljima taba 'Zadaci')
# ---------------------------------------------------------------------------------------------

def je_kandidat(redak: dict) -> bool:
    """Je li redak uopće kandidat za podjelu: samostalan je i tekst ima 2+ oznake po redu."""
    if not redak:
        return False
    if str(redak.get("uloga") or "").strip().lower() not in ("", "samostalan"):
        return False
    if str(redak.get("roditelj_id") or "").strip():
        return False
    return len(nadi_oznake(str(redak.get("tekst_zadatka_latex") or ""))) >= 2


def podijeli(redak: dict) -> dict | None:
    """Podijeli jedan zadatak. Vraća dict spreman za upis ILI None (nije deterministički).

    Rezultat:
        {"id": …, "uvod": …, "oznake": ["a", "b"], "stavke": [{"oznaka","tekst","rjesenje",
         "konacan_odgovor","max_bodovi"}, …], "napomene": [...], "sigurno": bool}
    None znači: nema niza oznaka, oznake teksta i rješenja se ne poklapaju, ili neki dio nema
    rješenja — takav zadatak treba AI/pregled i NE upisuje se automatski.
    """
    if not je_kandidat(redak):
        return None
    tekst = str(redak.get("tekst_zadatka_latex") or "")
    rjesenje = str(redak.get("rjesenje") or "")

    oznake_teksta = nadi_oznake(tekst)
    if len(oznake_teksta) < 2:
        return None
    uvod_sirov, dijelovi_sirov = _razdvoji_po_oznakama(tekst, oznake_teksta)
    if any(not sadrzaj for _, sadrzaj in dijelovi_sirov):
        return None                     # prazan dio (npr. "a) b) ...") - ne diraj, čeka pregled
    # čišćenje rubova je kozmetika (odvajači `\newline` i sl.) — provjera gubitka radi na sirovom
    uvod = ocisti_rubove(uvod_sirov)
    dijelovi = [(o, ocisti_rubove(s)) for o, s in dijelovi_sirov]

    napomene = []
    oznake_rjesenja = nadi_oznake(rjesenje) if rjesenje else []
    rjesenja_po_oznaci: dict[str, str] = {}
    if oznake_rjesenja and [o for o, _ in oznake_rjesenja] == [o for o, _ in oznake_teksta]:
        _, dijelovi_rj = _razdvoji_po_oznakama(rjesenje, oznake_rjesenja)
        rjesenja_po_oznaci = {o: ocisti_rubove(s) for o, s in dijelovi_rj}
    elif rjesenje:
        return None                     # rješenje nije po istim oznakama - treba AI/pregled
    else:
        napomene.append("RJESENJE: nedostaje - podjela bez rješenja (ručna provjera)")

    # bodovi: ukupno ostaje isto (zadnji dio nosi ostatak)
    try:
        ukupno_bodova = float(str(redak.get("max_bodovi") or "").replace(",", "."))
        ukupno_bodova = ukupno_bodova if ukupno_bodova > 0 else 0.0
    except ValueError:
        ukupno_bodova = 0.0
    po_dijelu = round(ukupno_bodova / len(dijelovi), 2) if ukupno_bodova else 0.0

    ima_sliku = (str(redak.get("slika_zadana") or "").strip().lower() == "da"
                 or bool(str(redak.get("slika_putanja") or "").strip()))
    if ima_sliku:
        napomene.append("SLIKA: ostaje na skupini (uvodu) - provjeri treba li kojem dijelu")

    stavke = []
    for i, (oznaka, sadrzaj) in enumerate(dijelovi):
        dio_rjesenja = rjesenja_po_oznaci.get(oznaka, "")
        bodovi = po_dijelu
        if ukupno_bodova and i == len(dijelovi) - 1:      # ostatak zaokruživanja na zadnji dio
            bodovi = round(ukupno_bodova - po_dijelu * (len(dijelovi) - 1), 2)
        stavke.append({
            "oznaka": oznaka,
            "tekst": sadrzaj,
            "rjesenje": dio_rjesenja,
            "konacan_odgovor": kratki_odgovor(dio_rjesenja) if dio_rjesenja else "",
            "max_bodovi": bodovi,
        })

    # provjera: ništa se ne smije izgubiti (uvod + dijelovi ≈ izvorni tekst, bez oznaka/razmaka)
    bez = lambda s: re.sub(r"\s+", "", s or "")                      # noqa: E731
    zbroj = len(bez(uvod_sirov)) + sum(len(bez(s)) for _, s in dijelovi_sirov)
    izvorno = len(bez(tekst)) - sum(len(o) + 1 for o, _ in oznake_teksta)
    if abs(zbroj - izvorno) > max(3, izvorno // 200):
        return None                     # maskiranje/rezanje ne slaže - ne upisuj

    return {
        "id": str(redak.get("id") or "").strip(),
        "uvod": uvod,
        "oznake": [o for o, _ in dijelovi],
        "stavke": stavke,
        "napomene": napomene,
        "sigurno": bool(rjesenja_po_oznaci) and not any("nedostaje" in n for n in napomene),
    }


def id_stavke(id_skupine: str, oznaka: str) -> str:
    """ID nove stavke: '<id>-a'. Sufiks s minusom da se ne sudari s postojećim '_' ID-jevima."""
    return f"{str(id_skupine).strip()}-{oznaka}"


def analiza(redci) -> dict:
    """Brojevi za audit/prikaz: koliko je zadataka, kandidata, koliko se dijeli deterministički,
    koliko ima rješenje i kratki odgovor. Ne mijenja ništa."""
    ukupno = samostalni = skupine = stavke = 0
    kand = podijeljeno = bez_rjesenja = sa_slikom = 0
    po_izvoru: Counter = Counter()
    for r in redci or []:
        ukupno += 1
        uloga = str(r.get("uloga") or "").strip().lower()
        if uloga == "skupina":
            skupine += 1
            continue
        if uloga == "stavka":
            stavke += 1
            continue
        samostalni += 1
        if not je_kandidat(r):
            continue
        kand += 1
        po_izvoru[str(r.get("izvor_naziv") or "(bez izvora)")] += 1
        p = podijeli(r)
        if p:
            podijeljeno += 1
            if not p["sigurno"]:
                bez_rjesenja += 1
            if any("SLIKA" in n for n in p["napomene"]):
                sa_slikom += 1
    return {
        "ukupno": ukupno, "samostalni": samostalni, "skupine": skupine, "stavke": stavke,
        "kandidati": kand, "podijeljeno": podijeljeno,
        "bez_rjesenja": bez_rjesenja, "sa_slikom": sa_slikom,
        "treba_ai": kand - podijeljeno,
        "po_izvoru": po_izvoru.most_common(),
    }
