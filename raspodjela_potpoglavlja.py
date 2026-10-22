"""
CAKI — raspodjela_potpoglavlja.py  (22.10.2026.)

🧩 AI RAZVRSTAVANJE ZADATAKA U **POTPOGLAVLJA** (iz Šifrarnika) i dodjela **TEŽINE**
(lako / srednje / teško) — za udžbenike Dakić, unesene zadatke i ponovnu provjeru fizike.

Zašto: pretraga po cjelini i potpoglavlju je Cakiju najvažnija, a kod grubo uvezenih baza
potpoglavlja su prazna ili pogrešna. Model dobiva **zatvoreni popis** potpoglavlja po cjelini
(iz taba `Sifrarnik_potpoglavlja` preko `get_potpoglavlja_po_cjelini`), predlaže, a **čovjek
potvrđuje** u pregledu prije upisa.

Namjerno zaseban modul (ne dira `raspodjela_cjelina.py`, koji razvrstava samo cjeline i koji je
napisala druga sesija): ovdje su potpoglavlje + težina, s istim obrascem (batch → validacija →
pregled → `batch_update`).

Tvrdi podaci (tab `Zadaci`): `id`, `cjelina`, `potpoglavlje`, `tezina` (+ `*_prije` za vraćanje).
"""
from __future__ import annotations

import json
import re

BATCH = 12
TEZINE = ["lako", "srednje", "teško"]
TEZINE_KLJUC = {"lako": "lako", "srednje": "srednje", "tesko": "teško", "teško": "teško"}
SIGURNOSTI = ("visoka", "srednja", "niska")

ZADATAK = """Ti si iskusan profesor matematike/fizike u hrvatskoj srednjoj školi. Razvrstavaš
zadatke iz udžbenika i zbirki u POTPOGLAVLJA iz zadanog popisa i procjenjuješ TEŽINU.

PRAVILA:
1. Cjelinu i potpoglavlje biraš ISKLJUČIVO iz priloženog popisa. Ako nijedno ne odgovara,
   stavi `null` — NIKAD ne izmišljaj nova imena.
2. Težina je jedno od: "lako", "srednje", "teško".
   - lako: jedan korak, izravna primjena formule/definicije
   - srednje: 2–3 koraka, kombinacija dvaju pravila, tipičan ispitni zadatak
   - teško: više koraka, dokaz/konstrukcija, povezivanje cjelina ili „pokaži da…”
3. `sigurnost`: "visoka" kad si siguran, "srednja" kad je moguće drugo potpoglavlje,
   "niska" kad je zadatak nejasan ili bez teksta.
4. Kratko obrazloži (`razlog`, do 12 riječi).
5. Odgovori ISKLJUČIVO JSON-om: {"stavke":[{"id":"...","cjelina":"...","potpoglavlje":"...",
   "tezina":"srednje","sigurnost":"visoka","razlog":"..."}]}"""


