"""CAKI — radnik_poslovi.py  (22.10.2026.)

POPIS POSLOVA koje `radnik.py` zna odraditi. Svaki posao je mali rječnik s 4 funkcije:

    predlozi(redak, sheet=None)  -> {"polja": {...}, "novi_redci": [...], "log": [...]} ili None
    vec_obradjeno(redak)         -> bool   (preskoči ako je već obrađeno)
    provjeri(redak, promjene)    -> bool   (tvrda provjera PRIJE upisa; False = ne diraj)
    naziv                        -> str

Dodavanje novog posla (kratki odgovori, prijevodi, kontrole) = ~100–150 linija ovdje; radnik,
stanje, log i undo ostaju isti. AI, ako ga posao koristi, dobiva se kao funkcija `pozovi` — isti
obrazac kao `raspodjela_cjelina.py`, pa testovi rade bez mreže.
"""
from __future__ import annotations

import re

import podjela_zadataka as pz


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _dodaj_napomenu(tekst: str, napomena: str) -> str:
    t = _s(tekst)
    return f"{t}; {napomena}" if t else napomena


def _redak_stavke(redak: dict, oznaka: str, tekst: str, rjesenje: str, odgovor: str,
                  bodovi, roditelj_id: str, napomena: str = "") -> dict:
    """Novi redak stavke: kopija roditeljevih podataka + vlastiti tekst, rješenje i oznaka."""
    novi = dict(redak)
    novi.update({
        "id": pz.id_stavke(roditelj_id, oznaka),
        "tekst_zadatka_latex": tekst,
        "tekst_zadatka_mathjax": tekst.replace("\\\\", "<br>"),
        "rjesenje": rjesenje,
        "rjesenje_status": "sluzbeno" if rjesenje else "nedostaje",
        "tip_rjesenja_izvor": _s(redak.get("tip_rjesenja_izvor")) if rjesenje else "",
        "konacan_odgovor": odgovor,
        "max_bodovi": "" if not bodovi else (f"{bodovi:g}"),
        "uloga": "stavka",
        "roditelj_id": roditelj_id,
        "oznaka_stavke": oznaka,
        # slika ostaje na skupini (uvodu) - vidi napomenu u podjeli
        "slika_zadana": "ne",
        "slika_putanja": "",
        "slika_rjesenje_putanja": "",
        "status_provjere": _dodaj_napomenu(redak.get("status_provjere"), napomena) if napomena
                           else _s(redak.get("status_provjere")),
    })
    return novi


# ---------------------------------------------------------------------------------------------
# POSAO: cijepanje zadatka na podpitanja (deterministički)
# ---------------------------------------------------------------------------------------------

def _predlozi_cijepanje(redak: dict, sheet=None):
    p = pz.podijeli(redak)
    if not p:
        return None
    roditelj_id = p["id"]
    uvod = p["uvod"]
    polja = {
        "uloga": "skupina",
        "tekst_zadatka_latex": uvod,
        "tekst_zadatka_mathjax": uvod.replace("\\\\", "<br>"),
        # 22.10.2026.: rješenje i konačni odgovor NE brišu se s roditelja (prvi pravi prolaz je
        # pokazao da se time gubi podatak, npr. "19.7907 km" kod B2010_jesenski_021). Ostaju na
        # skupini kao zapis; stavke nose svoje dijelove, a Test Builder rješenje skupine ionako
        # ne prikazuje (dodaj_jedinicu ga čisti u kopiji testa).
        "status_provjere": _dodaj_napomenu(
            redak.get("status_provjere"),
            "RAZDVOJENO: " + ", ".join(f"{o})" for o in p["oznake"])
            + ("; RJESENJE: cijelo ostaje na skupini" if _s(redak.get("rjesenje")) else ""),
        ),
    }
    novi_redci = [_redak_stavke(redak, s["oznaka"], s["tekst"], s["rjesenje"],
                                s["konacan_odgovor"], s["max_bodovi"], roditelj_id,
                                napomena=s.get("napomena", ""))
                  for s in p["stavke"]]
    log = [{"id": roditelj_id, "polje": k, "staro": _s(redak.get(k)), "novo": _s(v)}
           for k, v in polja.items()]
    log += [{"id": r["id"], "polje": "+redak", "staro": "", "novo": ""} for r in novi_redci]
    return {"polja": polja, "novi_redci": novi_redci, "log": log}


