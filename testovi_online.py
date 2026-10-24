"""
CAKI — testovi_online.py  (19.10.2026.)

Korak 3 sustava online testova (MASTER_BAZA §37.4): „Objavi kao online test” iz Test
Buildera. Odabrani zadaci spremaju se kao ZAMRZNUTA kopija u CRM Sheet, u tab
`Testovi_zakazani`. Portal Moj CAKI (repo caki-booking-termina, modul istog imena)
čita taj tab i daje učeniku test za rješavanje, ocjenjuje ga i upisuje rezultat u
`Rezultati_testova`.

ZAŠTO ZAMRZNUTA KOPIJA
    - izmjena zadatka u bazi ne mijenja test koji je učenik već dobio (test je dokaz),
    - portal ne treba pristup bazi zadataka ni Driveu — nema novih tajni u portalu,
    - jedan redak u Sheetu = jedan cijeli test (JSON unutra).

ŠTO SE NE MOŽE OBJAVITI (namjerno, v1)
    - skupine zadataka (uvod + stavke a/b/c) — portalu treba pojedinačan zadatak,
    - zadatak bez `konacan_odgovor` — bez njega nema automatskog ocjenjivanja.
    Slike se samo bilježe imenom datoteke; ako portal nije povezan s Driveom, uz
    zadatak piše da slika postoji (v. uputu).

Ne dira pipeline_upisi.py ni bazu zadataka — samo čita ono što je Test Builder odabrao.
"""
from __future__ import annotations

import json
import secrets as _secrets
import string
from datetime import date, datetime, timedelta

TEST_TAB = "Testovi_zakazani"

TEST_HEADERS = [
    "test_id", "naziv", "predmet", "ucenik_id", "ime_djeteta", "program", "razina",
    "zadaci_json", "broj_zadataka", "bodovi_ukupno", "trajanje_min",
    "otvara_od", "zatvara_do", "aktivan", "autor", "kreirano", "napomena",
    "serija",       # 21.10.2026.: oznaka zajedničke objave za više učenika (grupa/kanta)
    "pomoc",        # 22.10.2026.: "Da" = učenik smije pitati 💡 pomoć tijekom rješavanja
    "formule_json",  # 22.10.2026.: 📐 zamrznute formule koje učenik smije vidjeti uz test
    "rad",           # 22.10.2026.: "Da" = učenik šalje slike/sken svog rada nakon predaje
]

# Program na koji se test odnosi (prazno = svi učenici). Ista lista kao program_tip u Prijavama.
PROGRAMI = ["", "Upisi", "Matura", "Instrukcije"]

STATUS_AKTIVAN = "Da"

# 21.10.2026.: 🧠 Bloomove razine (revidirana taksonomija) — JEDAN popis za sve aplikacije.
# VAŽNO: `tezina` (lako/srednje/teško) NIJE isto što i Bloom. Težak zadatak može biti razina 1
# („nabroji sve identitete”), a lagan razina 3 („izračunaj 15 % od 240”). Zato je zasebno polje.
BLOOM_NAZIVI = {"1": "Zapamti", "2": "Razumije", "3": "Primijeni", "4": "Analiziraj", "5": "Vrednuj"}
BLOOM_OPCIJE = [""] + list(BLOOM_NAZIVI)
BLOOM_OPIS = {
    "1": "reprodukcija definicije, formule ili činjenice",
    "2": "objašnjenje, prepoznavanje ekvivalentnog oblika, čitanje grafa",
    "3": "rutinski postupak na novim brojevima (klasičan ispitni zadatak)",
    "4": "više koraka, povezivanje cjelina, odabir metode",
    "5": "provjera je li tuđi postupak točan / nalaženje pogreške",
}


def bloom_naziv(vrijednost) -> str:
    """'3' -> 'Primijeni'; prazno/ nepoznato -> ''."""
    return BLOOM_NAZIVI.get(_tekst_globalno(vrijednost), "")