def _t(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


# --------------------------------------------------------------------------- šifrarnik

def sifrarnik(sheet) -> dict:
    """{cjelina: [potpoglavlja…]} iz baze (tab `Sifrarnik_potpoglavlja`)."""
    try:
        from baza_zadataka_pipeline import get_potpoglavlja_po_cjelini
        po_cjelini = get_potpoglavlja_po_cjelini(sheet) or {}
    except Exception:                                   # noqa: BLE001 — nema modula/taba
        return {}
    izlaz = {}
    for cjelina, stavke in po_cjelini.items():
        imena = []
        for stavka in stavke or []:
            ime = _t(stavka[0] if isinstance(stavka, (list, tuple)) and stavka else stavka)
            if ime and ime not in imena:
                imena.append(ime)
        if _t(cjelina) and imena:
            izlaz[_t(cjelina)] = imena
    return izlaz


def sifrarnik_za_prompt(mapping) -> str:
    redci = [f"- CJELINA: {cjelina} | POTPOGLAVLJA: " + "; ".join(imena)
             for cjelina, imena in (mapping or {}).items()]
    return "\n".join(redci)


def sastavi_system(mapping, trazi_potpoglavlje: bool = True) -> str:
    if not mapping:
        raise ValueError("Šifrarnik potpoglavlja je prazan — nema u što razvrstavati.")
    dodatak = "" if trazi_potpoglavlje else (
        "\n6. Potpoglavlje NE mijenjaj: vrati `null` za potpoglavlje, samo procijeni težinu.")
    return f"POPIS DOPUŠTENIH CJELINA I POTPOGLAVLJA:\n{sifrarnik_za_prompt(mapping)}\n\n{ZADATAK}{dodatak}"


def _kratak_tekst(z) -> str:
    tekst = _t((z or {}).get("tekst_zadatka_latex")) or _t((z or {}).get("tekst_zadatka_mathjax"))
    tekst = re.sub(r"\s+", " ", tekst)
    if len(tekst) > 700:
        tekst = tekst[:700] + "…"
    return tekst


def sastavi_user(zadaci) -> str:
    dijelovi = []
    for z in zadaci or []:
        zid = _t(z.get("id"))
        dijelovi.append(
            f'ID: {zid}\nCIJELINA (postojeća): {_t(z.get("cjelina")) or "—"}\n'
            f'POTPOGLAVLJE (postojeće): {_t(z.get("potpoglavlje")) or "—"}\n'
            f"TEKST:\n{_kratak_tekst(z)}\n")
    return "RAZVRSTAJ OVE ZADATKE:\n\n" + "\n---\n".join(dijelovi)


# --------------------------------------------------------------------------- odgovor modela

def izvadi_json(tekst):
    """Iz odgovora izvuci JSON objekt (model zna dodati ```json ograde ili tekst prije)."""
    t = _t(tekst)
    if not t:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    dubina, pocetak = 0, None
    for i, znak in enumerate(t):
        if znak == "{":
            if dubina == 0:
                pocetak = i
            dubina += 1
        elif znak == "}":
            dubina -= 1
            if dubina == 0 and pocetak is not None:
                try:
                    return json.loads(t[pocetak:i + 1])
                except ValueError:
                    pocetak = None
    return None


def _bez_dijakritika(tekst) -> str:
    t = _t(tekst).lower()
    for a, b in (("č", "c"), ("ć", "c"), ("š", "s"), ("ž", "z"), ("đ", "d")):
        t = t.replace(a, b)
    return t


def _nadi(ime, opcije) -> str:
    """Vrati najbliže ime iz popisa (bez obzira na velika slova/dijakritike); "" ako nema."""
    cilj = _bez_dijakritika(ime)
    for opcija in opcije or []:
        if _bez_dijakritika(opcija) == cilj:
            return opcija
    return ""


def parsiraj_odgovor(tekst, zadaci, mapping) -> tuple:
    """Provjeri odgovor modela prema zatvorenom popisu. Vraća (predlozi, upozorenja)."""
    podaci = izvadi_json(tekst)
    if not isinstance(podaci, dict) or not isinstance(podaci.get("stavke"), list):
        return [], ["odgovor nije JSON s poljem „stavke”"]

    po_id = {_t(z.get("id")): z for z in zadaci or []}
    cjeline = list((mapping or {}).keys())
    predlozi, upozorenja = [], []

    for stavka in podaci["stavke"]:
        if not isinstance(stavka, dict):
            continue
        zid = _t(stavka.get("id"))
        if zid not in po_id:
            upozorenja.append(f"nepoznat ID „{zid}” — preskočeno")
            continue
        zadatak = po_id[zid]

        cjelina = _nadi(stavka.get("cjelina"), cjeline)
        if _t(stavka.get("cjelina")) and not cjelina:
            upozorenja.append(f"{zid}: cjelina „{_t(stavka.get('cjelina'))}” nije u šifrarniku")
        if not cjelina:
            cjelina = _t(zadatak.get("cjelina")) if _t(zadatak.get("cjelina")) in cjeline else ""

        potpoglavlje = ""
        if cjelina:
            potpoglavlje = _nadi(stavka.get("potpoglavlje"), mapping.get(cjelina, []))
            if _t(stavka.get("potpoglavlje")) and not potpoglavlje:
                upozorenja.append(
                    f"{zid}: potpoglavlje „{_t(stavka.get('potpoglavlje'))}” nije u cjelini {cjelina}")

        tezina = TEZINE_KLJUC.get(_bez_dijakritika(stavka.get("tezina")), "")

        sigurnost = _bez_dijakritika(stavka.get("sigurnost"))
        if sigurnost not in SIGURNOSTI:
            sigurnost = "niska"

        predlozi.append({
            "id": zid,
            "cjelina": cjelina,
            "sada_cjelina": _t(zadatak.get("cjelina")),
            "potpoglavlje": potpoglavlje,
            "sada_potpoglavlje": _t(zadatak.get("potpoglavlje")),
            "tezina": tezina,
            "sada_tezina": _t(zadatak.get("tezina")),
            "sigurnost": sigurnost,
            "razlog": _t(stavka.get("razlog"))[:120],
        })
    return predlozi, upozorenja


# --------------------------------------------------------------------------- pokretanje

def razvrsti(zadaci, mapping, pozovi, batch: int = BATCH, trazi_potpoglavlje: bool = True,
             napredak=None) -> dict:
    """Razvrsti zadatke u potpoglavlja i dodijeli težinu. `pozovi(system, user)` → {"tekst": …}."""
    if not pozovi:
        raise ValueError("Nedostaje funkcija za poziv modela.")
    if not mapping:
        raise ValueError("Šifrarnik potpoglavlja je prazan.")
    system = sastavi_system(mapping, trazi_potpoglavlje=trazi_potpoglavlje)

    predlozi, upozorenja, ulaz, izlaz = [], [], 0, 0
    ukupno = len(zadaci or [])
    for i in range(0, ukupno, batch):
        dio = zadaci[i:i + batch]
        try:
            odg = pozovi(system, sastavi_user(dio)) or {}
            ulaz += int(odg.get("tokeni_ulaz") or 0)
            izlaz += int(odg.get("tokeni_izlaz") or 0)
            p, u = parsiraj_odgovor(odg.get("tekst", ""), dio, mapping)
            predlozi += p
            upozorenja += [f"paket {i // batch + 1}: {x}" for x in u]
        except Exception as e:                          # noqa: BLE001 — jedan paket ne ruši sve
            upozorenja.append(f"paket {i // batch + 1}: {e}")
        if napredak:
            napredak(min(i + batch, ukupno), ukupno)
    return {"predlozi": predlozi, "upozorenja": upozorenja,
            "tokeni_ulaz": ulaz, "tokeni_izlaz": izlaz}


# --------------------------------------------------------------------------- pregled i upis

def _znak(sigurnost) -> str:
    return {"visoka": "🟢 visoka", "srednja": "🟡 srednja", "niska": "🔴 niska"}.get(
        _t(sigurnost).lower(), "🔴 niska")


def tablica_prijedloga(predlozi):
    """Pandas tablica za Cakijev pregled — što se mijenja i koliko je sigurno."""
    import pandas as pd

    redci = []
    for p in predlozi or []:
        mijenja = []
        if _t(p.get("potpoglavlje")) and _t(p.get("potpoglavlje")) != _t(p.get("sada_potpoglavlje")):
            mijenja.append("potpoglavlje")
        if _t(p.get("tezina")) and _t(p.get("tezina")) != _t(p.get("sada_tezina")):
            mijenja.append("težina")
        if _t(p.get("cjelina")) and _t(p.get("cjelina")) != _t(p.get("sada_cjelina")):
            mijenja.append("cjelina")
        redci.append({
            "ID": _t(p.get("id")),
            "Cjelina": _t(p.get("cjelina")) or _t(p.get("sada_cjelina")),
            "Potpoglavlje sada": _t(p.get("sada_potpoglavlje")) or "—",
            "Potpoglavlje novo": _t(p.get("potpoglavlje")) or "—",
            "Težina sada": _t(p.get("sada_tezina")) or "—",
            "Težina nova": _t(p.get("tezina")) or "—",
            "Mijenja": ", ".join(mijenja) or "—",
            "Sigurnost": _znak(p.get("sigurnost")),
            "Zašto": _t(p.get("razlog")),
        })
    return pd.DataFrame(redci)


def osiguraj_stupac(sheet, stupac: str, naziv_taba: str = "Zadaci") -> bool:
    """Dodaj stupac u zaglavlje ako ga nema (za `*_prije`). Vraća True ako je dodan."""
    import gspread

    try:
        ws = sheet.worksheet(naziv_taba)
    except gspread.exceptions.WorksheetNotFound:
        return False
    zagl = [_t(h) for h in (ws.row_values(1) or [])]
    if stupac in zagl:
        return False
    if ws.col_count < len(zagl) + 1:
        ws.add_cols(1)
    ws.update(range_name=gspread.utils.rowcol_to_a1(1, len(zagl) + 1), values=[[stupac]],
              value_input_option="RAW")
    return True


def primijeni(sheet, predlozi, stupci=("potpoglavlje", "tezina"), pamti_staro: bool = True,
              naziv_taba: str = "Zadaci") -> int:
    """Upiše potpoglavlje i težinu u tab `Zadaci` — JEDAN `batch_update` za sve.

    Upisuje se samo ono što je stvarno drugačije i što je valjano. Stare vrijednosti idu u
    `<stupac>_prije` (ako `pamti_staro`), da se promjena može vratiti. Vraća broj zadataka.
    """
    import gspread

    po_id = {_t(p.get("id")): p for p in predlozi or [] if _t(p.get("id"))}
    if not po_id:
        return 0

    ws = sheet.worksheet(naziv_taba)
    if pamti_staro:
        for stupac in stupci:
            osiguraj_stupac(sheet, f"{stupac}_prije", naziv_taba)
        ws = sheet.worksheet(naziv_taba)

    zagl = [_t(h) for h in (ws.row_values(1) or [])]
    if "id" not in zagl:
        raise ValueError("Tab nema stupac `id` — provjeri je li to tab Zadaci.")
    indeks = {h: i + 1 for i, h in enumerate(zagl)}

    izmjene, upisano = [], 0
    for redni, redak in enumerate(ws.get_all_values()[1:], start=2):
        zid = _t(redak[indeks["id"] - 1]) if len(redak) >= indeks["id"] else ""
        p = po_id.get(zid)
        if not p:
            continue
        promjena = False
        for stupac in stupci:
            if stupac not in indeks:
                continue
            novo = _t(p.get(stupac))
            if not novo:
                continue
            stara = _t(redak[indeks[stupac] - 1]) if len(redak) >= indeks[stupac] else ""
            if novo == stara and f"{stupac}_prije" in indeks:
                continue
            if novo != stara:
                izmjene.append({"range": gspread.utils.rowcol_to_a1(redni, indeks[stupac]),
                                "values": [[novo]]})
                promjena = True
            if pamti_staro and f"{stupac}_prije" in indeks:
                izmjene.append({"range": gspread.utils.rowcol_to_a1(redni, indeks[f"{stupac}_prije"]),
                                "values": [[stara]]})
        if promjena:
            upisano += 1

    if izmjene:
        ws.batch_update(izmjene, raw=True)
    return upisano


# --------------------------------------------------------------------------- odabir zadataka

def _upit_odgovara(tekst: str, upit: str) -> bool:
    """Ista tolerantna pretraga kao u Test Builderu: svaka riječ, a za duge riječi prvih 6 znakova."""
    for rijec in _bez_dijakritika(upit).split():
        if rijec in tekst:
            continue
        if len(rijec) >= 6 and rijec[:6] in tekst:
            continue
        return False
    return True


def odaberi(zadaci, izvori=(), samo_bez_potpoglavlja: bool = False, samo_bez_tezine: bool = False,
            cjeline=(), upit: str = "", najvise: int | None = None) -> list:
    """Filtriraj zadatke za razvrstavanje (izvor, prazna potpoglavlja/težina, cjelina, tekst)."""
    izvori = {_t(i) for i in izvori or [] if _t(i)}
    cjeline = {_t(c) for c in cjeline or [] if _t(c)}
    upit_n = _bez_dijakritika(upit)
    izlaz = []
    for z in zadaci or []:
        if izvori and _t(z.get("izvor_naziv")) not in izvori:
            continue
        if cjeline and _t(z.get("cjelina")) not in cjeline:
            continue
        if samo_bez_potpoglavlja and _t(z.get("potpoglavlje")):
            continue
        if samo_bez_tezine and _t(z.get("tezina")):
            continue
        if upit_n:
            hay = _bez_dijakritika(" ".join(_t(z.get(k)) for k in
                                            ("tekst_zadatka_latex", "id", "cjelina", "potpoglavlje")))
            if not _upit_odgovara(hay, upit):
                continue
        izlaz.append(z)
        if najvise and len(izlaz) >= najvise:
            break
    return izlaz


__all__ = [
    "BATCH", "TEZINE", "SIGURNOSTI", "sifrarnik", "sifrarnik_za_prompt", "sastavi_system",
    "sastavi_user", "izvadi_json", "parsiraj_odgovor", "razvrsti", "tablica_prijedloga",
    "osiguraj_stupac", "primijeni", "odaberi",
]
