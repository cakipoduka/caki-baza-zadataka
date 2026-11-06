"""
CAKI — skripta_latex.py (4.11.2026.)

Generator .tex TIJELA skripte za NOVU stazu „Skripta (LaTeX)" (pages/19_skripta_latex.py).
Gradi PDF IZRAVNO pdflatexom preko pages/caki-skripta.sty, isto kao Test Builder — a NE
preko PreTeXt-a.

ODNOS PREMA POSTOJEĆOJ SKRIPTI (Cakijeva odluka 4.11.2026.): postojeća PreTeXt staza
(pages/4_skripta.py + skripta_build.py + GitHub Actions) ostaje NEDIRNUTA i radi kao prije.
Ovo je PARALELNA, nova staza. Nijedna funkcija iz skripta_build.py se ovdje ne poziva niti
mijenja.

ZAŠTO IZRAVAN LaTeX (razlog iz analize prije pisanja koda):
  1. PreTeXt ne prima SIROVI LaTeX. Formule u tabu `Formule` su čisti LaTeX
     (\\frac, \\binom, \\operatorname{tg}, \\quad...) — da bi išle u PreTeXt skriptu,
     trebao bi pisati konverter LaTeX -> <md>/<mrow>. U .tex-u je to `\\[...\\]`.
  2. Rješenja NA KRAJU SVAKOG POGLAVLJA PreTeXt ne podržava — njegova <solutions>
     mehanika ih seli u backmatter cijelog dokumenta.
  3. Sve što je Caki tražio za izgled (veća matematika, A-D u jednom redu, uske margine,
     crn tekst) već je riješeno i dokazano u produkciji u caki-style.sty.

ŠTO SE OVDJE **NE** RADI: čitanje Sheeta, Drive, Streamlit, kompajliranje. Ovaj modul je
ČISTA funkcija (redci -> .tex tekst), pa je testabilan bez mreže — v. testovi/
test_skripta_latex.py.
"""
from __future__ import annotations

import os

import baza_zadataka_pipeline as bp
import latex_tekst as lt
import skupine_zadataka
import teorija_markup

# Naslovi odjeljaka unutar poglavlja — na jednom mjestu, da ih Caki mijenja bez
# diranja logike. („Primjeri za rad na satu" je bio naziv u PreTeXt verziji od
# 30.10.2026.; ovdje su kraći nazivi jer su primjeri i zadaci sada i vizualno
# odvojeni razdjelnikom.)
NASLOV_PRIMJERI = "Primjeri"
NASLOV_ZADACI = "Zadaci"
NASLOV_RJESENJA = "Rješenja"

# Načini ispisa rješenja
RJESENJA_POSTUPAK = "postupak"   # puni postupak iz polja `rjesenje` (pad na konačan odgovor)
RJESENJA_ODGOVOR = "odgovor"     # samo konačan odgovor (kompaktno, 2 stupca)
RJESENJA_BEZ = "bez"             # bez rješenja (čista učenička vježbenica)
RJESENJA_NACINI = (RJESENJA_POSTUPAK, RJESENJA_ODGOVOR, RJESENJA_BEZ)

# GDJE idu rješenja (5.11.2026., Cakijev nalaz „puno praznih stranica zbog ispisa rješenja"):
# svaka cjelina počinje na novoj stranici, pa blok rješenja na kraju svakog poglavlja često
# ostavi pola prazne stranice prije sljedeće cjeline. Zato sada i varijanta „sve na kraju".
MJESTO_POGLAVLJE = "poglavlje"   # blok rješenja iza svakog poglavlja (dosadašnje ponašanje)
MJESTO_KRAJ = "kraj"             # jedna cjelina „Rješenja" na kraju skripte
MJESTA_RJESENJA = (MJESTO_POGLAVLJE, MJESTO_KRAJ)


# ============================================================
# Pomoćno: tekst jednog zadatka/primjera -> LaTeX
# ============================================================

def _slike_csv(row, slike_dostupne) -> str:
    """'a.png | b.png' iz baze -> 'images/a.png,images/b.png' za \\cakislike (caki-style.sty
    ih slaže jednu uz drugu, v. §\\cakislike ondje).

    slike_dostupne: skup naziva slika koje su STVARNO skinute na disk. Slika koje nema se
    PRESKAČE — referenciranje nepostojeće datoteke ruši cijelo kompajliranje s
    "File not found" (ista zaštita kao u Test Builderu)."""
    izvori = [row] + list(row.get("stavke") or [])   # skupina: i slike njezinih stavki
    nazivi = []
    for r in izvori:
        for x in bp.razdvoji_slike(r.get("slika_putanja")):
            naziv = os.path.basename(x)
            if naziv and naziv not in nazivi:
                nazivi.append(naziv)
    if slike_dostupne is not None:
        nazivi = [x for x in nazivi if x in slike_dostupne]
    return ",".join(f"images/{x}" for x in nazivi)


