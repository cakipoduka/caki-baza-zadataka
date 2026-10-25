"""
CAKI — testovi_admin.py  (21.10.2026.)

UČITELJSKA STRANA sustava online testova (korak 1 od 4 iz plana od 21.10.):
pregled svih objavljenih testova, uređivanje (naziv, trajanje, datumi, aktivan),
kloniranje, pregled „kako učenik vidi” — i glavno: REZULTATI po testu te
USPJEH PO ZADATKU (koji zadatak učenici nisu znali).

Podaci se čitaju iz CRM Sheeta, iz tabova koje pišu:
  - `testovi_online.py` u ovom repou („Objavi kao online test” iz Test Buildera)
                                            -> tab `Testovi_zakazani`,
  - `caki-booking-termina/testovi_online.py` (portal Moj CAKI, rješavanje)
                                            -> tab `Rezultati_testova`.

ŠTO SE OVDJE PIŠE
    Samo tab `Testovi_zakazani` (uređivanje i kloniranje). Rezultati se NE diraju —
    oni su dokaz što je učenik predao. Portal (`Rezultati_testova`) i CRM tabovi se
    ne mijenjaju, pa za ovaj modul nije potrebna nijedna izmjena u drugim repoima.

ŠTO SE NE MIJENJA
    `pipeline_upisi.py`, baza zadataka (`Zadaci`), Test Builder. Jedina ovisnost je
    `testovi_online.py` iz ovog repoa (isti tabovi i ista zaglavlja).

STUPAC `serija` (priprema za korak 2 — zadavanje po grupi)
    Ako postoji, koristi se kao oznaka koja drži zajedno retke nastale jednom objavom
    za više učenika. Ako ga nema, sve radi kao prije (test ide jednom učeniku ili svima).
"""
from __future__ import annotations

import importlib.util as _importlib_util
import json
import os as _os
import re
from datetime import date, datetime, timedelta

from gspread.utils import rowcol_to_a1

# 21.10.2026.: upute unutar aplikacije. Zaštićen uvoz — modul s uputama NE smije blokirati
# testovi_admin (koristi se i iz testova koji taj modul ne trebaju).
try:
    import uputa_u_aplikaciji as _uputa
except Exception:  # noqa: BLE001
    _uputa = None

# 21.10.2026.: modul `testovi_online` postoji i u portalu (`caki-booking-termina`) pod ISTIM
# imenom. Običan `import testovi_online` znao bi (u zajedničkom pytest procesu, i u svakom
# alatu koji drži sys.modules) dohvatiti PORTALSKU kopiju — koja nema `TEST_HEADERS` ni
# `STATUS_AKTIVAN`. Zato se učitava točno datoteka iz OVE mape, bez obzira na sys.path.
_ONLINE_PUT = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "testovi_online.py")
_spec_online = _importlib_util.spec_from_file_location("testovi_online_baza", _ONLINE_PUT)
_online = _importlib_util.module_from_spec(_spec_online)
_spec_online.loader.exec_module(_online)
del _spec_online

PUBLIKE_UI = {"grupa": "👥 Grupa / kanta", "ucenici": "🧑 Pojedini učenici"}
TEST_TAB = _online.TEST_TAB                 # "Testovi_zakazani"
REZ_TAB = "Rezultati_testova"

# Ista zaglavlja kao u portalu (caki-booking-termina/testovi_online.py, REZ_HEADERS).
# Ovdje se koriste samo za čitanje i za CSV — redoslijed ne mijenjamo.
REZ_HEADERS = [
    "rezultat_id", "test_id", "naziv_testa", "ucenik_id", "ime_djeteta",
    "bodovi", "bodovi_max", "postotak", "odgovori_json", "detalji_json",
    "vrijeme_pocetka", "vrijeme_predaje", "trajanje_s", "status", "kreirano",
]

SERIJA_STUPAC = "serija"                    # korak 2 (grupe) — ne mora postojati
STATUS_AKTIVAN = _online.STATUS_AKTIVAN     # "Da"
GRANICA_CELIJE = 45000                      # Google: jedna ćelija najviše 50.000 znakova

# Tabovi u CRM Sheetu iz kojih se čitaju grupe (korak 2). Ako ih nema, stranica radi dalje.
GRUPE_TAB = "Grupe"
REZERVACIJE_TAB = "Rezervacije"
RASPORED_PREFIKS = "Raspored_Matura"
POCETAK_TAB = "Test_pocetak"      # piše ga PORTAL pri otvaranju testa (21.10.2026.)

DANI_REDOM = ("Ponedjeljak", "Utorak", "Srijeda", "Četvrtak", "Petak", "Subota", "Nedjelja")

# Statusi koje portal upisuje u Rezultati_testova.status
STATUSI_PREDANO = ("Predano", "Predano (vrijeme isteklo)")


# ============================================================
# Pomoćno
# ============================================================

def _tekst(vrijednost) -> str:
    return str(vrijednost if vrijednost is not None else "").strip()


def _broj(vrijednost, zadano: float = 0.0) -> float:
    try:
        return float(str(vrijednost).replace(",", ".").strip())
    except (TypeError, ValueError):
        return zadano


def _postotak(bodovi, maks) -> int:
    m = _broj(maks)
    return int(round(100 * _broj(bodovi) / m)) if m else 0


def _datum(vrijednost) -> str:
    """'2026-10-19 08:00' -> '2026-10-19' (prazno ostaje prazno)."""
    return _tekst(vrijednost)[:10]


def _aktivan(test) -> bool:
    """Prazno se broji kao Da — tako radi i portal (stariji redci)."""
    return _tekst((test or {}).get("aktivan")).lower() in ("", "da", "1", "true")


