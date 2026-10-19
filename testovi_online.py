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
]

# Program na koji se test odnosi (prazno = svi učenici). Ista lista kao program_tip u Prijavama.
PROGRAMI = ["", "Upisi", "Matura", "Instrukcije"]

STATUS_AKTIVAN = "Da"


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
                aktivan: bool = True, autor: str = "", napomena: str = "") -> dict:
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
    }
    ws.append_row([redak[h] for h in TEST_HEADERS], value_input_option="RAW")
    return redak


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


def prikazi_objavu(st, sheet, odabrani, predmet: str, autor: str = "Caki") -> None:
    """Odlomak na dnu Test Buildera: „Objavi kao online test”. `st` se predaje da modul
    ostane uvoziv u testovima bez Streamlita."""
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

    with st.form("forma_objave_testa"):
        naziv = st.text_input("Naziv testa (vidi ga učenik)", value=zadani_naziv)
        c1, c2 = st.columns(2)
        ucenik_id = c1.text_input("Šifra učenika (prazno = svi)", placeholder="npr. AA1111")
        program = c2.selectbox("Program (prazno = svi)", PROGRAMI)
        c3, c4, c5 = st.columns(3)
        trajanje = c3.number_input("Trajanje (minuta)", min_value=5, max_value=240, value=45, step=5)
        otvara = c4.date_input("Otvoren od", value=_danas(), format="DD.MM.YYYY")
        zatvara = c5.date_input("Otvoren do", value=_danas() + timedelta(days=7), format="DD.MM.YYYY")
        napomena = st.text_area("Napomena za sebe (ne prikazuje se učeniku)", height=70)
        objavi = st.form_submit_button("📝 Objavi test", type="primary",
                                       disabled=bool(problemi) or not zadaci)

    if objavi:
        greske = provjeri_objavu(naziv, zadaci, trajanje, str(otvara), str(zatvara))
        if greske:
            for g in greske:
                st.error(g)
        else:
            try:
                redak = objavi_test(
                    sheet, zadaci=zadaci, naziv=naziv, predmet=predmet,
                    ucenik_id=ucenik_id, program=program, trajanje_min=trajanje,
                    otvara_od=str(otvara), zatvara_do=str(zatvara), autor=autor,
                    napomena=napomena,
                )
            except Exception as e:  # noqa: BLE001 — Caki mora vidjeti što je Google rekao
                st.error(f"Objava nije uspjela: {e}")
            else:
                st.success(
                    f"✅ Test je objavljen. **ID: `{redak['test_id']}`** · "
                    f"{redak['broj_zadataka']} zadataka · {redak['bodovi_ukupno']:g} bodova · "
                    f"otvoren {redak['otvara_od']} – {redak['zatvara_do']}."
                )
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
    "osiguraj_tab", "objavi_test", "load_testovi", "zadaci_iz_retka",
    "prikazi_objavu", "naziv_predmeta",
]