# ============================================================
# Tablice u tekstu zadatka (6.11.2026., Cakijev nalaz)
#
# Baza drži tablice u DVA oblika:
#   1. markdown pipe tablica  — noviji uvozi (v. upute/UPDATE_04-11_uvoz_pipe_tablice.md)
#   2. `\begin{tabular}` s ESCAPEANIM `\&` — uvozi od 27.–30.10.2026.
# Prva verzija ove stranice ispisivala je oboje doslovno: pipe tablica je izlazila kao
# „| Litre | 9.1 | 23.45 |", a tabular kao jedan stupac s vidljivim `&` (jer `\&` u LaTeXu
# znači ZNAK &, a ne razdjelnik stupaca).
#
# Rješenje NAMJERNO ne piše vlastiti parser: koristi iste, već dokazane funkcije kojima i
# PreTeXt staza slaže tablice (bp._latex_tabular_u_pipe -> bp._pronadji_pipe_tablice), pa se
# dvije staze ne mogu razići u tome ŠTO je tablica. Ovdje je nova samo zadnja karika —
# ispis segmenta kao pravog LaTeX tabulara.
# ============================================================

def _latex_celija(raw) -> str:
    """Jedna ćelija tablice. Odluka „tekst ili matematika" ide kroz bp._je_obican_tekst —
    JEDINSTVENO mjesto za cijeli projekt (v. ondje): riječ ostaje tekst (matematički font
    nema č/ž/š/ć/đ!), a izraz ide u $...$ da brojevi budu u matematičkom fontu."""
    if raw is None or not str(raw).strip():
        return ""
    s = str(raw).strip()
    if "$" in s:
        return lt.escape_outside_math(s)
    if bp._je_obican_tekst(s):
        return lt.escape_outside_math(s)
    return f"${s}$"


def _latex_tabular(redovi) -> str:
    """[[ćelija, ...], ...] -> pravi LaTeX tabular, centriran, s mrežom crta (prvi redak je
    zaglavlje, kako markdown i definira). Mreža (`|c|c|` + \\hline) namjerno je ista kao u
    tablicama koje je AI uvozio, da izgled ostane prepoznatljiv."""
    redovi = [r for r in (redovi or []) if r]
    if not redovi:
        return ""
    sirina = max(len(r) for r in redovi)
    linije = ["\\par\\vspace{2mm}", "{\\centering",
              "\\begin{tabular}{|" + "c|" * sirina + "}", "\\hline"]
    for redak in redovi:
        celije = [_latex_celija(c) for c in redak] + [""] * (sirina - len(redak))
        linije.append(" & ".join(celije) + " \\\\ \\hline")
    linije += ["\\end{tabular}", "\\par}", "\\vspace{2mm}"]
    return "\n".join(linije)


def tekst_u_latex_blokove(raw) -> str:
    """Tekst zadatka -> LaTeX, s tablicama složenima kao prave tablice.

    Redoslijed je isti kao u bp._statement_tekst_lines (PreTeXt staza):
    1. `\\begin{tabular}` -> pipe tablica (usput rješava i escapeani `\\&`),
    2. tekst se razlomi na segmente (tekst / tablica),
    3. tekstualni segmenti idu kroz escape, tablični u \\begin{tabular}.
    Zadatak BEZ tablice prolazi kroz točno isti escape kao i prije — bez promjene."""
    raw = bp._latex_tabular_u_pipe(str(raw or ""))
    if not raw.strip():
        return ""
    dijelovi = []
    for vrsta, sadrzaj in bp._pronadji_pipe_tablice(raw):
        if vrsta == "tab":
            dijelovi.append(_latex_tabular(sadrzaj))
        else:
            tekst = lt.escape_outside_math(str(sadrzaj).strip(), cuvaj_okoline=True)
            if tekst:
                dijelovi.append(tekst)
    return "\n".join(dijelovi)


def _escape_stavke(sadrzaj) -> str:
    """Escape za stavke skupine i za rješenja: tablica se spljošti u čitljiv redak
    („x, f(x); -1, 7") umjesto blok-tablice. Razlog je isti kao kod bp._latex_tabular_u_tekst:
    blok-tablica unutar stavke a)/b)/c) ili unutar uskog stupca rješenja razbija slog —
    ali SIROVI `\\begin{tabular}` ne izlazi nikad."""
    return lt.escape_outside_math(bp._latex_tabular_u_tekst(str(sadrzaj or "")),
                                  cuvaj_okoline=True)


def _opcije_iz_retka(row) -> list:
    """ponudjeni_odgovori se u Sheetu drži kao 'a || b || c' (v. bp §1202) i vrijedi SAMO za
    tip_zadatka='visestruki_izbor'."""
    if (row.get("tip_zadatka") or "").strip() != "visestruki_izbor":
        return []
    raw = str(row.get("ponudjeni_odgovori") or "").strip()
    return [o.strip() for o in raw.split("||") if o.strip()]