def kratak_tekst(tekst, n: int = 80) -> str:
    """Tekst zadatka za tablicu: bez LaTeX naredbi i dolara, skraćen na n znakova."""
    t = re.sub(r"\\[a-zA-Z]+", " ", _tekst(tekst))
    t = t.replace("$", "").replace("{", "").replace("}", "").replace("&", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return (t[: n - 1] + "…") if len(t) > n else t


def _kao_datum(vrijednost, zadano=None):
    """Tekst/datum -> datetime.date (za st.date_input)."""
    if isinstance(vrijednost, datetime):
        return vrijednost.date()
    if isinstance(vrijednost, date):
        return vrijednost
    try:
        return datetime.strptime(_datum(vrijednost), "%Y-%m-%d").date()
    except ValueError:
        return zadano or date.today()


# ============================================================
# Čitanje
# ============================================================

def load_testovi(sheet) -> list[dict]:
    """Svi objavljeni testovi iz CRM Sheeta (prazna lista ako tab još ne postoji)."""
    return _online.load_testovi(sheet)


def load_rezultati(sheet) -> list[dict]:
    """Sve predaje iz `Rezultati_testova` (prazna lista ako tab još ne postoji)."""
    try:
        ws = sheet.worksheet(REZ_TAB)
    except Exception:                                   # noqa: BLE001 — tab još ne postoji
        return []
    try:
        redci = ws.get_all_records()
    except Exception:                                   # noqa: BLE001 — Google ne odgovara
        return []
    return [r for r in redci if _tekst(r.get("rezultat_id"))]


def zadaci_iz_testa(test) -> list[dict]:
    """JSON iz retka testa -> popis zadataka (prazna lista ako se ne čita)."""
    return _online.zadaci_iz_retka(test)


def detalji_iz_retka(rezultat) -> list[dict]:
    """JSON `detalji_json` jednog rezultata -> popis po zadatku (tolerantno na smeće)."""
    sirovo = (rezultat or {}).get("detalji_json") if isinstance(rezultat, dict) else rezultat
    try:
        detalji = json.loads(str(sirovo or "[]"))
    except (TypeError, ValueError):
        return []
    return detalji if isinstance(detalji, list) else []


def nadji_test(testovi, test_id) -> dict | None:
    tid = _tekst(test_id)
    for t in testovi or []:
        if _tekst(t.get("test_id")) == tid:
            return t
    return None


def filtruj_rezultate(rezultati, test_id) -> list[dict]:
    tid = _tekst(test_id)
    return [r for r in (rezultati or []) if _tekst(r.get("test_id")) == tid]


def filtruj_po_predmetu(testovi, predmet: str) -> list[dict]:
    """Testovi za jedan predmet (slug iz predmet_config). Prazno polje = svi predmeti."""
    p = _tekst(predmet)
    if not p:
        return list(testovi or [])
    return [t for t in (testovi or []) if not _tekst(t.get("predmet")) or _tekst(t.get("predmet")) == p]


def cilj_opis(test) -> str:
    """Kome je test objavljen: serija (grupa) / učenik / program / svi."""
    dijelovi = []
    serija = _tekst((test or {}).get(SERIJA_STUPAC))
    if serija:
        dijelovi.append(serija)
    ucenik = _tekst((test or {}).get("ucenik_id")).upper()
    if ucenik:
        dijelovi.append(ucenik)
    if not dijelovi:
        program = _tekst((test or {}).get("program"))
        dijelovi.append(program if program else "svi")
    return " · ".join(dijelovi)


def serija_iz_retka(test) -> str:
    """Oznaka zajedničke objave (grupa/kanta) ili prazno za pojedinačni test."""
    return _tekst((test or {}).get(SERIJA_STUPAC))


def testovi_serije(testovi, serija) -> list[dict]:
    """Svi retci jedne objave (jedan po učeniku)."""
    oznaka = _tekst(serija)
    if not oznaka:
        return []
    return [t for t in (testovi or []) if _tekst(t.get(SERIJA_STUPAC)) == oznaka]


def jedinstvena_serija(testovi, osnova) -> str:
    """Oznaka serije koja se ne ponavlja (inače se doda ' #2', ' #3'…)."""
    osnova = _tekst(osnova) or "serija"
    postojece = {_tekst(t.get(SERIJA_STUPAC)) for t in (testovi or []) if _tekst(t.get(SERIJA_STUPAC))}
    if osnova not in postojece:
        return osnova
    i = 2
    while f"{osnova} #{i}" in postojece:
        i += 1
    return f"{osnova} #{i}"


def oznaka_serije(naziv_grupe, danas=None) -> str:
    """Čitljiva oznaka za jednu objavu grupi: „MAT-DUGI · Uto 17:00 · 21.10.2026.”."""
    d = _kao_datum(danas or date.today())
    return f"{_tekst(naziv_grupe)[:60]} · {d:%d.%m.%Y.}"


# ============================================================
# Grupe i kante (korak 2 — zadavanje cijeloj grupi)
# ============================================================

def _load_opcionalni_tab(sheet, naziv: str) -> list[dict]:
    """`get_all_records` s taba; nepostojeći tab ili Google greška => prazna lista."""
    try:
        ws = sheet.worksheet(naziv)
        return ws.get_all_records()
    except Exception:                                   # noqa: BLE001 — tab ne postoji / Google
        return []


def load_grupe(sheet) -> list[dict]:
    """Tab `Grupe` iz CRM Sheeta (Upisi)."""
    return _load_opcionalni_tab(sheet, GRUPE_TAB)


def load_rezervacije(sheet) -> list[dict]:
    """Tab `Rezervacije` iz CRM Sheeta (kto je u kojoj grupi)."""
    return _load_opcionalni_tab(sheet, REZERVACIJE_TAB)


def naziv_taba_rasporeda(sheet) -> str:
    """Naziv taba `Raspored_Matura_<sezona>` (sezona se ne prepisuje u kod — traži se u Sheetu)."""
    try:
        for ws in sheet.worksheets():
            if _tekst(getattr(ws, "title", "")).startswith(RASPORED_PREFIKS):
                return _tekst(ws.title)
    except Exception:                                   # noqa: BLE001
        return ""
    return ""


def load_raspored_mature(sheet) -> list[dict]:
    naziv = naziv_taba_rasporeda(sheet)
    return _load_opcionalni_tab(sheet, naziv) if naziv else []


def _dan_indeks(dan) -> int:
    d = _tekst(dan)
    return DANI_REDOM.index(d) if d in DANI_REDOM else 9


def _naziv_grupe_upisa(grupa) -> str:
    vrijeme = " ".join(x for x in (_tekst((grupa or {}).get("dan")),
                                   _tekst((grupa or {}).get("vrijeme"))) if x)
    return " · ".join(x for x in (_tekst((grupa or {}).get("program")), vrijeme,
                                  _tekst((grupa or {}).get("ucionica"))) if x)


def ucenici_upisa(grupe, rezervacije, status: str = "Potvrđeno") -> list[dict]:
    """Grupe Upisa s učenicima koji su u njima (zadano: samo `Potvrđeno`).

    Vraća [{"kod", "naziv", "aktivna", "ucenici": [{"ucenik_id", "ime_djeteta"}]}],
    sortirano po nazivu; grupe bez učenika se preskaču.
    """
    po_grupi: dict[str, dict] = {}
    for g in grupe or []:
        gid = _tekst(g.get("grupa_id"))
        if not gid:
            continue
        po_grupi[gid] = {
            "kod": gid,
            "naziv": _naziv_grupe_upisa(g),
            "aktivna": _tekst(g.get("aktivna")).lower() in ("", "da", "1", "true"),
            "ucenici": [],
        }

    vidjeno = set()
    for r in rezervacije or []:
        gid = _tekst(r.get("grupa_id"))
        if gid not in po_grupi:
            continue
        if status and _tekst(r.get("status")) != status:
            continue
        uid = _tekst(r.get("ucenik_id")).upper()
        if not uid or (gid, uid) in vidjeno:
            continue
        vidjeno.add((gid, uid))
        po_grupi[gid]["ucenici"].append({"ucenik_id": uid,
                                         "ime_djeteta": _tekst(r.get("ime_djeteta"))})

    izlaz = [g for g in po_grupi.values() if g["ucenici"]]
    izlaz.sort(key=lambda g: g["naziv"])
    return izlaz


def kante_mature(raspored) -> list[dict]:
    """Kante rasporeda Mature (dan + termin + učionica) s učenicima iz tog termina.

    Jedan učenik može u istoj kanti imati dva predmeta — broji se jednom (test se
    zadaje osobi, ne predmetu).
    """
    po_kanti: dict[str, dict] = {}
    for r in raspored or []:
        dan, termin, ucionica = (_tekst(r.get("dan")), _tekst(r.get("termin")),
                                 _tekst(r.get("ucionica")))
        if not dan or not termin:
            continue
        kod = f"{dan}|{termin}|{ucionica}"
        kanta = po_kanti.get(kod)
        if kanta is None:
            naziv = " · ".join(x for x in (dan, f"T{termin} {_tekst(r.get('vrijeme'))}".strip(),
                                           f"uč. {ucionica}" if ucionica else "") if x)
            kanta = po_kanti[kod] = {"kod": kod, "naziv": naziv, "ucenici": [], "_vidjeno": set(),
                                     "_sort": (_dan_indeks(dan), _broj(termin, 99), ucionica)}
        uid = _tekst(r.get("ucenik_id")).upper()
        if uid and uid not in kanta["_vidjeno"]:
            kanta["_vidjeno"].add(uid)
            kanta["ucenici"].append({"ucenik_id": uid,
                                     "ime_djeteta": _tekst(r.get("ime_djeteta"))})

    izlaz = []
    for kanta in po_kanti.values():
        kanta.pop("_vidjeno", None)
        if kanta["ucenici"]:
            izlaz.append(kanta)
    izlaz.sort(key=lambda k: k.pop("_sort"))
    return izlaz


# ============================================================
# Analiza rezultata
# ============================================================

def sazetak(rezultati) -> dict:
    """Osnovni brojevi za odabrani test: broj predaja, prosjek, najbolji/najslabiji, trajanje."""
    redci = [r for r in (rezultati or []) if _tekst(r.get("rezultat_id"))]
    if not redci:
        return {"broj": 0, "prosjek": 0, "najbolji": 0, "najslabiji": 0,
                "prosj_trajanje_min": 0, "maks": 0, "proslo": 0}
    postoci = [_postotak(r.get("bodovi"), r.get("bodovi_max")) for r in redci]
    trajanja = [_broj(r.get("trajanje_s")) for r in redci]
    return {
        "broj": len(redci),
        "prosjek": int(round(sum(postoci) / len(postoci))),
        "najbolji": max(postoci),
        "najslabiji": min(postoci),
        "prosj_trajanje_min": int(round(sum(trajanja) / len(trajanja) / 60)),
        "maks": _broj(redci[0].get("bodovi_max")),
        "proslo": sum(1 for p in postoci if p >= 50),
    }


def uspjeh_po_zadatku(test, rezultati) -> list[dict]:
    """Koliko je učenika točno riješilo SVAKI zadatak — iz `detalji_json` predaja.

    Vraća popis sortiran od najslabijeg zadatka: to je odgovor na pitanje „što razred
    nije znao”. Ako neki rezultat nema detalje (stariji zapis), preskače se za tog
    učenika, ali ostaje u broju predaja.
    """
    zadaci = zadaci_iz_testa(test)
    if not zadaci:
        return []

    stavke = [{
        "redni": i + 1,
        "id": _tekst(z.get("id")),
        "tekst": kratak_tekst(z.get("tekst"), 70),
        "bodovi": _broj(z.get("bodovi"), 1.0),
        "tocno": 0,
        "netocno": 0,
        "ukupno": 0,
    } for i, z in enumerate(zadaci)]
    indeks_po_id = {s["id"]: k for k, s in enumerate(stavke) if s["id"]}

    for r in rezultati or []:
        for i, d in enumerate(detalji_iz_retka(r)):
            if not isinstance(d, dict):
                continue
            k = indeks_po_id.get(_tekst(d.get("id")))
            if k is None:
                k = i if i < len(stavke) else None
            if k is None:
                continue
            stavke[k]["ukupno"] += 1
            if d.get("tocno"):
                stavke[k]["tocno"] += 1
            else:
                stavke[k]["netocno"] += 1

    for s in stavke:
        s["postotak"] = int(round(100 * s["tocno"] / s["ukupno"])) if s["ukupno"] else 0

    stavke.sort(key=lambda s: (s["postotak"], -s["ukupno"], s["redni"]))
    return stavke


def ucenici_bez_predaje(redci, rezultati) -> list[str]:
    """Šifre učenika kojima je test zadan, a nemaju predaju.

    `redci` je popis redaka testa: jedan (pojedinačno zadavanje) ili svi retci serije
    (grupa/kanta). Preskaču se retci bez `ucenik_id` (test „svima s programom” — za njih
    se ne zna tko je trebao predati).
    """
    ocekivani: list[str] = []
    for t in redci or []:
        uid = _tekst((t or {}).get("ucenik_id")).upper()
        if uid and uid not in ocekivani:
            ocekivani.append(uid)
    predali = {_tekst(r.get("ucenik_id")).upper() for r in rezultati or []}
    return [u for u in ocekivani if u not in predali]


def ucenici_koji_nisu_predali(test, rezultati) -> list[str]:
    """Jedan redak testa -> šifre onih koji nisu predali (prazno ako nije zadan pojedincu)."""
    return ucenici_bez_predaje([test], rezultati)


def load_pocetke(sheet) -> list[dict]:
    """Počeci rješavanja iz taba `Test_pocetak` (piše ih portal). Prazno ako tab nema."""
    return _load_opcionalni_tab(sheet, POCETAK_TAB)


def zapoceli_bez_predaje(redci, pocetci, rezultati, sada=None) -> list[dict]:
    """Učenici koji su OTVORILI test, a nisu predali — za odabranu test/seriju.

    `minuta` = koliko minuta rješavaju (ako se zna vrijeme), inače None. Sortirano od
    najdulje otvorenog — to je ono što Caki prvo pogleda („je li zapeo?”).
    """
    idovi = {_tekst((t or {}).get("test_id")) for t in redci or [] if _tekst((t or {}).get("test_id"))}
    if not idovi:
        return []
    predali = {(_tekst(r.get("test_id")), _tekst(r.get("ucenik_id")).upper())
               for r in rezultati or []}
    sada = sada or datetime.now()

    izlaz = []
    for p in pocetci or []:
        tid = _tekst(p.get("test_id"))
        uid = _tekst(p.get("ucenik_id")).upper()
        if tid not in idovi or not uid or (tid, uid) in predali:
            continue
        minuta = None
        try:
            pocetak = datetime.fromisoformat(_tekst(p.get("pocetak"))).replace(tzinfo=None)
            minuta = int((sada - pocetak).total_seconds() // 60)
        except (TypeError, ValueError):
            pocetak = None
        izlaz.append({
            "test_id": tid,
            "ucenik_id": uid,
            "pocetak": _tekst(p.get("pocetak"))[:16],
            "minuta": minuta if (minuta is None or minuta >= 0) else None,
        })

    izlaz.sort(key=lambda z: (z["minuta"] is None, -(z["minuta"] or 0), z["ucenik_id"]))
    return izlaz


def tablica_zapocelih(zapoceli):
    import pandas as pd

    return pd.DataFrame([{
        "Učenik": z["ucenik_id"],
        "Počeo": z["pocetak"],
        "Rješava (min)": z["minuta"] if z["minuta"] is not None else "",
        "Test": z["test_id"],
    } for z in zapoceli or []])


def _cjelina_zadatka(z) -> str:
    return _tekst((z or {}).get("cjelina")) or "— bez cjeline —"


# ============================================================
# 🎯 Rezultati JEDNOG testa — po učenicima i po grupama (22.10.2026.)
# ============================================================

def grupe_za_publiku(sheet) -> list[dict]:
    """Sve grupe iz kojih se bira **kome ide test**: kante Mature + aktivne grupe Upisa.

    Vraća [{"kod", "naziv", "ucenici": [{"ucenik_id", "ime_djeteta"}]}]. Greška u jednom izvoru
    ne ruši drugi — grupa koja se ne pročita se preskoči (Caki mora moći objaviti test i ako
    raspored Mature još nije upisan).
    """
    izlaz: list[dict] = []
    try:
        izlaz += [g for g in kante_mature(load_raspored_mature(sheet)) if (g or {}).get("ucenici")]
    except Exception:                             # noqa: BLE001 — raspored nije obavezan
        pass
    try:
        izlaz += [g for g in ucenici_upisa(load_grupe(sheet), load_rezervacije(sheet))
                  if (g or {}).get("ucenici") and (g or {}).get("aktivna")]
    except Exception:                             # noqa: BLE001 — Upisi nisu obavezni
        pass
    return izlaz


def kolone_svih_testova(testovi) -> list[str]:
    """Svi nazivi stupaca (test ili serija), najnoviji prvi — i oni bez ijedne predaje."""
    seen, izlaz = {}, []
    for i, t in enumerate(testovi or []):
        k = kolona_testa(t)
        if not k or k == "—" or k in seen:
            continue
        seen[k] = (_tekst(t.get("kreirano")) or _tekst(t.get("otvara_od")), i)
        izlaz.append(k)
    return sorted(izlaz, key=lambda k: seen[k], reverse=True)


def pregled_testa(testovi, rezultati, kolona: str, kante=None) -> dict:
    """Svi učenici koji su pisali JEDAN test (ili grupu redaka iste serije) — po učeniku i grupi.

    Vraća redak po učeniku (bodovi, %, je li predao), sažetak (prosjek, medijan, najbolji,
    najslabiji) i prosjek po grupi/kanti. `nije_pisalo` su učenici kojima je test dodijeljen, a
    nisu predali — to je ono što se prije nije vidjelo.
    """
    ciljni = [t for t in testovi or [] if kolona_testa(t) == _tekst(kolona)]
    if not ciljni:
        return {"kolona": _tekst(kolona), "redci": [], "nije_pisalo": [], "po_grupi": [],
                "pisalo": 0, "dodijeljeno": 0, "prosjek": 0, "medijan": 0,
                "najbolji": None, "najslabiji": None}

    ucenik_po_testu = {_tekst(t.get("test_id")): _tekst(t.get("ucenik_id")).upper()
                       for t in ciljni if _tekst(t.get("test_id"))}
    dodijeljeni, imena = {}, {}
    for t in ciljni:
        uid = _tekst(t.get("ucenik_id")).upper()
        if uid:
            dodijeljeni.setdefault(uid, 0)
            imena.setdefault(uid, _tekst(t.get("ime_djeteta")))

    grupa_ucenika = {}
    for g in kante or []:
        for u in (g or {}).get("ucenici") or []:
            uid = _tekst(u.get("ucenik_id")).upper()
            if uid:
                grupa_ucenika.setdefault(uid, _tekst((g or {}).get("naziv")))

    po_uceniku: dict[str, dict] = {}
    for r in rezultati or []:
        tid = _tekst(r.get("test_id"))
        if tid not in ucenik_po_testu:
            continue
        uid = _tekst(r.get("ucenik_id")).upper() or ucenik_po_testu[tid]
        if not uid:
            continue
        imena.setdefault(uid, _tekst(r.get("ime_djeteta")))
        po_uceniku[uid] = r                  # više predaja: broji se ZADNJA (redoslijed u tabu)

    redci = []
    for uid in set(po_uceniku) | set(dodijeljeni):
        r = po_uceniku.get(uid)
        bodovi = float(r.get("bodovi") or 0) if r else 0.0
        maks = float(r.get("bodovi_max") or 0) if r else 0.0
        redci.append({
            "ucenik_id": uid,
            "ime": imena.get(uid) or uid,
            "grupa": grupa_ucenika.get(uid, ""),
            "predao": bool(r),
            "bodovi": bodovi,
            "bodovi_max": maks,
            "postotak": _postotak(bodovi, maks) if r else None,
        })
    redci.sort(key=lambda x: (-(x["postotak"] if x["postotak"] is not None else -1), x["ime"]))

    pisali = [x["postotak"] for x in redci if x["postotak"] is not None]
    prosjek = int(round(sum(pisali) / len(pisali))) if pisali else 0
    if pisali:
        _s = sorted(pisali)
        _n = len(_s)
        medijan = int(round((_s[_n // 2] + _s[(_n - 1) // 2]) / 2))   # parni broj: prosjek dviju srednjih
    else:
        medijan = 0

    po_grupi = {}
    for x in redci:
        if x["postotak"] is None:
            continue
        g = x["grupa"] or "— bez grupe —"
        d = po_grupi.setdefault(g, {"grupa": g, "broj": 0, "zbroj": 0})
        d["broj"] += 1
        d["zbroj"] += x["postotak"]
    grupe = [{"grupa": d["grupa"], "broj": d["broj"],
              "prosjek": int(round(d["zbroj"] / d["broj"]))} for d in po_grupi.values()]
    grupe.sort(key=lambda x: (-x["prosjek"], x["grupa"]))

    return {
        "kolona": _tekst(kolona),
        "redci": redci,
        "pisalo": len(pisali),
        "dodijeljeno": len(dodijeljeni),
        "nije_pisalo": [x["ime"] for x in redci if not x["predao"]],
        "prosjek": prosjek,
        "medijan": medijan,
        "najbolji": max(pisali) if pisali else None,
        "najslabiji": min(pisali) if pisali else None,
        "po_grupi": grupe,
    }


def tablica_pregleda_testa(rez) -> "object":
    """Tablica za prikaz: mjesto, učenik, grupa, bodovi, %, status."""
    import pandas as pd

    redci = []
    mjesto = 0
    for x in (rez or {}).get("redci", []):
        if x["postotak"] is not None:
            mjesto += 1
        redci.append({
            "Mj.": mjesto if x["postotak"] is not None else "",
            "Učenik": x["ime"],
            "Grupa / kanta": x["grupa"],
            "Bodovi": f"{x['bodovi']:g} / {x['bodovi_max']:g}" if x["predao"] else "—",
            "%": x["postotak"] if x["postotak"] is not None else "",
            "Status": "✅ predao" if x["predao"] else "⏳ nije predao",
        })
    return pd.DataFrame(redci)


def uspjeh_po_cjelinama(test, rezultati) -> list[dict]:
    """Uspjeh grupiran po CJELINI iz baze (cjelina se zamrzava u test od 21.10.2026.).

    Za starije objave (bez `cjelina` u JSON-u) vraća praznu listu — bolje ništa nego
    lažna slika. Redci sortirani od najslabije cjeline.
    """
    zadaci = zadaci_iz_testa(test)
    if not zadaci or not any(_tekst(z.get("cjelina")) for z in zadaci):
        return []

    po_cjelini: dict[str, dict] = {}
    cjeline_po_zadatku: list[str] = []
    indeks_po_id: dict[str, int] = {}
    for i, z in enumerate(zadaci):
        cj = _cjelina_zadatka(z)
        stavka = po_cjelini.setdefault(cj, {"cjelina": cj, "zadataka": 0,
                                            "tocno": 0, "netocno": 0, "ukupno": 0})
        stavka["zadataka"] += 1
        cjeline_po_zadatku.append(cj)
        if _tekst(z.get("id")):
            indeks_po_id.setdefault(_tekst(z.get("id")), i)

    for r in rezultati or []:
        for i, d in enumerate(detalji_iz_retka(r)):
            if not isinstance(d, dict):
                continue
            k = indeks_po_id.get(_tekst(d.get("id")))
            if k is None:
                k = i if i < len(cjeline_po_zadatku) else None
            if k is None:
                continue
            cj = cjeline_po_zadatku[k]
            po_cjelini[cj]["ukupno"] += 1
            if d.get("tocno"):
                po_cjelini[cj]["tocno"] += 1
            else:
                po_cjelini[cj]["netocno"] += 1

    izlaz = list(po_cjelini.values())
    for s in izlaz:
        s["postotak"] = int(round(100 * s["tocno"] / s["ukupno"])) if s["ukupno"] else 0
    izlaz.sort(key=lambda s: (s["postotak"], -s["ukupno"], s["cjelina"]))
    return izlaz


def spremnost_baze(zadaci) -> dict:
    """Koliko je baze spremno za online test — po cjelinama.

    „Spreman” = redak nije skupina (`uloga == "skupina"`, uvod + stavke a/b/c se ne mogu
    objaviti kao jedan zadatak) i ima upisan `konacan_odgovor` (bez njega nema automatskog
    ocjenjivanja). Vraća sažetak + redak po cjelini, najslabije spremne prve.
    """
    ukupno = spremno = skupine = visestruki = 0
    po_cjelini: dict[str, dict] = {}

    for z in zadaci or []:
        ukupno += 1
        uloga = _tekst(z.get("uloga")).lower()
        ima_odgovor = bool(_tekst(z.get("konacan_odgovor")))
        cj = _cjelina_zadatka(z)
        stavka = po_cjelini.setdefault(cj, {"cjelina": cj, "ukupno": 0, "spremno": 0,
                                            "skupine": 0, "visestruki": 0})
        stavka["ukupno"] += 1
        if uloga == "skupina":
            skupine += 1
            stavka["skupine"] += 1
        if _tekst(z.get("tip_zadatka")) == "visestruki_izbor":
            visestruki += 1
            stavka["visestruki"] += 1
        if ima_odgovor and uloga != "skupina":
            spremno += 1
            stavka["spremno"] += 1

    redci = sorted(po_cjelini.values(), key=lambda s: (s["spremno"] / max(s["ukupno"], 1),
                                                       -s["ukupno"], s["cjelina"]))
    for s in redci:
        s["postotak"] = int(round(100 * s["spremno"] / s["ukupno"])) if s["ukupno"] else 0
    return {
        "ukupno": ukupno,
        "spremno": spremno,
        "skupine": skupine,
        "visestruki": visestruki,
        "postotak": int(round(100 * spremno / ukupno)) if ukupno else 0,
        "po_cjelini": redci,
    }


# ============================================================
# Matrica učenik × zadatak i provjera zamrznute kopije
# ============================================================

def matrica_ucenika(test, rezultati):
    """Tablica: red = učenik, stupac = zadatak (✓ / ✗ / prazno), plus bodovi i %.

    Za grupni test (serija) daje cijeli razred na jednom ekranu: vidi se tko je što
    riješio i koji je zadatak pao kod svih.
    """
    import pandas as pd

    zadaci = zadaci_iz_testa(test)
    if not zadaci or not rezultati:
        return pd.DataFrame()

    redci = []
    for r in sorted(rezultati or [], key=lambda x: (_tekst(x.get("ime_djeteta")),
                                                    _tekst(x.get("ucenik_id")))):
        tocno_po = {}
        for i, d in enumerate(detalji_iz_retka(r)):
            if isinstance(d, dict):
                tocno_po[i] = bool(d.get("tocno"))
        red = {"Učenik": _tekst(r.get("ime_djeteta")) or "—",
               "Šifra": _tekst(r.get("ucenik_id")).upper()}
        for i in range(len(zadaci)):
            red[f"Z{i + 1}"] = "✓" if tocno_po.get(i) else ("✗" if i in tocno_po else "")
        red["Bodovi"] = _tekst(r.get("bodovi"))
        red["%"] = _postotak(r.get("bodovi"), r.get("bodovi_max"))
        redci.append(red)
    return pd.DataFrame(redci)


def csv_matrica(test, rezultati) -> str:
    df = matrica_ucenika(test, rezultati)
    return df.to_csv(index=False, sep=";", lineterminator="\n") if not df.empty else ""


def kolona_testa(test) -> str:
    """Naziv stupca u matrici razreda: serija (grupa) ako postoji, inače naziv testa.

    Tako cijela grupa (20 redaka s istom serijom) bude JEDAN stupac, a ne 20.
    """
    return (serija_iz_retka(test) or _tekst((test or {}).get("naziv"))
            or _tekst((test or {}).get("test_id")) or "—")


def matrica_razreda(testovi, rezultati, zadnjih: int = 8):
    """Učenici × testovi: postotak po svakom testu (posljednjih `zadnjih`) + prosjek.

    Za pregled razreda kroz vrijeme. Grupni test (serija) je jedan stupac. Ako učenik
    ima više predaja istog stupca (ponovno rješavanje), broji se zadnja.
    """
    import pandas as pd

    if not rezultati:
        return pd.DataFrame()

    kolona_po_testu = {_tekst(t.get("test_id")): kolona_testa(t)
                       for t in (testovi or []) if _tekst(t.get("test_id"))}
    # kad je test objavljen (za redoslijed stupaca) — vrijeme + redoslijed u tabu,
    # jer su dva testa objavljena u istoj minuti inače nerazlučiva
    kad = {}
    for i, t in enumerate(testovi or []):
        tid = _tekst(t.get("test_id"))
        if not tid:
            continue
        k = kolona_po_testu[tid]
        d = _tekst(t.get("kreirano")) or _tekst(t.get("otvara_od"))
        if k not in kad or (d, i) > kad[k]:
            kad[k] = (d, i)

    ima_predaju = {_tekst(r.get("test_id")) for r in rezultati}
    kolone = sorted({kolona_po_testu.get(tid, tid) for tid in ima_predaju},
                    key=lambda k: (kad.get(k, ("", -1)), k))
    kolone = kolone[-max(1, int(zadnjih)):] if zadnjih else kolone

    # (učenik, kolona) -> (vrijeme, postotak) — zadnja predaja pobjeđuje
    celije: dict[tuple[str, str], tuple[str, int]] = {}
    imena: dict[str, str] = {}
    for r in rezultati:
        uid = _tekst(r.get("ucenik_id")).upper()
        if not uid:
            continue
        k = kolona_po_testu.get(_tekst(r.get("test_id")), _tekst(r.get("test_id")))
        if k not in kolone:
            continue
        imena.setdefault(uid, _tekst(r.get("ime_djeteta")))
        vrijeme = _tekst(r.get("vrijeme_predaje")) or _tekst(r.get("kreirano"))
        postotak = _postotak(r.get("bodovi"), r.get("bodovi_max"))
        if (uid, k) not in celije or vrijeme >= celije[(uid, k)][0]:
            celije[(uid, k)] = (vrijeme, postotak)

    redci = []
    for uid in sorted(imena, key=lambda u: (imena.get(u) or u, u)):
        red = {"Učenik": imena.get(uid) or "—", "Šifra": uid}
        vrijednosti = []
        for k in kolone:
            v = celije.get((uid, k))
            red[k] = v[1] if v else ""          # prazno = nije predao (Excel i Streamlit to lako čitaju)
            if v:
                vrijednosti.append(v[1])
        red["Prosjek"] = (int(sum(vrijednosti) / len(vrijednosti) + 0.5)
                          if vrijednosti else None)
        redci.append(red)
    return pd.DataFrame(redci)


def csv_matrica_razreda(testovi, rezultati, zadnjih: int = 8) -> str:
    df = matrica_razreda(testovi, rezultati, zadnjih)
    return df.to_csv(index=False, sep=";", lineterminator="\n") if not df.empty else ""


def rezultati_po_koloni(testovi, rezultati) -> dict[str, list[dict]]:
    """{naziv stupca (test ili serija): [predaje]} — serija se gleda kao cjelina."""
    mapa = {_tekst(t.get("test_id")): kolona_testa(t)
            for t in (testovi or []) if _tekst(t.get("test_id"))}
    izlaz: dict[str, list[dict]] = {}
    for r in rezultati or []:
        k = mapa.get(_tekst(r.get("test_id")))
        if k:
            izlaz.setdefault(k, []).append(r)
    return izlaz


def kolone_sa_predajama(testovi, rezultati) -> list[str]:
    """Nazivi stupaca s barem jednom predajom, poredani po vremenu objave (najstariji prvi)."""
    kad = {}
    for i, t in enumerate(testovi or []):
        tid = _tekst(t.get("test_id"))
        if not tid:
            continue
        k = kolona_testa(t)
        d = _tekst(t.get("kreirano")) or _tekst(t.get("otvara_od"))
        if k not in kad or (d, i) > kad[k]:
            kad[k] = (d, i)
    ima = set(rezultati_po_koloni(testovi, rezultati))
    return sorted(ima, key=lambda k: (kad.get(k, ("", -1)), k))


def usporedba_kolona(testovi, rezultati, kolona_a: str, kolona_b: str) -> dict:
    """Usporedba dva testa (ili dvije serije) — samo učenici koji su pisali OBA.

    Vraća {"ucenici": [...], "cjeline": [...], "broj": n, "prosjek_delta": x,
    "bolji": k, "losiji": m, "isti": z}. Razlika je u postotnim bodovima (B − A).
    """
    po_koloni = rezultati_po_koloni(testovi, rezultati)
    test_po_koloni: dict[str, dict] = {}
    for t in testovi or []:
        test_po_koloni.setdefault(kolona_testa(t), t)

    a = {_tekst(r.get("ucenik_id")).upper(): r for r in po_koloni.get(_tekst(kolona_a), [])}
    b = {_tekst(r.get("ucenik_id")).upper(): r for r in po_koloni.get(_tekst(kolona_b), [])}
    a.pop("", None)
    b.pop("", None)

    ucenici = []
    for uid in set(a) & set(b):
        pa = _postotak(a[uid].get("bodovi"), a[uid].get("bodovi_max"))
        pb = _postotak(b[uid].get("bodovi"), b[uid].get("bodovi_max"))
        ucenici.append({
            "ucenik_id": uid,
            "ime_djeteta": _tekst(b[uid].get("ime_djeteta")) or _tekst(a[uid].get("ime_djeteta")),
            "a": pa, "b": pb, "delta": pb - pa,
        })
    ucenici.sort(key=lambda u: (-u["delta"], u["ime_djeteta"] or u["ucenik_id"]))

    # cjeline: ista cjelina u oba testa (samo ako su cjeline zamrznute), također SAMO
    # za učenike koji su pisali oba testa — da usporedba bude po istim ljudima
    zajednicki = set(a) & set(b)
    cj_a = {s["cjelina"]: s["postotak"]
            for s in uspjeh_po_cjelinama(test_po_koloni.get(_tekst(kolona_a), {}),
                                         [a[u] for u in zajednicki])}
    cj_b = {s["cjelina"]: s["postotak"]
            for s in uspjeh_po_cjelinama(test_po_koloni.get(_tekst(kolona_b), {}),
                                         [b[u] for u in zajednicki])}
    cjeline = []
    for naziv in sorted(set(cj_a) | set(cj_b)):
        pa, pb = cj_a.get(naziv), cj_b.get(naziv)
        cjeline.append({"cjelina": naziv, "a": pa, "b": pb,
                        "delta": (pb - pa) if (pa is not None and pb is not None) else None})
    cjeline.sort(key=lambda c: (c["delta"] if c["delta"] is not None else 0))

    delte = [u["delta"] for u in ucenici]
    return {
        "ucenici": ucenici,
        "cjeline": cjeline,
        "broj": len(ucenici),
        "prosjek_delta": int(round(sum(delte) / len(delte))) if delte else 0,
        "bolji": sum(1 for d in delte if d > 0),
        "losiji": sum(1 for d in delte if d < 0),
        "isti": sum(1 for d in delte if d == 0),
    }


def tablica_usporedbe_ucenika(rez) -> "object":
    import pandas as pd

    return pd.DataFrame([{
        "Učenik": u["ime_djeteta"] or "—",
        "Šifra": u["ucenik_id"],
        "Prvi test (%)": u["a"],
        "Drugi test (%)": u["b"],
        "Razlika (bod. % )": u["delta"],
    } for u in (rez or {}).get("ucenici", [])])


def tablica_usporedbe_cjelina(rez) -> "object":
    import pandas as pd

    return pd.DataFrame([{
        "Cjelina": c["cjelina"],
        "Prvi test (%)": c["a"],
        "Drugi test (%)": c["b"],
        "Razlika (bod. % )": c["delta"],
    } for c in (rez or {}).get("cjeline", [])])


def indeks_baze(zadaci) -> dict[str, dict]:
    """{id zadatka: redak iz taba `Zadaci`} — za usporedbu sa zamrznutim testom."""
    return {_tekst(z.get("id")): z for z in (zadaci or []) if _tekst(z.get("id"))}


def integritet_testa(test, baza) -> dict:
    """Usporedi zamrznuti test s današnjim stanjem baze.

    Vraća {"test_id","naziv","promijenjen_odgovor","promijenjen_tekst","nema_u_bazi"} —
    popise ID-eva. `promijenjen_odgovor` je najvažniji: učenik se ocjenjuje po STABOM
    (zamrznutom) odgovoru, pa ako je Caki u bazi ispravio rješenje, test i dalje traži staro.
    """
    baza = baza if isinstance(baza, dict) else indeks_baze(baza)
    promijenjen_odgovor, promijenjen_tekst, nema = [], [], []

    for i, z in enumerate(zadaci_iz_testa(test), start=1):
        zid = _tekst(z.get("id"))
        if not zid:
            continue
        trenutni = baza.get(zid)
        if trenutni is None:
            nema.append(zid)
            continue
        if _tekst(trenutni.get("konacan_odgovor")) != _tekst(z.get("odgovor")):
            promijenjen_odgovor.append(zid)
        if _tekst(trenutni.get("tekst_zadatka_latex")) != _tekst(z.get("tekst")):
            promijenjen_tekst.append(zid)

    return {
        "test_id": _tekst(test.get("test_id")),
        "naziv": _tekst(test.get("naziv")),
        "promijenjen_odgovor": promijenjen_odgovor,
        "promijenjen_tekst": promijenjen_tekst,
        "nema_u_bazi": nema,
    }


def integritet_svih(testovi, zadaci_baze) -> list[dict]:
    """Samoprovjera svih objavljenih testova prema bazi (samo oni s nalazima)."""
    baza = zadaci_baze if isinstance(zadaci_baze, dict) else indeks_baze(zadaci_baze)
    nalazi = []
    for t in testovi or []:
        rez = integritet_testa(t, baza)
        if rez["promijenjen_odgovor"] or rez["promijenjen_tekst"] or rez["nema_u_bazi"]:
            nalazi.append(rez)
    return nalazi


def tablica_integriteta(nalazi):
    import pandas as pd

    return pd.DataFrame([{
        "Test": n["test_id"],
        "Naziv": n["naziv"],
        "Odgovor promijenjen u bazi": ", ".join(n["promijenjen_odgovor"]) or "—",
        "Tekst promijenjen": len(n["promijenjen_tekst"]),
        "Nema u bazi": ", ".join(n["nema_u_bazi"]) or "—",
    } for n in nalazi or []])


# ============================================================
# Po učeniku (povijest kroz više testova)
# ============================================================

def ucenici_s_rezultatima(rezultati) -> list[dict]:
    """Učenici koji imaju barem jednu predaju: šifra, ime, broj testova, prosjek %."""
    grupa: dict[str, dict] = {}
    for r in rezultati or []:
        uid = _tekst(r.get("ucenik_id")).upper()
        if not uid:
            continue
        s = grupa.setdefault(uid, {"ucenik_id": uid, "ime_djeteta": "",
                                   "testova": 0, "_zbroj": 0})
        s["testova"] += 1
        s["_zbroj"] += _postotak(r.get("bodovi"), r.get("bodovi_max"))
        if not s["ime_djeteta"]:
            s["ime_djeteta"] = _tekst(r.get("ime_djeteta"))

    izlaz = list(grupa.values())
    for s in izlaz:
        s["prosjek"] = int(round(s.pop("_zbroj") / s["testova"])) if s["testova"] else 0
    izlaz.sort(key=lambda s: (s["ime_djeteta"] or s["ucenik_id"], s["ucenik_id"]))
    return izlaz


def povijest_ucenika(rezultati, ucenik_id) -> list[dict]:
    """Sve predaje jednog učenika, najnovija prva."""
    uid = _tekst(ucenik_id).upper()
    redci = [dict(r) for r in (rezultati or [])
             if _tekst(r.get("ucenik_id")).upper() == uid]
    redci.sort(key=lambda r: (_tekst(r.get("vrijeme_predaje")) or _tekst(r.get("kreirano")),
                              _tekst(r.get("test_id"))), reverse=True)
    return redci


def sazetak_ucenika(rezultati, ucenik_id) -> dict:
    """Brojevi za jednog učenika (isti oblik kao `sazetak`, plus ime)."""
    povijest = povijest_ucenika(rezultati, ucenik_id)
    rez = sazetak(povijest)
    rez["ime_djeteta"] = _tekst(povijest[0].get("ime_djeteta")) if povijest else ""
    rez["ucenik_id"] = _tekst(ucenik_id).upper()
    return rez


def slabe_cjeline_ucenika(rezultati, testovi, ucenik_id) -> list[dict]:
    """Cjeline iz svih njegovih testova, spojene — od najslabije.

    Za testove bez cjeline u JSON-u redak ide pod „— bez cjeline —” (da se ne izgubi).
    """
    uid = _tekst(ucenik_id).upper()
    po_cjelini: dict[str, dict] = {}

    for r in rezultati or []:
        if _tekst(r.get("ucenik_id")).upper() != uid:
            continue
        test = nadji_test(testovi, r.get("test_id"))
        zadaci = zadaci_iz_testa(test) if test else []
        for i, d in enumerate(detalji_iz_retka(r)):
            if not isinstance(d, dict):
                continue
            cj = _cjelina_zadatka(zadaci[i]) if i < len(zadaci) else "— bez cjeline —"
            s = po_cjelini.setdefault(cj, {"cjelina": cj, "tocno": 0, "netocno": 0, "ukupno": 0})
            s["ukupno"] += 1
            if d.get("tocno"):
                s["tocno"] += 1
            else:
                s["netocno"] += 1

    izlaz = list(po_cjelini.values())
    for s in izlaz:
        s["postotak"] = int(round(100 * s["tocno"] / s["ukupno"])) if s["ukupno"] else 0
        s["zadataka"] = s["ukupno"]        # isti oblik kao uspjeh_po_cjelinama (za istu tablicu)
    izlaz.sort(key=lambda s: (s["postotak"], -s["ukupno"], s["cjelina"]))
    return izlaz


def _bloom_razina(z) -> str:
    """Bloom razina zadatka ('1'–'5') ili '' ako nije označena. Oznaka je u zamrznutom testu."""
    b = _tekst((z or {}).get("bloom"))
    return b if b in _online.BLOOM_NAZIVI else ""


def bloom_profil_ucenika(rezultati, testovi, ucenik_id) -> list[dict]:
    """Uspjeh po Bloomovim razinama kroz SVE testove učenika (samo označeni zadaci).

    Odgovara na pitanje koje se brojkom ne može odgovoriti: „zna formule, ali ih ne prenosi na
    zadatak” = visoke razine 1–2, niske 3–4. Razina se čita iz ZAMRZNUTE kopije u testu.
    """
    uid = _tekst(ucenik_id).upper()
    po: dict[str, dict] = {}
    for r in rezultati or []:
        if _tekst(r.get("ucenik_id")).upper() != uid:
            continue
        test = nadji_test(testovi, r.get("test_id"))
        zadaci = zadaci_iz_testa(test) if test else []
        for i, d in enumerate(detalji_iz_retka(r)):
            if not isinstance(d, dict) or i >= len(zadaci):
                continue
            razina = _bloom_razina(zadaci[i])
            if not razina:
                continue
            s = po.setdefault(razina, {"razina": razina, "naziv": _online.BLOOM_NAZIVI[razina],
                                       "tocno": 0, "ukupno": 0})
            s["ukupno"] += 1
            if d.get("tocno"):
                s["tocno"] += 1
    izlaz = list(po.values())
    for s in izlaz:
        s["postotak"] = int(round(100 * s["tocno"] / s["ukupno"])) if s["ukupno"] else 0
    izlaz.sort(key=lambda s: s["razina"])
    return izlaz


def tablica_bloom(profil):
    """Profil po Bloom razinama kao pandas tablica."""
    import pandas as pd
    return pd.DataFrame([{
        "Razina": f"{s['razina']} · {s['naziv']}",
        "Zadataka": s["ukupno"],
        "Točno": s["tocno"],
        "Uspjeh": s["postotak"],
    } for s in (profil or [])])


def nacrt_testa(test) -> dict:
    """Raspodjela zadataka po Bloom razinama + upozorenja o VALJANOSTI testa (nacrt).

    Ovo je provjera kakvoće testa, ne učenika: test koji mjeri samo razinu 1 ne pokazuje razumije
    li učenik gradivo, a test bez razine 4 ne pokazuje može li znanje prenijeti.
    """
    zadaci = zadaci_iz_testa(test)
    brojevi = {k: 0 for k in _online.BLOOM_NAZIVI}
    neoznaceno = 0
    for z in zadaci:
        b = _bloom_razina(z)
        if b:
            brojevi[b] += 1
        else:
            neoznaceno += 1
    ukupno = len(zadaci)
    oznaceno = ukupno - neoznaceno
    upozorenja = []
    if neoznaceno:
        upozorenja.append(f"{neoznaceno} od {ukupno} zadataka nema Bloom razinu — analiza po "
                          "razinama ih preskače (označavaju se u Test Builderu, uz Bodove).")
    if oznaceno >= 5:
        naj = max(brojevi, key=lambda k: brojevi[k])
        if brojevi[naj] / oznaceno > 0.7:
            upozorenja.append(f"{brojevi[naj]} od {oznaceno} označenih zadataka je razina "
                              f"{naj} ({_online.BLOOM_NAZIVI[naj]}) — test mjeri uglavnom jednu vještinu.")
        if brojevi["4"] == 0:
            upozorenja.append("Nijedan zadatak nije razina 4 (Analiziraj) — test ne pokazuje može li "
                              "učenik prenijeti znanje na novi zadatak.")
        if brojevi["1"] / oznaceno > 0.4:
            upozorenja.append(f"{brojevi['1']} zadataka je razina 1 (Zapamti) — ocjena može nahraniti "
                              "znanje koje učenik ne zna primijeniti.")
    return {"ukupno": ukupno, "oznaceno": oznaceno, "neoznaceno": neoznaceno,
            "po_razini": [{"razina": k, "naziv": v, "zadataka": brojevi[k]} for k, v in
                          _online.BLOOM_NAZIVI.items()],
            "upozorenja": upozorenja}


def tablica_nacrta(nacrt):
    """Raspodjela zadataka po razinama kao pandas tablica."""
    import pandas as pd
    return pd.DataFrame([{
        "Razina": f"{s['razina']} · {s['naziv']}",
        "Zadataka": s["zadataka"],
        "Udio": (f"{int(round(100 * s['zadataka'] / nacrt['oznaceno']))} %"
                 if nacrt.get("oznaceno") else "—"),
    } for s in (nacrt or {}).get("po_razini", [])])


def promaseni_zadaci(rezultati, testovi, ucenik_id, limit: int = 20) -> list[dict]:
    """Zadaci koje učenik nije riješio točno (kroz sve testove), najnoviji prvi."""
    uid = _tekst(ucenik_id).upper()
    izlaz: list[dict] = []

    for r in povijest_ucenika(rezultati, uid):
        test = nadji_test(testovi, r.get("test_id"))
        zadaci = zadaci_iz_testa(test) if test else []
        for i, d in enumerate(detalji_iz_retka(r)):
            if not isinstance(d, dict) or d.get("tocno"):
                continue
            z = zadaci[i] if i < len(zadaci) else {}
            izlaz.append({
                "datum": _tekst(r.get("vrijeme_predaje"))[:10],
                "test": _tekst(r.get("naziv_testa")),
                "zadatak": _tekst(z.get("id")) or _tekst(d.get("id")),
                "tekst": kratak_tekst(z.get("tekst"), 80),
                "cjelina": _cjelina_zadatka(z),
                "odgovor": _tekst(d.get("odgovor")),
                "ocekivano": _tekst(d.get("ocekivano")),
            })
    return izlaz[:limit]


def tekst_sazetka_za_roditelja(rezultati, testovi, ucenik_id) -> str:
    """Kratak tekst (za WhatsApp/mail) — samo rezultati i što vježbati, bez internih bilješki."""
    povijest = povijest_ucenika(rezultati, ucenik_id)
    if not povijest:
        return ""
    ime = _tekst(povijest[0].get("ime_djeteta")) or _tekst(ucenik_id).upper()
    redci = [f"Testovi — {ime} ({_tekst(ucenik_id).upper()})"]
    for r in sorted(povijest, key=lambda x: _tekst(x.get("vrijeme_predaje"))):
        redci.append(
            f"• {_tekst(r.get('naziv_testa'))} ({_tekst(r.get('vrijeme_predaje'))[:10]}) — "
            f"{_tekst(r.get('bodovi'))}/{_tekst(r.get('bodovi_max'))} "
            f"({_postotak(r.get('bodovi'), r.get('bodovi_max'))} %)")
    cjeline = [s for s in slabe_cjeline_ucenika(rezultati, testovi, ucenik_id)
               if s["ukupno"] >= 2 and s["cjelina"] != "— bez cjeline —"][:3]
    if cjeline:
        redci.append("Najviše za vježbati: " +
                     ", ".join(f"{s['cjelina']} ({s['postotak']} %)" for s in cjeline) + ".")
    # 21.10.2026.: rješenja se u portalu otvaraju TEK nakon roka, pa tekst to mora reći točno
    # (prije je pisalo samo „Detalji i točni odgovori”, što je bilo netočno — portal ih nije ni imao).
    redci.append("Pregled rješenja: Moj CAKI → 📝 Testovi (otvara se odmah po isteku roka za pisanje).")
    return "\n".join(redci)


# ============================================================
# Tablice za prikaz (pandas se uvozi unutra — modul mora raditi i bez njega u testovima)
# ============================================================

def tablica_testova(testovi, rezultati):
    import pandas as pd

    prebroj = {}
    for r in rezultati or []:
        tid = _tekst(r.get("test_id"))
        prebroj[tid] = prebroj.get(tid, 0) + 1

    return pd.DataFrame([{
        "ID": _tekst(t.get("test_id")),
        "Naziv": _tekst(t.get("naziv")),
        "Kome": _kome_kratko(t),
        "Serija": serija_iz_retka(t),
        "Zadataka": _tekst(t.get("broj_zadataka")) or str(len(zadaci_iz_testa(t))),
        "Bodova": _tekst(t.get("bodovi_ukupno")),
        "Minuta": _tekst(t.get("trajanje_min")),
        "Otvoren": f"{_datum(t.get('otvara_od')) or '—'} – {_datum(t.get('zatvara_do')) or '—'}",
        "Aktivan": "Da" if _aktivan(t) else "Ne",
        "Predano": prebroj.get(_tekst(t.get("test_id")), 0),
    } for t in testovi or []])


def _kome_kratko(test) -> str:
    """Stupac „Kome” u tablici: šifra učenika, inače program, inače svi."""
    ucenik = _tekst((test or {}).get("ucenik_id")).upper()
    if ucenik:
        return ucenik
    return _tekst((test or {}).get("program")) or "svi"


def tablica_rezultata(rezultati):
    import pandas as pd

    redci = [{
        "Učenik": _tekst(r.get("ime_djeteta")) or "—",
        "Šifra": _tekst(r.get("ucenik_id")).upper(),
        "Bodovi": _tekst(r.get("bodovi")),
        "Od": _tekst(r.get("bodovi_max")),
        "%": _postotak(r.get("bodovi"), r.get("bodovi_max")),
        "Trajanje (min)": int(round(_broj(r.get("trajanje_s")) / 60)),
        "Predano": _tekst(r.get("vrijeme_predaje"))[:16],
        "Status": _tekst(r.get("status")),
    } for r in rezultati or []]
    redci.sort(key=lambda d: d["%"])          # najslabiji prvi — to Cakija zanima
    return pd.DataFrame(redci)


def tablica_uspjeha_po_zadatku(uspjeh):
    import pandas as pd

    return pd.DataFrame([{
        "Zadatak": s["redni"],
        "Kratki tekst": s["tekst"],
        "Točno": s["tocno"],
        "Netočno": s["netocno"],
        "Ukupno": s["ukupno"],
        "%": s["postotak"],
        "Bodovi": s["bodovi"],
    } for s in uspjeh or []])


def tablica_po_cjelinama(uspjeh):
    import pandas as pd

    return pd.DataFrame([{
        "Cjelina": s["cjelina"],
        "Zadataka": s["zadataka"],
        "Točno": s["tocno"],
        "Netočno": s["netocno"],
        "Odgovora": s["ukupno"],
        "%": s["postotak"],
    } for s in uspjeh or []])


def tablica_spremnosti(rez) -> "object":
    import pandas as pd

    return pd.DataFrame([{
        "Cjelina": s["cjelina"],
        "Zadataka": s["ukupno"],
        "Spremno": s["spremno"],
        "%": s["postotak"],
        "Skupine": s["skupine"],
        "Višestruki": s["visestruki"],
    } for s in (rez or {}).get("po_cjelini", [])])


# ============================================================
# 🧩 Pokrivenost baze po cjelinama i potpoglavljima (21.10.2026.)
# ============================================================

def pokrivenost_cjelina(zadaci, cjeline_iz_sifrarnika=None) -> dict:
    """Je li baza POKRIVENA po cjelinama i potpoglavljima — nije isto što `spremnost_baze`.

    `spremnost_baze` odgovara „može li se zadatak objaviti”; ovo odgovara „postoji li ijedan
    zadatak iz te cjeline”. Cakijev nalaz iz fizike (21.10.2026.): 1842 zadatka, ali samo 21 od
    55 cjelina iz šifrarnika ima ijedan zadatak, a potpoglavlje nema nijedan.

    `cjeline_iz_sifrarnika` = popis cjelina iz taba `Sifrarnik_cjelina` (nije obavezan — bez njega
    se ne računaju prazne cjeline ni cjeline izvan šifrarnika).
    """
    po: dict[str, dict] = {}
    bez_cjeline = 0
    s_potpoglavljem = 0
    for z in zadaci or []:
        cj = _tekst(z.get("cjelina"))
        if not cj:
            bez_cjeline += 1
            cj = "— bez cjeline —"
        s = po.setdefault(cj, {"cjelina": cj, "zadataka": 0, "potpoglavlja": set(), "spremno": 0})
        s["zadataka"] += 1
        pp = _tekst(z.get("potpoglavlje"))
        if pp:
            s["potpoglavlja"].add(pp)
            s_potpoglavljem += 1
        if _tekst(z.get("konacan_odgovor")) and _tekst(z.get("uloga")).lower() != "skupina":
            s["spremno"] += 1

    redci = []
    for s in po.values():
        redci.append({"cjelina": s["cjelina"], "zadataka": s["zadataka"],
                      "potpoglavlja": len(s["potpoglavlja"]), "spremno": s["spremno"]})
    redci.sort(key=lambda r: (r["zadataka"], r["cjelina"]))

    ukupno = len(zadaci or [])
    rez = {
        "ukupno": ukupno,
        "cjelina": {"razlicitih": len(po), "bez_cjeline": bez_cjeline},
        "potpoglavlje": {"popunjeno": s_potpoglavljem,
                         "postotak": int(round(100 * s_potpoglavljem / ukupno)) if ukupno else 0},
        "po_cjelini": redci,
        "prazne_cjeline": [],
        "izvan_sifrarnika": [],
        "tanke": [r["cjelina"] for r in redci if 0 < r["zadataka"] <= 5],
    }

    if cjeline_iz_sifrarnika:
        sif = [c for c in (_tekst(x) for x in cjeline_iz_sifrarnika) if c]
        ima = {r["cjelina"] for r in redci if r["cjelina"] != "— bez cjeline —"}
        rez["prazne_cjeline"] = sorted(set(sif) - ima)
        rez["izvan_sifrarnika"] = sorted(ima - set(sif))
    return rez


def tablica_pokrivenosti(rez) -> "object":
    """Cjeline poredane od najmanje pokrivene (prva je ona koju treba popuniti)."""
    import pandas as pd

    return pd.DataFrame([{
        "Cjelina": r["cjelina"],
        "Zadataka": r["zadataka"],
        "Spremno": r["spremno"],
        "Potpoglavlja": r["potpoglavlja"],
        "Status": ("🚨 prazna" if r["zadataka"] == 0 else
                   ("⚠️ tanka (≤5)" if r["zadataka"] <= 5 else "")),
    } for r in (rez or {}).get("po_cjelini", [])])


def csv_pokrivenosti(rez) -> str:
    """CSV pokrivenosti po cjelinama (za Excel) — uključuje i prazne cjeline iz šifrarnika."""
    redci = ["cjelina,zadataka,spremno,potpoglavlja,status"]
    for r in (rez or {}).get("po_cjelini", []):
        redci.append(f"{r['cjelina']},{r['zadataka']},{r['spremno']},{r['potpoglavlja']},")
    for c in (rez or {}).get("prazne_cjeline", []):
        redci.append(f"{c},0,0,0,prazna")
    return "\n".join(redci)


def csv_spremnosti(rez) -> str:
    linije = ["cjelina;zadataka;spremno;postotak;skupine;visestruki"]
    for s in (rez or {}).get("po_cjelini", []):
        linije.append(";".join([_tekst(s["cjelina"]).replace(";", ","), str(s["ukupno"]),
                                str(s["spremno"]), str(s["postotak"]), str(s["skupine"]),
                                str(s["visestruki"])]))
    return "\n".join(linije)


def tablica_povijesti(povijest):
    import pandas as pd

    return pd.DataFrame([{
        "Datum": _tekst(r.get("vrijeme_predaje"))[:16],
        "Test": _tekst(r.get("naziv_testa")),
        "Bodovi": _tekst(r.get("bodovi")),
        "Od": _tekst(r.get("bodovi_max")),
        "%": _postotak(r.get("bodovi"), r.get("bodovi_max")),
        "Trajanje (min)": int(round(_broj(r.get("trajanje_s")) / 60)),
        "Status": _tekst(r.get("status")),
    } for r in povijest or []])


def tablica_promasenih(promaseni):
    import pandas as pd

    return pd.DataFrame([{
        "Datum": p["datum"],
        "Test": p["test"],
        "Cjelina": p["cjelina"],
        "Zadatak": p["zadatak"],
        "Kratki tekst": p["tekst"],
        "Upisao": p["odgovor"],
        "Točno": p["ocekivano"],
    } for p in promaseni or []])


# ============================================================
# CSV (za Excel — Caki dalje radi svojom tablicom)
# ============================================================

def csv_rezultata(test, rezultati) -> str:
    """Rezultati jednog testa + jedan stupac po zadatku (1 = točno, 0 = netočno, prazno = nema detalja)."""
    zadaci = zadaci_iz_testa(test)
    zaglavlje = ["ucenik_id", "ime_djeteta", "bodovi", "bodovi_max", "postotak",
                 "trajanje_s", "vrijeme_predaje", "status"] + [f"Z{i + 1}" for i in range(len(zadaci))]
    linije = [";".join(zaglavlje)]
    for r in rezultati or []:
        detalji = detalji_iz_retka(r)
        po_zadatku = {}
        for i, d in enumerate(detalji):
            k = i
            if _tekst((d or {}).get("id")):
                for j, z in enumerate(zadaci):
                    if _tekst(z.get("id")) == _tekst(d.get("id")):
                        k = j
                        break
            if 0 <= k < len(zadaci):
                po_zadatku[k] = "1" if (d or {}).get("tocno") else "0"
        red = [
            _tekst(r.get("ucenik_id")).upper(),
            _tekst(r.get("ime_djeteta")),
            _tekst(r.get("bodovi")),
            _tekst(r.get("bodovi_max")),
            str(_postotak(r.get("bodovi"), r.get("bodovi_max"))),
            _tekst(r.get("trajanje_s")),
            _tekst(r.get("vrijeme_predaje")),
            _tekst(r.get("status")),
        ] + [po_zadatku.get(i, "") for i in range(len(zadaci))]
        linije.append(";".join(red))
    return "\n".join(linije)


def csv_uspjeha(uspjeh) -> str:
    linije = ["zadatak;id;tocno;netocno;ukupno;postotak;bodovi;kratki_tekst"]
    for s in uspjeh or []:
        linije.append(";".join([
            str(s["redni"]), _tekst(s["id"]), str(s["tocno"]), str(s["netocno"]),
            str(s["ukupno"]), str(s["postotak"]), str(s["bodovi"]), _tekst(s["tekst"]),
        ]))
    return "\n".join(linije)


# ============================================================
# Provjere prije spremanja
# ============================================================

# ============================================================
# 🧪 Provjera nakon pusha — je li sve spojeno
# ============================================================

def dijagnostika(sheet) -> list[dict]:
    """Popis provjera nakon deploya: koji tabovi postoje i imaju li očekivane stupce.

    Vraća [{"naziv", "status": "ok"|"napomena"|"greška", "opis"}]. Ne mijenja ništa —
    samo čita jedan popis tabova i po zaglavlje. Namijenjeno kartici 🩺 Provjere, da Caki
    nakon Push + Reboot u jednom pogledu vidi je li sustav spojen.
    """
    try:
        tabovi = {w.title: w for w in sheet.worksheets()}
    except Exception as e:                              # noqa: BLE001
        return [{"naziv": "CRM Sheet", "status": "greška",
                 "opis": f"ne može se otvoriti ({e}) — provjeri SHEET_ID i prava računa"}]

    nalazi = [{"naziv": "CRM Sheet", "status": "ok",
               "opis": f"otvoren, {len(tabovi)} tabova"}]

    def _stupci(naziv_taba: str, obavezni: tuple) -> None:
        ws = tabovi.get(naziv_taba)
        if ws is None:
            nalazi.append({"naziv": naziv_taba, "status": "napomena",
                           "opis": "tab još ne postoji — nastaje sam pri prvom upisu"})
            return
        try:
            zaglavlje = [_tekst(h) for h in ws.row_values(1)]
        except Exception as e:                          # noqa: BLE001
            nalazi.append({"naziv": naziv_taba, "status": "greška",
                           "opis": f"zaglavlje se ne može pročitati ({e})"})
            return
        fali = [h for h in obavezni if h not in zaglavlje]
        if fali:
            nalazi.append({"naziv": naziv_taba, "status": "napomena",
                           "opis": "nedostaju stupci: " + ", ".join(fali)})
        else:
            nalazi.append({"naziv": naziv_taba, "status": "ok",
                           "opis": f"{len(zaglavlje)} stupaca, sve na mjestu"})

    _stupci(TEST_TAB, ("test_id", "naziv", "zadaci_json", "aktivan", SERIJA_STUPAC))
    _stupci(REZ_TAB, ("rezultat_id", "test_id", "ucenik_id", "bodovi", "detalji_json"))
    _stupci(POCETAK_TAB, ("test_id", "ucenik_id", "pocetak"))

    ws_testovi = tabovi.get(TEST_TAB)
    if ws_testovi is not None:
        try:
            idovi = [_tekst(v) for v in ws_testovi.col_values(1)[1:] if _tekst(v)]
        except Exception:                               # noqa: BLE001
            idovi = []
        dupli = sorted({i for i in idovi if idovi.count(i) > 1})
        if dupli:
            nalazi.append({"naziv": "Jedinstveni ID-evi testova", "status": "greška",
                           "opis": "ponavlja se: " + ", ".join(dupli[:5])})
        elif idovi:
            nalazi.append({"naziv": "Jedinstveni ID-evi testova", "status": "ok",
                           "opis": f"{len(idovi)} testova, nijedan dvaput"})

    return nalazi


def sazetak_dijagnostike(nalazi) -> dict:
    """{"greska": n, "napomena": m, "ok": k} — za brzi prikaz na vrhu."""
    brojevi = {"greška": 0, "napomena": 0, "ok": 0}
    for n in nalazi or []:
        brojevi[n.get("status", "ok")] = brojevi.get(n.get("status", "ok"), 0) + 1
    return brojevi


def provjeri_izmjene(naziv, trajanje, otvara_od, zatvara_do) -> list[str]:
    """Popis grešaka za uređivanje testa (prazan = može se spremiti)."""
    greske: list[str] = []
    if not _tekst(naziv):
        greske.append("Naziv testa ne smije biti prazan — učenik ga vidi u portalu.")
    try:
        minuta = int(float(str(trajanje).replace(",", ".")))
    except (TypeError, ValueError):
        minuta = 0
    if not 5 <= minuta <= 240:
        greske.append("Trajanje mora biti između 5 i 240 minuta.")
    od, do = _datum(otvara_od), _datum(zatvara_do)
    if od and do and do < od:
        greske.append("Datum „otvoren do” je prije datuma „otvoren od”.")
    return greske


def problemi(testovi, rezultati, danas=None) -> list[dict]:
    """Što na objavljenim testovima smeta — za karticu 🩺 Provjere.

    Vraća [{"test_id", "naziv", "razina": "greška"|"upozorenje", "opis"}].
    """
    danas_str = _datum(danas or date.today())
    izlaz: list[dict] = []
    for t in testovi or []:
        tid, naziv = _tekst(t.get("test_id")), _tekst(t.get("naziv"))
        zadaci = zadaci_iz_testa(t)

        def dodaj(razina, opis):
            izlaz.append({"test_id": tid, "naziv": naziv, "razina": razina, "opis": opis})

        if not zadaci:
            dodaj("greška", "test nema čitljive zadatke (`zadaci_json`) — učenik ga ne može rješavati")
            continue

        bez_odgovora = [i + 1 for i, z in enumerate(zadaci) if not _tekst(z.get("odgovor"))]
        if bez_odgovora:
            dodaj("greška", "zadaci bez konačnog odgovora: "
                            + ", ".join(str(b) for b in bez_odgovora) + " — ne mogu se ocijeniti")

        velicina = len(str(t.get("zadaci_json") or ""))
        if velicina > GRANICA_CELIJE:
            dodaj("upozorenje", f"JSON testa ima {velicina} znakova — blizu granice ćelije "
                                f"({GRANICA_CELIJE}); podijeli test ako bude rastao")

        if _aktivan(t) and _datum(t.get("zatvara_do")) and _datum(t.get("zatvara_do")) < danas_str:
            dodaj("upozorenje", "još je aktivan, a rok je prošao — učenici ga više ne vide; "
                                "klikni ⏸️ Deaktiviraj da ne stoji u popisu")

        if _aktivan(t) and not (_datum(t.get("otvara_od")) and _datum(t.get("zatvara_do"))):
            dodaj("upozorenje", "nema puni rok („otvoren od” i „otvoren do”) — test se nudi "
                                "svaki dan dok ga ne deaktiviraš")

        if not filtruj_rezultate(rezultati, tid) and _aktivan(t) and \
                _datum(t.get("otvara_od")) and _datum(t.get("otvara_od")) < danas_str:
            dodaj("upozorenje", "otvoren je, a nema nijedne predaje — provjeri je li došao do učenika")
    return izlaz


# ============================================================
# Pisanje — samo tab Testovi_zakazani
# ============================================================

def _mapa_redaka(ws) -> dict[str, int]:
    """{test_id: broj retka (1-based)} iz stupca A."""
    return {_tekst(v): i + 1 for i, v in enumerate(ws.col_values(1)) if _tekst(v)}


def _redak_po_id(ws, test_id: str) -> int:
    """Broj retka (1-based) za test_id u stupcu A. Baca ValueError ako ga nema."""
    redak = _mapa_redaka(ws).get(_tekst(test_id))
    if not redak:
        raise ValueError(f"Test `{test_id}` nije u tabu `{TEST_TAB}` — osvježi stranicu.")
    return redak


def _kolone_taba(ws) -> dict[str, int]:
    zaglavlje = [_tekst(h) for h in ws.row_values(1)]
    return {h: i for i, h in enumerate(zaglavlje) if h}


def zatvori_test(sheet, test, cijela_serija: bool = False, testovi=None) -> list[str]:
    """22.10.2026. (Cakijev zahtjev): zatvori test **PRIJE roka** — rješenja se otvaraju odmah.

    Portal otvara rješenja kad je `danas > zatvara_do` (`rjesenja_dostupna`). Zato se rok
    postavlja na **jučer**: učenik više ne može pisati, a svi koji su predali odmah vide
    rješenja i točne odgovore. Vraća popis ID-eva zatvorenih testova.
    """
    jučer = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    redci = ([test] if not cijela_serija
             else testovi_serije(list(testovi or []), serija_iz_retka(test)))
    if not redci:
        redci = [test]
    idovi = []
    for redak in redci:
        tid = _tekst((redak or {}).get("test_id"))
        if not tid:
            continue
        azuriraj_test(sheet, tid, {"zatvara_do": jučer})
        idovi.append(tid)
    return idovi


def ima_stupac(sheet, stupac: str, tab: str = TEST_TAB) -> bool:
    """Postoji li stupac u zaglavlju taba — za značajke koje se dodaju s vremenom
    (npr. `pomoc`, `serija`): stare kopije taba nemaju ih dok se ne objavi novi test."""
    try:
        ws = sheet.worksheet(tab)
        return _tekst(stupac) in [_tekst(h) for h in ws.row_values(1)]
    except Exception:                                   # noqa: BLE001 — tab ne postoji
        return False


def _azuriraj_vise_redaka(sheet, redci, polja: dict) -> int:
    """Iste izmjene na više redaka u JEDNOM `batch_update` pozivu. Vraća broj redaka."""
    if not polja:
        raise ValueError("Nema što spremiti.")
    ws = sheet.worksheet(TEST_TAB)
    kolone = _kolone_taba(ws)
    nepoznato = [k for k in polja if k not in kolone]
    if nepoznato:
        raise ValueError("Tab `Testovi_zakazani` nema stupce: " + ", ".join(nepoznato))
    mapa = _mapa_redaka(ws)

    data, redci_pogodeni = [], set()
    for t in redci or []:
        redak = mapa.get(_tekst((t or {}).get("test_id")))
        if not redak:
            continue
        redci_pogodeni.add(redak)
        data.extend({"range": rowcol_to_a1(redak, kolone[k] + 1), "values": [[v]]}
                    for k, v in polja.items())
    if not data:
        raise ValueError("Nijedan redak nije pronađen u tabu — osvježi stranicu.")
    ws.batch_update(data, raw=True)
    return len(redci_pogodeni)


def azuriraj_test(sheet, test_id: str, polja: dict) -> int:
    """Mijenja SAMO predane ćelije retka tog testa. Vraća broj retka.

    Ne dopušta nepoznate stupce (bolje stati nego tiho upisati u pogrešno mjesto).
    """
    test_id = _tekst(test_id)
    if not polja:
        raise ValueError("Nema što spremiti.")
    ws = sheet.worksheet(TEST_TAB)
    redak = _redak_po_id(ws, test_id)
    kolone = _kolone_taba(ws)
    nepoznato = [k for k in polja if k not in kolone]
    if nepoznato:
        raise ValueError("Tab `Testovi_zakazani` nema stupce: " + ", ".join(nepoznato))
    ws.batch_update([
        {"range": rowcol_to_a1(redak, kolone[k] + 1), "values": [[v]]}
        for k, v in polja.items()
    ], raw=True)
    return redak


def azuriraj_seriju(sheet, testovi, serija, polja: dict) -> int:
    """Izmjena (npr. novi rok) za SVE retke jedne objave — jedan poziv prema Googleu."""
    redci = testovi_serije(testovi, serija)
    if not redci:
        raise ValueError("Serija nema nijedan redak — osvježi stranicu.")
    return _azuriraj_vise_redaka(sheet, redci, polja)


def postavi_aktivan(sheet, test_id: str, aktivan: bool) -> int:
    return azuriraj_test(sheet, test_id, {"aktivan": STATUS_AKTIVAN if aktivan else "Ne"})


def postavi_aktivan_seriju(sheet, testovi, serija, aktivan: bool) -> int:
    """Uključi/isključi CIJELU grupu testova odjednom (jedan poziv prema Googleu)."""
    redci = testovi_serije(testovi, serija)
    if not redci:
        raise ValueError("Serija nema nijedan redak — osvježi stranicu.")
    return _azuriraj_vise_redaka(sheet, redci,
                                 {"aktivan": STATUS_AKTIVAN if aktivan else "Ne"})


def _obrisi_redke_gdje(ws, stupac: int, vrijednosti: set[str]) -> int:
    """Briše retke u kojima je vrijednost u `stupac` (1-based) u zadanom skupu.

    Briše ODOZDO prema gore da se indeksi ne pomaknu. Vraća broj obrisanih redaka.
    """
    vrijednosti = {_tekst(v) for v in vrijednosti if _tekst(v)}
    if not vrijednosti:
        return 0
    u_tablici = [_tekst(v) for v in ws.col_values(stupac)]
    za_brisanje = [i + 1 for i, v in enumerate(u_tablici) if v in vrijednosti]
    for redak in sorted(za_brisanje, reverse=True):
        ws.delete_rows(redak)
    return len(za_brisanje)


def _obrisi_testove_i_rezultate(sheet, test_idovi: set[str], i_rezultate: bool) -> dict:
    ws_testovi = sheet.worksheet(TEST_TAB)
    broj_testova = _obrisi_redke_gdje(ws_testovi, 1, test_idovi)

    broj_rezultata = 0
    if i_rezultate:
        try:
            ws_rez = sheet.worksheet(REZ_TAB)
        except Exception:                               # noqa: BLE001 — tab još ne postoji
            ws_rez = None
        if ws_rez is not None:
            broj_rezultata = _obrisi_redke_gdje(ws_rez, 2, test_idovi)
    return {"testova": broj_testova, "rezultata": broj_rezultata}


def obrisi_test(sheet, test_id: str, i_rezultate: bool = True) -> dict:
    """TRAJNO briše test (i, po želji, njegove rezultate) — nestaje iz Moj CAKI i iz rezultata.

    Vraća {"testova": n, "rezultata": m}. Za „samo sakrij” koristi `postavi_aktivan(False)` —
    deaktiviran test učenik ne vidi, a rezultati ostaju.
    """
    tid = _tekst(test_id)
    if not tid:
        raise ValueError("Nema što obrisati — test nije odabran.")
    rez = _obrisi_testove_i_rezultate(sheet, {tid}, i_rezultate)
    if not rez["testova"]:
        raise ValueError(f"Test `{tid}` nije pronađen u tabu `{TEST_TAB}` — osvježi stranicu.")
    return rez


def obrisi_seriju(sheet, testovi, serija, i_rezultate: bool = True) -> dict:
    """TRAJNO briše sve retke jedne objave (grupa/kanta) i, po želji, njihove rezultate."""
    redci = testovi_serije(testovi, serija)
    idovi = {_tekst(t.get("test_id")) for t in redci if _tekst(t.get("test_id"))}
    if not idovi:
        raise ValueError("Serija nema nijedan redak — osvježi stranicu.")
    return _obrisi_testove_i_rezultate(sheet, idovi, i_rezultate)


def kloniraj_test(sheet, test_id: str, naziv: str = "", otvara_od: str = "",
                  zatvara_do: str = "", autor: str = "") -> dict:
    """Novi test s ISTIM zadacima (npr. ista vježba za drugu grupu ili drugi tjedan).

    Zamrznuti JSON se prepisuje u novi redak — izmjena izvornog testa ne dira kopiju.
    """
    stari = nadji_test(_online.load_testovi(sheet), test_id)
    if not stari:
        raise ValueError(f"Test `{_tekst(test_id)}` nije pronađen.")
    zadaci = zadaci_iz_testa(stari)
    if not zadaci:
        raise ValueError("Taj test nema čitljive zadatke — ne mogu ga klonirati.")

    return _online.objavi_test(
        sheet,
        zadaci=zadaci,
        naziv=_tekst(naziv) or (_tekst(stari.get("naziv")) + " (kopija)"),
        predmet=_tekst(stari.get("predmet")),
        ucenik_id=_tekst(stari.get("ucenik_id")),
        ime_djeteta=_tekst(stari.get("ime_djeteta")),
        program=_tekst(stari.get("program")),
        trajanje_min=int(_broj(stari.get("trajanje_min"), 45)),
        otvara_od=_datum(otvara_od) or _datum(stari.get("otvara_od")),
        zatvara_do=_datum(zatvara_do) or _datum(stari.get("zatvara_do")),
        aktivan=True,
        autor=_tekst(autor) or _tekst(stari.get("autor")),
        napomena=_tekst(stari.get("napomena")),
    )


def objavi_za_grupu(sheet, *, izvorni_test, ucenici, naziv: str = "", trajanje_min=None,
                    otvara_od: str = "", zatvara_do: str = "", serija: str = "",
                    autor: str = "") -> dict:
    """Zadaje POSTOJEĆI test cijeloj grupi: jedan redak po učeniku, svi pod istom serijom.

    Portal (`Moj CAKI`) ne treba mijenjati — bira test po `ucenik_id`, a svaki učenik iz
    grupe dobiva svoj redak. Upis ide u JEDNOM pozivu (Sheets write-kvota).

    Vraća {"serija": "...", "redci": [...]}.
    """
    zadaci = zadaci_iz_testa(izvorni_test)
    if not zadaci:
        raise ValueError("Izvorni test nema čitljive zadatke — ne može se zadati grupi.")
    if not ucenici:
        raise ValueError("Grupa nema nijednog učenika s potvrđenom rezervacijom.")

    oznaka = jedinstvena_serija(_online.load_testovi(sheet), serija or "serija")
    redci = _online.objavi_za_ucenike(
        sheet,
        zadaci=zadaci,
        ucenici=ucenici,
        naziv=_tekst(naziv) or _tekst(izvorni_test.get("naziv")),
        predmet=_tekst(izvorni_test.get("predmet")),
        program=_tekst(izvorni_test.get("program")),
        trajanje_min=int(_broj(trajanje_min if trajanje_min is not None
                               else izvorni_test.get("trajanje_min"), 45)),
        otvara_od=_datum(otvara_od) or _datum(izvorni_test.get("otvara_od")),
        zatvara_do=_datum(zatvara_do) or _datum(izvorni_test.get("zatvara_do")),
        aktivan=True,
        autor=_tekst(autor),
        napomena=_tekst(izvorni_test.get("napomena")),
        serija=oznaka,
    )
    return {"serija": oznaka, "redci": redci}


# ============================================================
# UI
# ============================================================

def _poruka(st) -> None:
    """Prikaži poruku postavljenu prije st.rerun() (isti obrazac kao u admin panelu)."""
    zapis = st.session_state.pop("testovi_poruka", None)
    if not zapis:
        return
    vrsta, tekst = zapis
    {"success": st.success, "warning": st.warning, "error": st.error,
     "info": st.info}.get(vrsta, st.info)(tekst)


def _osvjezi(st, vrsta: str, tekst: str) -> None:
    """Poruka + rerun; stranica na vrhu počisti keš kad vidi zastavicu."""
    st.session_state["testovi_poruka"] = (vrsta, tekst)
    st.session_state["testovi_osvjezi"] = True
    st.rerun()


def prikazi_pregled(st, test) -> None:
    """„Kako test izgleda” — s točnim odgovorima, da Caki uhvati grešku prije učenika."""
    zadaci = zadaci_iz_testa(test)
    if not zadaci:
        st.warning("Taj test nema čitljive zadatke.")
        return
    for i, z in enumerate(zadaci, start=1):
        st.markdown(f"**{i}.** {_tekst(z.get('tekst'))}")
        opcije = [_tekst(o) for o in (z.get("opcije") or []) if _tekst(o)]
        if opcije:
            st.caption(" · ".join(f"{chr(65 + k)}) {o}" for k, o in enumerate(opcije)))
        st.caption(f"✅ točno: **{_tekst(z.get('odgovor')) or '— nema —'}** · "
                   f"{_broj(z.get('bodovi'), 1.0):g} bod. · zadatak `{_tekst(z.get('id')) or '?'}`"
                   + (f" · 🖼️ {_tekst(z.get('slika'))}" if _tekst(z.get("slika")) else ""))


def prikazi_stranicu(st, sheet, testovi, rezultati, predmet: str = "",
                     danas=None, autor: str = "", grupe=None, kante=None,
                     ucitaj_bazu=None, ucitaj_sifrarnik=None) -> None:
    """Cijela stranica 📝 Testovi: popis, uređivanje, pregled, rezultati, zadavanje grupi,
    spremnost baze i provjere.

    `ucitaj_bazu` je funkcija bez argumenata koja vraća retke taba `Zadaci` — poziva se
    SAMO kad Caki klikne „Učitaj” (20.000 redaka se ne čita pri svakom otvaranju stranice).
    """
    testovi = list(testovi or [])
    rezultati = list(rezultati or [])
    _poruka(st)

    if not testovi:
        st.info("Još nema objavljenih testova. Složi test u 🧪 **Test Builder** i na dnu stranice "
                "klikni **📝 Objavi kao online test** — nakon toga se pojavljuje ovdje.")
        return

    aktivni = [t for t in testovi if _aktivan(t)]
    ukupno = sazetak(rezultati)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Objavljenih testova", len(testovi),
              help="Svi testovi u tabu `Testovi_zakazani` (CRM Sheet).")
    m2.metric("Aktivnih", len(aktivni))
    m3.metric("Predaja", len(rezultati))
    m4.metric("Prosječan rezultat", f"{ukupno['prosjek']} %" if ukupno["broj"] else "—")

    tab_popis, tab_rezultati, tab_ucenik, tab_zadaj, tab_baza, tab_provjere = st.tabs(
        ["📋 Testovi", "📊 Rezultati", "👤 Po učeniku", "👥 Zadaj grupi",
         "🎯 Spremnost baze", "🩺 Provjere"])

    # ------------------------------------------------ 📋 popis + uređivanje
    with tab_popis:
        # 22.10.2026.: 🧾 NACRTI — test spremljen ali NEobjavljen (`aktivan=Ne`, `serija=NACRT`).
        nacrti = [x for x in testovi or [] if _tekst(x.get("aktivan")).lower() in ("ne", "0", "false")]
        if nacrti:
            with st.expander(f"🧾 Nacrti — spremljeni, još neobjavljeni ({len(nacrti)})", expanded=False):
                st.caption("Nacrt vidiš samo ti. Odaberi kome ide i objavi — učenici ga do tada ne vide.")
                opcije_n = {_tekst(x.get("test_id")): x for x in nacrti if _tekst(x.get("test_id"))}
                odabrani_n = st.selectbox(
                    "Nacrt", list(opcije_n),
                    format_func=lambda k: f"{_tekst(opcije_n[k].get('naziv')) or k} · "
                                          f"{_tekst(opcije_n[k].get('broj_zadataka'))} zad.",
                    key="ta_nacrt_odabir")
                nacrt = opcije_n.get(odabrani_n) or {}
                publika_n = st.radio("Kome objaviti", ["grupa", "ucenici"],
                                     format_func=lambda k: PUBLIKE_UI[k], horizontal=True,
                                     key="ta_nacrt_publika")
                cilj_g = []
                if publika_n == "grupa":
                    sve_g = {g["kod"]: g for g in (list(kante or []) + list(grupe or []))
                             if (g or {}).get("ucenici")}
                    if not sve_g:
                        st.caption("Nema grupa ni kanti s učenicima.")
                    odab_g = st.multiselect(
                        "Grupa / kanta", list(sve_g),
                        format_func=lambda k: f"{sve_g[k].get('naziv', k)} ({len(sve_g[k]['ucenici'])} uč.)",
                        key="ta_nacrt_grupe")
                    cilj_g = [sve_g[k] for k in odab_g]
                rucno_n = st.text_input("Ili šifre učenika (zarez)", key="ta_nacrt_sifre",
                                        placeholder="AA1111, BB2222")
                ucenici_n = []
                for g in cilj_g:
                    ucenici_n += list(g.get("ucenici") or [])
                ucenici_n += [{"ucenik_id": x.strip().upper(), "ime_djeteta": ""}
                              for x in _tekst(rucno_n).split(",") if x.strip()]
                st.caption(f"Test ide za **{len({(u.get('ucenik_id') or '').upper() for u in ucenici_n})}** učenika.")
                if st.button("📝 Objavi odabranima", key="ta_nacrt_objavi", type="primary",
                             disabled=not ucenici_n):
                    try:
                        redci_n = _online.objavi_za_ucenike(
                            sheet, zadaci=zadaci_iz_testa(nacrt), ucenici=ucenici_n,
                            naziv=_tekst(nacrt.get("naziv")), predmet=_tekst(nacrt.get("predmet")),
                            program=_tekst(nacrt.get("program")),
                            trajanje_min=int(float(_tekst(nacrt.get("trajanje_min")) or 45)),
                            otvara_od=_tekst(nacrt.get("otvara_od")),
                            zatvara_do=_tekst(nacrt.get("zatvara_do")),
                            serija=_tekst(nacrt.get("naziv")), autor=autor,
                            napomena="Objavljeno iz nacrta " + _tekst(nacrt.get("test_id")),
                            pomoc=_tekst(nacrt.get("pomoc")),
                            formule=_tekst(nacrt.get("formule_json")),
                            rad=_tekst(nacrt.get("rad")))
                    except Exception as e:        # noqa: BLE001 — Caki mora vidjeti grešku
                        st.error(f"Objava nije uspjela: {e}")
                    else:
                        st.success(f"✅ Objavljeno za **{len(redci_n)}** učenika. Nacrt ostaje "
                                   "spremljen, pa ga možeš poslati i drugoj grupi.")
                        st.rerun()

        st.dataframe(tablica_testova(testovi, rezultati), hide_index=True, width="stretch")

        opcije = {_tekst(t.get("test_id")): f"{_tekst(t.get('naziv'))} · {_tekst(t.get('test_id'))}"
                  for t in testovi}
        odabrani_id = st.selectbox("Odaberi test", list(opcije), format_func=opcije.get,
                                   key="ta_odabrani_test")
        test = nadji_test(testovi, odabrani_id)
        if not test:
            return

        st.divider()
        st.markdown(f"### {_tekst(test.get('naziv'))}")
        st.caption(f"`{_tekst(test.get('test_id'))}` · {_tekst(test.get('broj_zadataka'))} zadataka · "
                   f"{_tekst(test.get('bodovi_ukupno'))} bodova · kome: **{cilj_opis(test)}** · "
                   f"program: {_tekst(test.get('program')) or 'svi'} · "
                   f"autor: {_tekst(test.get('autor')) or '—'} · "
                   f"objavljen {_tekst(test.get('kreirano')) or '—'}")
        serija_popis = serija_iz_retka(test)
        if serija_popis:
            st.caption(f"👥 Dio serije **{serija_popis}** — {len(testovi_serije(testovi, serija_popis))} "
                       f"učenika. Rezultati se zbrajaju za cijelu seriju u tabu 📊 Rezultati.")

        with st.form(f"ta_forma_{_tekst(test.get('test_id'))}"):
            c1, c2 = st.columns([3, 1])
            naziv = c1.text_input("Naziv testa (vidi ga učenik)", value=_tekst(test.get("naziv")))
            trajanje = c2.number_input("Trajanje (min)", min_value=5, max_value=240, step=5,
                                       value=int(_broj(test.get("trajanje_min"), 45)))
            c3, c4, c5 = st.columns(3)
            otvara = c3.date_input("Otvoren od", value=_kao_datum(test.get("otvara_od")),
                                   format="DD.MM.YYYY")
            zatvara = c4.date_input("Otvoren do", value=_kao_datum(test.get("zatvara_do"),
                                                                   date.today()),
                                    format="DD.MM.YYYY")
            aktivan = c5.checkbox("Aktivan (učenik ga vidi)", value=_aktivan(test))
            ima_pomoc = ima_stupac(sheet, "pomoc")
            pomoc_ukljucena = st.checkbox(
                "💡 Pomoć pri učenju dopuštena (bot kao profesor; nikad rješenje)",
                value=_tekst(test.get("pomoc")) == "Da", disabled=not ima_pomoc,
                help="Najviše 5 pitanja po učeniku. Za provjere i ocjenjivane testove ostavi "
                     "isključeno.")
            if not ima_pomoc:
                st.caption("Stupac `pomoc` još ne postoji u tabu — nastaje pri prvoj novoj "
                           "objavi iz Test Buildera.")
            st.caption("Izmjena ovdje mijenja test kakav ga učenik vidi. Već predani rezultati "
                       "ostaju kakvi su bili — oni su dokaz što je učenik riješio.")
            spremi = st.form_submit_button("💾 Spremi izmjene", type="primary")

        if spremi:
            greske = provjeri_izmjene(naziv, trajanje, otvara, zatvara)
            if greske:
                for g in greske:
                    st.error(g)
            else:
                polja_izmjene = {
                    "naziv": _tekst(naziv),
                    "trajanje_min": int(trajanje),
                    "otvara_od": _datum(otvara),
                    "zatvara_do": _datum(zatvara),
                    "aktivan": STATUS_AKTIVAN if aktivan else "Ne",
                }
                if ima_pomoc:
                    polja_izmjene["pomoc"] = "Da" if pomoc_ukljucena else "Ne"
                try:
                    if serija_popis:
                        n_iz = azuriraj_seriju(sheet, testovi, serija_popis, polja_izmjene)
                    else:
                        azuriraj_test(sheet, odabrani_id, polja_izmjene)
                        n_iz = 1
                except ValueError as e:
                    st.error(str(e))
                else:
                    _osvjezi(st, "success", f"✅ Spremljeno: {_tekst(naziv)}"
                             + (f" — za **{n_iz}** učenika u seriji." if serija_popis else "."))

        b1, b2, b3 = st.columns(3)
        if b1.button("⏸️ Deaktiviraj" if _aktivan(test) else "✅ Aktiviraj",
                     key=f"ta_akt_{odabrani_id}",
                     help="Deaktiviran test učenik više ne vidi, ali rezultati i zadaci ostaju."):
            try:
                postavi_aktivan(sheet, odabrani_id, not _aktivan(test))
            except ValueError as e:
                st.error(str(e))
            else:
                _osvjezi(st, "success",
                         f"Test `{odabrani_id}` je {'deaktiviran' if _aktivan(test) else 'aktiviran'}.")

        # 22.10.2026. (Cakijev zahtjev): ne čekati istek roka — kad su svi riješili, rješenja
        # se otvaraju odmah (portal ih otvara kad je rok prošao, pa se rok postavlja na jučer).
        with st.popover("⏹️ Zatvori test odmah"):
            st.caption("Rok se postavlja na **jučer**: učenici više ne mogu pisati, a svi koji "
                       "su predali **odmah vide rješenja** i točne odgovore.")
            _za_seriju = bool(serija_popis)
            if serija_popis:
                _za_seriju = st.checkbox("za cijelu seriju", value=True,
                                         key=f"ta_zat_sve_{odabrani_id}")
            if st.button("⏹️ Zatvori odmah", key=f"ta_zatvori_{odabrani_id}", type="primary"):
                try:
                    _zatvoreno = zatvori_test(sheet, test, cijela_serija=_za_seriju, testovi=testovi)
                except ValueError as e:
                    st.error(str(e))
                else:
                    _osvjezi(st, "success",
                             f"⏹️ Zatvoreno: **{len(_zatvoreno)}** test(ova). Učenici koji su "
                             "predali sada vide rješenja.")

        if b2.button("📄 Kloniraj", key=f"ta_klon_{odabrani_id}",
                     help="Novi test s ISTIM zadacima — npr. ista vježba za drugu grupu."):
            try:
                novi = kloniraj_test(sheet, odabrani_id, autor=_tekst(autor))
            except ValueError as e:
                st.error(str(e))
            else:
                _osvjezi(st, "success",
                         f"📄 Novi test `{novi['test_id']}` s istim zadacima je objavljen "
                         f"(aktivan, isti datumi). Uredi ga u popisu iznad.")
        b3.caption("Kloniranje ne dira izvorni test ni njegove rezultate.")

        if serija_popis:
            cijela = testovi_serije(testovi, serija_popis)
            if st.button(
                    (f"⏸️ Deaktiviraj cijelu seriju ({len(cijela)})" if _aktivan(test)
                     else f"✅ Aktiviraj cijelu seriju ({len(cijela)})"),
                    key=f"ta_ser_{odabrani_id}",
                    help="Mijenja sve retke te objave odjednom (jedan poziv prema Googleu)."):
                try:
                    n_ser = postavi_aktivan_seriju(sheet, testovi, serija_popis, not _aktivan(test))
                except ValueError as e:
                    st.error(str(e))
                else:
                    _osvjezi(st, "success",
                             f"Serija `{serija_popis}`: "
                             f"{'deaktivirano' if _aktivan(test) else 'aktivirano'} {n_ser} testova.")

        with st.expander("🗑️ Obriši test (trajno)"):
            st.caption("Brisanje uklanja test **iz Moj CAKI** (učenik ga više ne vidi) i briše "
                       "njegove rezultate iz tablice rezultata. **Nema povratka.** Ako želiš da "
                       "ga učenik samo prestane vidjeti, a rezultati ostanu — koristi "
                       "**⏸️ Deaktiviraj**.")
            potvrda = st.checkbox(
                f"Svjesno brišem test „{_tekst(test.get('naziv'))}” ({odabrani_id})",
                key=f"ta_brisi_pot_{odabrani_id}")
            i_rez = st.checkbox("Obriši i rezultate tog testa", value=True,
                                key=f"ta_brisi_rez_{odabrani_id}")
            if st.button("🗑️ Obriši test", key=f"ta_brisi_{odabrani_id}", disabled=not potvrda):
                try:
                    rez_brisanja = obrisi_test(sheet, odabrani_id, i_rezultate=i_rez)
                except ValueError as e:
                    st.error(str(e))
                else:
                    _osvjezi(st, "success",
                             f"🗑️ Obrisano: **{rez_brisanja['testova']}** test(ova), "
                             f"**{rez_brisanja['rezultata']}** rezultat(a).")

            if serija_popis:
                st.divider()
                cijela = testovi_serije(testovi, serija_popis)
                potvrda_ser = st.checkbox(
                    f"Svjesno brišem CIJELU seriju „{serija_popis}” "
                    f"({len(cijela)} učenika)", key=f"ta_brisi_ser_pot_{odabrani_id}")
                if st.button(f"🗑️ Obriši cijelu seriju ({len(cijela)})",
                             key=f"ta_brisi_ser_{odabrani_id}", disabled=not potvrda_ser):
                    try:
                        rez_ser = obrisi_seriju(sheet, testovi, serija_popis, i_rezultate=i_rez)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        _osvjezi(st, "success",
                                 f"🗑️ Obrisana serija `{serija_popis}`: "
                                 f"**{rez_ser['testova']}** test(ova), "
                                 f"**{rez_ser['rezultata']}** rezultat(a).")

        with st.expander("👁️ Kako ovaj test vidi učenik (s točnim odgovorima)"):
            prikazi_pregled(st, test)

    # ------------------------------------------------ 📊 rezultati
    with tab_rezultati:
        # 22.10.2026. (Cakijev zahtjev): pregled JEDNOG testa — svi koji su ga pisali, po učeniku
        # i po grupi/kanti, uključivo one koji NISU predali.
        with st.expander("🎯 Rezultati jednog testa — po učenicima i po grupama", expanded=True):
            opcije_k = kolone_svih_testova(testovi)
            if not opcije_k:
                st.caption("Još nema objavljenih testova.")
            else:
                odabrana_k = st.selectbox("Test", opcije_k, key="ta_pregled_kolona",
                                          help="Grupna objava (ista serija) gleda se kao jedan test.")
                rez_t = pregled_testa(testovi, rezultati, odabrana_k, list(kante or []) + list(grupe or []))
                if not rez_t["redci"]:
                    st.caption("Za taj test još nema ni dodjele ni predaja.")
                else:
                    q1, q2, q3, q4 = st.columns(4)
                    q1.metric("Predalo", f"{rez_t['pisalo']} / {rez_t['dodijeljeno'] or '—'}")
                    q2.metric("Prosjek", f"{rez_t['prosjek']} %")
                    q3.metric("Medijan", f"{rez_t['medijan']} %")
                    q4.metric("Raspon", f"{rez_t['najslabiji'] or 0}–{rez_t['najbolji'] or 0} %")
                    st.dataframe(tablica_pregleda_testa(rez_t), hide_index=True, width="stretch")
                    if rez_t["nije_pisalo"]:
                        st.warning("**Nije predalo ({n}):** {imena}".format(
                            n=len(rez_t["nije_pisalo"]), imena=", ".join(rez_t["nije_pisalo"][:15])
                            + (" …" if len(rez_t["nije_pisalo"]) > 15 else "")))
                    if rez_t["po_grupi"]:
                        st.caption("**Prosjek po grupama / kantama**")
                        st.dataframe({"Grupa / kanta": [g["grupa"] for g in rez_t["po_grupi"]],
                                      "Učenika": [g["broj"] for g in rez_t["po_grupi"]],
                                      "Prosjek %": [g["prosjek"] for g in rez_t["po_grupi"]]},
                                     hide_index=True, width="stretch")
                    st.download_button(
                        "⬇️ CSV — rezultati ovog testa",
                        data=tablica_pregleda_testa(rez_t).to_csv(index=False).encode("utf-8-sig"),
                        file_name="rezultati_testa.csv", mime="text/csv", key="ta_csv_pregled")
        with st.expander("🧮 Matrica razreda — svi učenici × posljednji testovi"):
            st.caption("Postotak po testu; grupna objava (serija) je jedan stupac. Prazno = "
                       "nije predao. Ako je učenik rješavao više puta, broji se zadnja predaja.")
            zadnjih = st.slider("Koliko posljednjih testova", 3, 20, 8, key="ta_zadnjih")
            matrica_r = matrica_razreda(testovi, rezultati, zadnjih)
            if matrica_r.empty:
                st.caption("Još nema predaja.")
            else:
                st.dataframe(matrica_r, hide_index=True, width="stretch")
                st.download_button(
                    "⬇️ CSV — matrica razreda",
                    data=csv_matrica_razreda(testovi, rezultati, zadnjih).encode("utf-8-sig"),
                    file_name="matrica_razreda.csv", mime="text/csv", key="ta_csv_razred")

        with st.expander("🔀 Usporedba dvaju testova — je li razred napredovao"):
            st.caption("Uspoređuju se samo učenici koji su pisali **oba** testa; grupna objava "
                       "(serija) se gleda kao cjelina. Razlika je u postotnim bodovima (drugi − prvi).")
            kolone_usp = kolone_sa_predajama(testovi, rezultati)
            if len(kolone_usp) < 2:
                st.caption("Potrebna su barem dva testa s predajama.")
            else:
                k1, k2 = st.columns(2)
                a_kol = k1.selectbox("Prvi test", kolone_usp, index=0, key="ta_usp_a")
                b_kol = k2.selectbox("Drugi test", kolone_usp, index=len(kolone_usp) - 1,
                                     key="ta_usp_b")
                if _tekst(a_kol) == _tekst(b_kol):
                    st.caption("Odaberi dva različita testa.")
                else:
                    usp = usporedba_kolona(testovi, rezultati, a_kol, b_kol)
                    if not usp["ucenici"]:
                        st.info("Nema učenika koji su pisali oba testa.")
                    else:
                        v1, v2, v3, v4 = st.columns(4)
                        v1.metric("Zajedničkih učenika", usp["broj"])
                        v2.metric("Prosječna razlika", f"{usp['prosjek_delta']:+d} bod. %")
                        v3.metric("Bolji", usp["bolji"])
                        v4.metric("Lošiji", usp["losiji"])
                        st.markdown("**Po učenicima** — najveći napredak prvi")
                        st.dataframe(tablica_usporedbe_ucenika(usp), hide_index=True,
                                     width="stretch")
                        if usp["cjeline"]:
                            st.markdown("**Po cjelinama** — najveći pad prvi")
                            st.dataframe(tablica_usporedbe_cjelina(usp), hide_index=True,
                                         width="stretch")

        opcije_r = {_tekst(t.get("test_id")): f"{_tekst(t.get('naziv'))} · {_tekst(t.get('test_id'))}"
                    for t in testovi}
        odabrani_r = st.selectbox("Test", list(opcije_r), format_func=opcije_r.get,
                                  key="ta_test_rezultati")
        test_r = nadji_test(testovi, odabrani_r)
        serija_r = serija_iz_retka(test_r)
        redci_r = testovi_serije(testovi, serija_r) or ([test_r] if test_r else [])
        moji = [r for t in redci_r for r in filtruj_rezultate(rezultati, t.get("test_id"))]
        sazetak_r = sazetak(moji)

        if not moji:
            st.info("Za taj test još nema predaja. Učenik ga vidi u Moj CAKI → 📝 Testovi "
                    "ako je aktivan i ako je unutar datuma.")
        else:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Predaja", sazetak_r["broj"])
            s2.metric("Prosjek", f"{sazetak_r['prosjek']} %")
            s3.metric("Najbolji / najslabiji", f"{sazetak_r['najbolji']} / {sazetak_r['najslabiji']} %")
            s4.metric("Prosječno trajanje", f"{sazetak_r['prosj_trajanje_min']} min")

            st.markdown("**Predaje (najslabiji prvi)**")
            st.dataframe(tablica_rezultata(moji), hide_index=True, width="stretch")

            uspjeh = uspjeh_po_zadatku(test_r, moji)
            if uspjeh:
                st.markdown("**Uspjeh po zadatku** — prvi redak je zadatak koji je najviše pao")
                st.dataframe(tablica_uspjeha_po_zadatku(uspjeh), hide_index=True, width="stretch",
                             column_config={"%": st.column_config.ProgressColumn(
                                 min_value=0, max_value=100, format="%d %%")})

            po_cjelinama = uspjeh_po_cjelinama(test_r, moji)
            if po_cjelinama:
                with st.expander("📚 Uspjeh po cjelinama (koja cjelina razredu ne ide)"):
                    st.caption("Cjelina se zamrzava u test pri objavi — za testove objavljene "
                               "prije 21.10.2026. ovaj pregled je prazan.")
                    st.dataframe(tablica_po_cjelinama(po_cjelinama), hide_index=True,
                                 width="stretch",
                                 column_config={"%": st.column_config.ProgressColumn(
                                     min_value=0, max_value=100, format="%d %%")})

            nisu = ucenici_bez_predaje(redci_r, moji)
            if nisu:
                st.warning("Nije predao: " + ", ".join(nisu))
            elif serija_r:
                st.caption(f"👥 Serija **{serija_r}** — test je zadan {len(redci_r)} učenika.")

            with st.expander("🧩 Matrica učenik × zadatak"):
                matrica = matrica_ucenika(test_r, moji)
                if matrica.empty:
                    st.caption("Nema podataka za matricu.")
                else:
                    st.caption("✓ = točno · ✗ = netočno · prazno = nema odgovora u predaji")
                    st.dataframe(matrica, hide_index=True, width="stretch")
                    st.download_button("⬇️ CSV — matrica", data=csv_matrica(test_r, moji).encode("utf-8-sig"),
                                       file_name=f"test_{odabrani_r}_matrica.csv", mime="text/csv",
                                       key=f"ta_csv_mat_{odabrani_r}")

            d1, d2 = st.columns(2)
            d1.download_button("⬇️ CSV — rezultati po zadacima", data=csv_rezultata(test_r, moji).encode("utf-8-sig"),
                               file_name=f"test_{odabrani_r}_rezultati.csv", mime="text/csv",
                               key=f"ta_csv_rez_{odabrani_r}")
            if uspjeh:
                d2.download_button("⬇️ CSV — uspjeh po zadatku", data=csv_uspjeha(uspjeh).encode("utf-8-sig"),
                                   file_name=f"test_{odabrani_r}_uspjeh.csv", mime="text/csv",
                                   key=f"ta_csv_usp_{odabrani_r}")

        # 🕓 Započeli, nisu predali — čita tab `Test_pocetak` koji piše portal
        try:
            pocetci = load_pocetke(sheet)
        except Exception:                           # noqa: BLE001 — tab još ne postoji
            pocetci = []
        zapoceli = zapoceli_bez_predaje(redci_r, pocetci, moji)
        if zapoceli:
            st.markdown(f"**🕓 Započeli, nisu predali ({len(zapoceli)})**")
            st.dataframe(tablica_zapocelih(zapoceli), hide_index=True, width="stretch")
            st.caption("Podatak dolazi iz taba `Test_pocetak` — portal ga upiše kad učenik otvori "
                       "test. Ako „Rješava (min)” prelazi predviđeno trajanje, učenik je vjerojatno "
                       "zapeo ili odustao.")

    # ------------------------------------------------ 👤 po učeniku
    with tab_ucenik:
        ucenici_sa = ucenici_s_rezultatima(rezultati)
        if not ucenici_sa:
            st.info("Još nema nijedne predaje, pa nema ni povijesti po učeniku.")
        else:
            opcije_u = {u["ucenik_id"]:
                        f"{u['ime_djeteta'] or u['ucenik_id']} ({u['ucenik_id']}) · "
                        f"{u['testova']} test(ova) · prosjek {u['prosjek']} %"
                        for u in ucenici_sa}
            odabrani_u = st.selectbox("Učenik", list(opcije_u), format_func=opcije_u.get,
                                      key="ta_ucenik")
            saz_u = sazetak_ucenika(rezultati, odabrani_u)
            povijest_u = povijest_ucenika(rezultati, odabrani_u)

            u1, u2, u3, u4 = st.columns(4)
            u1.metric("Testova", saz_u["broj"])
            u2.metric("Prosjek", f"{saz_u['prosjek']} %")
            u3.metric("Najbolji / najslabiji",
                      f"{saz_u['najbolji']} / {saz_u['najslabiji']} %")
            u4.metric("Prosječno trajanje", f"{saz_u['prosj_trajanje_min']} min")

            st.markdown("**Svi testovi tog učenika**")
            st.dataframe(tablica_povijesti(povijest_u), hide_index=True, width="stretch",
                         column_config={"%": st.column_config.ProgressColumn(
                             min_value=0, max_value=100, format="%d %%")})

            cjeline_u = slabe_cjeline_ucenika(rezultati, testovi, odabrani_u)
            if cjeline_u:
                st.markdown("**Cjeline kroz sve testove** — najslabija prva")
                st.dataframe(tablica_po_cjelinama(cjeline_u), hide_index=True, width="stretch",
                             column_config={"%": st.column_config.ProgressColumn(
                                 min_value=0, max_value=100, format="%d %%")})

            # 21.10.2026.: 🧠 profil po Bloomovim razinama — razlika između „zna” i „zna primijeniti”.
            bloom_u = bloom_profil_ucenika(rezultati, testovi, odabrani_u)
            if bloom_u:
                st.markdown("**🧠 Po razinama razmišljanja (Bloom)** — kroz sve testove")
                st.caption("Samo zadaci kojima je razina označena u Test Builderu. Visoke 1–2 i niske 3–4 "
                           "znače da učenik zna formule, ali ih ne prenosi na zadatak.")
                st.dataframe(tablica_bloom(bloom_u), hide_index=True, width="stretch",
                             column_config={"Uspjeh": st.column_config.ProgressColumn(
                                 min_value=0, max_value=100, format="%d %%")})
            else:
                st.caption("🧠 Bloom razine još nisu označene ni za jedan zadatak ovog učenika — "
                           "označavaju se u Test Builderu, uz polje Bodovi.")

            promaseni = promaseni_zadaci(rezultati, testovi, odabrani_u)
            if promaseni:
                with st.expander(f"❌ Zadatci koje nije riješio točno ({len(promaseni)})"):
                    st.dataframe(tablica_promasenih(promaseni), hide_index=True, width="stretch")

            tekst_rod = tekst_sazetka_za_roditelja(rezultati, testovi, odabrani_u)
            if tekst_rod:
                with st.expander("📋 Sažetak za roditelja (kopiraj u WhatsApp ili mail)"):
                    st.code(tekst_rod, language=None)

    # ------------------------------------------------ 👥 zadaj grupi
    with tab_zadaj:
        st.markdown("**Zadaj postojeći test cijeloj grupi**")
        st.caption("Zadaci se kopiraju (zamrznuti) — izmjena izvornog testa ne dira ovo. Svaki "
                   "učenik dobiva svoj redak i vidi test u Moj CAKI → 📝 Testovi; svi retci nose "
                   "istu oznaku serije, pa ih rezultati drže zajedno. Portal se pritom ne mijenja.")

        s_izborom = {_tekst(t.get("test_id")): f"{_tekst(t.get('naziv'))} · {_tekst(t.get('test_id'))}"
                     for t in testovi if zadaci_iz_testa(t)}
        if not s_izborom:
            st.info("Nema testa s čitljivim zadacima iz kojeg bi se moglo zadati grupi.")
        else:
            izvor_id = st.selectbox("Test koji zadaješ", list(s_izborom),
                                    format_func=s_izborom.get, key="ta_izvor_grupa")
            izvor = nadji_test(testovi, izvor_id)
            vrsta = st.radio("Kome", ["Upisi grupa", "Matura kanta"], horizontal=True,
                             key="ta_vrsta_grupe")
            ponuda = list(grupe or []) if str(vrsta).startswith("Upisi") else list(kante or [])
            if not ponuda:
                st.info("Nema grupa s učenicima. Za Upise se čitaju tabovi `Grupe` i `Rezervacije` "
                        "(samo status **Potvrđeno**); za Maturu `Raspored_Matura_<sezona>` iz CRM "
                        "Sheeta — ako ih nema, učenici se zadaju pojedinačno ili po programu.")
            else:
                opcije_g = {_tekst(g.get("kod")):
                            f"{_tekst(g.get('naziv'))} ({len(g.get('ucenici') or [])} učenika)"
                            for g in ponuda}
                kod = st.selectbox("Grupa", list(opcije_g), format_func=opcije_g.get,
                                   key=f"ta_grupa_{_tekst(vrsta)}")
                grupa = next((g for g in ponuda if _tekst(g.get("kod")) == _tekst(kod)), None)
                if grupa is None:
                    st.warning("Odabrana grupa nije pronađena — osvježi stranicu.")
                else:
                    ucenici_g = list(grupa.get("ucenici") or [])
                    st.caption("**Učenici:** " + ", ".join(
                        f"{_tekst(u.get('ime_djeteta')) or _tekst(u.get('ucenik_id'))} "
                        f"({_tekst(u.get('ucenik_id'))})" for u in ucenici_g))
                    with st.form(f"ta_forma_grupa_{_tekst(kod)}"):
                        naziv_g = st.text_input(
                            "Naziv testa (vidi ga učenik)",
                            value=(f"{_tekst(izvor.get('naziv'))} — {_tekst(grupa.get('naziv'))}"
                                   if izvor else ""))
                        c1, c2, c3 = st.columns(3)
                        trajanje_g = c1.number_input(
                            "Trajanje (min)", min_value=5, max_value=240, step=5,
                            value=int(_broj((izvor or {}).get("trajanje_min"), 45)))
                        otvara_g = c2.date_input("Otvoren od",
                                                 value=_kao_datum((izvor or {}).get("otvara_od")),
                                                 format="DD.MM.YYYY")
                        zatvara_g = c3.date_input(
                            "Otvoren do",
                            value=_kao_datum((izvor or {}).get("zatvara_do"), date.today()),
                            format="DD.MM.YYYY")
                        st.caption(f"Objavit će se **{len(ucenici_g)}** testova (jedan po učeniku), "
                                   f"oznaka serije: „{oznaka_serije(grupa.get('naziv'), danas)}”.")
                        posalji = st.form_submit_button(
                            f"📤 Objavi za {len(ucenici_g)} učenika", type="primary",
                            disabled=not ucenici_g or izvor is None)

                    if posalji:
                        greske_g = provjeri_izmjene(naziv_g, trajanje_g, otvara_g, zatvara_g)
                        if greske_g:
                            for g_ in greske_g:
                                st.error(g_)
                        else:
                            try:
                                rez = objavi_za_grupu(
                                    sheet, izvorni_test=izvor, ucenici=ucenici_g, naziv=naziv_g,
                                    trajanje_min=trajanje_g, otvara_od=_datum(otvara_g),
                                    zatvara_do=_datum(zatvara_g),
                                    serija=oznaka_serije(grupa.get("naziv"), danas),
                                    autor=_tekst(autor))
                            except ValueError as e:
                                st.error(str(e))
                            else:
                                _osvjezi(st, "success",
                                         f"📤 Objavljeno **{len(rez['redci'])}** testova za "
                                         f"„{_tekst(grupa.get('naziv'))}” (serija "
                                         f"`{rez['serija']}`). Učenici ga vide u Moj CAKI → 📝 Testovi.")

    # ------------------------------------------------ 🎯 spremnost baze
    with tab_baza:
        # 21.10.2026.: uputa UNUTAR funkcije (Cakijev zahtjev) — profesor ne izlazi iz aplikacije.
        if _uputa:
            _uputa.prikazi(st, "spremnost")
        st.markdown("**Koliko je baze spremno za online test**")
        st.caption("**Spreman** = zadatak nije skupina (uvod + stavke a/b/c) i ima upisan "
                   "**konačan odgovor**. Bez konačnog odgovora test se ne može automatski "
                   "ocijeniti, pa se takav zadatak ne može objaviti.")
        if ucitaj_bazu is None:
            st.info("Baza zadataka nije dostupna na ovoj stranici.")
        elif st.checkbox("Učitaj spremnost baze (cijeli tab `Zadaci` — zna potrajati)",
                         key="ta_ucitaj_bazu"):
            try:
                zadaci_baze = ucitaj_bazu()
            except Exception as e:                  # noqa: BLE001 — Caki mora vidjeti grešku
                st.error(f"Baza se ne može pročitati: {e}")
            else:
                rez = spremnost_baze(zadaci_baze)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Zadataka u bazi", rez["ukupno"])
                m2.metric("Spremno za test", rez["spremno"],
                          help="ima konačan odgovor i nije skupina")
                m3.metric("Udio spremnih", f"{rez['postotak']} %")
                m4.metric("Skupina (ne mogu u test)", rez["skupine"])
                st.dataframe(tablica_spremnosti(rez), hide_index=True, width="stretch",
                             column_config={"%": st.column_config.ProgressColumn(
                                 min_value=0, max_value=100, format="%d %%")})
                st.download_button("⬇️ CSV — spremnost po cjelinama",
                                   data=csv_spremnosti(rez).encode("utf-8-sig"),
                                   file_name="spremnost_baze.csv", mime="text/csv",
                                   key="ta_csv_baza")

                # 21.10.2026. (Cakijev nalaz iz fizike): „spremno” nije isto što i „pokriveno”.
                # Baza može biti 100 % spremna, a pola cjelina iz šifrarnika prazno.
                st.divider()
                st.markdown("**🧩 Pokrivenost po cjelinama i potpoglavljima**")
                st.caption("Razlika od tablice gore: tamo je „može li se zadatak objaviti”, ovdje je "
                           "„postoji li ijedan zadatak iz te cjeline i je li razvrstan po potpoglavlju”.")
                cjeline_sif = None
                if ucitaj_sifrarnik is not None:
                    try:
                        cjeline_sif = ucitaj_sifrarnik()
                    except Exception as e_sif:      # noqa: BLE001 — šifrarnik ne smije rušiti stranicu
                        st.caption(f"Šifrarnik nije pročitan ({e_sif}) — prazne cjeline se ne mogu izračunati.")
                pok = pokrivenost_cjelina(zadaci_baze, cjeline_sif)
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Cjelina u bazi", pok["cjelina"]["razlicitih"])
                p2.metric("Cjelina u šifrarniku", len(cjeline_sif) if cjeline_sif else "—",
                          help="Ako je šifrarnik dostupan; inače se ne računa.")
                p3.metric("Praznih cjelina", len(pok["prazne_cjeline"]) if cjeline_sif else "—",
                          help="Cjeline iz šifrarnika bez ijednog zadatka.")
                p4.metric("S potpoglavljem", f"{pok['potpoglavlje']['postotak']} %",
                          help=f"{pok['potpoglavlje']['popunjeno']} od {pok['ukupno']} zadataka ima "
                               "upisano potpoglavlje.")
                st.dataframe(tablica_pokrivenosti(pok), hide_index=True, width="stretch")
                if pok["prazne_cjeline"]:
                    st.warning(f"**{len(pok['prazne_cjeline'])} cjelina iz šifrarnika nema nijedan zadatak:** "
                               + ", ".join(pok["prazne_cjeline"][:12])
                               + (" …" if len(pok["prazne_cjeline"]) > 12 else ""))
                if pok["izvan_sifrarnika"]:
                    st.info("**Cjeline koje postoje u bazi, a nema ih u šifrarniku** (dodane ručno ili "
                            "drugim imenom): " + ", ".join(pok["izvan_sifrarnika"]))
                if pok["tanke"]:
                    st.caption("Tanke cjeline (≤ 5 zadataka): " + ", ".join(pok["tanke"]))
                st.download_button("⬇️ CSV — pokrivenost po cjelinama",
                                   data=csv_pokrivenosti(pok).encode("utf-8-sig"),
                                   file_name="pokrivenost_cjelina.csv", mime="text/csv",
                                   key="ta_csv_pokrivenost")
        else:
            st.info("Označi kvačicu da se izračuna — čita se tab `Zadaci` ovog predmeta.")

    # ------------------------------------------------ 🩺 provjere
    with tab_provjere:
        st.markdown("**🧪 Provjera nakon pusha** — je li sve spojeno")
        try:
            nalazi_dij = dijagnostika(sheet)
        except Exception as e:                      # noqa: BLE001 — ni dijagnostika ne ruši stranicu
            nalazi_dij = [{"naziv": "Dijagnostika", "status": "greška", "opis": str(e)}]
        for n in nalazi_dij:
            ikona = {"ok": "✅", "napomena": "⚠️", "greška": "❌"}.get(n["status"], "ℹ️")
            st.markdown(f"{ikona} **{n['naziv']}** — {n['opis']}")

        st.divider()
        nalazi = problemi(testovi, rezultati, danas=danas)
        if not nalazi:
            st.success("Svi objavljeni testovi izgledaju dobro — nema što popraviti. 🎉")
        else:
            greske = [n for n in nalazi if n["razina"] == "greška"]
            upozorenja = [n for n in nalazi if n["razina"] != "greška"]
            if greske:
                st.error(f"**{len(greske)} stvari koje stvarno smetaju:**")
                for n in greske:
                    st.markdown(f"- `{n['test_id']}` — **{n['naziv']}**: {n['opis']}")
            if upozorenja:
                st.warning(f"**{len(upozorenja)} za provjeru:**")
                for n in upozorenja:
                    st.markdown(f"- `{n['test_id']}` — **{n['naziv']}**: {n['opis']}")

        st.divider()
        st.markdown("**🔒 Jesu li se zadaci promijenili u bazi nakon objave?**")
        st.caption("Test je zamrznuta kopija: učenik se ocjenjuje po odgovoru kakav je bio u "
                   "trenutku objave. Ako je rješenje u bazi kasnije ispravljeno, objavljeni test "
                   "i dalje traži staro — ovo pokazuje gdje se to dogodilo.")
        if ucitaj_bazu is None:
            st.caption("Baza zadataka nije dostupna na ovoj stranici.")
        elif st.checkbox("Provjeri objavljene testove prema bazi zadataka", key="ta_ucitaj_bazu_provjere"):
            try:
                zadaci_baze = ucitaj_bazu()
            except Exception as e:                  # noqa: BLE001
                st.error(f"Baza se ne može pročitati: {e}")
            else:
                nalazi_int = integritet_svih(testovi, zadaci_baze)
                if not nalazi_int:
                    st.success("Svi objavljeni testovi odgovaraju današnjoj bazi. 🎉")
                else:
                    st.warning(f"**{len(nalazi_int)} test(ova) se razlikuje od baze:**")
                    st.dataframe(tablica_integriteta(nalazi_int), hide_index=True, width="stretch")
                    st.caption("Ako je odgovor promijenjen, objavi test ponovno iz Test Buildera "
                               "(nastaje nova zamrznuta kopija) i stari deaktiviraj.")


__all__ = [
    "TEST_TAB", "REZ_TAB", "REZ_HEADERS", "SERIJA_STUPAC", "STATUS_AKTIVAN", "GRANICA_CELIJE",
    "GRUPE_TAB", "REZERVACIJE_TAB", "RASPORED_PREFIKS", "DANI_REDOM", "POCETAK_TAB",
    "load_testovi", "load_rezultati", "load_grupe", "load_rezervacije",
    "naziv_taba_rasporeda", "load_raspored_mature", "ucenici_upisa", "kante_mature",
    "zadaci_iz_testa", "detalji_iz_retka", "nadji_test",
    "filtruj_rezultate", "filtruj_po_predmetu", "cilj_opis",
    "serija_iz_retka", "testovi_serije", "jedinstvena_serija", "oznaka_serije",
    "sazetak", "uspjeh_po_zadatku", "ucenici_bez_predaje", "ucenici_koji_nisu_predali",
    "load_pocetke", "zapoceli_bez_predaje", "tablica_zapocelih", "zatvori_test",
    "uspjeh_po_cjelinama", "spremnost_baze",
    "ucenici_s_rezultatima", "povijest_ucenika", "sazetak_ucenika", "slabe_cjeline_ucenika",
    "promaseni_zadaci", "tekst_sazetka_za_roditelja",
    "matrica_ucenika", "csv_matrica", "indeks_baze", "integritet_testa", "integritet_svih",
    "tablica_integriteta", "kolona_testa", "matrica_razreda", "csv_matrica_razreda",
    "rezultati_po_koloni", "kolone_sa_predajama", "usporedba_kolona",
    "tablica_usporedbe_ucenika", "tablica_usporedbe_cjelina",
    "tablica_testova", "tablica_rezultata", "tablica_uspjeha_po_zadatku",
    "tablica_po_cjelinama", "tablica_spremnosti", "csv_spremnosti",
    "tablica_povijesti", "tablica_promasenih",
    "csv_rezultata", "csv_uspjeha", "provjeri_izmjene", "problemi",
    "azuriraj_test", "postavi_aktivan", "kloniraj_test", "objavi_za_grupu",
    "azuriraj_seriju", "postavi_aktivan_seriju",
    "prikazi_pregled", "prikazi_stranicu", "kratak_tekst",
]


# ============================================================
# 🧑‍🏫 Ručna provjera rješenja (25.10.2026.)
# ============================================================

def potrebna_provjera(rezultat) -> bool:
    """Ima li rezultat ijedan zadatak sa statusom "ceka" (nema ključa ili je postupak)."""
    return any(_tekst(d.get("status")) == "ceka" for d in detalji_iz_retka(rezultat))


def zadaci_za_provjeru(rezultat) -> list:
    """Popis (redni_broj, detalj) samo za zadatke koji čekaju provjeru."""
    return [(i, d) for i, d in enumerate(detalji_iz_retka(rezultat))
            if _tekst(d.get("status")) == "ceka"]


def primijeni_provjeru(ws, redak: int, rezultat: dict, odluke: dict, provjerio: str = "") -> dict:
    """Upiši Cakijeve odluke u JEDAN redak rezultata i preračunaj ukupno.

    `odluke` = {redni_broj_zadatka: {"status": "tocno"|"netocno"|"ceka", "bodovi": broj}}
    Pravilo: "tocno" nosi sve bodove zadatka (`max`), "netocno" 0, "ceka" ostaje otvoreno
    (npr. dio koji se provjerava naknadno). Vraća polja koja su upisana.
    """
    import json as _json
    from datetime import datetime as _dt

    detalji = detalji_iz_retka(rezultat)
    for i, d in enumerate(detalji):
        o = (odluke or {}).get(i)
        if not o:
            continue
        st = _tekst(o.get("status")) or "netocno"
        d["status"] = st if st in ("tocno", "netocno", "ceka") else "netocno"
        d["tocno"] = d["status"] == "tocno"
        if d["status"] == "tocno":
            d["bodovi"] = round(_broj(d.get("max")), 2)
        elif d["status"] == "netocno":
            d["bodovi"] = 0.0
        else:
            d["bodovi"] = round(_broj(o.get("bodovi"), 0.0), 2)

    bodovi = round(sum(_broj(d.get("bodovi")) for d in detalji), 2)
    maks = round(sum(_broj(d.get("max")) for d in detalji), 2)
    ostalo = any(_tekst(d.get("status")) == "ceka" for d in detalji)
    polja = {
        "detalji_json": _json.dumps(detalji, ensure_ascii=False),
        "bodovi": bodovi,
        "postotak": int(round(100 * bodovi / maks)) if maks else 0,
        "provjera": "ceka" if ostalo else "ocjenjeno",
        "provjerio": _tekst(provjerio),
        "provjereno": _dt.now().strftime("%Y-%m-%d %H:%M"),
    }

    zaglavlje = [_tekst(h) for h in ws.row_values(1)]
    paket = []
    for naziv, vrijednost in polja.items():
        if naziv in zaglavlje:
            slovo = ""
            idx = zaglavlje.index(naziv) + 1
            while idx > 0:
                idx, ostatak = divmod(idx - 1, 26)
                slovo = chr(65 + ostatak) + slovo
            paket.append({"range": f"{slovo}{redak}", "values": [[vrijednost]]})
    if paket:
        ws.batch_update(paket, value_input_option="RAW")
    return polja
