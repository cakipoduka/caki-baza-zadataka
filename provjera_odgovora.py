r"""
CAKI — provjera_odgovora.py  (1.11.2026.)
PROVJERA KRATKOG ODGOVORA: normalizacija → broj/jedinica → AI kao DRUGO MIŠLJENJE → sumnja.
ZAŠTO POSTOJI (Cakijev nalaz, 31.10./1.11.2026.)
    U `Rezultati_testova` su točni odgovori završavali kao NETOČNI jer se uspoređivao zapis, a ne
    vrijednost. Primjer iz stvarnog testa (`tablica_promasenih`, stupci `Upisao` / `Točno`):

        upisano  \mathrm{8.8605}          ključ  8.8605
        upisano  \mathrm{58}              ključ  58 eura
        upisano  \mathrm{8}               ključ  8 °C
        upisano  \mathrm{(-\infty,-3) U (11,+\infty)}   ključ  (-\infty,-3) \cup (11,+\infty)
        upisano  \mathrm{65\degree50^{\prime}}          ključ  65°50' ili 114°10'

    Sve su to ISTI odgovori, samo drugim zapisom. Stari `normalizuj()` nije skidao `\\mathrm{}`
    (a kamoli ugniježđeni `\\mathrm{\\frac{3-a}{3a}}`), nije znao `\\frac78` bez zagrada, `\\degree`,
    `\\prime`, `\\cup` ni mjerne jedinice — pa je učenik dobivao 0 za točan odgovor.

TRI PRAVILA (i ništa izvan njih)
    1. **ZAPIS** — deterministički: skini omotače (`\\mathrm`, `\\text`, `$`), sjedini razlomke,
       °/', ∪, ∞, jedinice. Ista vrijednost drugim zapisom = TOČNO. Ovo rješava ~95 % slučajeva.
    2. **AI je DRUGO MIŠLJENJE, ne rješavač** — poziva se SAMO kad je odgovor „blizu" (isti brojevi
       ili gotovo isti zapis), dobiva ključ i smije reći samo „isti je / nije isti", nikad drugi
       rezultat. Bez ključa AI se ne poziva. Niska/srednja sigurnost = sumnja.
    3. **SUMNJA ide profesoru** — kad se ne može odlučiti (nema AI-ja, AI nije siguran, jedinica se
       razlikuje), odgovor NIJE 0 nego status `sumnja` → 🧑‍🏫 Provjera rješenja. Bolje prijaviti
       sumnju nego pogoditi (GDPR čl. 22: automatska odluka mora imati ljudsku provjeru).

UGOVOR ZA AI (`pozovi`)
    `pozovi(uputa: str, pitanje: str) -> {"tekst": str}` (može i čisti str). Isti ugovor kao
    `caki-testovi/ocjenjivanje.py::prijedlog_ai` i `provedba.predaj(..., pozovi=...)` — zato se ovaj
    modul može prenijeti u v2 bez prepisivanja. `pozovi=None` = AI isključen (sve „blizu" ide
    profesoru; ništa se ne ruši).

DVA PRIMJERKA, JEDAN IZVOR
    Datoteka je NAMJERNO ista u `caki-booking-termina/` (portal, ocjenjuje stvarnog učenika) i u
    `caki-baza-zadataka/` (👁️ Pretpregled testa) — Streamlit Cloud deploya samo repo u kojem je
    aplikacija, pa cross-repo import u produkciji ne radi. Kopije su bajt-identične; test
    `testovi/test_provjera_odgovora.py` to provjerava (md5), da se ne raziđu.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

# ============================================================
# Statusi i izvori odluke
# ============================================================

STATUS_TOCNO = "tocno"
STATUS_NETOCNO = "netocno"
STATUS_SUMNJA = "sumnja"        # 1.11.2026.: čeka profesora, NIJE konačna nula
STATUS_PRAZNO = "prazno"
STATUS_CEKA = "ceka"            # zatečeno: nema ključa ili je postupak (prosireni_odgovor)

IZVOR_ZAPIS = "zapis"
IZVOR_BROJ = "broj"
IZVOR_JEDINICA = "jedinica"
IZVOR_AI = "ai"
IZVOR_SUMNJA = "sumnja"

# Statusi koje profesor još mora pogledati (v. `testovi_admin.potrebna_provjera`)
OTVORENI_STATUSI = (STATUS_CEKA, STATUS_SUMNJA)

# ============================================================
# Pomoćno
# ============================================================

_OMOTACI = ("mathrm", "text", "textrm", "textnormal", "textbf", "textit",
            "mathbf", "mathit", "mathsf", "mathtt", "operatorname", "mbox", "hbox")

_RX_OMOTAC = re.compile(r"\\(?:" + "|".join(_OMOTACI) + r")\s*\{")
_RX_MINUS = re.compile("[\u2212\u2013\u2014]")
_RX_RAZLOMAK_KRATKO = re.compile(r"\\[dt]?frac\s*([A-Za-z0-9])\s*([A-Za-z0-9])")
_RX_RAZLOMAK = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_RX_UNION = re.compile(r"(?<=[\)\]0-9])\s*[uU]\s*(?=[\(\[])")


def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def _skini_jedan_omotac(tekst: str) -> str:
    """`\\mathrm{...}` → `...` (poštuje UGNIJEŽĐENE zagrade: `\\mathrm{\\frac{3-a}{3a}}`)."""
    m = _RX_OMOTAC.search(tekst)
    if not m:
        return tekst
    dubina, i = 1, m.end()
    while i < len(tekst):
        if tekst[i] == "{":
            dubina += 1
        elif tekst[i] == "}":
            dubina -= 1
            if dubina == 0:
                return tekst[:m.start()] + tekst[m.end():i] + tekst[i + 1:]
        i += 1
    return tekst                                   # nezAtvorena zagrada — ne diraj (radije ništa)


def skini_omotace(tekst) -> str:
    """Skini sve LaTeX omotače oko sadržaja (`\\mathrm`, `\\text`, …), do 6 razina."""
    t = _tekst(tekst)
    for _ in range(6):
        novi = _skini_jedan_omotac(t)
        if novi == t:
            break
        t = novi
    return t


def normalizuj(tex) -> str:
    """LaTeX/tekst u oblik pogodan za usporedbu: bez $, \\left, razmaka, s razlomkom kao (a)/(b).

    Isti ugovor kao stari `normalizuj()` u `testovi_online.py` (postojeći testovi ga provjeravaju),
    ali dodatno skida `\\mathrm{}`/`\\text{}`, zna `\\frac78`, `\\degree`, `\\prime`, `\\cup`, `\\infty`.
    """
    t = _tekst(tex)
    if not t:
        return ""
    t = t.replace("$", "")
    t = skini_omotace(t)                       # \mathrm{8.8605} -> 8.8605
    t = t.replace("\\left", "").replace("\\right", "").replace("\\displaystyle", "")
    t = re.sub(r"\\[,;!:]", "", t)
    t = t.replace("\\ ", "").replace("~", "")
    # stepeni i minute: \degree, ^{\circ}, \circ -> °   ·   \prime, ^{\prime} -> '
    t = re.sub(r"\^\s*\{\s*\\circ\s*\}", "\u00b0", t)
    t = re.sub(r"\^\s*\{\s*\\prime\s*\}", "'", t)
    t = t.replace("\\degree", "\u00b0").replace("\\circ", "\u00b0")
    t = t.replace("\\prime", "'").replace("\u2032", "'").replace("\u2033", "''")
    # beskonačno i unija (učenik često piše slovo U umjesto \cup)
    t = t.replace("\\infty", "inf")
    t = t.replace("\\cup", "\u222a").replace("\\cap", "\u2229")
    t = _RX_UNION.sub("\u222a", t)
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = (t.replace("\\leq", "<=").replace("\\geq", ">=")
         .replace("\\le", "<=").replace("\\ge", ">="))
    t = t.replace("\\sqrt", "sqrt").replace("\u221a", "sqrt")
    t = t.replace("\\pi", "pi")
    t = _RX_MINUS.sub("-", t)
    t = t.replace("{,}", ".")
    t = _RX_RAZLOMAK_KRATKO.sub(r"(\1)/(\2)", t)          # \frac78 -> (7)/(8)
    for _ in range(4):                                    # \frac{a}{b} -> (a)/(b), i ugniježđeno
        novi = _RX_RAZLOMAK.sub(r"(\1)/(\2)", t)
        if novi == t:
            break
        t = novi
    t = re.sub(r"\s+", "", t)
    return t.rstrip(".").lower()


def _bez_varijable(izraz: str) -> str:
    """'x=2' -> '2', 'n:5' -> '5' — učenik često napise ime nepoznanice."""
    return re.sub(r"^[a-z]=|^[a-z]:", "", izraz.strip())


def _uparena_cjelina(izraz: str) -> bool:
    """Je li CIJELI izraz jedna zagrada: `(a+b)` -> True, `(a)/(b)` -> False."""
    if len(izraz) < 2 or izraz[0] != "(" or izraz[-1] != ")":
        return False
    dubina = 0
    for i, znak in enumerate(izraz):
        if znak == "(":
            dubina += 1
        elif znak == ")":
            dubina -= 1
            if dubina == 0:
                return i == len(izraz) - 1
    return False


def bez_suvisnih_zagrada(izraz) -> str:
    """Ukloni zagrade koje ne mijenjaju vrijednost: `((3-a))` -> `(3-a)`, `(3a)` -> `3a`.

    Zašto (Cakijev nalaz 1.11.2026.): učenik je upisao
    `\\mathrm{\\frac{\\left(3-a\\right)}{3a}}`, a ključ je `\\frac{3-a}{3a}` — ISTI izraz, ali
    `\\left(…\\right)` ostavi dodatne zagrade u brojniku (`((3-a))/(3a)` prema `(3-a)/(3a)`) pa je
    sustav rekao „sumnja". Ovim se takve zagrade ignoriraju pri usporedbi.

    Namjerno usko: skida se samo zagrada koja obuhvaća CIJELI izraz i zagrada oko jednog
    „atoma" (`(3a)`), i to samo kad ispred nje nije slovo ili zagrada — tako `f(x)` ostaje
    `f(x)` (nije isto što i `fx`), a `(a+b)/(c+d)` se ne dira.
    """
    t = _tekst(izraz)
    for _ in range(6):
        novi = re.sub(r"\(\s*\(([^()]*)\)\s*\)", r"(\1)", t)      # ((x)) -> (x)
        if _uparena_cjelina(novi):
            novi = novi[1:-1]                                     # (a+b) -> a+b
        novi = re.sub(r"(?<![\w)])\(([A-Za-z0-9.]+)\)", r"\1", novi)  # (3a) -> 3a ; f(x) ostaje
        if novi == t:
            return t
        t = novi
    return t


# ============================================================
# Mjerne jedinice
# ============================================================

# Višeznakovne jedinice (+ ° i %) — te se SMEJU izostaviti u odgovoru ("58" za "58 eura").
JEDINICE_MJERNE = (
    "cm^3", "cm^2", "dm^3", "dm^2", "mm^3", "mm^2", "km^2", "m^3", "m^2",
    "km/h", "m/s^2", "m/s2", "m/s", "kg/m^3", "kg/m3",
    "litara", "litre", "litri", "litar", "lit", "ml", "dl", "cl",
    "eura", "euro", "eur", "\u20ac", "kn", "din", "dinara",
    "u\u010denika", "ucenika", "u\u010denik", "bodova",
    "sati", "sata", "sat", "minuta", "minute", "min", "sekundi", "sek", "dana",
    "godina", "mjeseci",
    "kg", "mg", "km", "cm", "mm", "dm", "mol", "kpa", "hpa", "pa", "kw", "kwh",
    "hz", "khz", "kvadratnih", "kubnih",
    "\u00b0c", "\u00b0f", "\u00b0", "%",
)

# Jednoznakovne oznake — koriste se SAMO za prepoznavanje SUKOBA jedinica ("8 m" nije "8 cm"),
# nikad same za „jedinica nedostaje" (da se "5a" ne proglašava isto što i "5").
JEDINICE_KRATKE = ("m", "g", "l", "s", "h", "v", "a", "w", "j", "n", "k")

_JEDINICE_SVE = tuple(sorted(JEDINICE_MJERNE + JEDINICE_KRATKE, key=len, reverse=True))


def razdvoji_jedinicu(izraz: str) -> tuple:
    """`'254.55cm'` -> `('254.55', 'cm')` · `'32picm^2'` -> `('32pi', 'cm^2')` · bez jedinice -> (x, '')."""
    s = _tekst(izraz)
    for j in _JEDINICE_SVE:
        if s.endswith(j) and len(s) > len(j):
            return s[: -len(j)], j
    return s, ""


def _je_mjerna(jedinica: str) -> bool:
    return bool(jedinica) and jedinica in JEDINICE_MJERNE


# ============================================================
# Brojevi i izrazi
# ============================================================

def _jednaki(x, y) -> bool:
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def _kao_broj(izraz: str):
    """'2', '-2', '(7)/(8)', '2,5' -> float; inače None."""
    s = _tekst(izraz)
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
    """Brojevna vrijednost izraza — za EKVIVALENTNE OBLIKE (`2^{12}` = `4096`, `\\sqrt{8}` = `2\\sqrt{2}`).

    Namjerno strogo: računa se tek ako u izrazu NEMA ničega osim brojki i operatora — inače None.
    """
    t = _tekst(tekst)
    if not t:
        return None
    t = t.replace("$", "")
    t = skini_omotace(t)
    t = t.replace("\\left", "").replace("\\right", "").replace("\\displaystyle", "")
    t = re.sub(r"\\[,;!:]", "", t)
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = _RX_MINUS.sub("-", t).replace("\u00b7", "*")
    for _ in range(3):
        try:
            novi = _RX_RAZLOMAK.sub(r"((\1)/(\2))", t)
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


def brojevi(tekst) -> list:
    """Svi brojevi iz teksta, redom (`-3`, `11`, `7.5`); decimalni zarez se prihvaća."""
    return [float(x.replace(",", ".")) for x in re.findall(r"-?\d+(?:[.,]\d+)?", _tekst(tekst))]


def _alt_kljucevi(kljuc) -> list:
    """Više prihvaćenih rješenja: `3|4|5`, `3; 4`, `65°50' ili 114°10'` -> popis.

    ` ili ` se dijeli samo kad su svi dijelovi kratki i sadrže broj (da se „manje od 5 ili jednako 5"
    ne pretvori u dva prihvaćena rješenja).
    """
    k = _tekst(kljuc)
    if not k:
        return [""]
    dijelovi = [d.strip() for d in re.split(r"[|;]", k) if d.strip()]
    if len(dijelovi) < 2 and re.search(r"\sili\s", k, re.IGNORECASE):
        kandidati = [d.strip() for d in re.split(r"\sili\s", k, flags=re.IGNORECASE) if d.strip()]
        if (len(kandidati) > 1 and all(len(d) <= 25 and re.search(r"\d", d) for d in kandidati)
                and not any(re.search(r"[<>+\-*/]", d) for d in kandidati)):
            dijelovi = kandidati
    return dijelovi if len(dijelovi) > 1 else [k]


# ============================================================
# 1. sloj — deterministička usporedba
# ============================================================

def _uporedi_jedan(kljuc, odgovor) -> tuple:
    """(status, izvor) za JEDAN oblik ključa; (None, "") = nije odlučeno."""
    a, b = normalizuj(kljuc), normalizuj(odgovor)
    if not a or not b:
        return None, ""

    va, vb = _bez_varijable(a), _bez_varijable(b)
    if va == vb:
        return STATUS_TOCNO, IZVOR_ZAPIS
    # ista formula, ali s dodatnim zagradama (\left( … \right) iz MathLive-a / Mathpix-a)
    z1, z2 = bez_suvisnih_zagrada(va), bez_suvisnih_zagrada(vb)
    if z1 and z1 == z2:
        return STATUS_TOCNO, IZVOR_ZAPIS

    ka, ua = razdvoji_jedinicu(va)
    kb, ub = razdvoji_jedinicu(vb)

    # ključ opisan riječima, a odgovor je SAMO taj broj: "58 eura"/"58", "254.55 m"/"254.55",
    # "za više od 7.5 km"/"7.5". (Imena nepoznanice "5a" ovdje NE prolaze — nema razmaka u ključu.
    #  Ako odgovor ima SVOJU mjernu jedinicu, ona mora biti ista — "8 m" nije "8 cm".)
    if re.search(r"\s", _tekst(kljuc)) and (not ub or not ua or ub == ua):
        bk, bo = brojevi(kljuc), brojevi(odgovor)
        if len(bk) == 1 and len(bo) == 1 and _jednaki(bk[0], bo[0]):
            core, jed = razdvoji_jedinicu(vb)
            if re.fullmatch(r"-?\d+(?:\.\d+)?", core) and (not jed or _je_mjerna(jed)):
                return STATUS_TOCNO, IZVOR_JEDINICA

    if ka and ka == kb:
        if ua and ub and ua != ub:
            return STATUS_SUMNJA, IZVOR_JEDINICA        # "8 m" nije "8 cm" — profesor odlučuje
        if _je_mjerna(ua or ub):
            return STATUS_TOCNO, IZVOR_JEDINICA         # mjerna jedinica napisana ili izostavljena
        return STATUS_SUMNJA, IZVOR_JEDINICA            # samo slovo ("5a" prema "5") — ne odlučujem

    if va.rstrip("%") == vb.rstrip("%"):                # "50%" = "50"
        return STATUS_TOCNO, IZVOR_ZAPIS

    x, y = _kao_broj(va), _kao_broj(vb)
    if x is not None and y is not None:
        return (STATUS_TOCNO if _jednaki(x, y) else STATUS_NETOCNO), IZVOR_BROJ

    nx, ny = _vrijednost_izraza(kljuc), _vrijednost_izraza(odgovor)
    if nx is not None and ny is not None:
        return (STATUS_TOCNO if _jednaki(nx, ny) else STATUS_NETOCNO), IZVOR_BROJ

    return None, ""


def uporedi(kljuc, odgovor) -> dict:
    """Deterministička odluka (bez AI-ja): `{"status", "izvor", "zasto"}`.

    `status` je `tocno` / `netocno` / `sumnja` / `prazno` / `ceka`. Nikad ne baca.
    """
    if not _tekst(odgovor):
        return {"status": STATUS_PRAZNO, "izvor": "", "zasto": "nema odgovora"}
    if not _tekst(kljuc):
        return {"status": STATUS_CEKA, "izvor": "", "zasto": "zadatak nema ključ"}

    sumnja = None
    netocno_broj = None
    for alt in _alt_kljucevi(kljuc):
        status, izvor = _uporedi_jedan(alt, odgovor)
        if status == STATUS_TOCNO:
            return {"status": STATUS_TOCNO, "izvor": izvor, "zasto": ""}
        if status == STATUS_SUMNJA and sumnja is None:
            sumnja = {"status": STATUS_SUMNJA, "izvor": izvor,
                      "zasto": "isti broj, različita jedinica"}
        if status == STATUS_NETOCNO and izvor == IZVOR_BROJ and netocno_broj is None:
            netocno_broj = {"status": STATUS_NETOCNO, "izvor": IZVOR_BROJ,
                            "zasto": "vrijednost se razlikuje od ključa"}
    if sumnja:
        return sumnja
    if netocno_broj:
        return netocno_broj                          # dokazivo druga vrijednost — nije stvar zapisa
    return {"status": STATUS_NETOCNO, "izvor": "", "zasto": ""}


# ============================================================
# „Je li blizu?" — treba li uopće AI / profesor
# ============================================================

def blizu(kljuc, odgovor) -> bool:
    """Je li odgovor KANDIDAT za sumnju (da se ne zove AI za svaki pogrešan odgovor)?

    Tri jeftina signala: isti skup brojeva, vrlo sličan zapis, ili jedan zapis sadrži drugi.
    """
    a, b = normalizuj(kljuc), normalizuj(odgovor)
    if not a or not b:
        return False
    ba, bb = set(brojevi(kljuc)), set(brojevi(odgovor))
    if ba and ba == bb:
        return True
    if SequenceMatcher(None, a, b).ratio() >= 0.9:
        return True
    kraca, duza = sorted((a, b), key=len)
    return len(kraca) >= 3 and kraca in duza


# ============================================================
# 2. sloj — AI (samo „isti / nije isti", nikad rješenje)
# ============================================================

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
MAX_TOKENA = 200
TEMPERATURA = 0.0
TIMEOUT_S = 15

UPUTA = """Ti si asistent profesora i provjeravaš KRATKI ODGOVOR učenika u testu.