def _opcije_su_slike(opcije, row, slike_dostupne):
    """28.10.2026. slučaj prenesen iz Test Buildera/pipelinea: ponuđeni odgovori koji su SAME
    SLIKE (grafovi/crteži). AI pri uvozu sprema ponudjeni_odgovori kao placeholder
    'slika A'/'slika B'/..., a stvarne slike idu u slika_putanja istim redoslijedom — uz
    eventualno JOŠ JEDNU sliku ISPRED (slika samog pitanja).

    Vraća (je_slike, slika_pitanja ili None, [nazivi slika opcija]). Kad se broj slika ne
    poklapa s brojem opcija, vraća se (False, None, []) — siguran fallback na tekstualne
    opcije, isto kao u postojećem kodu."""
    if len(opcije) < 2 or not all(bp._SLIKA_OPCIJA_RE.match(o) for o in opcije):
        return False, None, []
    nazivi = [os.path.basename(x) for x in bp.razdvoji_slike(row.get("slika_putanja"))]
    if slike_dostupne is not None and not all(x in slike_dostupne for x in nazivi):
        return False, None, []          # barem jedna slika nije skinuta — ne riskiraj
    if len(nazivi) == len(opcije):
        return True, None, nazivi
    if len(nazivi) == len(opcije) + 1:
        return True, nazivi[0], nazivi[1:]
    return False, None, []


# Podjela polja na "izjavnu" i "rješenjsku" stranu — kad je jedno polje neispravno, zamjenjuje
# se SAMO njegova strana, a ne cijeli zadatak (npr. pokvareno `rjesenje` ne briše tekst pitanja).
POLJA_IZJAVE = {"tekst zadatka", "uputa"}
POLJA_RJESENJA = {"rješenje", "konačan odgovor"}


def _je_losa_izjava(losa_polja) -> bool:
    # "stavka a) tekst zadatka" — polje stavke skupine (v. provjeri_latex).
    return any(p in POLJA_IZJAVE or p.startswith("opcija ") or p.endswith(" tekst zadatka")
               for p in losa_polja or ())


def _je_lose_rjesenje(losa_polja) -> bool:
    return any(p in POLJA_RJESENJA or p.endswith(" rješenje") or p.endswith(" konačan odgovor")
               for p in losa_polja or ())


def _oznaka_neispravnog(row, losa_polja) -> str:
    """Vidljiva zamjena u PDF-u za zadatak čiji LaTeX ne bi prošao kompajliranje. Zadatak se
    NE izbacuje nego ostaje na svom mjestu s ovom oznakom — tako numeracija (i veza s
    rješenjima) ostaje netaknuta i u PDF-u se TOČNO vidi što treba popraviti u bazi."""
    zid = str(row.get("id") or "bez id-a")
    polja = ", ".join(sorted(losa_polja or ())) or "LaTeX"
    return (f"\\cakineispravno{{{lt.escape_outside_math(zid)}}}"
            f"{{{lt.escape_outside_math(polja)}}}")


def tekst_stavke(row, slike_dostupne=None, s_oznakom_tezine=True, losa_polja=None) -> tuple:
    """Gradi (tekst_tex, slike_csv) za JEDAN redak baze — zajednička jezgra za primjer i
    zadatak (isti obrazac kao bp._build_statement_hint_solution_video za PreTeXt).

    s_oznakom_tezine: prefiks '[matura 2010, S] ' ispred teksta. Oznake L/S/T Caki je
    izričito tražio zadržati (4.11.2026.) — funkcija se NE duplicira, nego se poziva
    bp._oznaka_izvor_tezina, pa pravilo („zbirka" se ne ispisuje, matura dobiva godinu…)
    ostaje na JEDNOM mjestu za obje staze.

    losa_polja: imena polja ovog retka koja ne bi prošla kompajliranje (v. provjeri_latex).
    Ako je među njima tekst/uputa/opcija, umjesto teksta se ispisuje vidljiva oznaka i
    zadatak se NE izbacuje — v. _oznaka_neispravnog."""
    if _je_losa_izjava(losa_polja):
        return _oznaka_neispravnog(row, losa_polja), ""
    raw = str(row.get("tekst_zadatka_latex") or "")
    opcije = _opcije_iz_retka(row)
    if opcije:
        # 30.10.2026.: opcije se ispisuju JEDNOM (ispod teksta), pa ih makni iz teksta
        # pitanja ako ih je AI pri uvozu ostavio i tamo.
        raw = bp._bez_opcija_u_tekstu(raw)

    oznaka = bp._oznaka_izvor_tezina(row) if s_oznakom_tezine else ""
    # Oznaka težine se escapira zasebno i lijepi ISPRED tijela: tijelo može početi tablicom,
    # koja je blok, pa se oznaka ne smije provući kroz isti prolaz.
    tekst = lt.escape_outside_math(oznaka) + tekst_u_latex_blokove(raw)

    # SKUPINA ZADATAKA (6.11.2026., Cakijev nalaz „a, b, c se prikazuju kao zasebni zadaci"):
    # uvod skupine + stavke a), b), c)… u JEDNOM zadatku. Blok gradi skupine_zadataka —
    # isti modul i isti izgled kao u Test Builderu, da se dva ispisa ne raziđu. Dodaje se
    # NAKON escapiranja uvoda, jer sadrži prave LaTeX naredbe (\textbf, \qquad).
    stavke = row.get("stavke") or []
    if stavke:
        tekst += skupine_zadataka.izgradi_stavke_blok(stavke, escape=_escape_stavke)

    slike_csv = _slike_csv(row, slike_dostupne)
    if opcije:
        je_slike, slika_pitanja, slike_opcija = _opcije_su_slike(opcije, row, slike_dostupne)
        if je_slike:
            if slika_pitanja:
                tekst += ("\n\\par\\vspace{2mm}\n{\\centering\\cakislike{images/"
                          + slika_pitanja + "}\\par}")
            lista = ",".join(f"images/{x}" for x in slike_opcija)
            tekst += f"\n\\par\\vspace{{2mm}}\n{{\\centering\\cakislikeopcije{{{lista}}}\\par}}"
            slike_csv = ""   # slike su VEĆ umetnute u tekst — ne prikazuj ih drugi put
        else:
            tekst += lt.izgradi_opcije_blok(opcije)

    uputa = str(row.get("uputa") or "").strip()
    if uputa:
        tekst += ("\n\\par\\vspace{1mm}\n{\\small\\itshape "
                  + lt.escape_outside_math(uputa, cuvaj_okoline=True) + "}\\par")
    return tekst, slike_csv


