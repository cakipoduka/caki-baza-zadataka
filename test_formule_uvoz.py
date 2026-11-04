"""Testovi za skupni uvoz formula i dodjelu ID-eva (4.11.2026.).

Pokriva dva stvarna pada s 4.11.2026.:
  1. `APIError [429] Quota exceeded` — uvoz 54 formule radio je ~216 poziva prema Sheetsu
     (po retku: otvori tab + zaglavlje + stupac ID-eva + upis), a Google dopušta 60
     čitanja/min. Sada: jedno čitanje + jedan upis, bez obzira na broj formula.
  2. `RuntimeError: Ne mogu složiti jedinstven ID formule` — `novi_id()` je računao broj kao
     `len(postojeci) + 1` i kod zauzetog ID-a radio `postojeci.add(kandidat)`, što za
     postojeći član ne mijenja veličinu skupa → ista vrijednost 200 puta.

Lažni Sheet je namjerno minimalan i broji pozive (bez ovisnosti o gspreadu).
Pokreni s: pytest test_formule_uvoz.py -v   (ili: python3 test_formule_uvoz.py)
"""
from datetime import datetime

import formule as F

DANAS = datetime.now().strftime("%y%m%d")


class _FakeWorksheet:
    col_count = len(F.FORMULE_HEADERS)

    def __init__(self, redci=None):
        self.redci = redci if redci is not None else [list(F.FORMULE_HEADERS)]
        self.pozivi = []

    def row_values(self, n):
        self.pozivi.append("row_values")
        return self.redci[n - 1] if n <= len(self.redci) else []

    def col_values(self, n):
        self.pozivi.append("col_values")
        return [r[n - 1] if n <= len(r) else "" for r in self.redci]

    def get_all_values(self):
        self.pozivi.append("get_all_values")
        return [list(r) for r in self.redci]

    def append_rows(self, matrica, value_input_option=None):
        self.pozivi.append(f"append_rows:{len(matrica)}")
        self.redci.extend([list(r) for r in matrica])

    def append_row(self, red, value_input_option=None):
        self.pozivi.append("append_row")
        self.redci.append(list(red))

    def update_cell(self, *args):
        self.pozivi.append("update_cell")


class _FakeSheet:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, naziv):
        self.ws.pozivi.append("worksheet")
        return self.ws


def _blok(n):
    return "\n".join(f"Formula {i} || Cjelina A || x_{{{i}}}=\\frac{{1}}{{{i}}}"
                     for i in range(1, n + 1))


def _stupac(ws, ime):
    i = ws.redci[0].index(ime)
    return [r[i] for r in ws.redci[1:]]


# ----------------------------------------------------------------- novi_id
def test_novi_id_preskace_rupu_u_numeraciji():
    """Pad od 4.11.: 10 ID-eva numeriranih 1-6 i 8-11 → kandidat `len+1` = 11 je zauzet."""
    postojeci = {f"F{DANAS}-{i}" for i in (1, 2, 3, 4, 5, 6, 8, 9, 10, 11)}
    assert F.novi_id(postojeci) == f"F{DANAS}-12"


def test_novi_id_prazan_i_bez_dupliranja():
    assert F.novi_id([]) == f"F{DANAS}-1"
    assert F.novi_id([f"F{DANAS}-1"]) == f"F{DANAS}-2"


def test_novi_id_ignorira_druge_dane_i_smece():
    postojeci = {"F260101-7", "F260101-9", "", "ne-id", f"F{DANAS}-3"}
    assert F.novi_id(postojeci) == f"F{DANAS}-4"


def test_novi_id_uvijek_jedinstven_u_nizu():
    idovi = set()
    for _ in range(300):
        novi = F.novi_id(idovi)
        assert novi not in idovi
        idovi.add(novi)
    assert len(idovi) == 300


# ----------------------------------------------------------------- iz_teksta
def test_iz_teksta_preskace_komentare_i_prazne():
    redci, greske = F.iz_teksta("# komentar\n\nA || C || x^2\nB || C\n")
    assert [r["naslov"] for r in redci] == ["A"]
    assert len(greske) == 1 and "redak 4" in greske[0]


