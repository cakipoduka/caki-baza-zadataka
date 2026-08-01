"""
CAKI Upisi u SŠ — pipeline_upisi.py
Pomoćne funkcije za rad s Učenici/Prijave tabovima preko gspread-a.
Isti stack kao baza zadataka (get_credentials/get_gspread_client pattern).
"""
import random
import string
from datetime import datetime, timedelta

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Nazivi komponenti — kod : čitljiva labela za dropdown
KOMPONENTE = {
    "MAT-KRATKI": "Matematika — kratki (20h)",
    "MAT-DUGI": "Matematika — dugi (36h)",
    "PRELOG-KRATKI": "Prelog — kratki (34h)",
    "PRELOG-DUGI": "Prelog — dugi (46h)",
    "HR": "Hrvatski (10h)",
    "ENG": "Engleski (10h)",
    "SIM-A": "Simulacija A — Prelog",
    "SIM-B": "Simulacija B — Matematika (matematičke gimnazije)",
    "SIM-C": "Simulacija C — Matematika i hrvatski (opće gimnazije)",
}

STATUSI_POZIVA = ["Čeka poziv", "Potvrdio", "Čeka", "Odustao"]

# Ista konstanta kao u Apps Scriptu — mijenja se jednom godišnje
SEZONA = "2026/27"

# Koje komponente uopće imaju tjedne termine za booking (SIM-* i HR isključeni — drugi obrasci rasporeda)
KOMPONENTE_ZA_BOOKING = ["MAT-KRATKI", "MAT-DUGI", "PRELOG-KRATKI", "PRELOG-DUGI", "ENG"]

REZERVACIJA_ROK_DANA = 5

# Popis nastavnika — jednostavan popis imena, dovoljno za sad (bez zasebnog Nastavnici taba)
NASTAVNICI = ["Caki (ja)", "Neira", "Slađana", "Mirela", "Ivica", "Martina"]

DANI_U_TJEDNU = ["Ponedjeljak", "Utorak", "Srijeda", "Četvrtak", "Petak", "Subota", "Nedjelja"]


# --- Autentifikacija (identično baza zadataka) ---

def get_credentials(service_account_info: dict):
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


def get_gspread_client(service_account_info: dict):
    return gspread.authorize(get_credentials(service_account_info))


# --- Učitavanje podataka ---

def _load_worksheet_df(ws) -> pd.DataFrame:
    """Robustno učitavanje - radi ispravno i kad tab ima samo header, bez ijednog retka podataka."""
    headers = ws.row_values(1)
    records = ws.get_all_records()
    if not records:
        df = pd.DataFrame(columns=headers)
    else:
        df = pd.DataFrame(records)
    df["_row"] = range(2, len(df) + 2)
    return df


