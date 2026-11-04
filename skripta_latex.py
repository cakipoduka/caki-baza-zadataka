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
import teorija_markup

# Naslovi odjeljaka unutar poglavlja — na jednom mjestu, da ih Caki mijenja bez
# diranja logike. („Primjeri za rad na satu" je bio naziv u PreTeXt verziji od
# 30.10.2026.; ovdje su kraći nazivi jer su primjeri i zadaci sada i vizualno
# odvojeni razdjelnikom.)
NASLOV_PRIMJERI = "Primjeri"
NASLOV_ZADACI = "Zadaci"
NASLOV_RJESENJA = "Rješenja"

# Načini ispisa rješenja na kraju poglavlja
RJESENJA_POSTUPAK = "postupak"   # puni postupak iz polja `rjesenje` (pad na konačan odgovor)
RJESENJA_ODGOVOR = "odgovor"     # samo konačan odgovor (kompaktno, 2 stupca)
RJESENJA_BEZ = "bez"             # bez rješenja (čista učenička vježbenica)
RJESENJA_NACINI = (RJESENJA_POSTUPAK, RJESENJA_ODGOVOR, RJESENJA_BEZ)


# ============================================================
# Pomoćno: tekst jednog zadatka/primjera -> LaTeX
# ============================================================

def _slike_csv(row, slike_dostupne) -> str:
    """'a.png | b.png' iz baze -> 'images/a.png,images/b.png' za \\cakislike (caki-style.sty
    ih slaže jednu uz drugu, v. §\\cakislike ondje).

    slike_dostupne: skup naziva slika koje su STVARNO skinute na disk. Slika koje nema se
    PRESKAČE — referenciranje nepostojeće datoteke ruši cijelo kompajliranje s
    "File not found" (ista zaštita kao u Test Builderu)."""
    nazivi = [os.path.basename(x) for x in bp.razdvoji_slike(row.get("slika_putanja"))]
    if slike_dostupne is not None:
        nazivi = [x for x in nazivi if x in slike_dostupne]
    return ",".join(f"images/{x}" for x in nazivi)


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


def tekst_stavke(row, slike_dostupne=None, s_oznakom_tezine=True) -> tuple:
    """Gradi (tekst_tex, slike_csv) za JEDAN redak baze — zajednička jezgra za primjer i
    zadatak (isti obrazac kao bp._build_statement_hint_solution_video za PreTeXt).

    s_oznakom_tezine: prefiks '[matura 2010, S] ' ispred teksta. Oznake L/S/T Caki je
    izričito tražio zadržati (4.11.2026.) — funkcija se NE duplicira, nego se poziva
    bp._oznaka_izvor_tezina, pa pravilo („zbirka" se ne ispisuje, matura dobiva godinu…)
    ostaje na JEDNOM mjestu za obje staze."""
    raw = str(row.get("tekst_zadatka_latex") or "")
    opcije = _opcije_iz_retka(row)
    if opcije:
        # 30.10.2026.: opcije se ispisuju JEDNOM (ispod teksta), pa ih makni iz teksta
        # pitanja ako ih je AI pri uvozu ostavio i tamo.
        raw = bp._bez_opcija_u_tekstu(raw)

    oznaka = bp._oznaka_izvor_tezina(row) if s_oznakom_tezine else ""
    tekst = lt.escape_outside_math(oznaka + raw.strip(), cuvaj_okoline=True)

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


