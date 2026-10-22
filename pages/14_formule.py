"""
CAKI — pages/14_formule.py  (22.10.2026.)

📐 **Formule** — Caki unosi formule u LaTeXu, slaže ih u pakete (npr. „Matura 2026 — službene")
i uključuje/isključuje. Pri objavi testa u Test Builderu odabere što učenik smije vidjeti u
desnoj koloni portala; u test se tada zamrzne kopija teksta.

Zašto u bazi: formule pripadaju gradivu (uz `Zadaci`), a u test idu kao zamrznuta kopija — zato
ih portal ne mora čitati iz baze (dovoljan mu je CRM Sheet).
"""
import streamlit as st

import formule as F
from baza_zadataka_pipeline import get_gspread_client
from secrets_json import ucitaj as _ucitaj_json

st.set_page_config(page_title="CAKI — Formule", page_icon="📐", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_formule"] = (
            st.session_state.get("lozinka_unos_formule") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_formule"):
        return True
    st.title("📐 CAKI — Formule")
    st.text_input("Lozinka", type="password", key="lozinka_unos_formule", on_change=na_unos)
    if st.session_state.get("autoriziran_formule") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


@st.cache_resource(show_spinner=False)
def _spreadsheet(_kljuc: str):
    sa = _ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    return get_gspread_client(sa).open_by_key(str(st.secrets["SHEET_ID"]))


try:
    sheet = _spreadsheet(str(st.secrets.get("SHEET_ID", "")))
except Exception as e:                                  # noqa: BLE001
    st.error(f"Baza se ne može otvoriti: {e}")
    st.stop()

st.title("📐 Formule")
st.caption("Unesi formulu u LaTeXu (npr. `\\frac{a}{b}`, `x_{1,2}=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}`). "
           "Ispod vidiš kako će je učenik vidjeti.")

formule = F.load_formule(sheet)

# 22.10.2026.: cjeline se biraju iz ŠIFRARNIKA TE BAZE (kurikulum po predmetu), a ne upisuju
# ručno — formula može pripadati VIŠE cjelina.
def _cjeline_baze() -> list[str]:
    try:
        ws = sheet.worksheet("Zadaci")
        redci = ws.get_all_records()
    except Exception:                                   # noqa: BLE001
        return []
    return sorted({str(r.get("cjelina", "")).strip() for r in redci
                   if str(r.get("cjelina", "")).strip()})


CJELINE = _cjeline_baze()

# ---------------------------------------------------------------- unos nove
with st.expander("➕ Dodaj formulu", expanded=not formule):
    with st.form("formula_nova", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        f_naslov = c1.text_input("Naziv (vidi ga učenik)", placeholder="Kvadratna formula")
        f_paket = c2.text_input("Paket", placeholder="Matura 2026 — službene")
        f_cjeline = st.multiselect(
            "Cjeline (može više — iz kurikuluma ove baze)", CJELINE,
            help="Popis dolazi iz taba `Zadaci` ove baze. Ako je baza prazna, cjelina nema — "
                 "tada se može upisati ručno u polje ispod.")
        f_cjelina_rucno = st.text_input("…ili upiši cjelinu ručno (odvoji s `;`)",
                                        placeholder="Kvadratna jednadžba; Funkcije")
        f_opis = st.text_input("Kratki opis (neobavezan, ne prikazuje se učeniku)",
                               placeholder="za rješavanje ax²+bx+c=0")
        f_latex = st.text_area("LaTeX", height=110,
                               placeholder="x_{1,2} = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}")
        f_datoteka = st.text_input("…ili naziv datoteke u `03_Formule` (PDF/slika)",
                                   placeholder="matura_2026_sluzbene.pdf")
        if st.form_submit_button("➕ Dodaj formulu", type="primary"):
            _cjeline_odabrane = list(f_cjeline) + [x for x in [f_cjelina_rucno] if x.strip()]
            try:
                nova = F.dodaj_formulu(sheet, naslov=f_naslov, tekst_latex=f_latex,
                                       cjelina=_cjeline_odabrane, paket=f_paket,
                                       opis=f_opis, datoteka=f_datoteka)
            except ValueError as e:
                st.error(str(e))
            else:
                st.success(f"✅ Dodana **{nova['naslov']}** (`{nova['formula_id']}`).")
                st.cache_data.clear()
                st.rerun()

if not formule:
    st.info("Još nema formula. Dodaj prvu gore — nakon toga je možeš odabrati pri objavi testa.")
    st.stop()

# ---------------------------------------------------------------- pregled po paketima
st.subheader(f"📚 {len(formule)} formula u {len(F.paketi(formule)) or 1} paketa")
paket_odabir = st.multiselect("Prikaži pakete", F.paketi(formule), default=F.paketi(formule))
prikaz = [f for f in formule
          if not paket_odabir or F._tekst(f.get("paket")) in paket_odabir]

for f in prikaz:
    with st.container(border=True):
        c_lijevo, c_desno = st.columns([3, 2])
        with c_lijevo:
            st.markdown(f"**{F._tekst(f.get('naslov'))}** · `{F._tekst(f.get('formula_id'))}`")
            st.caption(" · ".join(x for x in [F._tekst(f.get("cjelina")),
                                              F._tekst(f.get("paket")),
                                              F._tekst(f.get("opis"))] if x) or "—")
            st.markdown(F.tekst_formule(f))
        with c_desno:
            _aktivna = F._tekst(f.get("aktivno")) in ("Da", "da", "")
            _novo_aktivno = st.toggle("Aktivna (nudi se pri objavi)", value=_aktivna,
                                      key=f"akt_{f.get('formula_id')}")
            if _novo_aktivno != _aktivna:
                F.azuriraj_formulu(sheet, F._tekst(f.get("formula_id")),
                                   {"aktivno": "Da" if _novo_aktivno else "Ne"})
                st.rerun()
            if st.button("🗑️ Obriši", key=f"del_{f.get('formula_id')}"):
                F.obrisi_formulu(sheet, F._tekst(f.get("formula_id")))
                st.cache_data.clear()
                st.rerun()