def load_ucenici(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Učenici"))


def load_prijave(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Prijave"))


# --- Uređivanje kontakt podataka učenika ---

def azuriraj_ucenika(sheet, row_number: int, polja: dict):
    """polja = {"ime_djeteta": "...", "mobitel_djeteta": "...", ...}"""
    ws = sheet.worksheet("Učenici")
    headers = ws.row_values(1)
    for naziv_polja, vrijednost in polja.items():
        if naziv_polja in headers:
            col = headers.index(naziv_polja) + 1
            ws.update_cell(row_number, col, vrijednost)


def ocisti_duplikat_flag(sheet, row_number: int):
    azuriraj_ucenika(sheet, row_number, {"moguci_duplikat_id": ""})


def spoji_ucenike(sheet, primarni_id: str, duplikat_id: str):
    """Prebacuje sve Prijave retke s duplikat_id na primarni_id, briše duplikat iz Učenici."""
    ws_prijave = sheet.worksheet("Prijave")
    prijave = ws_prijave.get_all_records()
    headers = ws_prijave.row_values(1)
    col_ucenik_id = headers.index("ucenik_id") + 1

    for i, red in enumerate(prijave, start=2):
        if red.get("ucenik_id") == duplikat_id:
            ws_prijave.update_cell(i, col_ucenik_id, primarni_id)

    ws_ucenici = sheet.worksheet("Učenici")
    ucenici = ws_ucenici.get_all_records()
    for i, red in enumerate(ucenici, start=2):
        if red.get("ucenik_id") == duplikat_id:
            ws_ucenici.delete_rows(i)
            break


# --- Status poziva ---

def postavi_status_poziva(sheet, ucenik_id: str, novi_status: str):
    """Postavlja status_kontakta na sve 'Čeka poziv' retke tog učenika.
    Ako je novi_status == 'Potvrdio', upisuje i posalji_nakon = sada + 24h."""
    ws = sheet.worksheet("Prijave")
    prijave = ws.get_all_records()
    headers = ws.row_values(1)
    col_status = headers.index("status_kontakta") + 1
    col_posalji = headers.index("posalji_nakon") + 1 if "posalji_nakon" in headers else None

    posalji_nakon_vrijednost = ""
    if novi_status == "Potvrdio":
        posalji_nakon_vrijednost = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    azurirano = 0
    for i, red in enumerate(prijave, start=2):
        if red.get("ucenik_id") == ucenik_id and red.get("status_kontakta") == "Čeka poziv":
            ws.update_cell(i, col_status, novi_status)
            if novi_status == "Potvrdio" and col_posalji:
                ws.update_cell(i, col_posalji, posalji_nakon_vrijednost)
            azurirano += 1

    return azurirano


def oznaci_otkazano(sheet, row_number: int):
    ws = sheet.worksheet("Prijave")
    headers = ws.row_values(1)
    col_status = headers.index("status_kontakta") + 1
    ws.update_cell(row_number, col_status, "Otkazano")


# --- Dodavanje nove komponente postojećem učeniku ---

def dodaj_komponentu(sheet, ucenik_id: str, ime_djeteta: str, komponenta_kod: str, nacin_placanja: str, napomena: str = ""):
    ws = sheet.worksheet("Prijave")
    redak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws.append_row([
        redak_id,
        str(ucenik_id),
        str(ime_djeteta),
        str(komponenta_kod),
        str(nacin_placanja),
        "Čeka poziv",
        "Ne",
        str(napomena),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "",
        SEZONA,
    ])


# ============================================================
# GRUPE / REZERVACIJE — booking sustav
# ============================================================

def postavi_tabove_booking(sheet):
    """Kreira 'Grupe' i 'Rezervacije' tabove ako ne postoje. Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]

    if "Grupe" not in postojeci:
        ws = sheet.add_worksheet(title="Grupe", rows=200, cols=11)
        ws.append_row([
            "grupa_id", "program", "dan", "vrijeme", "ucionica",
            "kapacitet", "tip", "aktivna", "admin_rezervirano", "redovni_nastavnik", "sezona"
        ])

    if "Rezervacije" not in postojeci:
        ws = sheet.add_worksheet(title="Rezervacije", rows=500, cols=8)
        ws.append_row([
            "rezervacija_id", "grupa_id", "ucenik_id", "ime_djeteta",
            "kontakt_roditelja", "vrijeme_rezervacije", "status", "sezona"
        ])


def load_grupe(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Grupe"))


def load_rezervacije(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Rezervacije"))


def kreiraj_grupu(sheet, program, dan, vrijeme, ucionica, kapacitet, tip, aktivna=True, redovni_nastavnik=""):
    ws = sheet.worksheet("Grupe")
    grupa_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    ws.append_row([
        grupa_id, program, dan, vrijeme, ucionica,
        kapacitet, tip, "da" if aktivna else "ne", 0, str(redovni_nastavnik), SEZONA
    ])
    return grupa_id


def azuriraj_grupu(sheet, row_number: int, polja: dict):
    ws = sheet.worksheet("Grupe")
    headers = ws.row_values(1)
    for naziv, vrijednost in polja.items():
        if naziv in headers:
            col = headers.index(naziv) + 1
            ws.update_cell(row_number, col, vrijednost)


def izracunaj_dostupnost(grupa_red: dict, df_rezervacije: pd.DataFrame) -> dict:
    """Vraća {'slobodna': int, 'potvrdjeno': int, 'na_cekanju_uplate': int, 'status_boja': 'zeleno'/'narancasto'/'crveno'}"""
    grupa_id = grupa_red["grupa_id"]
    kapacitet = int(grupa_red.get("kapacitet") or 0)
    admin_rez = int(grupa_red.get("admin_rezervirano") or 0)

    rez_grupe = df_rezervacije[df_rezervacije["grupa_id"] == grupa_id] if not df_rezervacije.empty else df_rezervacije

    potvrdjeno = 0
    na_cekanju = 0
    if not rez_grupe.empty:
        potvrdjeno = len(rez_grupe[rez_grupe["status"] == "Potvrđeno"])
        sada = datetime.now()

        def nije_isteklo(red):
            try:
                vrijeme = datetime.strptime(red["vrijeme_rezervacije"], "%Y-%m-%d %H:%M:%S")
                return (sada - vrijeme).days < REZERVACIJA_ROK_DANA
            except (ValueError, TypeError):
                return True

        cekaju = rez_grupe[rez_grupe["status"] == "Rezervirano"]
        na_cekanju = sum(1 for _, r in cekaju.iterrows() if nije_isteklo(r))

    zauzeto = potvrdjeno + na_cekanju + admin_rez
    slobodna = kapacitet - zauzeto

    if slobodna > 0:
        boja = "zeleno"
    elif na_cekanju > 0:
        boja = "narancasto"
    else:
        boja = "crveno"

    return {
        "slobodna": max(slobodna, 0),
        "potvrdjeno": potvrdjeno,
        "na_cekanju_uplate": na_cekanju,
        "status_boja": boja,
    }


def kreiraj_rezervaciju(sheet, grupa_id, ucenik_id, ime_djeteta, kontakt_roditelja, status="Rezervirano"):
    ws = sheet.worksheet("Rezervacije")
    rezervacija_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws.append_row([
        rezervacija_id,
        str(grupa_id),
        str(ucenik_id),
        str(ime_djeteta),
        str(kontakt_roditelja),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        str(status),
        SEZONA,
    ])
    return rezervacija_id


def azuriraj_rezervaciju(sheet, row_number: int, novi_status: str, resetiraj_vrijeme: bool = False):
    ws = sheet.worksheet("Rezervacije")
    headers = ws.row_values(1)
    col_status = headers.index("status") + 1
    ws.update_cell(row_number, col_status, novi_status)

    if resetiraj_vrijeme and "vrijeme_rezervacije" in headers:
        col_vrijeme = headers.index("vrijeme_rezervacije") + 1
        ws.update_cell(row_number, col_vrijeme, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def dohvati_ucenika_po_id(df_ucenici: pd.DataFrame, ucenik_id: str):
    red = df_ucenici[df_ucenici["ucenik_id"] == ucenik_id]
    return red.iloc[0] if not red.empty else None


# ============================================================
# DOLASCI — Termini / Dolasci / Gostovanja / Zamjene log
# ============================================================

def postavi_tabove_dolasci(sheet):
    """Kreira Termini, Dolasci, Gostovanja, Zamjene log tabove ako ne postoje. Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]

    if "Termini" not in postojeci:
        ws = sheet.add_worksheet(title="Termini", rows=1000, cols=6)
        ws.append_row(["termin_id", "grupa_id", "datum", "nastavnik_odrzao", "sezona"])

    if "Dolasci" not in postojeci:
        ws = sheet.add_worksheet(title="Dolasci", rows=5000, cols=8)
        ws.append_row(["dolazak_id", "termin_id", "grupa_id", "ucenik_id", "ime_djeteta", "status", "sezona"])

    if "Gostovanja" not in postojeci:
        ws = sheet.add_worksheet(title="Gostovanja", rows=500, cols=8)
        ws.append_row(["gostovanje_id", "datum", "ucenik_id", "ime_djeteta", "maticna_grupa", "grupa_gostovanja", "sezona"])

    if "Zamjene log" not in postojeci:
        ws = sheet.add_worksheet(title="Zamjene log", rows=500, cols=6)
        ws.append_row(["datum", "grupa_id", "redovni_nastavnik", "zamjena_nastavnik", "razlog", "iznos_obracuna"])


def load_termini(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Termini"))


def load_dolasci(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Dolasci"))


def load_gostovanja(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Gostovanja"))


def pronadji_ili_kreiraj_termin(sheet, grupa_id: str, datum: str, nastavnik_odrzao: str, redovni_nastavnik: str) -> str:
    """Vraća termin_id za (grupa_id, datum) - reuse ako već postoji (npr. nastavnik uređuje isti dan),
    inače kreira novi. Ako nastavnik_odrzao != redovni_nastavnik, upisuje u Zamjene log (samo jednom)."""
    ws_termini = sheet.worksheet("Termini")
    postojeci = ws_termini.get_all_records()
    headers = ws_termini.row_values(1)

    for i, red in enumerate(postojeci, start=2):
        if str(red.get("grupa_id")) == str(grupa_id) and str(red.get("datum")) == str(datum):
            # Termin već postoji — ažuriraj nastavnika ako se promijenio
            if str(red.get("nastavnik_odrzao")) != str(nastavnik_odrzao):
                col = headers.index("nastavnik_odrzao") + 1
                ws_termini.update_cell(i, col, str(nastavnik_odrzao))
                _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, nastavnik_odrzao)
            return red.get("termin_id")

    # Novi termin
    termin_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    ws_termini.append_row([termin_id, str(grupa_id), str(datum), str(nastavnik_odrzao), SEZONA])

    if str(nastavnik_odrzao) != str(redovni_nastavnik):
        _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, nastavnik_odrzao)

    return termin_id


def _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, zamjena_nastavnik):
    ws = sheet.worksheet("Zamjene log")
    postojeci = ws.get_all_records()
    for red in postojeci:
        if str(red.get("grupa_id")) == str(grupa_id) and str(red.get("datum")) == str(datum):
            return  # već zabilježeno, ne dupliciraj
    ws.append_row([str(datum), str(grupa_id), str(redovni_nastavnik), str(zamjena_nastavnik), "", ""])


def spremi_dolazak(sheet, termin_id: str, grupa_id: str, ucenik_id: str, ime_djeteta: str, status: str):
    """Upsert - ako već postoji zapis za (termin_id, ucenik_id), ažurira status umjesto duplog upisa.
    NAPOMENA: koristi spremi_cijeli_termin() za spremanje više učenika odjednom - puno manje API poziva."""
    ws = sheet.worksheet("Dolasci")
    postojeci = ws.get_all_records()
    headers = ws.row_values(1)

    for i, red in enumerate(postojeci, start=2):
        if str(red.get("termin_id")) == str(termin_id) and str(red.get("ucenik_id")) == str(ucenik_id):
            col = headers.index("status") + 1
            ws.update_cell(i, col, str(status))
            return

    dolazak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    ws.append_row([dolazak_id, str(termin_id), str(grupa_id), str(ucenik_id), str(ime_djeteta), str(status), SEZONA])


def spremi_cijeli_termin(sheet, grupa_id, datum, nastavnik_odrzao, redovni_nastavnik, roster_zapisi, gosti_zapisi):
    """Sprema termin + sve dolaske (roster i goste) u minimalnom broju API poziva - jedan Save klik = par poziva, ne desetci.
    roster_zapisi / gosti_zapisi = liste dictova: {"ucenik_id":..., "ime_djeteta":..., "status":..., "maticna_grupa": (samo gosti)}"""

    # --- 1) Termin: jedan get_all_records + jedan append/update ---
    ws_termini = sheet.worksheet("Termini")
    termini_postojeci = ws_termini.get_all_records()
    termini_headers = ws_termini.row_values(1)

    termin_id = None
    for i, red in enumerate(termini_postojeci, start=2):
        if str(red.get("grupa_id")) == str(grupa_id) and str(red.get("datum")) == str(datum):
            termin_id = red.get("termin_id")
            if str(red.get("nastavnik_odrzao")) != str(nastavnik_odrzao):
                col = termini_headers.index("nastavnik_odrzao") + 1
                ws_termini.update_cell(i, col, str(nastavnik_odrzao))
            break

    if termin_id is None:
        termin_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        ws_termini.append_row([termin_id, str(grupa_id), str(datum), str(nastavnik_odrzao), SEZONA])

    if str(nastavnik_odrzao) != str(redovni_nastavnik):
        _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, nastavnik_odrzao)

    # --- 2) Dolasci: jedan get_all_records, pa batch update + batch append ---
    ws_dolasci = sheet.worksheet("Dolasci")
    dolasci_postojeci = ws_dolasci.get_all_records()
    dolasci_headers = ws_dolasci.row_values(1)
    col_status = dolasci_headers.index("status") + 1

    postojeci_lookup = {}
    for i, red in enumerate(dolasci_postojeci, start=2):
        if str(red.get("termin_id")) == str(termin_id):
            postojeci_lookup[str(red.get("ucenik_id"))] = i

    svi_zapisi = list(roster_zapisi) + list(gosti_zapisi)

    batch_update_podaci = []
    novi_redovi = []
    for z in svi_zapisi:
        uid = str(z["ucenik_id"])
        if uid in postojeci_lookup:
            redak = postojeci_lookup[uid]
            batch_update_podaci.append({
                "range": gspread.utils.rowcol_to_a1(redak, col_status),
                "values": [[str(z["status"])]],
            })
        else:
            dolazak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
            novi_redovi.append([dolazak_id, str(termin_id), str(grupa_id), uid, str(z["ime_djeteta"]), str(z["status"]), SEZONA])

    if batch_update_podaci:
        ws_dolasci.batch_update(batch_update_podaci)
    if novi_redovi:
        ws_dolasci.append_rows(novi_redovi)

    # --- 3) Gostovanja: jedan get_all_records, pa batch append (samo novi) ---
    if gosti_zapisi:
        ws_gost = sheet.worksheet("Gostovanja")
        gost_postojeci = ws_gost.get_all_records()
        gost_postojeci_set = {
            (str(r.get("datum")), str(r.get("ucenik_id")), str(r.get("grupa_gostovanja")))
            for r in gost_postojeci
        }
        novi_gosti = []
        for z in gosti_zapisi:
            kljuc = (str(datum), str(z["ucenik_id"]), str(grupa_id))
            if kljuc not in gost_postojeci_set:
                gostovanje_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
                novi_gosti.append([
                    gostovanje_id, str(datum), str(z["ucenik_id"]), str(z["ime_djeteta"]),
                    str(z["maticna_grupa"]), str(grupa_id), SEZONA
                ])
        if novi_gosti:
            ws_gost.append_rows(novi_gosti)

    return termin_id


