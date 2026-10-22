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
    "cjelina", "potpoglavlje", "kljucne_rijeci", "biblioteka_izvora", "tezina",
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



# ---------------------------------------------------------------------------
# UVOZ: ravna lista Claudeovih objekata -> jedinice za upis (v2, 10.10.2026.)
# ---------------------------------------------------------------------------
# Claude (vidi EXTRACTION_SYSTEM_PROMPT, točka 1b) vraća RAVNU listu: objekt s
# uloga="skupina", iza njega objekti uloga="stavka" s roditelj_privremeni_broj = privremeni_broj
# skupine; svi ostali su uloga="samostalan" (ili prazno). Ova funkcija to slaže u jedinice
# i ispravlja uobičajene Claudeove pogreške, a NIKAD ne gubi zadatak.

def _uloga_claude(z):
    u = _s(z.get("uloga")).lower()
    return u if u in (ULOGA_SKUPINA, ULOGA_STAVKA) else ULOGA_SAMOSTALAN


def _popuni_prazno_iz(cilj, izvor, polja):
    for p in polja:
        if not _s(cilj.get(p)) and _s(izvor.get(p)):
            cilj[p] = izvor[p]


def pripremi_jedinice(zadaci, log=None):
    """Vraća listu jedinica redoslijedom iz ulaza:
       {"tip": "samostalan", "z": zadatak}
       {"tip": "skupina", "skupina": zadatak, "stavke": [zadatak, ...]}   (uvijek >= 2 stavke)
    Pravila:
      - stavka bez postojeće skupine (roditelj_privremeni_broj ne postoji)  -> samostalan + upozorenje
      - skupina s 0 stavki -> samostalan + upozorenje (njen tekst je samo uvod, pa se označi za provjeru)
      - skupina s 1 stavkom -> spaja se u JEDAN samostalan zadatak (uvod + stavka)
      - stavke dobivaju (kopiraju) cjelinu, potpoglavlje, kategoriju, ključne riječi i težinu od skupine
        ako su prazni - da ostatak aplikacije, koji čita ta polja po retku, radi bez izmjena.
    Ulazni rječnici se ne mijenjaju (radi se na kopijama)."""
    zadaci = [dict(z) for z in zadaci]
    skupine = {}
    for z in zadaci:
        pb = _s(z.get("privremeni_broj"))
        if _uloga_claude(z) == ULOGA_SKUPINA and pb and pb not in skupine:
            skupine[pb] = z
    djeca = {pb: [] for pb in skupine}
    for z in zadaci:
        if _uloga_claude(z) == ULOGA_STAVKA:
            rod = _s(z.get("roditelj_privremeni_broj"))
            if rod in djeca:
                djeca[rod].append(z)

    def upozori(poruka):
        if log:
            log(poruka)

    jedinice = []
    spojene = set()       # id() stavki koje su već spojene sa svojom (jedinom) skupinom
    for z in zadaci:
        if id(z) in spojene:
            continue
        u = _uloga_claude(z)
        pb = _s(z.get("privremeni_broj"))
        if u == ULOGA_SAMOSTALAN:
            jedinice.append({"tip": ULOGA_SAMOSTALAN, "z": z})
        elif u == ULOGA_STAVKA:
            if _s(z.get("roditelj_privremeni_broj")) in djeca:
                continue                                    # obradit će se uz svoju skupinu
            upozori(f"⚠️ Stavka #{pb} nema skupinu (roditelj '{_s(z.get('roditelj_privremeni_broj'))}') - "
                    "upisana kao samostalan zadatak.")
            z["uloga"] = ULOGA_SAMOSTALAN
            z["status_provjere"] = (_s(z.get("status_provjere")) + "; " if _s(z.get("status_provjere")) else "") + \
                "stavka bez skupine - provjeriti uvod zadatka"
            jedinice.append({"tip": ULOGA_SAMOSTALAN, "z": z})
        else:  # skupina
            if skupine.get(pb) is not z:
                z["uloga"] = ULOGA_SAMOSTALAN              # duplikat oznake skupine - ne gubi se
                jedinice.append({"tip": ULOGA_SAMOSTALAN, "z": z})
                continue
            st = djeca[pb]
            if not st:
                upozori(f"⚠️ Skupina #{pb} nema nijednu stavku - upisana kao samostalan zadatak (provjeri).")
                z["uloga"] = ULOGA_SAMOSTALAN
                z["status_provjere"] = (_s(z.get("status_provjere")) + "; " if _s(z.get("status_provjere")) else "") + \
                    "skupina bez stavki - provjeriti"
                jedinice.append({"tip": ULOGA_SAMOSTALAN, "z": z})
            elif len(st) == 1:
                s = st[0]
                upozori(f"ℹ️ Skupina #{pb} ima samo jednu stavku - spojeno u jedan zadatak.")
                _popuni_prazno_iz(s, z, NASLJEDNA_POLJA + ["slika_zadana", "slika_url", "slika_putanja", "vizualni_potencijal"])
                s["tekst_zadatka_latex"] = f"{_s(z.get('tekst_zadatka_latex'))} {_s(s.get('tekst_zadatka_latex'))}".strip()
                s["uloga"] = ULOGA_SAMOSTALAN
                spojene.add(id(s))
                jedinice.append({"tip": ULOGA_SAMOSTALAN, "z": s})
            else:
                for s in st:
                    _popuni_prazno_iz(s, z, NASLJEDNA_POLJA)
                jedinice.append({"tip": ULOGA_SKUPINA, "skupina": z, "stavke": st})
    return jedinice