# ----------------------------------------------------------------- dodaj_vise
def test_uvoz_radi_jedno_citanje_i_jedan_upis():
    """429 od 4.11.: broj poziva prema Sheetsu ne smije rasti s brojem formula."""
    ws = _FakeWorksheet()
    F.dodaj_vise(_FakeSheet(ws), _blok(54), paket="P")
    assert ws.pozivi.count("get_all_values") == 1
    assert [p for p in ws.pozivi if p.startswith("append_row")] == ["append_rows:54"]
    assert len(ws.pozivi) <= 4

    ws200 = _FakeWorksheet()
    F.dodaj_vise(_FakeSheet(ws200), _blok(200), paket="P")
    assert len(ws200.pozivi) == len(ws.pozivi)          # 200 formula = isti broj poziva


def test_uvoz_upisuje_ispravne_vrijednosti():
    ws = _FakeWorksheet()
    dodano, greske = F.dodaj_vise(_FakeSheet(ws), _blok(3), paket="Matura 2026")
    assert (dodano, greske) == (3, [])
    assert _stupac(ws, "naslov") == ["Formula 1", "Formula 2", "Formula 3"]
    assert _stupac(ws, "cjelina") == ["Cjelina A"] * 3
    assert _stupac(ws, "paket") == ["Matura 2026"] * 3
    assert _stupac(ws, "aktivno") == ["Da"] * 3
    assert _stupac(ws, "tekst_latex")[0] == "x_{1}=\\frac{1}{1}"
    assert len(set(_stupac(ws, "formula_id"))) == 3


def test_uvoz_preskace_duplikate_pa_se_smije_ponoviti():
    ws = _FakeWorksheet()
    sheet = _FakeSheet(ws)
    F.dodaj_vise(sheet, _blok(20), paket="P")           # prvi uvoz stao na 20 (npr. 429)
    dodano, poruke = F.dodaj_vise(sheet, _blok(54), paket="P")
    assert dodano == 34
    assert len(_stupac(ws, "naslov")) == 54
    assert len(set(_stupac(ws, "formula_id"))) == 54
    assert any("Preskočeno 20" in p for p in poruke)


def test_isti_naziv_u_drugom_paketu_nije_duplikat():
    ws = _FakeWorksheet()
    sheet = _FakeSheet(ws)
    F.dodaj_vise(sheet, _blok(2), paket="Paket A")
    assert F.dodaj_vise(sheet, _blok(2), paket="Paket B")[0] == 2


def test_uvoz_bez_preskakanja_dodaje_sve():
    ws = _FakeWorksheet()
    sheet = _FakeSheet(ws)
    F.dodaj_vise(sheet, _blok(5), paket="P")
    assert F.dodaj_vise(sheet, _blok(5), paket="P", preskoci_duplikate=False)[0] == 5
    assert len(set(_stupac(ws, "formula_id"))) == 10    # ID-evi i dalje jedinstveni


def test_uvoz_u_tab_s_rupama_u_ID_numeraciji():
    """Isti slučaj koji je srušio uvoz: postojeći ID-evi nisu neprekinuti niz."""
    zaglavlje = list(F.FORMULE_HEADERS)
    redci = [zaglavlje]
    for i in (1, 2, 3, 4, 5, 6, 8, 9, 10, 11):
        red = [""] * len(zaglavlje)
        red[zaglavlje.index("formula_id")] = f"F{DANAS}-{i}"
        red[zaglavlje.index("naslov")] = f"Stara {i}"
        redci.append(red)
    ws = _FakeWorksheet(redci)
    dodano, _ = F.dodaj_vise(_FakeSheet(ws), _blok(3), paket="P")
    assert dodano == 3
    idovi = [x for x in _stupac(ws, "formula_id") if x]
    assert len(set(idovi)) == len(idovi) == 13


def test_neispravan_redak_ne_rusi_ostatak():
    ws = _FakeWorksheet()
    blok = "Dobra || C || x^2\n || C || y^2\nPreduga || C || " + "x" * (F.MAX_FORMULA_ZNAKOVA + 1)
    dodano, greske = F.dodaj_vise(_FakeSheet(ws), blok, paket="P")
    assert dodano == 1
    assert _stupac(ws, "naslov") == ["Dobra"]
    assert any("preduga" in g.lower() for g in greske)


def test_prazan_blok_ne_dira_sheet():
    ws = _FakeWorksheet()
    assert F.dodaj_vise(_FakeSheet(ws), "# samo komentar\n\n", paket="P") == (0, [])
    assert ws.pozivi == []


if __name__ == "__main__":                              # pokretanje bez pytesta
    testovi = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    pali = 0
    for t in testovi:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            pali += 1
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n{len(testovi) - pali}/{len(testovi)} prolazi")