def dodaj_gostovanje(sheet, datum: str, ucenik_id: str, ime_djeteta: str, maticna_grupa: str, grupa_gostovanja: str):
    ws = sheet.worksheet("Gostovanja")
    postojeci = ws.get_all_records()
    for red in postojeci:
        if (
            str(red.get("datum")) == str(datum)
            and str(red.get("ucenik_id")) == str(ucenik_id)
            and str(red.get("grupa_gostovanja")) == str(grupa_gostovanja)
        ):
            return  # već zabilježeno ovaj dan za ovu grupu, ne dupliciraj
    gostovanje_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    ws.append_row([gostovanje_id, str(datum), str(ucenik_id), str(ime_djeteta), str(maticna_grupa), str(grupa_gostovanja), SEZONA])


def roster_grupe(df_rezervacije: pd.DataFrame, grupa_id: str) -> pd.DataFrame:
    """Potvrđeni učenici (platili, mjesto sigurno) za tu grupu - službeni roster za dolaske."""
    if df_rezervacije.empty:
        return df_rezervacije
    return df_rezervacije[
        (df_rezervacije["grupa_id"] == grupa_id) & (df_rezervacije["status"] == "Potvrđeno")
    ]


def izgradi_grid_dolazaka(df_dolasci: pd.DataFrame, df_termini: pd.DataFrame, grupa_id: str):
    """Vraća (grid_df, nastavnici_po_datumu) za pregled - redovi=učenici, stupci=datumi."""
    if df_dolasci.empty or df_termini.empty:
        return pd.DataFrame(), {}

    termini_grupe = df_termini[df_termini["grupa_id"] == grupa_id]
    if termini_grupe.empty:
        return pd.DataFrame(), {}

    termin_id_u_datum = dict(zip(termini_grupe["termin_id"], termini_grupe["datum"]))
    nastavnici_po_datumu = dict(zip(termini_grupe["datum"], termini_grupe["nastavnik_odrzao"]))

    dolasci_grupe = df_dolasci[df_dolasci["termin_id"].isin(termini_grupe["termin_id"])].copy()
    if dolasci_grupe.empty:
        return pd.DataFrame(), nastavnici_po_datumu

    dolasci_grupe["datum"] = dolasci_grupe["termin_id"].map(termin_id_u_datum)

    ikone = {"1": "✅", "0": "❌", "2": "💻"}
    dolasci_grupe["prikaz"] = dolasci_grupe["status"].astype(str).map(ikone).fillna("")

    grid = dolasci_grupe.pivot_table(
        index="ime_djeteta", columns="datum", values="prikaz", aggfunc="first", fill_value=""
    )
    # Sortiraj stupce kronološki
    grid = grid[sorted(grid.columns)]
    return grid, nastavnici_po_datumu