# ---------------------------------------------------------------------------
# UI POMOĆNE FUNKCIJE (v3, 10.10.2026.) - pregled/uređivanje i Test Builder
# ---------------------------------------------------------------------------

def oznaka_za_popis(row, indeks_stavke=None):
    """Prefiks za popis zadataka u aplikaciji: 📦 za skupinu, '↳ a)' za stavku, '' za ostalo."""
    u = uloga_retka(row)
    if u == ULOGA_SKUPINA:
        return "📦 "
    if u == ULOGA_STAVKA:
        o = _s(row.get("oznaka_stavke"))
        return f"↳ {o} " if o else "↳ "
    return ""


def stavke_skupine(rows, skupina_id):
    """Stavke (redovi) jedne skupine, sortirane po oznaka_stavke."""
    sid = _s(skupina_id)
    st = [r for r in rows if uloga_retka(r) == ULOGA_STAVKA and _s(r.get("roditelj_id")) == sid]
    return sorted(st, key=lambda x: _oznaka_sort(x.get("oznaka_stavke")))


def normalizuj_upit(tekst) -> str:
    """Mala slova bez dijakritika — da „logaritam” nađe i „Logaritamska”."""
    t = _s(tekst).lower()
    for a, b in (("č", "c"), ("ć", "c"), ("š", "s"), ("ž", "z"), ("đ", "d")):
        t = t.replace(a, b)
    return t


def tekst_za_pretragu(redak) -> str:
    r"""Sve po čemu se zadatak smije naći u pretrazi.

    22.10.2026. (Cakijev nalaz „ne mogu naći logaritme iz udžbenika”): prije se tražilo samo
    u tekstu i ključnim riječima — a udžbenički zadaci imaju prazne ključne riječi i u tekstu
    piše `\log`, ne „logaritam”. Zato sada pretraga gleda i cjelinu, potpoglavlje, naziv izvora,
    tip izvora, ID i konačan odgovor.
    """
    dijelovi = [
        redak.get("tekst_zadatka_latex"), redak.get("tekst_zadatka_mathjax"),
        redak.get("kljucne_rijeci"), redak.get("potpoglavlje"), redak.get("cjelina"),
        redak.get("izvor_naziv"), redak.get("izvor_tip"), redak.get("id"),
        redak.get("konacan_odgovor"), redak.get("uputa"),
    ]
    return normalizuj_upit(" ".join(_s(x) for x in dijelovi if _s(x)))


def upit_odgovara(tekst: str, upit) -> bool:
    """Tolerantna pretraga: svaka riječ upita mora se naći, a za duge riječi je dovoljno
    prvih 6 znakova — tako „logaritmi” nađe „logaritamska”, a „jednadzbe” nađe „jednadžba”."""
    hay = tekst if isinstance(tekst, str) else ""
    for rijec in normalizuj_upit(upit).split():
        if rijec in hay:
            continue
        if len(rijec) >= 6 and rijec[:6] in hay:
            continue
        return False
    return True


def jedinica_odgovara(j, f_cjelina=(), f_potpoglavlje=(), f_tezina=(), upit="", f_biblioteka=()):
    """Filter Test Buildera na razini JEDINICE (samostalan ili skupina+stavke).
    Cjelina/potpoglavlje/težina: prolazi ako ih ima skupina ILI bilo koja stavka.
    Tekst: traži se u tekstu i ključnim riječima skupine i svih stavki (pa se skupina
    nađe i kad se traži izraz iz podzadatka)."""
    redovi = [j["glavni"]] + list(j.get("stavke", []))

    def bilo_koji(polje, dopusteno):
        return any(_s(r.get(polje)) in dopusteno for r in redovi)

    if f_cjelina and not bilo_koji("cjelina", f_cjelina):
        return False
    if f_potpoglavlje and not bilo_koji("potpoglavlje", f_potpoglavlje):
        return False
    if f_tezina and not bilo_koji("tezina", f_tezina):
        return False
    if f_biblioteka and not bilo_koji("biblioteka_izvora", f_biblioteka):
        return False
    if upit:
        # 22.10.2026.: tolerantna pretraga (v. upit_odgovara) po SVIM poljima, ne samo tekstu.
        if not any(upit_odgovara(tekst_za_pretragu(r), upit) for r in redovi):
            return False
    return True


def spoji_u_samostalan(skupina, stavka):
    """Jedna odabrana stavka + uvod skupine -> običan samostalan redak (uvod + stavka),
    s poljima stavke (rješenje, bodovi...) i nasljeđenom klasifikacijom/slikom skupine."""
    out = nasljedi(skupina, stavka)
    for p in ("slika_zadana", "slika_url", "slika_putanja"):
        if not _s(out.get(p)) and _s(skupina.get(p)):
            out[p] = skupina[p]
    out["tekst_zadatka_latex"] = puni_tekst(skupina, stavka)
    out["uloga"] = ULOGA_SAMOSTALAN
    return out