def _vec_obradjeno_cijepanje(redak: dict) -> bool:
    return _s(redak.get("uloga")).lower() in ("skupina", "stavka") or bool(_s(redak.get("roditelj_id")))


def _provjeri_cijepanje(redak: dict, promjene: dict) -> bool:
    """Tvrda provjera prije upisa: stavke imaju tekst, ID-evi su novi, bodovi se zbrajaju."""
    stavke = promjene["novi_redci"]
    if len(stavke) < 2:
        return False
    if any(not _s(s.get("tekst_zadatka_latex")) for s in stavke):
        return False
    if any(_s(s.get("id")) == _s(redak.get("id")) for s in stavke):
        return False
    try:
        ukupno = float(_s(redak.get("max_bodovi")).replace(",", ".") or 0)
    except ValueError:
        ukupno = 0.0
    if ukupno:
        try:
            zbroj = sum(float(_s(s.get("max_bodovi")).replace(",", ".") or 0) for s in stavke)
        except ValueError:
            return False
        if abs(zbroj - ukupno) > 0.01:
            return False
    return True




# ---------------------------------------------------------------------------------------------
# POSAO: cijepanje uz AI (samo za zadatke koje deterministički postupak NE može razdvojiti)
# ---------------------------------------------------------------------------------------------
# Pravilo: AI smije SAMO odlučiti GDJE se reže i koji dio rješenja pripada kojem dijelu.
# Tekst mora biti doslovno prepisan (provjerava se), a svaki dio rješenja mora postojati u
# izvornom rješenju. Ako provjera ne prođe — predlog se ODBIJA i ništa se ne upisuje.

AI_SISTEM = """Ti si pomoćnik koji CIJEPA zadatak s više podpitanja na dijelove.
Vraćaš ISKLJUČIVO JSON objekt, bez ikakvog teksta prije ili poslije.

PRAVILA (obavezna):
1. Tekst svakog dijela mora biti DOSLOVNO prepisan iz zadanog teksta zadatka — bez prepričavanja,
   bez ispravljanja, bez dodavanja i bez izmišljanja. LaTeX ostavlja netaknut.
2. "uvod" je dio teksta PRIJE prve oznake (zajednički kontekst). Ako ga nema, stavi "".
3. "oznaka" je oznaka iz izvornog teksta (npr. "a", "b" ili "1", "2").
4. "rjesenje" je SAMO dio iz zadanog rješenja koji pripada tom dijelu; ako tog dijela u rješenju
   nema, stavi "". Nikad ne izmišljaj rješenje.
5. "konacan_odgovor" stavi samo ako je u rješenju očito naveden konačni odgovor tog dijela;
   inače "".

Shema: {"uvod": "...", "dijelovi": [{"oznaka": "a", "tekst": "...", "rjesenje": "...", "konacan_odgovor": ""}]}"""


def _norm_za_usporedbu(tekst: str) -> str:
    """Isto pravilo kao u podjela_zadataka.norm: slova/brojke/formule, bez oznaka i praznina."""
    t = _s(tekst).lower()
    t = t.replace("\\newline", "").replace("\\\\", "").replace("<br>", "")
    t = t.replace(")", "").replace("\\", "")
    return re.sub(r"\s+", "", t)


