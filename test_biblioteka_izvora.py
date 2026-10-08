"""Test za get_biblioteke_izvora()/dodaj_biblioteku_izvora() (prijedlog, 8.10.2026.).

Samostalan lažni Sheet (bez ovisnosti o testovi/fake_gspread.py iz CRM repozitorija -
ovaj repo dosad nije imao test infrastrukturu, pa se ne uvodi međurepo ovisnost samo
radi ova dva testa) - dovoljno malen da pokrije: (1) prvi poziv kreira tab i seedira
početni popis, (2) drugi poziv NE re-seedira, (3) dodaj_biblioteku_izvora dodaje samo
nove, jedinstvene vrijednosti.

Pokreni s: pytest test_biblioteka_izvora.py -v
"""
import gspread
import pytest

from baza_zadataka_pipeline import (
    BIBLIOTEKA_IZVORA_HEADERS,
    _BIBLIOTEKA_IZVORA_POCETNI_SEED,
    dodaj_biblioteku_izvora,
    get_biblioteke_izvora,
)


class _FakeWorksheet:
    def __init__(self, title):
        self.title = title
        self.data = []

    def get_all_values(self):
        return list(self.data)

    def append_row(self, values):
        self.data.append(list(values))

    def append_rows(self, values):
        for v in values:
            self.data.append(list(v))


class _FakeSheet:
    """Minimalni lažni gspread.Spreadsheet - samo worksheet()/add_worksheet(), što je
    sve što get_biblioteke_izvora()/dodaj_biblioteku_izvora() stvarno koriste."""

    def __init__(self):
        self.tabs = {}

    def worksheet(self, title):
        if title not in self.tabs:
            raise gspread.exceptions.WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows, cols):
        ws = _FakeWorksheet(title)
        self.tabs[title] = ws
        return ws


def test_prvi_poziv_kreira_tab_i_seedira():
    sheet = _FakeSheet()
    popis = get_biblioteke_izvora(sheet)
    assert popis == _BIBLIOTEKA_IZVORA_POCETNI_SEED
    ws = sheet.tabs["Sifrarnik_biblioteka_izvora"]
    assert ws.data[0] == BIBLIOTEKA_IZVORA_HEADERS
    assert [r[0] for r in ws.data[1:]] == _BIBLIOTEKA_IZVORA_POCETNI_SEED


def test_drugi_poziv_ne_reseedira_prazan_tab():
    # Tab već postoji ali je NAMJERNO prazan (npr. korisnik ručno obrisao sve retke) -
    # drugi poziv ne smije tiho vratiti seed popis natrag.
    sheet = _FakeSheet()
    ws = sheet.add_worksheet("Sifrarnik_biblioteka_izvora", rows=100, cols=1)
    ws.append_row(BIBLIOTEKA_IZVORA_HEADERS)
    popis = get_biblioteke_izvora(sheet)
    assert popis == []


def test_citanje_postojecih_vrijednosti():
    sheet = _FakeSheet()
    ws = sheet.add_worksheet("Sifrarnik_biblioteka_izvora", rows=100, cols=1)
    ws.append_row(BIBLIOTEKA_IZVORA_HEADERS)
    ws.append_row(["zbirka-Test-primjer"])
    popis = get_biblioteke_izvora(sheet)
    assert popis == ["zbirka-Test-primjer"]


def test_dodaj_biblioteku_izvora_novu_vrijednost():
    sheet = _FakeSheet()
    get_biblioteke_izvora(sheet)  # kreira + seedira tab
    dodaj_biblioteku_izvora(sheet, "zbirka-Nova-2026")
    popis = get_biblioteke_izvora(sheet)
    assert "zbirka-Nova-2026" in popis
    assert popis.count("zbirka-Nova-2026") == 1


def test_dodaj_biblioteku_izvora_ne_duplicira_postojecu():
    sheet = _FakeSheet()
    get_biblioteke_izvora(sheet)
    broj_prije = len(get_biblioteke_izvora(sheet))
    dodaj_biblioteku_izvora(sheet, _BIBLIOTEKA_IZVORA_POCETNI_SEED[0])
    assert len(get_biblioteke_izvora(sheet)) == broj_prije


def test_dodaj_biblioteku_izvora_prazan_naziv_ne_radi_nista():
    sheet = _FakeSheet()
    get_biblioteke_izvora(sheet)
    broj_prije = len(get_biblioteke_izvora(sheet))
    dodaj_biblioteku_izvora(sheet, "   ")
    assert len(get_biblioteke_izvora(sheet)) == broj_prije


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