def rjesenje_stavke(row, nacin=RJESENJA_POSTUPAK, losa_polja=None) -> str:
    """Tekst rješenja za blok na kraju poglavlja. RJESENJA_POSTUPAK uzima puni postupak iz
    polja `rjesenje`, a ako ga nema pada na `konacan_odgovor` (bolje konačan odgovor nego
    prazan redak). RJESENJA_ODGOVOR uzima SAMO konačan odgovor.

    cuvaj_okoline=True: polje `rjesenje` zna sadržavati \\begin{tabular}/\\begin{align} —
    v. objašnjenje u latex_tekst.escape_outside_math.

    losa_polja: v. tekst_stavke — neispravno `rjesenje`/`konacan_odgovor` zamjenjuje se
    vidljivom oznakom, a redak rješenja ostaje na svom mjestu."""
    if _je_lose_rjesenje(losa_polja):
        return _oznaka_neispravnog(row, [p for p in losa_polja if _je_lose_rjesenje([p])])

    # Skupina: rješenje po stavci a), b), c)… (isti blok kao u Test Builderu).
    stavke = row.get("stavke") or []
    if stavke:
        rjesenje_tex, konacan_tex = skupine_zadataka.izgradi_rjesenja_blok(
            stavke, escape=_escape_stavke)
        if nacin == RJESENJA_ODGOVOR:
            return konacan_tex or rjesenje_tex
        return rjesenje_tex

    postupak = str(row.get("rjesenje") or "").strip()
    odgovor = str(row.get("konacan_odgovor") or "").strip()
    if nacin == RJESENJA_ODGOVOR:
        izvor = odgovor
    else:
        izvor = postupak or odgovor
    if not izvor:
        return "\\textit{(rješenje nije uneseno u bazu)}"
    return lt.escape_outside_math(izvor, cuvaj_okoline=True)


# ============================================================
# Blokovi: teorija i formule
# ============================================================

def teorija_blok(tekst_teorije: str, verzija: str = "ucenik") -> str:
    """Teorija ISPOD naslova cjeline (Caki 4.11.2026.). Markup (!!…!!, \\pojam{}, [RJESENJE])
    obrađuje teorija_markup.teorija_u_latex_odlomke — ISTA pravila odlomaka kao PreTeXt
    staza, samo drugi izlaz. Prazan tekst -> prazan string (blok se izostavlja, bez greške)."""
    tekst_teorije = (tekst_teorije or "").strip()
    if not tekst_teorije:
        return ""
    odlomci = teorija_markup.teorija_u_latex_odlomke(
        tekst_teorije, verzija=verzija,
        render=lambda s: lt.escape_outside_math(s, cuvaj_okoline=True))
    odlomci = [o for o in odlomci if o.strip()]
    if not odlomci:
        return ""
    # \par\smallskip, ne samo \par: unutar tcolorboxa je \parskip nula, pa su se na probnom
    # PDF-u (4.11.2026.) odlomci teorije slijepili u jedan blok teksta.
    return "\\cakiteorija{%\n" + "\n\\par\\smallskip\n".join(odlomci) + "%\n}\n"


