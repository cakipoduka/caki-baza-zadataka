# -*- coding: utf-8 -*-
"""
skupine_zadataka.py - PRIJEDLOG v1 (10.10.2026.), NIJE spojeno s živim kodom.

Dvije razine zadataka u ISTOJ tablici 'Zadaci':
  - skupina  : zajednički uvod ("Izračunaj:", "Koliko znamenki ima broj:")
  - stavka   : jedan podzadatak (1), 2), 3)...), vezan na skupinu preko roditelj_id
  - samostalan (prazan stupac 'uloga' = SVI POSTOJEĆI REDCI, ništa se ne mijenja)

Modul je NAMJERNO samostalan (nema gspread/anthropic/streamlit uvoza), da se može
testirati bez Googlea. Pomoćne funkcije iz pipelinea (_pretext_text, ...) prosljeđuju
se kao argumenti pri integraciji.
"""
import re

NOVI_STUPCI = ["uloga", "roditelj_id", "oznaka_stavke"]   # dodati na KRAJ ZADACI_HEADERS

ULOGA_SAMOSTALAN = "samostalan"
ULOGA_SKUPINA = "skupina"
ULOGA_STAVKA = "stavka"

# Stavka nasljeđuje od skupine ako joj je polje prazno (npr. cjelina, potpoglavlje).
NASLJEDNA_POLJA = [
    "izvor_tip", "izvor_naziv", "godina", "razina", "razred", "kategorija",
    "cjelina", "potpoglavlje", "biblioteka_izvora", "tezina",
]


def _s(v):
    return "" if v is None else str(v).strip()


def uloga_retka(row):
    u = _s(row.get("uloga")).lower()
    return u if u in (ULOGA_SKUPINA, ULOGA_STAVKA) else ULOGA_SAMOSTALAN


def _oznaka_sort(v):
    try:
        return (0, float(_s(v).replace(",", ".")), "")
    except ValueError:
        return (1, 0.0, _s(v))


def grupiraj(rows):
    """Vraća (jedinice, upozorenja).
    jedinica = {"tip": "samostalan"|"skupina", "glavni": red, "stavke": [redovi...]}
    Redoslijed jedinica = redoslijed prvog pojavljivanja u tablici. Stavke su sortirane
    po oznaka_stavke. Stavka čiji roditelj_id ne postoji NE nestaje: postaje samostalna
    jedinica + upozorenje (da se ne izgubi tiho)."""
    upozorenja = []
    skupine = {_s(r.get("id")): r for r in rows if uloga_retka(r) == ULOGA_SKUPINA}
    djeca = {}
    for r in rows:
        if uloga_retka(r) == ULOGA_STAVKA:
            djeca.setdefault(_s(r.get("roditelj_id")), []).append(r)

    jedinice = []
    for r in rows:
        u = uloga_retka(r)
        if u == ULOGA_SAMOSTALAN:
            jedinice.append({"tip": ULOGA_SAMOSTALAN, "glavni": r, "stavke": []})
        elif u == ULOGA_SKUPINA:
            st = sorted(djeca.get(_s(r.get("id")), []), key=lambda x: _oznaka_sort(x.get("oznaka_stavke")))
            if not st:
                upozorenja.append(f"Skupina {_s(r.get('id'))} nema nijednu stavku.")
            jedinice.append({"tip": ULOGA_SKUPINA, "glavni": r, "stavke": st})
        else:  # stavka
            if _s(r.get("roditelj_id")) not in skupine:
                upozorenja.append(
                    f"Stavka {_s(r.get('id'))}: roditelj_id '{_s(r.get('roditelj_id'))}' ne postoji "
                    "- prikazana kao samostalan zadatak.")
                jedinice.append({"tip": ULOGA_SAMOSTALAN, "glavni": r, "stavke": []})
    return jedinice, upozorenja


def nasljedi(skupina, stavka):
    """Kopija stavke u kojoj su prazna nasljedna polja popunjena iz skupine."""
    out = dict(stavka)
    for p in NASLJEDNA_POLJA:
        if not _s(out.get(p)):
            out[p] = skupina.get(p, "")
    return out


