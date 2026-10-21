"""
CAKI — raspodjela_cjelina.py  (21.10.2026.)
🧩 AI RAZVRSTAVANJE ZADATAKA U CJELINE IZ ŠIFRARNIKA — za baze koje su uvezene grubo.

Zašto postoji (Cakijev nalaz iz fizike): u bazu je ušlo 1842 zadatka, ali u **21 cjelinu**, dok
šifrarnik ima **55**. Sadržaj 35 cjelina nije nestao — pomiješan je unutar širokih (npr. „Sile i
Newtonovi zakovi", 280 zadataka, sadrži i kosinu, i impuls sile, i gibanje po kružnici). Caki ne
može ručno razvrstati 1842 zadatka, pa model predlaže, a **čovjek potvrđuje**.

Kako radi:
  1. model dobije tekst zadatka i ZATVORENI popis cjelina iz šifrarnika (ništa izvan popisa),
  2. vrati {id, cjelina, sigurnost, razlog} — uz „NESIGURNO" kad stvarno ne zna,
  3. sve što nije iz popisa se ODBIJA (upozorenje), ne upisuje,
  4. upisuje se SAMO ono što Caki označi u pregledu; prije upisa se stara vrijednost pamti u
     `cjelina_prije` (vraćanje je moguće).

Ovaj modul ne dira mrežu: poziv modela se predaje kao funkcija (`pozovi`), pa se sve provjerava
testovima bez API-ja i bez Googlea. Sučelje je `pages/12_raspodjela_cjelina.py`.
"""
from __future__ import annotations

import json
import re

NESIGURNO = "NESIGURNO"
MAX_TEKSTA = 700          # koliko znakova zadatka ide modelu (dovoljno za razvrstavanje)
BATCH = 25                # zadataka po jednom pozivu (kraći odgovor = manje odrezanih JSON-ova)

ZADATAK = """ZADATAK: Razvrstaj svaki zadatak u TOČNO JEDNU cjelinu iz priloženog popisa.

PRAVILA:
1. `cjelina` MORA biti doslovno jedno od ponuđenih imena (isti znakovi, ista slova). Ništa izvan popisa.
2. Razvrstavaj po tome što učenik treba znati da bi zadatak riješio, ne po tome što u tekstu spominje.
3. Ako zadatak stvarno pripada u dvije, odaberi onu koja je bliža glavnom postupku.
4. Ako ne možeš pouzdano odlučiti, stavi `"cjelina": "NESIGURNO"` — bolje priznati nego pogoditi.
5. `sigurnost`: "visoka" (jasan zadatak), "srednja" (vjerojatno), "niska" (nagađam).
6. `razlog`: najviše 10 riječi, na hrvatskom, zašto ta cjelina.
7. Vrati ISKLJUČIVO JSON: {"zadaci": [{"id": "...", "cjelina": "...", "sigurnost": "...", "razlog": "..."}]}
   — točno jedan objekt po zadatku iz ulaza, bez teksta izvan JSON-a."""


# ------------------------------------------------------------------------------------ priprema