def _formula_u_latex(tekst_latex: str) -> str:
    """Tab `Formule` drži formulu kao ČISTU matematiku BEZ $ omotača (v. formule.py i
    formule_matura_MAT_A.txt, npr. 'z=a+bi,\\ a,b\\in\\mathbb{R}'). Ovdje se omata u
    \\[...\\] (istaknuta formula u vlastitom retku).

    IZNIMKE koje se propuštaju doslovno: tekst koji VEĆ sadrži $ ili cijelu okolinu
    (\\begin{align}, \\begin{cases}, \\begin{array}) — takav je autor već sam oblikovao i
    dodatno omatanje bi dalo "$ unutar $" odnosno pogrešno ugniježđenu matematiku."""
    t = (tekst_latex or "").strip()
    if not t:
        return ""
    if "$" in t or "\\begin{" in t or t.startswith("\\["):
        # 4.11.2026. (nalaz s probnog PDF-a): nezvjezdane okoline (align, gather, equation)
        # u knjižici formula ispisuju BROJEVE JEDNADŽBI "(1) (2)" uz desni rub - u popisu
        # formula to nema smisla i izgleda kao greška. Prebacuje se na zvjezdanu inačicu.
        for ime in ("align", "gather", "equation", "multline", "eqnarray"):
            t = t.replace("\\begin{" + ime + "}", "\\begin{" + ime + "*}")
            t = t.replace("\\end{" + ime + "}", "\\end{" + ime + "*}")
            # ako je autor VEĆ pisao zvjezdano, gornje bi dalo "**" - vrati natrag
            t = t.replace("\\begin{" + ime + "**}", "\\begin{" + ime + "*}")
            t = t.replace("\\end{" + ime + "**}", "\\end{" + ime + "*}")
        return t
    return "\\[" + t + "\\]"


def formule_blok(formule=None, rucno: str = "") -> str:
    """formule: lista rječnika iz taba `Formule` ({naslov, tekst_latex, …}); rucno: slobodan
    LaTeX blok upisan na stranici za TO poglavlje (Cakijev izbor 4.11.2026.: oba izvora).
    Prazno -> prazan string (blok se izostavlja)."""
    dijelovi = []
    for f in formule or []:
        tekst = _formula_u_latex(f.get("tekst_latex"))
        if not tekst:
            continue
        naslov = lt.escape_outside_math(str(f.get("naslov") or "").strip())
        dijelovi.append(f"\\cakiformula{{{naslov}}}{{{tekst}}}")
    rucno = (rucno or "").strip()
    if rucno:
        # Ručni blok ide DOSLOVNO — Caki ga piše kao LaTeX (to je i smisao polja).
        dijelovi.append(rucno)
    if not dijelovi:
        return ""
    return "\\cakiformule{%\n" + "\n".join(dijelovi) + "%\n}\n"


# ============================================================
# Glavna funkcija: tijelo dokumenta
# ============================================================