def _tekst_globalno(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def bloom_opis(vrijednost) -> str:
    """'3' -> 'Primijeni — rutinski postupak na novim brojevima' (za pomoć u sučelju)."""
    v = _tekst_globalno(vrijednost)
    return f"{BLOOM_NAZIVI[v]} — {BLOOM_OPIS[v]}" if v in BLOOM_NAZIVI else ""


def _poruka_json(naziv_kljuca: str, sto: str) -> str:
    return (f"`{naziv_kljuca}` u Streamlit Secrets {sto}.\n\n"
            "**Kako popraviti:** otvori Secrets → taj ključ → mora biti JSON servisnog računa "
            "(`{\"type\": \"service_account\", …}`). Najčešća greška je da `private_key` sadrži "
            "STVARNE prijelome redaka — u JSON-u mora stajati `\\n` (jedna linija), ili se cijeli JSON "
            "zalijepi u TOML s trostrukim navodnicima. Ne stavljaj navodnike oko cijelog JSON-a.")


def sa_info_iz_teksta(tekst, naziv_kljuca: str = "GOOGLE_SERVICE_ACCOUNT_JSON") -> dict:
    """JSON servisnog računa iz Secrets — tolerantno na uobičajene pogreške pri lijepljenju.

    Zašto postoji (21.10.2026.): u Secrets je zalijepljen JSON u kojem `private_key` ima STVARNE
    prijelome redaka umjesto `\\n`. `json.loads` to odbija („Invalid control character at: line 5
    column 46”), stranica padne, a poruka je glasila na krivu stranu („CRM Sheet se ne može otvoriti”
    / „dodaj servisni račun na Sheet”) iako je Sheet bio ispravno podijeljen. Takav se JSON ovdje
    prihvati (`strict=False`) jer se nakon parsiranja dobije isti ključ kakav Google očekuje.

    Prihvaća i JSON u navodnicima (zalijepljen s `"…"`), BOM na početku i višak praznina.
    Ako ni to ne prođe, greška kaže TOČNO koji ključ u Secrets je u pitanju i što napraviti.
    """
    import json
    t = str(tekst or "").replace("\ufeff", "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"') and t[1:2] == "{":
        t = t[1:-1].strip()                       # zalijepljen s navodnicima oko cijelog JSON-a
    podaci, zadnja = None, None
    for strogo in (True, False):                  # False dopušta stvarne \n unutar stringa
        try:
            podaci = json.loads(t, strict=strogo)
            break
        except json.JSONDecodeError as e:
            zadnja = e
    if podaci is None:
        raise ValueError(_poruka_json(naziv_kljuca, f"nije ispravan JSON ({zadnja})"))
    if not isinstance(podaci, dict):
        raise ValueError(_poruka_json(naziv_kljuca, "nije JSON objekt (mora biti od `{` do `}`)"))
    fale = [k for k in ("private_key", "client_email", "token_uri") if not str(podaci.get(k) or "").strip()]
    if fale:
        raise ValueError(_poruka_json(naziv_kljuca, "nema obavezna polja: " + ", ".join(fale)))
    if "BEGIN" not in str(podaci["private_key"])[:60]:
        raise ValueError(_poruka_json(naziv_kljuca, "polje `private_key` ne sadrži "
                                                    "„-----BEGIN PRIVATE KEY-----”"))
    return podaci


def sa_info_za_testove(st) -> dict:
    """Servisni racun za sustav testiranja (Testovi_zakazani/Rezultati_testova).

    Cakijeva odluka 21.10.2026. (v. TRACKER): ZASEBAN servisni racun samo za sustav
    testiranja, da se njegova write-kvota (v. `Claude outputs/CAKI_BRIEF_kvota_sheets-
    2026-10-18-0730.md`) ne dijeli s CRM/booking/evidencija prometom. Koristi
    `GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI` ako postoji u Secrets, inace pada natrag na
    dijeljeni `GOOGLE_SERVICE_ACCOUNT_JSON` -- nista ne puca prije nego Caki postavi
    novi racun.

    Parsiranje ide kroz `sa_info_iz_teksta` (21.10.2026.) da stvarni prijelom retka u
    `private_key` ne sruši cijelu stranicu.
    """
    kljuc = ("GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI" if "GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI" in st.secrets
             else "GOOGLE_SERVICE_ACCOUNT_JSON")
    return sa_info_iz_teksta(st.secrets[kljuc], kljuc)


# ============================================================
# ID i priprema zadataka
# ============================================================

def novi_test_id(postojeci=()) -> str:
    """Jedinstven, kratak i čitljiv ID testa: T + datum + 4 znaka (npr. T261019-7K2M)."""
    danas = datetime.now().strftime("%y%m%d")
    postojeci = {str(x).strip() for x in (postojeci or ()) if str(x).strip()}
    for _ in range(50):
        kraj = "".join(_secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        kandidat = f"T{danas}-{kraj}"
        if kandidat not in postojeci:
            return kandidat
    raise RuntimeError("Ne mogu složiti jedinstven test_id — probaj ponovno.")


def broj_bodova(vrijednost, zadano: float = 1.0) -> float:
    """'2' / '2,5' / '2.5' -> broj; prazno ili smeće -> zadano (1 bod)."""
    try:
        b = float(str(vrijednost).replace(",", ".").strip())
    except (TypeError, ValueError):
        return zadano
    return b if b > 0 else zadano


def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def pripremi_zadatke(odabrani) -> tuple[list[dict], list[str]]:
    """Pretvara `st.session_state.odabrani` iz Test Buildera u popis zadataka za online test.

    Vraća (zadaci, problemi). Ako `problemi` nije prazan, objava se ne dopušta — bolje
    reći Cakiju točno koji zadatak smeta nego objaviti test koji se ne može ocijeniti.
    """
    zadaci: list[dict] = []
    problemi: list[str] = []

    for i, z in enumerate(odabrani or [], start=1):
        zid = _tekst(z.get("id")) or f"rucni-{i}"

        if z.get("stavke"):
            problemi.append(
                f"Zadatak {i} (`{zid}`) je skupina (uvod + stavke a/b/c) — skupine se zasad "
                f"ne mogu objaviti kao online test. Objavi ih kao PDF ili ih rastavi na zasebne zadatke."
            )
            continue

        tekst = _tekst(z.get("tekst"))
        if not tekst:
            problemi.append(f"Zadatak {i} (`{zid}`) nema tekst — provjeri ga u bazi.")
            continue

        odgovor = _tekst(z.get("konacan_odgovor"))
        if not odgovor:
            problemi.append(
                f"Zadatak {i} (`{zid}`) nema konačan odgovor u bazi — bez njega se ne može "
                f"automatski ocijeniti. Upiši ga u bazu (stupac „konačan odgovor”) i pokušaj ponovno."
            )
            continue

        opcije = [_tekst(o) for o in (z.get("ponudjeni_odgovori") or []) if _tekst(o)]
        visestruki = _tekst(z.get("tip_zadatka")) == "visestruki_izbor" and bool(opcije)

        zadaci.append({
            "id": zid,
            "tekst": tekst,
            "tip": "visestruki_izbor" if visestruki else "kratki_odgovor",
            "opcije": opcije if visestruki else [],
            "odgovor": odgovor,
            "bodovi": broj_bodova(z.get("bodovi")),
            "slika": _tekst(z.get("slika_putanja")),
            # 21.10.2026.: klasifikacija ide u zamrznutu kopiju da 📝 Testovi može
            # pokazati uspjeh PO CJELINAMA („razred pao na trigonometriji”).
            # Portal je ne čita — ne smeta mu.
            "cjelina": _tekst(z.get("cjelina")),
            "potpoglavlje": _tekst(z.get("potpoglavlje")),
            "tezina": _tekst(z.get("tezina")),
            # 21.10.2026.: 🧠 Bloom razina (1–5), označena LIJENO u Test Builderu — samo za zadatke
            # koji stvarno uđu u test, da se ne mora označiti 20.000 zadataka. Služi za profil
            # učenika po razinama razmišljanja (📊 Rezultati → 👤 Po učeniku).
            "bloom": _tekst(z.get("bloom")),
        })

    return zadaci, problemi


def provjeri_objavu(naziv: str, zadaci: list[dict], trajanje_min, otvara_od: str,
                    zatvara_do: str) -> list[str]:
    """Vraća popis grešaka (prazan = može se objaviti)."""
    greske: list[str] = []
    if not _tekst(naziv):
        greske.append("Upiši naziv testa (učenik ga vidi u portalu).")
    if not zadaci:
        greske.append("Nema zadataka za objavu.")
    try:
        trajanje = int(trajanje_min)
    except (TypeError, ValueError):
        trajanje = 0
    if not 5 <= trajanje <= 240:
        greske.append("Trajanje mora biti između 5 i 240 minuta.")
    if otvara_od and zatvara_do and str(zatvara_do)[:10] < str(otvara_od)[:10]:
        greske.append("Datum „otvoren do” je prije datuma „otvoren od”.")
    # Google Sheet: jedna ćelija najviše 50.000 znakova — cijeli test ide u jednu ćeliju (JSON).
    velicina = len(json.dumps(zadaci, ensure_ascii=False)) if zadaci else 0
    if velicina > 45000:
        greske.append(
            f"Test je prevelik za jednu ćeliju Sheeta ({velicina} znakova, najviše ~45.000). "
            f"Podijeli ga na dva testa ili skrati tekstove zadataka."
        )
    return greske


# ============================================================
# Sheet — tab Testovi_zakazani
# ============================================================

def osiguraj_tab(sheet):
    """Vraća radni list `Testovi_zakazani`; stvara ga (sa zaglavljem) ako ne postoji."""
    try:
        ws = sheet.worksheet(TEST_TAB)
    except Exception:
        ws = sheet.add_worksheet(title=TEST_TAB, rows=200, cols=len(TEST_HEADERS))
        ws.append_row(TEST_HEADERS, value_input_option="RAW")
        return ws

    zaglavlje = [_tekst(h) for h in ws.row_values(1)]
    if not any(zaglavlje):
        ws.append_row(TEST_HEADERS, value_input_option="RAW")
    else:
        fali = [h for h in TEST_HEADERS if h not in zaglavlje]
        if fali:
            # Samo dopuni stupce na kraj — postojeće podatke ne diramo.
            # 21.10.2026.: kad zaglavlje dobije novi stupac (npr. `serija`), tab u Googleu
            # zna biti uži od novog zaglavlja, a upis izvan mreže Google odbija — zato se
            # mreža prvo proširi. Ako proširenje nije podržano, pokušava se upis kao prije.
            try:
                ws.add_cols(len(fali))
            except Exception:                       # noqa: BLE001 — lažni Sheet / starije verzije
                pass
            ws.update(values=[zaglavlje + fali], range_name="A1")
    return ws


def _postojeci_idovi(ws) -> list[str]:
    try:
        return [_tekst(v) for v in ws.col_values(1) if _tekst(v)]
    except Exception:
        return []


def objavi_test(sheet, *, zadaci: list[dict], naziv: str, predmet: str = "",
                ucenik_id: str = "", ime_djeteta: str = "", program: str = "",
                trajanje_min=45, otvara_od: str = "", zatvara_do: str = "",
                aktivan: bool = True, autor: str = "", napomena: str = "",
                serija: str = "", pomoc: str = "", formule: str = "", rad: str = "") -> dict:
    """Upisuje JEDAN redak u `Testovi_zakazani` (jedan API poziv) i vraća upisani redak."""
    ws = osiguraj_tab(sheet)
    test_id = novi_test_id(_postojeci_idovi(ws))

    bodovi_ukupno = sum(float(z.get("bodovi") or 1) for z in zadaci)
    redak = {
        "test_id": test_id,
        "naziv": _tekst(naziv),
        "predmet": _tekst(predmet),
        "ucenik_id": _tekst(ucenik_id).upper(),
        "ime_djeteta": _tekst(ime_djeteta),
        "program": _tekst(program),
        "razina": "",
        "zadaci_json": json.dumps(zadaci, ensure_ascii=False),
        "broj_zadataka": len(zadaci),
        "bodovi_ukupno": round(bodovi_ukupno, 2),
        "trajanje_min": int(trajanje_min),
        "otvara_od": _tekst(otvara_od)[:10],
        "zatvara_do": _tekst(zatvara_do)[:10],
        "aktivan": STATUS_AKTIVAN if aktivan else "Ne",
        "autor": _tekst(autor),
        "kreirano": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "napomena": _tekst(napomena),
        "serija": _tekst(serija),
        "pomoc": "Da" if _tekst(pomoc).lower() in ("da", "1", "true") else "Ne",
        "formule_json": _tekst(formule),
        "rad": "Da" if _tekst(rad).lower() in ("da", "1", "true") else "Ne",
    }
    # Piše se po STVARNOM zaglavlju taba (ne po TEST_HEADERS): ako je neki stupac dodan
    # ili ručno obrisan, vrijednosti i dalje sjedaju u pravu kolonu.
    stvarno = [_tekst(h) for h in ws.row_values(1)] or list(TEST_HEADERS)
    ws.append_row([redak.get(h, "") for h in stvarno], value_input_option="RAW")
    return redak


def objavi_za_ucenike(sheet, *, zadaci: list[dict], ucenici, naziv: str, predmet: str = "",
                      program: str = "", trajanje_min=45, otvara_od: str = "",
                      zatvara_do: str = "", aktivan: bool = True, autor: str = "",
                      napomena: str = "", serija: str = "", pomoc: str = "",
                      formule: str = "", rad: str = "") -> list[dict]:
    """Isti test za VIŠE učenika: po jedan redak za svakoga, u JEDNOM upisu (`append_rows`).

    Zašto po redak: portal (`caki-booking-termina/testovi_online.py`) bira test po
    `ucenik_id`, pa tako radi bez ijedne izmjene portala. Zašto jedan upis: Sheets
    write-kvota je 60/min po servisnom računu (nalaz 18.10.), a razred od 20 učenika
    ne smije potrošiti 20 poziva.

    `ucenici` je popis dictova ({"ucenik_id", "ime_djeteta"}) ili popis šifri.
    Vraća popis upisanih redaka (svaki sa svojim `test_id`).
    """
    popis = list(ucenici or [])
    if not popis:
        raise ValueError("Nema učenika za koje bi se test objavio.")
    if not zadaci:
        raise ValueError("Nema zadataka za objavu.")

    ws = osiguraj_tab(sheet)
    postojeci = _postojeci_idovi(ws)
    bodovi_ukupno = sum(float(z.get("bodovi") or 1) for z in zadaci)
    zadaci_json = json.dumps(zadaci, ensure_ascii=False)
    kreirano = datetime.now().strftime("%Y-%m-%d %H:%M")

    redci: list[dict] = []
    for u in popis:
        if isinstance(u, dict):
            uid = _tekst(u.get("ucenik_id")).upper()
            ime = _tekst(u.get("ime_djeteta"))
        else:
            uid, ime = _tekst(u).upper(), ""
        if not uid:
            continue
        test_id = novi_test_id(postojeci)
        postojeci.append(test_id)              # sljedeći krug ne smije dobiti isti ID
        redci.append({
            "test_id": test_id,
            "naziv": _tekst(naziv),
            "predmet": _tekst(predmet),
            "ucenik_id": uid,
            "ime_djeteta": ime,
            "program": _tekst(program),
            "razina": "",
            "zadaci_json": zadaci_json,
            "broj_zadataka": len(zadaci),
            "bodovi_ukupno": round(bodovi_ukupno, 2),
            "trajanje_min": int(trajanje_min),
            "otvara_od": _tekst(otvara_od)[:10],
            "zatvara_do": _tekst(zatvara_do)[:10],
            "aktivan": STATUS_AKTIVAN if aktivan else "Ne",
            "autor": _tekst(autor),
            "kreirano": kreirano,
            "napomena": _tekst(napomena),
            "serija": _tekst(serija),
            "pomoc": "Da" if _tekst(pomoc).lower() in ("da", "1", "true") else "Ne",
            "formule_json": _tekst(formule),
            "rad": "Da" if _tekst(rad).lower() in ("da", "1", "true") else "Ne",
        })

    if not redci:
        raise ValueError("Nijedan učenik nema šifru — nema što objaviti.")
    stvarno = [_tekst(h) for h in ws.row_values(1)] or list(TEST_HEADERS)
    ws.append_rows([[r.get(h, "") for h in stvarno] for r in redci], value_input_option="RAW")
    return redci


def load_testovi(sheet) -> list[dict]:
    """Svi objavljeni testovi (prazna lista ako tab još ne postoji)."""
    try:
        ws = sheet.worksheet(TEST_TAB)
    except Exception:
        return []
    try:
        redci = ws.get_all_records()
    except Exception:
        return []
    return [r for r in redci if _tekst(r.get("test_id"))]


def zadaci_iz_retka(redak) -> list[dict]:
    """JSON iz retka -> popis zadataka. Neispravan JSON vraća praznu listu (ne ruši portal)."""
    sirovo = redak.get("zadaci_json") if isinstance(redak, dict) else redak
    try:
        zadaci = json.loads(str(sirovo or "[]"))
    except (TypeError, ValueError):
        return []
    return zadaci if isinstance(zadaci, list) else []


# ============================================================
# UI — objava iz Test Buildera
# ============================================================

def _danas() -> date:
    return datetime.now().date()


# ------------------------------------------------------------------------------------ publika
# 22.10.2026. — Cakijev zahtjev: test se NE smije odmah vidjeti svima. Pri objavi se bira kome
# ide, a zadano je NACRT (spremljen, ali ga ne vidi nitko) — da se slučajno ne pošalje cijelom
# programu kad je trebao samo jednoj kanti Mature.
NACRT = "NACRT"          # oznaka `serija` za neobjavljeni test (`aktivan="Ne"`)

PUBLIKE = {
    "nacrt": "🔒 Nacrt — spremi, ne vidi ga nitko",
    "grupa": "👥 Grupa / kanta (Matura ili Upisi)",
    "ucenici": "🧑 Pojedini učenici",
    "svi": "🌍 Svi učenici programa",
}


def ucenici_publike(cilj_grupe=(), cilj_ucenici=()) -> list[dict]:
    """Spoji odabrane grupe i pojedince u JEDAN popis učenika bez dvostrukih (`ucenik_id`).

    Grupa je dict s `ucenici` = [{"ucenik_id", "ime_djeteta"}]; pojedinac isto. Redoslijed je
    stabilan (prvo grupe, pa pojedinci), da test bude isti u svakom pokretanju.
    """
    izlaz: list[dict] = []
    videno: set[str] = set()
    for g in cilj_grupe or ():
        for u in (g or {}).get("ucenici") or ():
            uid = _tekst(u.get("ucenik_id")).upper()
            if not uid or uid in videno:
                continue
            videno.add(uid)
            izlaz.append({"ucenik_id": uid, "ime_djeteta": _tekst(u.get("ime_djeteta"))})
    for u in cilj_ucenici or ():
        uid = _tekst((u or {}).get("ucenik_id")).upper() if isinstance(u, dict) else _tekst(u).upper()
        if not uid or uid in videno:
            continue
        videno.add(uid)
        izlaz.append({"ucenik_id": uid,
                      "ime_djeteta": _tekst((u or {}).get("ime_djeteta")) if isinstance(u, dict) else ""})
    return izlaz


def opis_publike(publika: str, cilj_grupe=(), ucenici=()) -> str:
    """Kratak zapis u `napomena` — poslije se vidi kome je test stvarno objavljen."""
    if publika == "nacrt":
        return "NACRT — nije objavljeno"
    if publika == "grupa":
        return "Publika: " + ", ".join(_tekst((g or {}).get("naziv")) for g in cilj_grupe or ()) \
               + f" ({len(ucenici)} uč.)"
    if publika == "ucenici":
        return f"Publika: {len(ucenici)} odabranih učenika"
    return "Publika: svi učenici programa"


def objavi_prema_publici(sheet, *, zadaci, naziv: str, predmet: str = "", publika: str = "nacrt",
                         cilj_grupe=(), cilj_ucenici=(), program: str = "",
                         trajanje_min=45, otvara_od: str = "", zatvara_do: str = "",
                         autor: str = "", napomena: str = "", pomoc: str = "",
                         formule: str = "", rad: str = "") -> dict:
    """Objavi test prema odabranoj publici. Vraća {"redci": [...], "opis": str, "publika": str}.

    `nacrt` upisuje JEDAN redak s `aktivan="Ne"` i `serija="NACRT"` — ne vidi ga nitko, a ostaje
    u Sheetu da se poslije objavi bez ponovnog slaganja testa.
    """
    publika = publika if publika in PUBLIKE else "nacrt"
    zajednicko = dict(zadaci=zadaci, naziv=naziv, predmet=predmet, trajanje_min=trajanje_min,
                      otvara_od=otvara_od, zatvara_do=zatvara_do, autor=autor,
                      pomoc=pomoc, formule=formule, rad=rad)

    if publika == "nacrt":
        redak = objavi_test(sheet, aktivan=False, serija=NACRT,
                            napomena=(_tekst(napomena) + "\n" if _tekst(napomena) else "")
                                      + opis_publike("nacrt"), **zajednicko)
        return {"redci": [redak], "publika": publika, "opis": opis_publike("nacrt")}

    if publika == "svi":
        redak = objavi_test(sheet, program=program,
                            napomena=(_tekst(napomena) + "\n" if _tekst(napomena) else "")
                                      + opis_publike("svi"), **zajednicko)
        return {"redci": [redak], "publika": publika, "opis": opis_publike("svi")}

    ucenici = ucenici_publike(cilj_grupe, cilj_ucenici)
    if not ucenici:
        raise ValueError("Nije odabran nijedan učenik — test ne bi imao kome ići.")
    opis = opis_publike(publika, cilj_grupe, ucenici)
    redci = objavi_za_ucenike(sheet, ucenici=ucenici, serija=naziv,
                              napomena=(_tekst(napomena) + "\n" if _tekst(napomena) else "") + opis,
                              **zajednicko)
    return {"redci": redci, "publika": publika, "opis": opis}


def prikazi_objavu(st, sheet, odabrani, predmet: str, autor: str = "Caki",
                     formule_sheet=None, grupe=None) -> None:
    """Odlomak na dnu Test Buildera: „Objavi kao online test”. `st` se predaje da modul
    ostane uvoziv u testovima bez Streamlita.

    `grupe` = [{"kod", "naziv", "ucenici": [{"ucenik_id", "ime_djeteta"}]}] — kante Mature i
    grupe Upisa iz kojih Caki bira kome ide test (22.10.2026.). Bez njih ostaje samo nacrt i svi.
    """
    import pandas as pd

    st.divider()
    st.subheader("📝 Objavi kao online test")
    st.caption(
        "Odabrani zadaci spremaju se u CRM Sheet (tab `Testovi_zakazani`) i učenik ih rješava "
        "u portalu **Moj CAKI** pod karticom 📝 Testovi. Test se ocjenjuje automatski "
        "(višestruki izbor i kratki odgovor), a rezultat se upisuje u `Rezultati_testova`."
    )

    if not odabrani:
        st.info("Dodaj zadatke s lijeve strane pa ih možeš objaviti kao online test.")
        return

    zadaci, problemi = pripremi_zadatke(odabrani)

    if problemi:
        st.error("❌ Ovi zadaci ne mogu u online test:")
        for p in problemi:
            st.markdown(f"- {p}")
    if zadaci:
        bez_slike = sum(1 for z in zadaci if not z.get("slika"))
        st.caption(
            f"Spremno za objavu: **{len(zadaci)} zadataka**, "
            f"**{sum(float(z['bodovi']) for z in zadaci):g} bodova** · "
            f"{len(zadaci) - bez_slike} sa slikom (slika se u portalu prikazuje samo ako je portal povezan s Driveom)."
        )

    zadani_naziv = _tekst(st.session_state.get("naslov_dok")) or f"Test — {naziv_predmeta(predmet)}"

    # 22.10.2026. (Cakijev zahtjev): prije je prazno polje značilo „svima" — test je odmah
    # vidio cijeli program. Sada se KOME objavljuje bira izrijekom, a zadano je NACRT.
    # 24.10.2026. (Cakijev zahtjev): 👁️ pretpregled IDENTIČAN učeničkom — isti kod, isti
    # matematički unos (MathLive), iste slike, formule i 💡 pomoć. Ništa se ne sprema.
    _osnovni_url = str(st.secrets.get("PORTAL_URL", "https://moj-caki.streamlit.app")).rstrip("/")
    st.link_button("👁️ Otvori pretpregled — kako ovo vidi učenik", f"{_osnovni_url}/Pretpregled",
                   help="Otvara se u novom tabu na portalu učenika i traži lozinku. "
                        "Ništa se ne sprema: ni početak, ni odgovori, ni pomoć.")

    st.markdown("**Kome objavljujem**")
    publika = st.radio("Kome objavljujem", list(PUBLIKE), format_func=lambda k: PUBLIKE[k],
                       index=0, key="obj_publika", label_visibility="collapsed")
    cilj_grupe, cilj_ucenici, program = [], [], ""

    if publika == "grupa":
        opcije_g = {g["kod"]: g for g in (grupe or []) if (g or {}).get("ucenici")}
        if not opcije_g:
            st.warning("Nema grupa ni kanti s učenicima — provjeri raspored Mature ili grupe Upisa.")
        else:
            odabrane = st.multiselect(
                "Grupa / kanta", list(opcije_g),
                format_func=lambda k: f"{opcije_g[k].get('naziv', k)} ({len(opcije_g[k]['ucenici'])} uč.)",
                key="obj_grupe")
            cilj_grupe = [opcije_g[k] for k in odabrane]
            if cilj_grupe:
                st.caption(f"Test će dobiti **{len(ucenici_publike(cilj_grupe))}** učenika.")
    elif publika == "ucenici":
        svi_u = {}
        for g in grupe or []:
            for u in (g or {}).get("ucenici") or ():
                uid = _tekst(u.get("ucenik_id")).upper()
                if uid:
                    svi_u.setdefault(uid, _tekst(u.get("ime_djeteta")))
        if svi_u:
            odabrani_u = st.multiselect("Učenici", sorted(svi_u),
                                        format_func=lambda k: f"{svi_u[k] or '—'} ({k})",
                                        key="obj_ucenici")
            cilj_ucenici = [{"ucenik_id": k, "ime_djeteta": svi_u.get(k, "")} for k in odabrani_u]
        rucno = st.text_input("Ili šifre ručno (odvoji zarezom)", key="obj_sifre",
                              placeholder="AA1111, BB2222")
        for sifra in [x.strip().upper() for x in _tekst(rucno).split(",") if x.strip()]:
            cilj_ucenici.append({"ucenik_id": sifra, "ime_djeteta": ""})
        if cilj_ucenici:
            st.caption(f"Test će dobiti **{len(ucenici_publike(cilj_ucenici=cilj_ucenici))}** učenika.")
    elif publika == "svi":
        program = st.selectbox("Program", PROGRAMI, key="obj_program")
        st.warning("Ovo objavljuje **svim učenicima odabranog programa** — koristi kad test "
                   "stvarno ide svima.", icon="⚠️")
    else:
        st.caption("🔒 Nacrt se sprema u Sheet, ali ga **ne vidi nijedan učenik**. Poslije ga "
                   "objavljuješ u 📝 Testovi → 🧾 Nacrti.")

    with st.form("forma_objave_testa"):
        naziv = st.text_input("Naziv testa (vidi ga učenik)", value=zadani_naziv)
        c3, c4, c5 = st.columns(3)
        trajanje = c3.number_input("Trajanje (minuta)", min_value=5, max_value=240, value=45, step=5)
        otvara = c4.date_input("Otvoren od", value=_danas(), format="DD.MM.YYYY")
        zatvara = c5.date_input("Otvoren do", value=_danas() + timedelta(days=7), format="DD.MM.YYYY")
        napomena = st.text_area("Napomena za sebe (ne prikazuje se učeniku)", height=70)
        # 22.10.2026.: 💡 pomoć pri učenju — učenik smije pitati bota (maskiran kao profesor)
        # za sljedeći korak/pravilo, NIKAD za rješenje. Zadano ISKLJUČENO.
        pomoc = st.checkbox(
            "💡 Dopusti pomoć pri učenju (učenik može pitati za korak/pravilo)",
            value=False,
            help="Bot se predstavlja kao profesor i ne otkriva rješenje. Najviše 5 pitanja "
                 "po učeniku. Za provjere i ocjenjivane testove ostavi isključeno.")

        # 22.10.2026.: 📷 rad na papiru — učenik šalje fotografije/sken nakon predaje.
        rad = st.checkbox(
            "📷 Učenik šalje svoj rad (fotografije ili sken nakon predaje)",
            value=False,
            help="Uključi za ispite koji se rješavaju na papiru (npr. simulacija mature). "
                 "Učenik dobije uputu kako uredno skenirati; radovi se brišu nakon 7 dana.")
        # 22.10.2026.: 📐 formule uz test — paket (npr. „Matura — službene") ILI pojedinačne.
        # U test se upisuje ZAMRZNUTA kopija teksta, pa učenik vidi isto što i Caki sad.
        _formule_json = ""
        _sve_formule = []
        if formule_sheet is not None:
            try:
                import formule as _formule_mod          # noqa: PLC0415 — modul je u bazi
                _sve_formule = _formule_mod.aktivne(_formule_mod.load_formule(formule_sheet))
            except Exception:                           # noqa: BLE001 — formule ne blokiraju objavu
                _sve_formule = []
        if _sve_formule:
            _nazivi = {_tekst(f.get("formula_id")): _tekst(f.get("naslov")) for f in _sve_formule}
            _sve_f = st.checkbox("📐 Sve formule (sve aktivne)", value=False,
                                 help="Učenik vidi sve formule iz baze — najlakše za maturu.")
            _pak_od = st.multiselect("📐 Paketi formula", _formule_mod.paketi(_sve_formule),
                                     help="Npr. „Matura 2026 — službene”.")
            _id_od = st.multiselect("📐 Pojedinačne formule", list(_nazivi),
                                    format_func=lambda i, n=_nazivi: n.get(i) or i,
                                    help="Ako želiš dati samo nekoliko formula.")
            _formule_json = _formule_mod.u_json(_formule_mod.izbor_za_test(
                _sve_formule, _pak_od, _id_od, sve=_sve_f))
            if _formule_json:
                st.caption(f"📐 Učenik će vidjeti **{len(_formule_mod.iz_retka({'formule_json': _formule_json}))}** formula.")
        else:
            st.caption("📐 Nema formula u bazi — dodaj ih na stranici **📐 Formule**.")

        objavi = st.form_submit_button("📝 Objavi test", type="primary",
                                       disabled=bool(problemi) or not zadaci)

    if objavi:
        greske = provjeri_objavu(naziv, zadaci, trajanje, str(otvara), str(zatvara))
        if greske:
            for g in greske:
                st.error(g)
        else:
            try:
                rez = objavi_prema_publici(
                    sheet, zadaci=zadaci, naziv=naziv, predmet=predmet, publika=publika,
                    cilj_grupe=cilj_grupe, cilj_ucenici=cilj_ucenici, program=program,
                    trajanje_min=trajanje, otvara_od=str(otvara), zatvara_do=str(zatvara),
                    autor=autor, napomena=napomena, pomoc="Da" if pomoc else "Ne",
                    formule=_formule_json, rad="Da" if rad else "Ne",
                )
            except Exception as e:  # noqa: BLE001 — Caki mora vidjeti što je Google rekao
                st.error(f"Objava nije uspjela: {e}")
            else:
                prvi = rez["redci"][0]
                if rez["publika"] == "nacrt":
                    st.info(f"🔒 **Spremljeno kao nacrt** (ID `{prvi['test_id']}`). Test je u "
                            "Sheetu, ali ga **ne vidi nijedan učenik**. Objavi ga kad budeš "
                            "spreman — 📝 Testovi → 🧾 Nacrti.", icon="🔒")
                else:
                    st.success(
                        f"✅ Objavljeno: **{len(rez['redci'])} učenika** · {prvi['broj_zadataka']} "
                        f"zadataka · {prvi['bodovi_ukupno']:g} bodova · otvoren "
                        f"{prvi['otvara_od']} – {prvi['zatvara_do']}.\n\n{rez['opis']}.")
                    st.caption("Učenici ga vide u Moj CAKI → 📝 Testovi unutar razdoblja. Rezultati "
                               "se upisuju u `Rezultati_testova` (isti CRM Sheet).")
                st.caption("Učenik ga vidi u Moj CAKI → 📝 Testovi. Rezultati se upisuju u "
                           "`Rezultati_testova` (isti CRM Sheet).")

    # Popis zadnjih objava — da se vidi da je upis prošao i da se ID može prepisati.
    try:
        testovi = load_testovi(sheet)
    except Exception:
        testovi = []
    if testovi:
        zadnji = sorted(testovi, key=lambda r: _tekst(r.get("kreirano")), reverse=True)[:5]
        st.markdown("**Zadnjih 5 objavljenih testova**")
        st.dataframe(
            pd.DataFrame([{
                "ID": r.get("test_id", ""),
                "Naziv": r.get("naziv", ""),
                "Učenik": r.get("ucenik_id", "") or "svi",
                "Program": r.get("program", "") or "svi",
                "Zadataka": r.get("broj_zadataka", ""),
                "Otvoren": f"{r.get('otvara_od', '')} – {r.get('zatvara_do', '')}",
                "Aktivan": r.get("aktivan", ""),
            } for r in zadnji]),
            hide_index=True, width="stretch",
        )


def naziv_predmeta(predmet: str) -> str:
    """Naziv predmeta za zadani naziv testa — bez uvoza cijelog predmet_config u testove."""
    nazivi = {"matematika": "Matematika", "matematika_os": "Matematika OŠ", "fizika": "Fizika"}
    return nazivi.get(_tekst(predmet), "Matematika")


__all__ = [
    "TEST_TAB", "TEST_HEADERS", "PROGRAMI", "STATUS_AKTIVAN",
    "novi_test_id", "broj_bodova", "pripremi_zadatke", "provjeri_objavu",
    "osiguraj_tab", "objavi_test", "objavi_za_ucenike", "load_testovi", "zadaci_iz_retka",
    "prikazi_objavu", "naziv_predmeta",
    "sa_info_za_testove", "sa_info_iz_teksta",
]