def _pozovi_ai(sistem: str, korisnik: str, model: str) -> str:
    """Pozovi model preko REST-a (bez SDK-a, da radnik ne treba nove pakete).

    Claude: POST /v1/messages (ANTHROPIC_API_KEY). DeepSeek: OpenAI obrazac (DEEPSEEK_API_KEY).
    Vraća tekst odgovora; baca iznimku ako nema ključa ili API vrati grešku.
    """
    import os

    import requests

    if str(model).lower().startswith("deepseek"):
        kljuc = os.environ.get("DEEPSEEK_API_KEY", "")
        if not kljuc:
            raise RuntimeError("nema DEEPSEEK_API_KEY u okolini")
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {kljuc}"},
            json={"model": model, "max_tokens": 4000, "temperature": 0.1,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": sistem},
                               {"role": "user", "content": korisnik}]},
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]

    kljuc = os.environ.get("ANTHROPIC_API_KEY", "")
    if not kljuc:
        raise RuntimeError("nema ANTHROPIC_API_KEY u okolini")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": kljuc, "anthropic-version": "2023-06-01"},
        # BEZ `temperature` i s ISKLJUČENIM razmišljanjem: Claude Sonnet 5 po defaultu uključi
        # "adaptive thinking", a Anthropic tada odbija temperature != 1 (400). Isto radi i app
        # u `extract_zadaci_with_claude` (thinking disabled), pa je i ovdje tako.
        json={"model": model, "max_tokens": 4000, "thinking": {"type": "disabled"},
              "system": sistem, "messages": [{"role": "user", "content": korisnik}]},
        timeout=120,
    )
    if r.status_code >= 400:
        # Bez ovoga log kaže samo "HTTPError" i ne zna se je li ključ, model ili oblik zahtjeva.
        raise RuntimeError(f"Claude HTTP {r.status_code} (model {model}): {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


def _json_iz_odgovora(tekst: str):
    import json

    t = re.sub(r"^```(?:json)?", "", _s(tekst)).strip()
    t = re.sub(r"```$", "", t).strip()
    pocetak = t.find("{")
    if pocetak == -1:
        return None
    try:
        return json.loads(t[pocetak:])
    except ValueError:
        return None


def _ocisti_ai_podjelu(redak: dict, podaci: dict):
    """Provjeri AI predlog PRIJE ijednog upisa. Vraća (uvod, dijelovi) ili None.

    Tvrde provjere (AI ne smije izmisliti):
      - uvod + svi dijelovi MORAJU dati izvorni tekst (normalizirano) — inače odbij,
      - svaki dio rješenja MORA biti dio izvornog rješenja — inače odbij,
      - barem 2 dijela, svaki s tekstom, oznake jedinstvene.
    """
    if not isinstance(podaci, dict):
        return None
    tekst = _s(redak.get("tekst_zadatka_latex"))
    rjesenje = _s(redak.get("rjesenje"))
    uvod = _s(podaci.get("uvod"))
    dijelovi = podaci.get("dijelovi")
    if not isinstance(dijelovi, list) or len(dijelovi) < 2:
        return None

    ocisceni = []
    oznake = set()
    for d in dijelovi:
        if not isinstance(d, dict):
            return None
        oznaka = _s(d.get("oznaka"))
        deo_teksta = _s(d.get("tekst"))
        deo_rjesenja = _s(d.get("rjesenje"))
        odgovor = _s(d.get("konacan_odgovor"))
        if not oznaka or not deo_teksta or oznaka in oznake:
            return None
        oznake.add(oznaka)
        if deo_rjesenja and _norm_za_usporedbu(deo_rjesenja) not in _norm_za_usporedbu(rjesenje):
            return None                      # izmišljeno rješenje - odbij
        if odgovor and (not deo_rjesenja
                        or _norm_za_usporedbu(odgovor) not in _norm_za_usporedbu(deo_rjesenja)):
            # kratak odgovor mora biti u rjesenju TOG dijela (ne bilo gdje u cijelom rjesenju -
            # inace "42" slucajno prode jer je dio nekog veceg broja)
            odgovor = ""
        ocisceni.append({"oznaka": oznaka, "tekst": deo_teksta, "rjesenje": deo_rjesenja,
                         "konacan_odgovor": odgovor})

    # doslovnost: uvod + oznake + dijelovi moraju dati izvorni tekst (oznaka je u izvorniku
    # dio teksta kao "a)" — zato se u usporedbu uključuje i oznaka, bez zagrade)
    sastavljeno = _norm_za_usporedbu(uvod) + "".join(
        _norm_za_usporedbu(d["oznaka"]) + _norm_za_usporedbu(d["tekst"]) for d in ocisceni)
    if sastavljeno != _norm_za_usporedbu(tekst):
        return None
    return uvod, ocisceni


def _predlozi_cijepanje_ai(redak: dict, sheet=None):
    """Kao determinističko cijepanje, ali podjelu predlaže AI (samo kad deterministički ne ide)."""
    if pz.podijeli(redak) is not None:
        return None                                   # deterministički zna - ne troši AI
    import os

    model = _s(os.environ.get("AI_MODEL")) or "claude-sonnet-5"
    korisnik = (
        "TEKST ZADATKA:\n" + _s(redak.get("tekst_zadatka_latex"))
        + "\n\nRJEŠENJE (službeno):\n" + (_s(redak.get("rjesenje")) or "(nema)")
        + "\n\nVrati JSON po pravilima."
    )
    try:
        odgovor = _pozovi_ai(AI_SISTEM, korisnik, model)
    except Exception as e:                            # noqa: BLE001 - bez AI-ja se preskače
        print(f"AI nije odgovorio: {type(e).__name__}: {str(e)[:300]}; zadatak preskočen.")
        return None
    podaci = _json_iz_odgovora(odgovor)
    rezultat = _ocisti_ai_podjelu(redak, podaci) if podaci else None
    if not rezultat:
        return None                                   # provjera nije prošla - ne upisujemo
    uvod, dijelovi = rezultat

    roditelj_id = _s(redak.get("id"))
    polja = {
        "uloga": "skupina",
        "tekst_zadatka_latex": uvod,
        "tekst_zadatka_mathjax": uvod.replace("\\\\", "<br>"),
        "status_provjere": _dodaj_napomenu(
            redak.get("status_provjere"),
            "RAZDVOJENO: " + ", ".join(f"{d['oznaka']})" for d in dijelovi) + "; AI podjela (provjereno)"),
    }
    novi_redci = [_redak_stavke(redak, d["oznaka"], d["tekst"], d["rjesenje"],
                                d["konacan_odgovor"], "", roditelj_id)
                  for d in dijelovi]
    log = [{"id": roditelj_id, "polje": k, "staro": _s(redak.get(k)), "novo": _s(v)}
           for k, v in polja.items()]
    log += [{"id": r["id"], "polje": "+redak", "staro": "", "novo": ""} for r in novi_redci]
    return {"polja": polja, "novi_redci": novi_redci, "log": log}


# ---------------------------------------------------------------------------------------------
# POSAO: kratki odgovori (odgovori_posao.py)
# ---------------------------------------------------------------------------------------------

def _predlozi_kratki_odgovor(redak: dict, sheet=None):
    from odgovori_posao import predlozi
    return predlozi(redak)


def _vec_obradjeno_kratki_odgovor(redak: dict) -> bool:
    from odgovori_posao import vec_obradjeno
    return vec_obradjeno(redak)


def _provjeri_kratki_odgovor(redak: dict, promjene: dict) -> bool:
    from odgovori_posao import provjeri
    return provjeri(redak, promjene)


POSLOVI = {
    "kratki_odgovor": {
        "naziv": "Kratki odgovori iz rješenja (deterministički + AI, uz provjeru)",
        "predlozi": _predlozi_kratki_odgovor,
        "vec_obradjeno": _vec_obradjeno_kratki_odgovor,
        "provjeri": _provjeri_kratki_odgovor,
    },
    "cijepanje_ai": {
        "naziv": "Cijepanje uz AI (samo zadaci koje deterministički ne može)",
        "predlozi": _predlozi_cijepanje_ai,
        "vec_obradjeno": _vec_obradjeno_cijepanje,
        "provjeri": _provjeri_cijepanje,
    },
    "cijepanje": {
        "naziv": "Cijepanje zadatka na podpitanja (uvod + a)/b)/…)",
        "predlozi": _predlozi_cijepanje,
        "vec_obradjeno": _vec_obradjeno_cijepanje,
        "provjeri": _provjeri_cijepanje,
    },
}


def dohvati(naziv: str):
    return POSLOVI.get(_s(naziv))


def dostupni() -> list[str]:
    return list(POSLOVI)