def izgradi_tijelo(poglavlja, verzija: str = "ucenik", rjesenja: str = RJESENJA_POSTUPAK,
                   slike_dostupne=None, preskoci_neispravne: bool = False,
                   mjesto_rjesenja: str = MJESTO_POGLAVLJE) -> tuple:
    """Gradi cijelo tijelo skripte (ono što ide u generated/skripta_body.tex).

    poglavlja: lista rječnika, redoslijedom kojim idu u PDF:
        {
          "oznaka":  "3.1"      (neobavezno, ispisuje se ispred naslova cjeline),
          "naslov":  "Kvadratna jednadžba",
          "teorija": "sirovi tekst_teorije_latex"  (neobavezno),
          "formule": [ {naslov, tekst_latex}, ... ]  (neobavezno),
          "formule_rucno": "LaTeX blok"              (neobavezno),
          "primjeri": [redak baze, ...],
          "zadaci":   [redak baze, ...],
        }
    verzija: "ucenik" | "profesor" — prosljeđuje se teoriji ([RJESENJE] blokovi).
    rjesenja: v. RJESENJA_NACINI.
    slike_dostupne: skup naziva slika skinutih na disk (None = ne provjeravaj).
    preskoci_neispravne: True = polja koja bi srušila kompajliranje (v. provjeri_latex) se
        zamjenjuju VIDLJIVOM oznakom u PDF-u umjesto da gradnja stane. Zadatak ostaje na
        svom mjestu, pa se numeracija i veza sa rješenjima NE mijenjaju.
    mjesto_rjesenja: v. MJESTA_RJESENJA. MJESTO_KRAJ skuplja rješenja SVIH poglavlja u jednu
        cjelinu „Rješenja" na kraju (manje poluparaznih stranica); oznake ostaju iste
        („3.1.2."), pa se i dalje točno zna kojem zadatku rješenje pripada.

    Vraća (tijelo_tex, broj_primjera, broj_zadataka).

    NUMERIRANJE je ovdje, u Pythonu (ne LaTeX brojačima) — v. obrazloženje u
    pages/caki-skripta.sty: rješenja na kraju poglavlja moraju nositi TOČNO iste oznake
    kao zadaci."""
    if rjesenja not in RJESENJA_NACINI:
        raise ValueError(f"rjesenja mora biti jedno od {RJESENJA_NACINI}, dobiveno: {rjesenja!r}")
    if mjesto_rjesenja not in MJESTA_RJESENJA:
        raise ValueError(f"mjesto_rjesenja mora biti jedno od {MJESTA_RJESENJA}, "
                         f"dobiveno: {mjesto_rjesenja!r}")
    na_kraju = mjesto_rjesenja == MJESTO_KRAJ
    rjesenja_na_kraju = []        # [(naslov poglavlja, [(oznaka, tekst), ...]), ...]

    losa = losa_polja_po_retku(provjeri_latex(poglavlja)) if preskoci_neispravne else {}

    def _losa_za(kljuc_pog, row):
        return losa.get((kljuc_pog, str(row.get("id") or "bez id-a")), set())

    redovi = []
    ukupno_primjera = 0
    ukupno_zadataka = 0
    k = 0
    for pog in poglavlja or []:
        primjeri = list(pog.get("primjeri") or [])
        zadaci = list(pog.get("zadaci") or [])
        if not primjeri and not zadaci:
            continue                      # prazno poglavlje nema smisla u PDF-u
        k += 1
        kljuc_pog = str(pog.get("kljuc") or pog.get("naslov") or "")
        naslov = lt.escape_outside_math(str(pog.get("naslov") or "").strip())
        oznaka = lt.escape_outside_math(str(pog.get("oznaka") or "").strip())
        redovi.append(f"\\cakicjelina{{{oznaka}}}{{{naslov}}}")
        # Brojevi zadataka moraju pratiti oznaku cjeline: ako cjelina nosi "3.1", zadatak je
        # "3.1.2.", a ne "1.2." (nalaz s probnog PDF-a 4.11.2026. - naslov je pisao 3.2, a
        # zadatak 2.1, što zbunjuje). Bez oznake se koristi redni broj cjeline u skripti.
        broj = oznaka or str(k)

        teorija_sirova = pog.get("teorija")
        if preskoci_neispravne and lt.provjeri_polje(teorija_sirova):
            # Pokvarena teorija ne smije blokirati cijelu skriptu — mjesto ostaje vidljivo.
            redovi.append("\\cakiteorija{\\cakineispravno{teorija}{tekst teorije}}")
            teorija_sirova = ""
        blok = teorija_blok(teorija_sirova, verzija=verzija)
        if blok:
            redovi.append(blok)
        blok = formule_blok(pog.get("formule"), pog.get("formule_rucno"))
        if blok:
            redovi.append(blok)

        if primjeri:
            redovi.append(f"\\cakipodnaslovskripte{{{NASLOV_PRIMJERI}}}")
            for n, row in enumerate(primjeri, start=1):
                tekst, slike = tekst_stavke(row, slike_dostupne,
                                            losa_polja=_losa_za(kljuc_pog, row))
                redovi.append(f"\\cakiprimjer{{Primjer {broj}.{n}.}}{{{tekst}}}{{{slike}}}")
                redovi.append("")
            ukupno_primjera += len(primjeri)
            # Razdjelni simbol — traži ga Caki da se primjeri jasno odvoje od zadataka.
            # Ispisuje se SAMO ako iza primjera doista slijede zadaci.
            if zadaci:
                redovi.append("\\cakirazdjelnik")

        if zadaci:
            redovi.append(f"\\cakipodnaslovskripte{{{NASLOV_ZADACI}}}")
            for n, row in enumerate(zadaci, start=1):
                tekst, slike = tekst_stavke(row, slike_dostupne,
                                            losa_polja=_losa_za(kljuc_pog, row))
                redovi.append(f"\\cakizadatakskripte{{Zadatak {broj}.{n}.}}{{{tekst}}}{{{slike}}}")
                redovi.append("")
            ukupno_zadataka += len(zadaci)

        # --- Rješenja NA KRAJU POGLAVLJA (Caki, 4.11.2026.) ---
        if rjesenja != RJESENJA_BEZ:
            stavke = []
            # Verzija za profesora dodatno nosi KONAČNE ODGOVORE primjera (primjeri se
            # rješavaju uživo na satu pa im puni postupak ne treba) - isto pravilo kao u
            # PreTeXt verziji, gdje to radi _skripta_backmatter_lines s primjeri_rjesenja.
            if str(verzija).strip().lower() == "profesor":
                for n, row in enumerate(primjeri, start=1):
                    odgovor = str(row.get("konacan_odgovor") or "").strip()
                    if not odgovor:
                        continue
                    if "konačan odgovor" in _losa_za(kljuc_pog, row):
                        stavke.append((f"Primjer {broj}.{n}.",
                                       _oznaka_neispravnog(row, ["konačan odgovor"])))
                    else:
                        stavke.append((f"Primjer {broj}.{n}.",
                                       lt.escape_outside_math(odgovor, cuvaj_okoline=True)))
            for n, row in enumerate(zadaci, start=1):
                stavke.append((f"{broj}.{n}.",
                               rjesenje_stavke(row, rjesenja,
                                               losa_polja=_losa_za(kljuc_pog, row))))

            if stavke and na_kraju:
                rjesenja_na_kraju.append((naslov, stavke))
            elif stavke:
                redovi.append(f"\\cakirjesenjanaslov{{{NASLOV_RJESENJA} \\textendash{{}} {naslov}}}")
                redovi.extend(_blok_rjesenja(stavke, rjesenja))
                redovi.append("")

    # Sva rješenja u JEDNOJ cjelini na kraju skripte (v. mjesto_rjesenja). Cjelina se zove
    # „Rješenja" i, kao i svaka druga, počinje na novoj stranici i ulazi u sadržaj.
    if rjesenja_na_kraju:
        redovi.append(f"\\cakicjelina{{}}{{{NASLOV_RJESENJA}}}")
        for naslov_pog, stavke in rjesenja_na_kraju:
            redovi.append(f"\\cakirjesenjanaslov{{{naslov_pog}}}")
            redovi.extend(_blok_rjesenja(stavke, rjesenja))
            redovi.append("")

    return "\n".join(redovi), ukupno_primjera, ukupno_zadataka