def _t(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def popis_cjelina(sifrarnik) -> list:
    """Iz šifrarnika (retci s `cjelina` i `kategorija`) → jedinstveni popis cjelina, po kategoriji.

    Vraća [{"cjelina": ..., "kategorija": ...}] — redoslijed kategorija i cjelina kako je u šifrarniku.
    """
    out, vidjeno = [], set()
    for r in sifrarnik or []:
        cj = _t((r or {}).get("cjelina"))
        if not cj or cj.lower() in vidjeno:
            continue
        vidjeno.add(cj.lower())
        out.append({"cjelina": cj, "kategorija": _t((r or {}).get("kategorija"))})
    return out


def sifrarnik_za_prompt(cjeline) -> str:
    """Popis za model: 'KATEGORIJA › cjelina' — da model vidi kontekst, ne samo naziv."""
    redci, zadnja = [], None
    for c in cjeline or []:
        kat = _t(c.get("kategorija"))
        if kat and kat != zadnja:
            redci.append(f"\n[{kat}]")
            zadnja = kat
        redci.append(f"- {_t(c.get('cjelina'))}")
    return "\n".join(redci).strip()


def sastavi_system(cjeline) -> str:
    return f"POPIS DOPUŠTENIH CJELINA (jedino iz ovoga smiješ birati):\n{sifrarnik_za_prompt(cjeline)}\n\n{ZADATAK}"


def _kratak_tekst(z) -> str:
    t = _t(z.get("tekst_zadatka_latex")) or _t(z.get("tekst"))
    t = re.sub(r"\s+", " ", t)
    return t[:MAX_TEKSTA]


def sastavi_user(zadaci) -> str:
    """JSON popis za model: id, sadašnja cjelina (pomoć) i tekst zadatka."""
    return json.dumps([{"id": _t(z.get("id")), "sada": _t(z.get("cjelina")), "tekst": _kratak_tekst(z)}
                       for z in zadaci or []], ensure_ascii=False)


# ------------------------------------------------------------------------------------ odgovor

def izvadi_json(tekst: str):
    """Odgovor modela → Python objekt. Podnosi ``` ograde i uvodni tekst (isti obrazac kao ai_asistent)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(tekst or "").strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("odgovor modela nije valjan JSON")


def parsiraj_odgovor(tekst, zadaci, valjane) -> tuple:
    """(predlozi, upozorenja). Predlozi su u redoslijedu ulaznih zadataka; nepoznata cjelina se odbija."""
    valjane = {str(x).lower(): str(x) for x in (valjane or [])}
    upozorenja = []
    obj = izvadi_json(tekst)
    lista = obj.get("zadaci") if isinstance(obj, dict) else obj
    if not isinstance(lista, list):
        raise ValueError("u odgovoru nema popisa 'zadaci'")
    po_id, nepoznato = {}, 0
    for r in lista:
        if not isinstance(r, dict):
            continue
        zid = _t(r.get("id"))
        if not zid:
            continue
        cj = _t(r.get("cjelina"))
        sig = _t(r.get("sigurnost")).lower()
        if cj and cj != NESIGURNO and cj.lower() not in valjane:
            nepoznato += 1
            upozorenja.append(f"„{cj}” nije u šifrarniku — odbijeno (zadatak {zid})")
            continue
        po_id[zid] = {"id": zid,
                      "cjelina": valjane.get(cj.lower(), cj),
                      "sigurnost": sig if sig in ("visoka", "srednja", "niska") else "niska",
                      "razlog": _t(r.get("razlog"))[:120]}
    if nepoznato:
        upozorenja.append(f"ukupno odbijenih prijedloga izvan šifrarnika: {nepoznato}")
    predlozi = []
    for z in zadaci or []:
        zid = _t(z.get("id"))
        p = po_id.get(zid)
        if p is None:
            upozorenja.append(f"model nije vratio zadatak {zid} — preskočen")
            continue
        p["sada"] = _t(z.get("cjelina"))
        predlozi.append(p)
    return predlozi, upozorenja


# ------------------------------------------------------------------------------------ razvrstavanje

def razvrsti(zadaci, cjeline, pozovi, batch: int = BATCH, napredak=None) -> dict:
    """Razvrsti zadatke u cjeline iz šifrarnika. `pozovi(system, user)` → {"tekst": ...}.

    Greška jednog paketa ne ruši ostale — postaje upozorenje. `napredak(gotovo, ukupno)` se poziva
    nakon svakog paketa (za progress bar u sučelju).
    """
    if not pozovi:
        raise ValueError("Nedostaje funkcija za poziv modela.")
    cjeline = popis_cjelina(cjeline) if cjeline and isinstance(cjeline[0], dict) else \
        [{"cjelina": c, "kategorija": ""} for c in (cjeline or [])]
    if not cjeline:
        raise ValueError("Šifrarnik cjelina je prazan — nema u što razvrstavati.")
    valjane = [c["cjelina"] for c in cjeline]
    system = sastavi_system(cjeline)

    predlozi, upozorenja = [], []
    ulaz = izlaz = 0
    ukupno = len(zadaci or [])
    for i in range(0, ukupno, batch):
        dio = zadaci[i:i + batch]
        try:
            odg = pozovi(system, sastavi_user(dio)) or {}
            ulaz += int(odg.get("tokeni_ulaz") or 0)
            izlaz += int(odg.get("tokeni_izlaz") or 0)
            if odg.get("odrezano"):
                upozorenja.append(f"paket {i // batch + 1}: odgovor odrezan — neki zadaci mogu nedostajati")
            p, u = parsiraj_odgovor(odg.get("tekst", ""), dio, valjane)
            predlozi += p
            upozorenja += [f"paket {i // batch + 1}: {x}" for x in u]
        except Exception as e:                       # noqa: BLE001 — jedan paket ne ruši sve
            upozorenja.append(f"paket {i // batch + 1}: {e}")
        if napredak:
            napredak(min(i + batch, ukupno), ukupno)
    return {"predlozi": predlozi, "upozorenja": upozorenja, "tokeni_ulaz": ulaz, "tokeni_izlaz": izlaz}


# ------------------------------------------------------------------------------------ prikaz i upis

def tablica_prijedloga(predlozi):
    """Pandas tablica za pregled: što mijenja, koliko je sigurno i zašto."""
    import pandas as pd

    redci = []
    for p in predlozi or []:
        sada = _t(p.get("sada"))
        novo = _t(p.get("cjelina"))
        redci.append({
            "ID": _t(p.get("id")),
            "Sada": sada or "—",
            "Predloženo": novo,
            "Mijenja se": "✅ da" if _mijenja(p) else "—",
            "Sigurnost": {"visoka": "🟢 visoka", "srednja": "🟡 srednja", "niska": "🔴 niska"}
            .get(_t(p.get("sigurnost")).lower(), "🔴 niska"),
            "Zašto": _t(p.get("razlog")),
        })
    return pd.DataFrame(redci)


def _mijenja(p) -> bool:
    """Mijenja li taj prijedlog cjelinu? NESIGURNO i prazno se NE računaju — to se ne bi upisalo."""
    cj = _t((p or {}).get("cjelina"))
    return bool(cj) and cj != NESIGURNO and cj != _t((p or {}).get("sada"))


def sazetak(predlozi) -> dict:
    """Koliko se mijenja, koliko je nesigurno, koliko ostaje isto."""
    ukupno = len(predlozi or [])
    mijenja = sum(1 for p in predlozi or [] if _mijenja(p))
    nesigurno = sum(1 for p in predlozi or [] if _t(p.get("cjelina")) in ("", NESIGURNO)
                    or _t(p.get("sigurnost")).lower() == "niska")
    return {"ukupno": ukupno, "mijenja": mijenja, "isto": ukupno - mijenja, "nesigurno": nesigurno}


def novi_po_cjelini(predlozi) -> dict:
    """{cjelina: broj} nakon primjene — za usporedbu sa šifrarnikom (koje ostaju prazne)."""
    po = {}
    for p in predlozi or []:
        cj = _t(p.get("cjelina"))
        if cj and cj != NESIGURNO:
            po[cj] = po.get(cj, 0) + 1
    return dict(sorted(po.items(), key=lambda x: (-x[1], x[0])))


def osiguraj_stupac(sheet, naziv_taba: str, stupac: str) -> bool:
    """Doda `stupac` na desni kraj taba ako ne postoji. True = dodan."""
    import gspread
    try:
        ws = sheet.worksheet(naziv_taba)
    except gspread.exceptions.WorksheetNotFound:
        return False
    zagl = [str(h).strip() for h in (ws.row_values(1) or [])]
    if stupac in zagl:
        return False
    if ws.col_count < len(zagl) + 1:
        ws.add_cols(1)
    ws.update(range_name=gspread.utils.rowcol_to_a1(1, len(zagl) + 1), values=[[stupac]],
              value_input_option="RAW")
    return True


def primijeni(sheet, mapa_cjelina: dict, naziv_taba: str = "Zadaci", pamti_staro: bool = True) -> int:
    """Upiše nove cjeline u tab `Zadaci` — JEDAN batch_update za sve (Sheets kvota).

    `mapa_cjelina` = {id_zadatka: nova_cjelina}. Prije upisa stara vrijednost ide u `cjelina_prije`
    (ako `pamti_staro`), da se promjena može vratiti. Vraća broj upisanih redaka.
    """
    import gspread
    mapa = {_t(k): _t(v) for k, v in (mapa_cjelina or {}).items() if _t(k) and _t(v)}
    if not mapa:
        return 0
    ws = sheet.worksheet(naziv_taba)
    if pamti_staro:
        osiguraj_stupac(sheet, naziv_taba, "cjelina_prije")
        ws = sheet.worksheet(naziv_taba)          # ponovno, zbog novog zaglavlja
    zagl = [str(h).strip() for h in (ws.row_values(1) or [])]
    if "id" not in zagl or "cjelina" not in zagl:
        raise ValueError("Tab nema stupce `id` i `cjelina` — provjeri je li to tab Zadaci.")
    i_id, i_cj = zagl.index("id") + 1, zagl.index("cjelina") + 1
    i_prije = zagl.index("cjelina_prije") + 1 if "cjelina_prije" in zagl else None

    izmjene, upisano = [], 0
    for redni, r in enumerate(ws.get_all_values()[1:], start=2):
        zid = _t(r[i_id - 1]) if len(r) >= i_id else ""
        if zid not in mapa:
            continue
        stara = _t(r[i_cj - 1]) if len(r) >= i_cj else ""
        izmjene.append({"range": gspread.utils.rowcol_to_a1(redni, i_cj), "values": [[mapa[zid]]]})
        if i_prije:
            izmjene.append({"range": gspread.utils.rowcol_to_a1(redni, i_prije), "values": [[stara]]})
        upisano += 1
    if izmjene:
        ws.batch_update(izmjene, raw=True)
    return upisano
