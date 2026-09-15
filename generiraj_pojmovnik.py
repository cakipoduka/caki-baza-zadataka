"""
CAKI Matematika - generiraj_pojmovnik.py

Skenira SVE retke u 'Teorija_potpoglavlja' tabu i izvlaci pojmove oznacene s
\\pojam{Naziv} u tekst_teorije_latex (vidi teorija_markup.py), te ih upisuje u novi tab
'Pojmovnik' (cjelina, potpoglavlje, pojam, recenica_definicije).

Pokrece se RUCNO (npr. gumb "Osvjezi pojmovnik" u Streamlit sucelju, ili direktno kao
skripta) - NIJE dio Korak 3.1 PreTeXt builda, jer pojmovnik zivi kao zaseban, pretrazivi
popis (npr. buduca WP stranica "Pojmovnik"), ne kao dio teksta unutar potpoglavlja.

Pojmovnik tab se pri svakom pokretanju POTPUNO regenerira iz izvora (Teorija_potpoglavlja
ostaje jedini source of truth) - nema rucnog unosa izravno u Pojmovnik tab, isto nacelo
kao "WordPress je disposable" iz ostatka sustava.
"""
import re

from baza_zadataka_pipeline import get_gspread_client, get_or_create_worksheet

POJMOVNIK_HEADERS = ["cjelina", "potpoglavlje", "pojam", "recenica_definicije"]

# Recenica = sve od pocetka retka (ili proslog zavrsetka recenice) do prve tocke NAKON
# \pojam{...} oznake. Namjerno jednostavno (bez podrske za kratice tipa "npr." unutar
# definicije) - dovoljno dobro za ovu namjenu, ne pokusava biti savrseni parser recenica.
_POJAM_RECENICA_RE = re.compile(r"([^.\n]*\\pojam\{([^}]+)\}[^.\n]*\.)")


def izvuci_pojmove_iz_teksta(tekst: str):
    """Vraca listu (pojam, cista_recenica_bez_markupa) za dani tekst_teorije_latex."""
    rezultati = []
    for recenica, pojam in _POJAM_RECENICA_RE.findall(tekst or ""):
        cista = re.sub(r"\\pojam\{([^}]+)\}", r"\1", recenica).strip()
        cista = re.sub(r"!!(.+?)!!", r"\1", cista, flags=re.DOTALL)
        rezultati.append((pojam.strip(), cista))
    return rezultati


def generiraj_pojmovnik(spreadsheet) -> int:
    """Vraca broj upisanih pojmova. Baca iznimku ako 'Teorija_potpoglavlja' tab ne
    postoji - namjerno se ne stvara prazan pojmovnik iz nepostojeceg izvora."""
    izvor = spreadsheet.worksheet("Teorija_potpoglavlja")
    redovi = izvor.get_all_records()

    novi_redovi = []
    for redak in redovi:
        tekst = redak.get("tekst_teorije_latex", "")
        for pojam, recenica in izvuci_pojmove_iz_teksta(tekst):
            novi_redovi.append([
                redak.get("cjelina", ""),
                redak.get("potpoglavlje", ""),
                pojam,
                recenica,
            ])

    odrediste = get_or_create_worksheet(spreadsheet, "Pojmovnik", POJMOVNIK_HEADERS)
    odrediste.clear()
    odrediste.append_row(POJMOVNIK_HEADERS)
    if novi_redovi:
        odrediste.append_rows(novi_redovi)
    return len(novi_redovi)


if __name__ == "__main__":
    # Pokretanje kao samostalna skripta (izvan Streamlita) - koristi iste secrete kao
    # baza_zadataka_app.py, ali ih ovdje cita direktno iz streamlit.secrets ako se
    # pokrece preko `streamlit run`, ili ih zamijeni s os.environ ako se zeli pokretati
    # cistim `python generiraj_pojmovnik.py` iz terminala/cron-a.
    import json

    import streamlit as st

    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    ss = gc.open_by_key(st.secrets["SHEET_ID"])
    broj = generiraj_pojmovnik(ss)
    print(f"Pojmovnik azuriran: {broj} pojmova.")