def puni_tekst(skupina, stavka):
    """Uvod + stavka kao jedan običan tekst - za pretragu i za sve dijelove koda koji
    još ne znaju za skupine."""
    return f"{_s(skupina.get('tekst_zadatka_latex'))} {_s(stavka.get('tekst_zadatka_latex'))}".strip()


def slovo(i):
    """0 -> 'a)', 1 -> 'b)' ... (na radnom materijalu numeracija kreće ispočetka,
    neovisno o knjizi)."""
    return (chr(ord("a") + i) if i < 26 else str(i + 1)) + ")"


def izgradi_stavke_blok(stavke, escape=lambda s: s, prag_znakova=45):
    """LaTeX blok za Test Builder - isti obrazac kao izgradi_opcije_blok(): dodaje se
    NAKON escapiranja uvoda, jer sadrži prave LaTeX naredbe. Kratke stavke idu u jedan
    redak, duge svaka u svoj redak."""
    tekstovi = [escape(_s(s.get("tekst_zadatka_latex"))) for s in stavke]
    oznake = [f"\\textbf{{{slovo(i)}}}" for i in range(len(tekstovi))]
    stavke_tex = [f"{o}~{t}" for o, t in zip(oznake, tekstovi)]
    if max((len(_s(s.get("tekst_zadatka_latex"))) for s in stavke), default=0) <= prag_znakova:
        return "\\par\\noindent " + "\\qquad ".join(stavke_tex)
    return "".join(f"\\par\\noindent\\hspace*{{1em}}{x}" for x in stavke_tex)


def build_skupina_pretext(skupina, stavke, pt_text, pt_math_or_text, sanitize_id, indent="      "):
    """<exercise> s <introduction> i <task> po stavci (PreTeXt-ova ugrađena struktura za
    podzadatke). NIJE još provjereno PreTeXt-om na stvarnom buildu - prvo probati na jednoj
    skupini. Pomoćne funkcije dolaze iz baza_zadataka_pipeline.py."""
    zid = sanitize_id(f"zad-{_s(skupina.get('id'))}")
    L = [f'{indent}<exercise xml:id="{zid}">']
    uvod = _s(skupina.get("tekst_zadatka_latex"))
    if uvod:
        L += [f"{indent}  <introduction>", f"{indent}    <p>{pt_text(uvod)}</p>", f"{indent}  </introduction>"]
    for s in stavke:
        tid = sanitize_id(f"zad-{_s(s.get('id'))}")
        L.append(f'{indent}  <task xml:id="{tid}">')
        L += [f"{indent}    <statement>", f"{indent}      <p>{pt_text(_s(s.get('tekst_zadatka_latex')))}</p>",
              f"{indent}    </statement>"]
        rj, ko = _s(s.get("rjesenje")), _s(s.get("konacan_odgovor"))
        if rj or ko:
            L.append(f"{indent}    <solution>")
            if ko:
                L.append(f"{indent}      <p>Odgovor: {pt_math_or_text(ko)}</p>")
            if rj:
                L.append(f"{indent}      <p>{pt_math_or_text(rj)}</p>")
            L.append(f"{indent}    </solution>")
        L.append(f"{indent}  </task>")
    L.append(f"{indent}</exercise>")
    return L


def _norm_izraz(t):
    t = _s(t).replace("$", "")
    t = re.sub(r"\\cdot|\\times|·|\\left|\\right|\\,|\;|\s+", "", t)
    return t.lower()


def nadji_moguce_duplikate(rows):
    """Grupe ID-ova (>=2) čiji je IZRAZ isti (uvod se namjerno ne uspoređuje: 'Pomnoži:' i
    'Izračunaj:' uz isti izraz je i dalje isti zadatak). Samo PRIJEDLOG za ljudsku provjeru,
    ništa se ne spaja automatski. Skupine se ne uspoređuju (njihov tekst je samo uvod)."""
    po_izrazu = {}
    for r in rows:
        if uloga_retka(r) == ULOGA_SKUPINA:
            continue
        k = _norm_izraz(r.get("tekst_zadatka_latex"))
        if k:
            po_izrazu.setdefault(k, []).append(_s(r.get("id")))
    return [ids for ids in po_izrazu.values() if len(ids) > 1]