def rjesenje_stavke(row, nacin=RJESENJA_POSTUPAK) -> str:
    """Tekst rješenja za blok na kraju poglavlja. RJESENJA_POSTUPAK uzima puni postupak iz
    polja `rjesenje`, a ako ga nema pada na `konacan_odgovor` (bolje konačan odgovor nego
    prazan redak). RJESENJA_ODGOVOR uzima SAMO konačan odgovor.

    cuvaj_okoline=True: polje `rjesenje` zna sadržavati \\begin{tabular}/\\begin{align} —
    v. objašnjenje u latex_tekst.escape_outside_math."""
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
                   slike_dostupne=None) -> tuple:
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

    Vraća (tijelo_tex, broj_primjera, broj_zadataka).

    NUMERIRANJE je ovdje, u Pythonu (ne LaTeX brojačima) — v. obrazloženje u
    pages/caki-skripta.sty: rješenja na kraju poglavlja moraju nositi TOČNO iste oznake
    kao zadaci."""
    if rjesenja not in RJESENJA_NACINI:
        raise ValueError(f"rjesenja mora biti jedno od {RJESENJA_NACINI}, dobiveno: {rjesenja!r}")

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
        naslov = lt.escape_outside_math(str(pog.get("naslov") or "").strip())
        oznaka = lt.escape_outside_math(str(pog.get("oznaka") or "").strip())
        redovi.append(f"\\cakicjelina{{{oznaka}}}{{{naslov}}}")
        # Brojevi zadataka moraju pratiti oznaku cjeline: ako cjelina nosi "3.1", zadatak je
        # "3.1.2.", a ne "1.2." (nalaz s probnog PDF-a 4.11.2026. - naslov je pisao 3.2, a
        # zadatak 2.1, što zbunjuje). Bez oznake se koristi redni broj cjeline u skripti.
        broj = oznaka or str(k)

        blok = teorija_blok(pog.get("teorija"), verzija=verzija)
        if blok:
            redovi.append(blok)
        blok = formule_blok(pog.get("formule"), pog.get("formule_rucno"))
        if blok:
            redovi.append(blok)

        if primjeri:
            redovi.append(f"\\cakipodnaslovskripte{{{NASLOV_PRIMJERI}}}")
            for n, row in enumerate(primjeri, start=1):
                tekst, slike = tekst_stavke(row, slike_dostupne)
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
                tekst, slike = tekst_stavke(row, slike_dostupne)
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
                    if odgovor:
                        stavke.append((f"Primjer {broj}.{n}.",
                                       lt.escape_outside_math(odgovor, cuvaj_okoline=True)))
            for n, row in enumerate(zadaci, start=1):
                stavke.append((f"{broj}.{n}.", rjesenje_stavke(row, rjesenja)))

            if stavke:
                redovi.append(f"\\cakirjesenjanaslov{{{NASLOV_RJESENJA} \\textendash{{}} {naslov}}}")
                # Samo konačni odgovori su kratki retci pa stanu u 2 stupca (isti trik kao
                # rjesenja_sekcija u Test Builderu, 8.10.2026.); puni postupak ostaje
                # jednostupčan jer zna sadržavati tablice/poravnate jednadžbe koje se u
                # uskom stupcu lome.
                dva_stupca = rjesenja == RJESENJA_ODGOVOR
                if dva_stupca:
                    redovi.append("\\begin{multicols}{2}\\small")
                for oznaka_st, tekst_st in stavke:
                    redovi.append(f"\\cakirjesenjeskripte{{{oznaka_st}}}{{{tekst_st}}}")
                if dva_stupca:
                    redovi.append("\\end{multicols}")
                redovi.append("")

    return "\n".join(redovi), ukupno_primjera, ukupno_zadataka


# ============================================================
# Grupiranje redaka baze u poglavlja (ista pravila kao PreTeXt skripta iz knjige)
# ============================================================

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

    po_poglavlju = {}
    for row in rows or []:
        kljuc = bp.parsiraj_poglavlje_iz_izvora(row.get("izvor_naziv", ""))
        po_poglavlju.setdefault(kljuc, []).append(row)

    izlaz = []
    for kljuc in sorted(po_poglavlju,
                        key=lambda p: bp._poglavlje_sort_key_s_redoslijedom(p, redoslijed_poglavlja)):
        odabir = odabir_poglavlja.get(kljuc) or {}
        if odabir.get("ukljuceno") is False:
            continue
        grupa = po_poglavlju[kljuc]
        tipovi = odabir.get("tipovi") or {}
        primjeri = bp._filtriraj_po_odabiru(
            [r for r in grupa if bp._je_primjer_za_skriptu(r, tipovi)], odabir.get("primjeri"))
        zadaci = bp._filtriraj_po_odabiru(
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


def provjeri_neuparene_dolare(poglavlja) -> list:
    """Vraća [(poglavlje, oznaka_retka, polje, tekst)] za svaki redak gdje BILO KOJE polje
    koje ide u LaTeX ima neparan broj '$' znakova — NAJČEŠĆI uzrok pucanja kompajliranja
    (ista blokirajuća provjera kao u Test Builderu, prije generiranja)."""
    problemi = []
    for pog in poglavlja or []:
        naslov = str(pog.get("naslov") or pog.get("kljuc") or "")
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
                for naziv_polja, sadrzaj in polja:
                    if lt.broj_dolara(sadrzaj) % 2 != 0:
                        problemi.append((naslov, zid, naziv_polja, str(sadrzaj)))
        if lt.broj_dolara(pog.get("teorija")) % 2 != 0:
            problemi.append((naslov, "teorija", "tekst teorije", str(pog.get("teorija") or "")))
    return problemi


def sve_slike(poglavlja) -> list:
    """Svi nazivi slika koje skripta treba (bez duplikata, zadržan redoslijed) — stranica ih
    prije kompajliranja skine s Drivea i zapiše u images/."""
    nazivi = []
    for pog in poglavlja or []:
        for vrsta in ("primjeri", "zadaci"):
            for row in pog.get(vrsta) or []:
                for x in bp.razdvoji_slike(row.get("slika_putanja")):
                    naziv = os.path.basename(x)
                    if naziv and naziv not in nazivi:
                        nazivi.append(naziv)
    return nazivi