def _blok_rjesenja(stavke, nacin) -> list:
    """Retci rješenja, po potrebi u dva stupca.

    Samo konačni odgovori su kratki retci pa stanu u 2 stupca (isti trik kao rjesenja_sekcija
    u Test Builderu, 8.10.2026.); puni postupak ostaje jednostupčan jer zna sadržavati
    tablice/poravnate jednadžbe koje se u uskom stupcu lome."""
    dva_stupca = nacin == RJESENJA_ODGOVOR
    redovi = ["\\begin{multicols}{2}\\small"] if dva_stupca else []
    redovi += [f"\\cakirjesenjeskripte{{{oznaka}}}{{{tekst}}}" for oznaka, tekst in stavke]
    if dva_stupca:
        redovi.append("\\end{multicols}")
    return redovi


# ============================================================
# Grupiranje redaka baze u poglavlja (ista pravila kao PreTeXt skripta iz knjige)
# ============================================================

def _filtriraj_jedinice(redovi, izbor):
    """Kao bp._filtriraj_po_odabiru, ali svjesno SKUPINA: jedinica ostaje ako je u odabiru
    glavni redak ILI bilo koja njezina stavka.

    Zašto: plan na stranici 📘 Skripta nabraja POJEDINAČNE retke baze, pa odabir zna
    sadržavati samo id-eve stavki. Da se gleda isključivo glavni redak, takva bi skupina
    tiho ispala iz skripte."""
    if izbor is None:
        return redovi
    skup = {str(x) for x in izbor}
    izlaz = []
    for r in redovi:
        idovi = {str(r.get("id", ""))} | {str(s.get("id", "")) for s in (r.get("stavke") or [])}
        if idovi & skup:
            izlaz.append(r)
    return izlaz


def grupiraj_po_poglavljima(rows, naslovi_poglavlja=None, redoslijed_poglavlja=None,
                            odabir_poglavlja=None) -> list:
    """Redci baze -> lista poglavlja (bez teorije i formula — njih dodaje stranica).

    NAMJERNO koristi ISTE pipeline funkcije kao PreTeXt skripta iz knjige, da se dvije
    staze ne raziđu u tome ŠTO ulazi u skriptu:
      - bp.parsiraj_poglavlje_iz_izvora           (poglavlje iz izvor_naziv)
      - bp._poglavlje_sort_key_s_redoslijedom     (prirodni poredak + Cakijev ručni)
      - bp._je_primjer_za_skriptu                 (primjer vs. zadatak, uz lokalnu promjenu)
      - bp._filtriraj_po_odabiru                  (pojedinačno označeni redci)
      - get_naslovi_poglavlja / get_odabir_poglavlja (tab Sifrarnik_poglavlja_knjige)
    """
    naslovi_poglavlja = naslovi_poglavlja or {}
    odabir_poglavlja = odabir_poglavlja or {}

    # 1) SKUPINE PRIJE razvrstavanja po poglavljima (6.11.2026.). Redoslijed je bitan: stavka
    #    zna imati prazan `izvor_naziv` (nasljeđuje ga od skupine), pa bi sama završila u
    #    poglavlju „bez naziva", odvojena od svoje skupine. Nakon grupiranja poglavlje se
    #    određuje iz GLAVNOG retka, a stavke putuju s njim.
    jedinice, _upozorenja = skupine_zadataka.grupiraj(list(rows or []))

    po_poglavlju = {}
    for jedinica in jedinice:
        glavni = jedinica["glavni"]
        red = dict(glavni)          # kopija — redci iz Sheeta se ne diraju
        if jedinica["stavke"]:
            # nasljedi(): prazna polja stavke (cjelina, težina, izvor…) popuni iz skupine
            red["stavke"] = [skupine_zadataka.nasljedi(glavni, s) for s in jedinica["stavke"]]
        kljuc = bp.parsiraj_poglavlje_iz_izvora(glavni.get("izvor_naziv", ""))
        po_poglavlju.setdefault(kljuc, []).append(red)

    izlaz = []
    for kljuc in sorted(po_poglavlju,
                        key=lambda p: bp._poglavlje_sort_key_s_redoslijedom(p, redoslijed_poglavlja)):
        odabir = odabir_poglavlja.get(kljuc) or {}
        if odabir.get("ukljuceno") is False:
            continue
        grupa = po_poglavlju[kljuc]
        tipovi = odabir.get("tipovi") or {}
        primjeri = _filtriraj_jedinice(
            [r for r in grupa if bp._je_primjer_za_skriptu(r, tipovi)], odabir.get("primjeri"))
        zadaci = _filtriraj_jedinice(
            [r for r in grupa if not bp._je_primjer_za_skriptu(r, tipovi)], odabir.get("zadaci"))
        if not primjeri and not zadaci:
            continue
        izlaz.append({
            "kljuc": kljuc,
            "oznaka": "",
            "naslov": naslovi_poglavlja.get(kljuc) or kljuc,
            "primjeri": primjeri,
            "zadaci": zadaci,
        })
    return izlaz