def stavke_za_unos(stavke):
    """Stavke -> lagani JSON-siguran oblik za Test Builder (session_state + nacrt u Sheetu)."""
    return [{
        "id": _s(s.get("id")),
        "oznaka_stavke": _s(s.get("oznaka_stavke")),
        "tekst_zadatka_latex": _s(s.get("tekst_zadatka_latex")),
        "rjesenje": _s(s.get("rjesenje")),
        "konacan_odgovor": _s(s.get("konacan_odgovor")),
    } for s in stavke]


def zbroji_bodove(stavke):
    """Zbroj max_bodovi stavki kao tekst ('' ako nijedna nema broj). Decimalni zarez dopušten."""
    ukupno, ima = 0.0, False
    for s in stavke:
        v = _s(s.get("max_bodovi")).replace(",", ".")
        if v:
            try:
                ukupno += float(v)
                ima = True
            except ValueError:
                pass
    if not ima:
        return ""
    return str(int(ukupno)) if ukupno == int(ukupno) else str(ukupno).replace(".", ",")


def izgradi_rjesenja_blok(stavke, escape=lambda s: s):
    """(rjesenje_tex, konacan_tex) za skupinu u sekciji 'Rješenja': po stavci a), b), c)...
    Oznake su prave LaTeX naredbe pa se dodaju NAKON escapiranja sadržaja."""
    dijelovi, konacni, ima_nesto = [], [], False
    for i, s in enumerate(stavke):
        o = f"\\textbf{{{slovo(i)}}}"
        rj, ko = _s(s.get("rjesenje")), _s(s.get("konacan_odgovor"))
        if rj or ko:
            ima_nesto = True
        dijelovi.append(f"{o}~{escape(rj)}" if rj else f"{o}~\\textit{{---}}")
        if ko:
            konacni.append(f"{o}~{escape(ko)}")
    if not ima_nesto:
        return "\\textit{Rješenje se dodaje naknadno.}", ""
    rjesenje_tex = "\\par\\noindent ".join(dijelovi) if any(_s(s.get("rjesenje")) for s in stavke) \
        else "\\textit{Puni postupak nije unesen u bazu.}"
    return rjesenje_tex, "\\quad ".join(konacni)


def sve_stavke_dolari_neuparene(stavke, broj_dolara):
    """[(oznaka, polje, sadrzaj)] za stavke s neparnim brojem $ (isti test kao za obične zadatke)."""
    out = []
    for i, s in enumerate(stavke):
        for polje, kljuc in (("tekst", "tekst_zadatka_latex"), ("rješenje", "rjesenje"), ("konačan odgovor", "konacan_odgovor")):
            if broj_dolara(s.get(kljuc, "")) % 2 != 0:
                out.append((slovo(i), polje, s.get(kljuc, "")))
    return out


def azuriranja_biblioteke(redovi, odabrani_ids, biblioteka, col_letter, ukljuci_stavke=True, prepisi=False):
    """Grupno dodjeljivanje biblioteke izvora (zbirke). `redovi` = rječnici redoka tablice 'Zadaci' po
    redoslijedu u Sheetu (prvi je redak 2). Vraća (azuriranja, info) za ws.batch_update.
      ukljuci_stavke: odabrana SKUPINA povlači sa sobom i sve svoje stavke.
      prepisi: False = zadaci koji VEĆ imaju DRUGU biblioteku se preskaču (ne prepisuju se tiho).
    biblioteka == '' briše vrijednost (isti mehanizam)."""
    biblioteka = _s(biblioteka)
    ids = {_s(i) for i in odabrani_ids if _s(i)}
    dodano_stavki = 0
    if ukljuci_stavke:
        skupine = {_s(r.get("id")) for r in redovi if uloga_retka(r) == ULOGA_SKUPINA and _s(r.get("id")) in ids}
        for r in redovi:
            if uloga_retka(r) == ULOGA_STAVKA and _s(r.get("roditelj_id")) in skupine and _s(r.get("id")) not in ids:
                ids.add(_s(r.get("id")))
                dodano_stavki += 1
    slovo_stupca = col_letter("biblioteka_izvora")
    azur, vec, preskoceno = [], 0, []
    for broj, r in enumerate(redovi, start=2):
        rid = _s(r.get("id"))
        if rid not in ids:
            continue
        trenutna = _s(r.get("biblioteka_izvora"))
        if trenutna == biblioteka:
            vec += 1
        elif trenutna and not prepisi:
            preskoceno.append((rid, trenutna))
        else:
            azur.append({"range": f"{slovo_stupca}{broj}", "values": [[biblioteka]]})
    return azur, {"odabrano": len(ids), "dodano_stavki": dodano_stavki, "vec_ima": vec,
                  "preskoceno": preskoceno, "za_upis": len(azur)}
