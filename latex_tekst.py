"""
CAKI — latex_tekst.py (4.11.2026.)

Pretvaranje teksta iz baze (Google Sheet) u SIGURAN LaTeX. Izdvojeno u zaseban modul
jer ga od 4.11.2026. trebaju DVA generatora PDF-a:
  - pages/2_test_builder.py  (testovi/radni listići)   — još uvijek ima SVOJU kopiju
  - skripta_latex.py         (skripta, LaTeX verzija)  — koristi ovaj modul

ZNANA DUPLIKACIJA (prijedlog za čišćenje, NIJE napravljeno): funkcije
`escape_outside_math`, `formatiraj_opciju` i `izgradi_opcije_blok` POSTOJE I DALJE u
pages/2_test_builder.py, doslovno istog sadržaja. Namjerno se tamo NIJE diralo u ovoj
isporuci (Test Builder je u svakodnevnoj upotrebi, a ovo je nova, još neisprobana
staza) — ali to znači da popravak jednog mjesta NE popravlja drugo, isti rizik kao kod
`pipeline_upisi.py` triplikacije. Kad Caki potvrdi da nova skripta radi, u Test Builderu
se tih ~60 redaka zamijeni s `from latex_tekst import ...` i duplikat nestaje.

Logika je PRENESENA DOSLOVNO, uključujući sve komentare o tome ZAŠTO je tako — svaki
od njih je nastao iz stvarnog pada kompajliranja (v. datume).
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------
# LaTeX escape (izvan $...$ regija)
# ---------------------------------------------------------------

SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}

# 17.9.2026. - pad kompajliranja "! LaTeX Error: Unicode character ̇ (U+0307)
# not set up for use with LaTeX" na tekstu poput "iz intervala [-0.13̇, -0.13]".
# U+0307 (COMBINING DOT ABOVE) je Mathpix OCR-ov zapis PERIODIČKOG decimalnog
# broja (znamenka koja se ponavlja u periodu ima točku iznad, npr. "0,1̇3" =
# 0,1333...) - dva odvojena Unicode znaka (znamenka + kombinirajuća točka), gdje
# se drugi "lijepi" na prvi VIZUALNO, ali pdflatex (8-bit OT1/T1 fontovi, ne
# xelatex/lualatex) ne zna prikazati samostalan U+0307 nijednom običnom
# naredbom/paketom - baca Fatal error i RUŠI CIJELO kompajliranje (ne samo taj
# zadatak). SPECIAL_CHARS gore ovo ne može riješiti (znak-po-znak, nema pojma o
# PRETHODNOM znaku) - treba par (znak + U+0307) zamijeniti CIJELIM, već
# ispravnim LaTeX math naglaskom \dot{znak} (standardni LaTeX2e math accent,
# radi bez dodatnih paketa) PRIJE escapiranja, da se { } iz \dot{...} slučajno
# ne escapiraju istim prolazom.
KOMBINIRAJUCA_TOCKA_IZNAD = "̇"

# 4.11.2026. (NOVO, samo za skriptu): cijele LaTeX okoline koje se propuštaju NEDIRNUTE,
# isto kao $...$ regije. Zašto: skripta ispisuje PUNI POSTUPAK rješenja, a Caki u polje
# `rjesenje` zna upisati tablicu (\begin{tabular}...\end{tabular}) ili poravnate jednadžbe
# (\begin{align}...). Escapiranje bi od toga napravilo doslovan tekst
# "\textbackslash{}begin\{tabular\}" nasred stranice. Test Builder ovaj problem NEMA jer od
# 8.10.2026. ispisuje samo konačan odgovor, pa je ovo namjerno OPCIONALNO (zadano
# isključeno = ponašanje bit-po-bit isto kao u Test Builderu).
_OKOLINA_RE = re.compile(r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}", re.DOTALL)


def _escape_plain_segment(segment: str) -> str:
    """Escapira SPECIAL_CHARS znak-po-znak, ali PRIJE toga izdvaja parove
    (bilo koji znak + KOMBINIRAJUCA_TOCKA_IZNAD) u already-LaTeX "$\\dot{znak}$"
    komad koji se NE escapira (mora ostati literalan LaTeX)."""
    if KOMBINIRAJUCA_TOCKA_IZNAD not in segment:
        return "".join(SPECIAL_CHARS.get(ch, ch) for ch in segment)
    komadi = re.split(r"(.̇)", segment)
    out = []
    for komad in komadi:
        if len(komad) == 2 and komad[1] == KOMBINIRAJUCA_TOCKA_IZNAD:
            out.append(f"$\\dot{{{komad[0]}}}$")
        else:
            out.append("".join(SPECIAL_CHARS.get(ch, ch) for ch in komad))
    return "".join(out)


def escape_outside_math(text: str, cuvaj_okoline: bool = False) -> str:
    """Escapira sve izvan $...$ regija; $...$ ostaje doslovno.

    cuvaj_okoline=True dodatno propušta nedirnute cijele \\begin{...}...\\end{...}
    blokove (v. _OKOLINA_RE). Zadano False = identično Test Builderu."""
    if not text:
        return ""
    if cuvaj_okoline:
        out = []
        zadnji = 0
        for m in _OKOLINA_RE.finditer(text):
            out.append(escape_outside_math(text[zadnji:m.start()], cuvaj_okoline=False))
            out.append(m.group(0))          # cijela okolina — doslovno
            zadnji = m.end()
        out.append(escape_outside_math(text[zadnji:], cuvaj_okoline=False))
        return "".join(out)
    parts = re.split(r"(\$[^$]*\$)", text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part)
        else:
            out.append(_escape_plain_segment(part))
    return "".join(out)


def saldo_viticastih(text: str) -> int:
    """Saldo NEESCAPIRANIH vitičastih zagrada: 0 = uravnoteženo, >0 = višak `{`, <0 = višak `}`.
    Escapirani par (`\\{`, `\\}`) i `\\\\` se preskaču — oni su literalni znakovi, ne grupe.
    Vraća prvi negativan saldo (zatvaranje bez otvaranja) odmah, jer je to već greška."""
    saldo = 0
    i, n = 0, len(text or "")
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2                      # `\{`, `\}`, `\\`, `\frac` -> drugi znak se preskače
            continue
        if c == "{":
            saldo += 1
        elif c == "}":
            saldo -= 1
            if saldo < 0:
                return saldo
        i += 1
    return saldo


def provjeri_polje(sadrzaj) -> list:
    """Vraća popis OPISA problema zbog kojih bi pdflatex pao na ovom polju (prazno = u redu).

    Namjerno provjerava SAMO ono što je stvarno fatalno, da ne prijavljuje lažne greške:

    1. **Neparan broj `$`** — matematički način ostaje otvoren i ruši cijeli dokument.
    2. **Neuravnotežene `{ }` UNUTAR `$...$`** (ili unutar sačuvane okoline). Izvan
       matematike `{` i `}` prolaze kroz escape_outside_math i postaju bezopasan tekst, pa
       bi provjera cijelog polja prijavljivala bezbroj bezopasnih redaka (npr. „skup {1,2}").
       Unutar matematike se prenose doslovno, pa `$\\frac{1}{2$` doista puca.

    Namjerno se NE prijavljuje nesparen `\\begin{...}` bez `\\end{...}`: takav se blok ne
    prepoznaje kao okolina, pa ga escape pretvori u običan tekst — ružno, ali ne pada."""
    s = str(sadrzaj if sadrzaj is not None else "")
    if not s:
        return []
    problemi = []
    if broj_dolara(s) % 2 != 0:
        problemi.append("neparan broj `$` (otvorena matematika)")

    # Regije koje idu u LaTeX DOSLOVNO: $...$ i cijele \begin{...}...\end{...} okoline.
    doslovno = [m.group(0)[1:-1] for m in re.finditer(r"\$[^$]*\$", s)]
    doslovno += [m.group(0) for m in _OKOLINA_RE.finditer(s)]
    for regija in doslovno:
        if saldo_viticastih(regija) != 0:
            problemi.append("neuravnotežene `{ }` unutar matematike")
            break
    return problemi


def broj_dolara(text) -> int:
    """Broji '$' znakove koji NISU escapirani (\\$) - koristi se za provjeru parnosti
    prije slanja u LaTeX. Neparan broj = tekst će razbiti kompajliranje.

    NAPOMENA (15.9.2026.): neka polja (konacan_odgovor, rjesenje) znaju stići kao broj
    (int/float) umjesto string - str() to ispravlja bez obzira na tip."""
    return len(re.findall(r"(?<!\\)\$", str(text) if text is not None else ""))


# ---------------------------------------------------------------
# Ponuđeni odgovori (višestruki izbor) A) B) C) D)
# ---------------------------------------------------------------

SLOVA_OPCIJA = ["A", "B", "C", "D", "E", "F", "G", "H"]


def formatiraj_opciju(opcija: str) -> str:
    """Baza sprema ponudjeni_odgovori kao ČIST LaTeX BEZ $...$ omotača kad je opcija
    matematika (npr. "\\frac{1}{(2 a-1)^{3}}"). Ali OPREZ: neke opcije su čist tekst bez
    ikakve matematike (npr. "trostrana piramida") - te NE SMIJU u $...$, jer LaTeX
    matematički način rada IGNORIRA razmake među riječima (postalo bi "trostranapiramida",
    bez razmaka - stvarni bug koji smo vidjeli).

    Razlikovanje: ako opcija sadrži LaTeX naredbu ili math-specifičan znak (\\, ^, _) ->
    tretiramo kao čistu matematiku, omatamo u $...$ BEZ escapiranja (escapiranje bi razbilo
    \\frac{...}). Inače -> čist tekst, ide kroz escape_outside_math (čuva razmake, escapira
    posebne znakove poput %/&)."""
    opcija = (opcija or "").strip()
    if "$" in opcija:
        # Već ima $ (npr. ručno upisano "$x=1$") - slobodan tekst s ugrađenom matematikom.
        return escape_outside_math(opcija)
    if re.search(r"[\\^_]", opcija):
        # Sadrži LaTeX naredbu (\frac, \sqrt...) ili ^ / _ - čista matematika.
        return f"${opcija}$"
    # Običan tekst bez ikakve matematike - NE omatati u $...$.
    return escape_outside_math(opcija)


def izgradi_opcije_blok(ponudjeni_odgovori) -> str:
    """Gradi LaTeX za prikaz ponuđenih odgovora (A/B/C/D...) ispod teksta zadatka, kao
    PRIRODAN tok teksta (ne fiksna tablica/popis) - LaTeX sam odlučuje hoće li sve stati u
    JEDAN REDAK (kompaktno, štedi papir) ili prelomiti na više redaka. Upravo to je ono što
    je Caki tražio za skriptu ("a,b,c,d odgovori u jednom redu ako mogu stati") - pravilo se
    NE može pouzdano odlučiti u Pythonu jer se stvarna širina sloga zna tek kad LaTeX složi
    stranicu.

    VAŽNO: ovaj blok se NE smije propuštati kroz escape_outside_math kao cjelina - dodaje se
    NAKON escapiranja teksta zadatka, jer sadrži prave LaTeX naredbe (\\textbf, \\quad...).
    Svaka POJEDINA opcija obrađuje se zasebno preko formatiraj_opciju()."""
    opcije = [formatiraj_opciju(o) for o in (ponudjeni_odgovori or []) if str(o).strip()]
    if not opcije:
        return ""
    dijelovi = [f"\\textbf{{{SLOVA_OPCIJA[j] if j < len(SLOVA_OPCIJA) else str(j + 1)})}}~{opc}"
                for j, opc in enumerate(opcije)]
    return "\n\\par\\vspace{3mm}\n\\noindent " + "\\quad ".join(dijelovi) + "\\par"