def provjeri_latex(poglavlja) -> list:
    """Vraća popis SVIH polja koja bi srušila kompajliranje, kao rječnike:
        {"poglavlje_kljuc", "poglavlje", "vrsta", "id", "polje", "problem", "tekst"}

    4.11./5.11.2026. (Cakijev nalaz „ispisuje jednu po jednu, a može ih biti stotine"):
    provjera prolazi kroz SVE retke SVIH predanih poglavlja i vraća sve nalaze odjednom —
    pozivatelj ih prikazuje kao tablicu, a ne jedan po jedan. Ovo je SAV popis problema koje
    se može naći bez pokretanja LaTeXa; ostale greške pdflatex javlja tek pri kompajliranju
    (i to po jednu, zbog -halt-on-error), pa je zato tu i `preskoci_neispravne` u
    izgradi_tijelo — da jedna pokvarena ćelija ne blokira ispis cijele skripte.

    Što se provjerava i zašto samo to: v. latex_tekst.provjeri_polje."""
    problemi = []
    for pog in poglavlja or []:
        naslov = str(pog.get("naslov") or pog.get("kljuc") or "")
        kljuc = str(pog.get("kljuc") or naslov)
        for vrsta in ("primjeri", "zadaci"):
            for row in pog.get(vrsta) or []:
                zid = str(row.get("id") or "bez id-a")
                polja = [("tekst zadatka", row.get("tekst_zadatka_latex")),
                         ("rješenje", row.get("rjesenje")),
                         ("konačan odgovor", row.get("konacan_odgovor")),
                         ("uputa", row.get("uputa"))]
                for j, opcija in enumerate(_opcije_iz_retka(row)):
                    slovo = lt.SLOVA_OPCIJA[j] if j < len(lt.SLOVA_OPCIJA) else str(j + 1)
                    polja.append((f"opcija {slovo}", opcija))
                # Stavke skupine (a, b, c…) idu u isti ispis pa se moraju i provjeriti —
                # inače bi neparan `$` u stavci srušio build, a tablica ga ne bi pokazala.
                for j, stavka in enumerate(row.get("stavke") or []):
                    oznaka_st = skupine_zadataka.slovo(j)
                    polja += [(f"stavka {oznaka_st} tekst zadatka", stavka.get("tekst_zadatka_latex")),
                              (f"stavka {oznaka_st} rješenje", stavka.get("rjesenje")),
                              (f"stavka {oznaka_st} konačan odgovor", stavka.get("konacan_odgovor"))]
                for naziv_polja, sadrzaj in polja:
                    for opis in lt.provjeri_polje(sadrzaj):
                        problemi.append({
                            "poglavlje_kljuc": kljuc, "poglavlje": naslov,
                            "vrsta": "primjer" if vrsta == "primjeri" else "zadatak",
                            "id": zid, "polje": naziv_polja, "problem": opis,
                            "tekst": str(sadrzaj if sadrzaj is not None else ""),
                        })
        for opis in lt.provjeri_polje(pog.get("teorija")):
            problemi.append({
                "poglavlje_kljuc": kljuc, "poglavlje": naslov, "vrsta": "teorija",
                "id": "(teorija)", "polje": "tekst teorije", "problem": opis,
                "tekst": str(pog.get("teorija") or ""),
            })
    return problemi


def losa_polja_po_retku(problemi) -> dict:
    """{(poglavlje_kljuc, id): {naziv_polja, ...}} iz izlaza provjeri_latex."""
    mapa = {}
    for p in problemi or []:
        mapa.setdefault((p["poglavlje_kljuc"], p["id"]), set()).add(p["polje"])
    return mapa


def sve_slike(poglavlja) -> list:
    """Svi nazivi slika koje skripta treba (bez duplikata, zadržan redoslijed) — stranica ih
    prije kompajliranja skine s Drivea i zapiše u images/."""
    nazivi = []
    for pog in poglavlja or []:
        for vrsta in ("primjeri", "zadaci"):
            for row in pog.get(vrsta) or []:
                for r in [row] + list(row.get("stavke") or []):
                    for x in bp.razdvoji_slike(r.get("slika_putanja")):
                        naziv = os.path.basename(x)
                        if naziv and naziv not in nazivi:
                            nazivi.append(naziv)
    return nazivi
