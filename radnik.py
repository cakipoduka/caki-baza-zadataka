"""CAKI — radnik.py  (22.10.2026.)

POKRETAČ dugotrajnih poslova nad bazom zadataka — namjerno **bez Streamlita**, jer posao u
Streamlitu ne preživi zatvaranje taba ni hibernaciju appa (vidi `upute/ARHITEKTURA_RADNIK.md`).
Radnik se pokreće kao GitHub Actions posao (`radnik.yml`) ili lokalno:

    python radnik.py --posao cijepanje --predmet matematika --limit 50 --isprobaj
    python radnik.py --posao cijepanje --predmet matematika --limit 500
    python radnik.py --vrati cijepanje-matematika-20261023-0130

Što jamči:
  - **Nastavak:** napredak ide u tab `Radnik_stanje` (zadnji obrađeni ID, broj, status). Ponovni
    start s istom `--serija` nastavlja gdje je stao, ne počinje iznova.
  - **Idempotencija:** preskače retke koji su već razdvojeni (`uloga` postavljena) ili već zabilježeni
    u `Promjene_log` za tu seriju — dvostruki start ne udvostručuje stavke.
  - **Undo:** `Promjene_log` pamti staro i novo za svaku ćeliju i svaki novi redak, pa `--vrati`
    vraća stanje prije serije.
  - **Kvota:** upisi idu u paketima (`batch_update`, `append_rows`), s pauzom između paketa.
  - **Tajne i logovi:** ključevi dolaze iz okoline (GitHub Secrets), a ispis u log NIKAD ne sadrži
    tekst zadatka — logovi ovog repoa su javni (isto pravilo kao u `skripta_build.py`).

Poslovi su plugini u `radnik_poslovi.py`; ovdje je samo „motor" (čitanje, upis, stanje, undo).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

ZADACI_TAB = "Zadaci"
STANJE_TAB = "Radnik_stanje"
LOG_TAB = "Promjene_log"

STANJE_HEADERS = ["serija", "posao", "predmet", "zadnji_id", "obradeno", "status", "greska", "azurirano"]
LOG_HEADERS = ["serija", "vrijeme", "posao", "predmet", "id", "polje", "staro", "novo"]

PAKET = 50            # koliko promjena ide u jednom pozivu prema Sheetu
PAUZA_S = 1.0         # pauza između paketa (kvota: ~60 upisa/min)


def _s(vrijednost) -> str:
    return str(vrijednost if vrijednost is not None else "").strip()


def _sada() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def serija_id(posao: str, predmet: str, sada: datetime | None = None) -> str:
    return f"{posao}-{predmet}-{(sada or datetime.now()).strftime('%Y%m%d-%H%M')}"


# ---------------------------------------------------------------------------------------------
# Tabovi: stanje i log
# ---------------------------------------------------------------------------------------------

def osiguraj_tab(sheet, naziv: str, headers: list):
    """Otvori tab po nazivu ili ga kreiraj sa zaglavljem (kao get_or_create_worksheet u pipelineu)."""
    try:
        return sheet.worksheet(naziv)
    except Exception:                                    # noqa: BLE001 — tab još ne postoji
        ws = sheet.add_worksheet(title=naziv, rows=2000, cols=max(len(headers), 8))
        ws.append_row(headers, value_input_option="RAW")
        return ws


def ucitaj_stanje(ws) -> dict:
    """{serija: {…}} iz taba Radnik_stanje (prazno ako tab nema redaka)."""
    try:
        zapisi = ws.get_all_records()
    except Exception:                                    # noqa: BLE001
        return {}
    return {_s(z.get("serija")): z for z in zapisi if _s(z.get("serija"))}


def zapisi_stanje(ws, *args, **kw):
    """Dopiši/izmjeni jedan redak stanja — vidi `postavi_stanje` niže (ista svrha, čitljivije ime)."""
    return postavi_stanje(ws, *args, **kw)


def postavi_stanje(ws, serija: str, posao: str, predmet: str, zadnji_id: str, obradeno: int,
                   status: str, greska: str = "") -> None:
    """Upiši stanje serije: postojeći redak se MIJENJA (jedan upis), inače se dodaje novi."""
    redak = [serija, posao, predmet, _s(zadnji_id), int(obradeno), status, _s(greska)[:300], _sada()]
    try:
        celije = ws.findall(serija, case_sensitive=True)      # traži po bilo kojoj ćeliji
    except Exception:                                          # noqa: BLE001
        celije = []
    redak_broj = next((c.row for c in celije if c.col == 1), None)
    if redak_broj:
        ws.update(values=[redak], range_name=f"A{redak_broj}:{chr(ord('A') + len(redak) - 1)}{redak_broj}",
                  value_input_option="RAW")
    else:
        ws.append_row(redak, value_input_option="RAW")


def zapisi_promjene(ws, serija: str, posao: str, predmet: str, promjene: list) -> None:
    """Promjene u tab `Promjene_log`: [{"id","polje","staro","novo"}, …]."""
    if not promjene:
        return
    vrijeme = _sada()
    ws.append_rows([[serija, vrijeme, posao, predmet, p["id"], p["polje"], _s(p["staro"]), _s(p["novo"])]
                    for p in promjene], value_input_option="RAW")


def procitaj_log(ws) -> list:
    try:
        return ws.get_all_records()
    except Exception:                                    # noqa: BLE001
        return []


# ---------------------------------------------------------------------------------------------
# Čitanje baze
# ---------------------------------------------------------------------------------------------

def ucitaj_zadatke(ws) -> tuple[list, list]:
    """(headers, redci) — redci su dictovi {stupac: vrijednost}, redom kako stoje u tabu."""
    sve = ws.get_all_values()
    if not sve:
        return [], []
    headers = [_s(h) for h in sve[0]]
    redci = []
    for r in sve[1:]:
        redci.append({h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)})
    return headers, redci


def _stupac(headers: list, naziv: str) -> int:
    return headers.index(naziv) if naziv in headers else -1


def _slovo(indeks: int) -> str:
    """0-indeks -> A, B, … Z, AA, AB (isto pravilo kao _col_letter u pipelineu)."""
    slova, indeks = "", indeks + 1
    while indeks > 0:
        indeks, ostatak = divmod(indeks - 1, 26)
        slova = chr(65 + ostatak) + slova
    return slova


# ---------------------------------------------------------------------------------------------
# Primjena promjena
# ---------------------------------------------------------------------------------------------

def primijeni(ws_zadaci, headers: list, azuriranja: list, novi_redci: list) -> tuple[int, int]:
    """Upiši promjene u paketima. Vraća (broj izmijenjenih redaka, broj novih redaka).

    `azuriranja` = [{"redak": 2, "polja": {"uloga": "skupina", …}}, …]
    `novi_redci` = [ {stupac: vrijednost} u redoslijedu `headers`, … ]
    """
    izmijenjeno = 0
    for i in range(0, len(azuriranja), PAKET):
        paket = []
        for a in azuriranja[i:i + PAKET]:
            for polje, vrijednost in a["polja"].items():
                idx = _stupac(headers, polje)
                if idx < 0:
                    continue
                paket.append({"range": f"{_slovo(idx)}{a['redak']}",
                              "values": [[vrijednost]]})
        if paket:
            ws_zadaci.batch_update(paket, value_input_option="RAW")
            izmijenjeno += len(azuriranja[i:i + PAKET])
        time.sleep(PAUZA_S)
    for i in range(0, len(novi_redci), PAKET):
        ws_zadaci.append_rows([[r.get(h, "") for h in headers] for r in novi_redci[i:i + PAKET]],
                              value_input_option="RAW")
        time.sleep(PAUZA_S)
    return izmijenjeno, len(novi_redci)


def vrati_seriju(sheet, serija: str) -> dict:
    """Undo: vrati stare vrijednosti i obriši retke koje je serija dodala.

    Briše se ODOZDO PREMA GORE (da pomicanje redaka ne pokvari indekse), a vraćanje vrijednosti
    traži redak po `id` (nikad po zapamćenom broju retka — između dva pokretanja redoslijed se
    može promijeniti).
    """
    log = [r for r in procitaj_log(osiguraj_tab(sheet, LOG_TAB, LOG_HEADERS))
           if _s(r.get("serija")) == _s(serija)]
    if not log:
        return {"vraceno_polja": 0, "obrisano_redaka": 0, "greska": "serija nije u Promjene_log"}

    ws = sheet.worksheet(ZADACI_TAB)
    headers, redci = ucitaj_zadatke(ws)
    redak_po_id = {_s(r.get("id")): br for br, r in enumerate(redci, start=2) if _s(r.get("id"))}
    id_stupac = _stupac(headers, "id")

    brisati = []
    vraceno = 0
    for z in log:
        rid = _s(z.get("id"))
        if _s(z.get("polje")) == "+redak":
            if rid in redak_po_id:
                brisati.append(redak_po_id[rid])
            continue
        br = redak_po_id.get(rid)
        idx = _stupac(headers, _s(z.get("polje")))
        if not br or idx < 0:
            continue
        ws.update(values=[[_s(z.get("staro"))]], range_name=f"{_slovo(idx)}{br}", value_input_option="RAW")
        vraceno += 1

    for br in sorted(set(brisati), reverse=True):
        ws.delete_rows(br)
    return {"vraceno_polja": vraceno, "obrisano_redaka": len(set(brisati))}


# ---------------------------------------------------------------------------------------------
# Pokretač (CLI)
# ---------------------------------------------------------------------------------------------

def _secrets_iz_okoline() -> dict:
    """Sve iz okoline kao dict — predmet_config čita Sheet ID po ključu predmeta."""
    return dict(os.environ)


def _otvori_sheet(token_ili_sa: dict, predmet: str, sheet_id: str):
    """gspread klijent iz servisnog računa + Sheet po ID-u (iz argumenta ili predmet_config)."""
    import gspread
    from google.oauth2.service_account import Credentials

    sa = token_ili_sa
    if isinstance(sa, str):
        sa = json.loads(sa)
    kredencijali = Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    klijent = gspread.authorize(kredencijali)
    return klijent.open_by_key(sheet_id)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="CAKI radnik — dugotrajni poslovi nad bazom zadataka")
    p.add_argument("--posao", default="cijepanje", help="cijepanje | kratki_odgovor | (v. radnik_poslovi.py)")
    p.add_argument("--predmet", default="matematika",
                   help="matematika | matematika_os | fizika | matematika_fakultet")
    p.add_argument("--limit", type=int, default=0, help="najviše zadataka u ovom pokretanju (0 = svi)")
    p.add_argument("--serija", default="", help="ID serije za nastavak; prazno = nova serija")
    p.add_argument("--isprobaj", action="store_true", help="ništa ne piše, samo izbroji")
    p.add_argument("--vrati", default="", help="ID serije koju treba vratiti (undo)")
    p.add_argument("--sheet-id", default="", help="ako je prazno, uzima se iz predmet_config")
    p.add_argument("--pauza", type=float, default=PAUZA_S)
    args = p.parse_args(argv)

    import predmet_config as pc
    import radnik_poslovi as rp

    sirovi_kljuc = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sirovi_kljuc:
        print("GREŠKA: nema GOOGLE_SERVICE_ACCOUNT_JSON u okolini.")
        return 2

    sheet_id = args.sheet_id or pc.sheet_id(args.predmet, _secrets_iz_okoline())
    if not sheet_id:
        print(f"GREŠKA: predmet '{args.predmet}' nema Sheet ID u okolini.")
        return 2

    sheet = _otvori_sheet(sirovi_kljuc, args.predmet, sheet_id)

    if args.vrati:
        rez = vrati_seriju(sheet, args.vrati)
        print(f"UNDO {args.vrati}: vraćeno polja {rez['vraceno_polja']}, "
              f"obrisano redaka {rez['obrisano_redaka']}" + (f" ({rez['greska']})" if rez.get("greska") else ""))
        return 0 if not rez.get("greska") else 1

    posao = rp.dohvati(args.posao)
    if posao is None:
        print(f"GREŠKA: nepoznat posao '{args.posao}'. Dostupno: {', '.join(rp.dostupni())}")
        return 2

    ws_zadaci = sheet.worksheet(ZADACI_TAB)
    headers, redci = ucitaj_zadatke(ws_zadaci)
    ws_stanje = osiguraj_tab(sheet, STANJE_TAB, STANJE_HEADERS)
    ws_log = osiguraj_tab(sheet, LOG_TAB, LOG_HEADERS)

    serija = args.serija or serija_id(args.posao, args.predmet)
    stanje = ucitaj_stanje(ws_stanje).get(serija) or {}
    zadnji_id = _s(stanje.get("zadnji_id"))
    obradeno = int(stanje.get("obradeno") or 0)

    # nastavak: preskoči sve do (uključivo) zadnjeg obrađenog retka
    if zadnji_id:
        for i, r in enumerate(redci):
            if _s(r.get("id")) == zadnji_id:
                redci = redci[i + 1:]
                break

    postavi_stanje(ws_stanje, serija, args.posao, args.predmet, zadnji_id, obradeno, "u_tijeku")
    print(f"Radnik: posao={args.posao} predmet={args.predmet} serija={serija} "
          f"nastavak={bool(zadnji_id)} isprobaj={args.isprobaj}")

    azuriranja, novi_redci, log_promjene, preskoceno = [], [], [], 0
    ukupno = 0
    for br, redak in enumerate(redci, start=2):
        if args.limit and ukupno >= args.limit:
            break
        rid = _s(redak.get("id"))
        if not rid:
            continue
        promjene = posao["predlozi"](redak, sheet=sheet)
        if not promjene:
            continue
        if posao["vec_obradjeno"](redak):
            preskoceno += 1
            continue
        if not posao["provjeri"](redak, promjene):
            preskoceno += 1
            continue
        azuriranja.append({"redak": br, "polja": promjene["polja"]})
        novi_redci.extend(promjene["novi_redci"])
        log_promjene.extend(promjene["log"])
        ukupno += 1
        zadnji_id = rid

    print(f"Za upis: {len(azuriranja)} zadataka, {len(novi_redci)} novih redaka, preskočeno {preskoceno}.")

    if args.isprobaj:
        print("ISPROBAJ: ništa nije upisano.")
        return 0

    if azuriranja or novi_redci:
        izmijenjeno, dodano = primijeni(ws_zadaci, headers, azuriranja, novi_redci)
        zapisi_promjene(ws_log, serija, args.posao, args.predmet, log_promjene)
        obradeno += len(azuriranja)
        postavi_stanje(ws_stanje, serija, args.posao, args.predmet, zadnji_id, obradeno, "gotovo")
        print(f"Upisano: izmijenjeno {izmijenjeno}, novih {dodano}. Serija {serija}.")
    else:
        postavi_stanje(ws_stanje, serija, args.posao, args.predmet, zadnji_id, obradeno, "gotovo")
        print("Nema što upisati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