STROGA PRAVILA:
1. TOČNO RJEŠENJE (ključ) je JEDINI izvor istine. Nikad ga ne računaj ponovno, ne provjeravaj je li
   točno i ne predlaži drugi rezultat. Nikad ne napiši rješenje.
2. Odlučuješ SAMO o tome je li učenikov zapis PRIHVATLJIV OBLIK tog istog rješenja.
3. "tocno": true kad se razlikuje samo ZAPIS: interpunkcija i decimalni zarez, LaTeX ukrasi
   (\\mathrm, \\text, $), oblik razlomka (1/2, \\frac{1}{2}, 0,5), mjerna jedinica napisana,
   izostavljena ili napisana riječju (8, 8°, 8 °C, 8 stupnjeva), valuta (58, 58 eura, 58 €),
   red riječi, veliko/malo slovo, razmak, ime nepoznanice (x=2 prema 2).
4. "tocno": false kad se razlikuje VRIJEDNOST: drugi broj, predznak ili eksponent, jedinica koja
   mijenja vrijednost (8 m nije 8 cm, 8 kg nije 8 g), kriva formula ili krivi izraz.
5. Ako nisi siguran, stavi sigurnost "niska". Bolje prijaviti sumnju nego pogoditi.

Odgovori ISKLJUČIVO JSON-om, bez ijedne riječi izvan JSON-a:
{"tocno": true, "sigurnost": "visoka", "zasto": "do 15 riječi na hrvatskom"}
"""


def sastavi_pitanje(kljuc, odgovor, tekst="") -> str:
    """Pitanje za AI: ključ + odgovor + (skraćen) tekst zadatka — samo za kontekst."""
    zadatak = _tekst(tekst)
    blok = f"\nZADATAK (kontekst, ne rješavaj ga): {zadatak[:500]}\n" if zadatak else "\n"
    return (f"TOČNO RJEŠENJE (ključ): {_tekst(kljuc)}\n"
            f"UČENIKOV ODGOVOR: {_tekst(odgovor)}\n"
            f"{blok}\nVrati JSON po pravilima.")


def _izvuci_json(tekst: str):
    """Tolerantno: JSON u ogradi, JSON u tekstu ili čisti JSON."""
    t = _tekst(tekst)
    if not t:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (ValueError, TypeError):
        return None


def ai_uporedi(kljuc, odgovor, tekst="", pozovi=None) -> dict:
    """AI kao drugo mišljenje: `{"tocno", "sigurnost", "zasto"}` ili `None` (nema AI-ja / ne razumije).

    Nikad ne baca — greška AI-ja znači „ne znam", a to vodi u sumnju (profesor).
    """
    if not pozovi:
        return None
    try:
        odgovor_ai = pozovi(UPUTA, sastavi_pitanje(kljuc, odgovor, tekst))
    except Exception:                                   # noqa: BLE001 — AI ne smije rušiti ocjenu
        return None
    if isinstance(odgovor_ai, dict) and "tocno" in odgovor_ai:
        podaci = odgovor_ai                              # već strukturiran odgovor (testovi)
    elif isinstance(odgovor_ai, dict):
        podaci = _izvuci_json(odgovor_ai.get("tekst", ""))
    else:
        podaci = _izvuci_json(odgovor_ai)
    if not isinstance(podaci, dict) or "tocno" not in podaci:
        return None
    sigurnost = _tekst(podaci.get("sigurnost")).lower()
    return {"tocno": bool(podaci.get("tocno")),
            "sigurnost": sigurnost if sigurnost in ("visoka", "srednja", "niska") else "niska",
            "zasto": _tekst(podaci.get("zasto"))[:160]}


def napravi_pozivac(secrets, model: str = MODEL, timeout: int = TIMEOUT_S):
    """`pozovi` iz Streamlit Secrets (DeepSeek) ili `None` ako ključa nema.

    Tajna: `DEEPSEEK_API_KEY` u Secrets. `secrets` može biti i običan dict (testovi).
    """
    kljuc = ""
    try:
        kljuc = _tekst(secrets.get("DEEPSEEK_API_KEY"))
    except Exception:                                   # noqa: BLE001 — nema Secrets
        kljuc = ""
    if not kljuc:
        return None

    def pozovi(uputa: str, pitanje: str) -> dict:
        import requests                                 # lokalno: booking repo nema requests u requirements

        tijelo = {"model": model,
                  "messages": [{"role": "system", "content": uputa},
                               {"role": "user", "content": pitanje}],
                  "temperature": TEMPERATURA,
                  "max_tokens": MAX_TOKENA}
        odgovor = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {kljuc}", "Content-Type": "application/json"},
            json=tijelo, timeout=timeout)
        if odgovor.status_code != 200:
            raise RuntimeError(f"AI nije odgovorio (HTTP {odgovor.status_code}).")
        return {"tekst": _tekst(odgovor.json()["choices"][0]["message"]["content"])}

    return pozovi


# ============================================================
# 3. sloj — konačna odluka
# ============================================================

def _sigurno_razlicita_vrijednost(kljuc, odgovor) -> bool:
    """Tvrdi dokaz da je vrijednost drugačija (AI to ne smije proglasiti točnim)."""
    x, y = _vrijednost_izraza(kljuc), _vrijednost_izraza(odgovor)
    return x is not None and y is not None and not _jednaki(x, y)


def odluci(kljuc, odgovor, *, tekst="", pozovi=None, dopusti_ai=True) -> dict:
    """Konačna odluka: `{"status", "izvor", "zasto"}`.

    Redom: prazno → bez ključa → deterministički točno → (blizu) AI → sumnja → netočno.
    """
    if not _tekst(odgovor):
        return {"status": STATUS_PRAZNO, "izvor": "", "zasto": "nema odgovora"}
    if not _tekst(kljuc):
        return {"status": STATUS_CEKA, "izvor": "", "zasto": "zadatak nema ključ"}

    rez = uporedi(kljuc, odgovor)
    if rez["status"] in (STATUS_TOCNO, STATUS_CEKA, STATUS_PRAZNO):
        return rez

    if rez["status"] == STATUS_SUMNJA:
        return rez

    if rez["status"] == STATUS_NETOCNO and rez["izvor"] == IZVOR_BROJ:
        return rez                                      # vrijednost je dokazivo druga — AI tu ne pomaže

    if not blizu(kljuc, odgovor):
        return rez                                      # očito pogrešno — ne troši AI ni profesora

    if dopusti_ai and pozovi:
        prijedlog = ai_uporedi(kljuc, odgovor, tekst, pozovi)
        if prijedlog is not None:
            if _sigurno_razlicita_vrijednost(kljuc, odgovor):
                return {"status": STATUS_NETOCNO, "izvor": IZVOR_BROJ,
                        "zasto": "vrijednost se razlikuje od ključa"}
            if prijedlog["sigurnost"] == "visoka":
                return {"status": STATUS_TOCNO if prijedlog["tocno"] else STATUS_NETOCNO,
                        "izvor": IZVOR_AI, "zasto": prijedlog["zasto"]}
            return {"status": STATUS_SUMNJA, "izvor": IZVOR_AI,
                    "zasto": prijedlog["zasto"] or "AI nije siguran"}

    return {"status": STATUS_SUMNJA, "izvor": IZVOR_SUMNJA,
            "zasto": "sličan zapis, nije moguće automatski odlučiti"}


def tocno(kljuc, odgovor) -> bool:
    """Kratki odgovor JE točan (deterministički, bez AI-ja) — zamjena za staru provjeru."""
    return odluci(kljuc, odgovor, dopusti_ai=False)["status"] == STATUS_TOCNO


__all__ = [
    "STATUS_TOCNO", "STATUS_NETOCNO", "STATUS_SUMNJA", "STATUS_PRAZNO", "STATUS_CEKA",
    "IZVOR_ZAPIS", "IZVOR_BROJ", "IZVOR_JEDINICA", "IZVOR_AI", "IZVOR_SUMNJA",
    "OTVORENI_STATUSI", "JEDINICE_MJERNE", "UPUTA", "MODEL",
    "skini_omotace", "normalizuj", "razdvoji_jedinicu", "brojevi", "blizu",
    "bez_suvisnih_zagrada", "uporedi", "ai_uporedi", "sastavi_pitanje", "napravi_pozivac",
    "odluci", "tocno",
]
