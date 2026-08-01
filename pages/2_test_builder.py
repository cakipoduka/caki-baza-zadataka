"""
CAKI Matematika - test_builder.py
Streamlit "Test Builder": profesor pretraži i odabere zadatke iz baze
(ili doda ručni/ad-hoc zadatak), posloži redoslijed strelicama, unese
naslov/datum/bodove (ako je test), i generira gotov PDF za print —
sve iz preglednika, bez LaTeX/Overleaf koraka.

Očekuje da su u istom repozitoriju/folderu prisutne datoteke:
  caki-style.sty, main_test_template.tex

Streamlit Cloud: za pdflatex, dodaj packages.txt (vidi README.md).
"""
import copy
import datetime
import os
import re
import subprocess
import tempfile

import streamlit as st

from baza_zadataka_pipeline import get_gspread_client

st.set_page_config(page_title="CAKI Test Builder", page_icon="📝", layout="wide")

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------
# Lozinka (isti obrazac kao u app.py)
# ---------------------------------------------------------------

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos_tb") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran_tb"] = True
        else:
            st.session_state["autoriziran_tb"] = False

    if st.session_state.get("autoriziran_tb"):
        return True

    st.title("📝 CAKI Test Builder")
    st.text_input("Lozinka", type="password", key="lozinka_unos_tb", on_change=na_unos)
    if st.session_state.get("autoriziran_tb") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# ---------------------------------------------------------------
# Google Sheets — dohvat zadataka (keširano 5 min da ne udaramo API)
# ---------------------------------------------------------------

@st.cache_resource
def init_sheet():
    import json
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    sheet = gc.open_by_key(st.secrets["SHEET_ID"])
    return sheet.worksheet("Zadaci")


@st.cache_data(ttl=300)
def ucitaj_zadatke():
    ws = init_sheet()
    return ws.get_all_records()


# ---------------------------------------------------------------
# LaTeX escape (izvan $...$ regija) — ista logika kao generate_tex.py
# ---------------------------------------------------------------

SPECIAL_CHARS = {
    "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def escape_outside_math(text: str) -> str:
    if not text:
        return ""
    parts = re.split(r"(\$[^$]*\$)", text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part)
        else:
            out.append("".join(SPECIAL_CHARS.get(ch, ch) for ch in part))
    return "".join(out)


# ---------------------------------------------------------------
# Session state — odabrani zadaci (redoslijed = redoslijed u listi)
# ---------------------------------------------------------------

if "odabrani" not in st.session_state:
    st.session_state.odabrani = []  # [{id, tekst, video_url, bodovi, izvor}]


def dodaj_zadatak(row, bodovi_default=""):
    st.session_state.odabrani.append({
        "id": row.get("id", ""),
        "tekst": row.get("tekst_zadatka_latex", ""),
        "video_url": row.get("video_url", ""),
        "bodovi": str(row.get("max_bodovi") or bodovi_default or ""),
        "izvor": "baza",
        "tip_zadatka": row.get("tip_zadatka", ""),
        # U bazi je spremljeno kao " || " odvojen string (vidi nadopuni_ili_dodaj_zadatke
        # u pipeline.py) - ovdje ga odmah pretvaramo u listu radi lakšeg rada dalje.
        "ponudjeni_odgovori": [
            o.strip() for o in str(row.get("ponudjeni_odgovori", "")).split("||") if o.strip()
        ],
    })


def pomakni(idx, smjer):
    novi = idx + smjer
    lst = st.session_state.odabrani
    if 0 <= novi < len(lst):
        lst[idx], lst[novi] = lst[novi], lst[idx]


def ukloni(idx):
    st.session_state.odabrani.pop(idx)


# ---------------------------------------------------------------
# UI — dvije kolone: pretraga baze (lijevo) / odabrani zadaci (desno)
# ---------------------------------------------------------------

st.title("📝 CAKI Test Builder")
st.caption("Odaberi zadatke iz baze ili dodaj ručne, posloži redoslijed, unesi metapodatke, generiraj PDF.")

col_pretraga, col_odabrano = st.columns([1, 1], gap="large")

with col_pretraga:
    st.subheader("1. Pretraga baze")
    try:
        zadaci = ucitaj_zadatke()
    except Exception as e:
        st.error(f"Ne mogu učitati bazu: {e}")
        zadaci = []

    sve_cjeline = sorted({z.get("cjelina", "") for z in zadaci if z.get("cjelina")})
    sve_tezine = sorted({z.get("tezina", "") for z in zadaci if z.get("tezina")})

    f_cjelina = st.multiselect("Cjelina", sve_cjeline)
    f_tezina = st.multiselect("Težina", sve_tezine)
    f_tekst = st.text_input("Pretraži tekst / ključne riječi")

    filtrirano = zadaci
    if f_cjelina:
        filtrirano = [z for z in filtrirano if z.get("cjelina") in f_cjelina]
    if f_tezina:
        filtrirano = [z for z in filtrirano if z.get("tezina") in f_tezina]
    if f_tekst:
        upit = f_tekst.lower()
        filtrirano = [
            z for z in filtrirano
            if upit in (z.get("tekst_zadatka_latex", "") or "").lower()
            or upit in (z.get("kljucne_rijeci", "") or "").lower()
        ]

    st.caption(f"{len(filtrirano)} zadataka pronađeno (prikazano prvih 30)")

    for row in filtrirano[:30]:
        with st.container(border=True):
            st.markdown(
                f"`{row.get('id','')}` · {row.get('cjelina','')} · "
                f"{row.get('tezina','')} · {row.get('max_bodovi','') or '?'} bod."
            )
            st.markdown(row.get("tekst_zadatka_latex", ""))
            if st.button("➕ Dodaj", key=f"add_{row.get('id')}"):
                dodaj_zadatak(row)
                st.rerun()

    with st.expander("➕ Dodaj ručni (ad-hoc) zadatak"):
        rucni_tekst = st.text_area("Tekst zadatka (LaTeX matematika unutar $...$)", key="rucni_tekst")
        rucni_video = st.text_input("Video URL (opcionalno)", key="rucni_video")
        rucni_bodovi = st.text_input("Bodovi (opcionalno)", key="rucni_bodovi")
        rucni_je_mc = st.checkbox("Višestruki izbor (A/B/C/D...)", key="rucni_je_mc")
        rucni_odgovori_raw = ""
        if rucni_je_mc:
            rucni_odgovori_raw = st.text_input(
                "Ponuđeni odgovori, odvojeni s ';' (npr. $x=1$; $x=2$; $x=4$; $x=6$)",
                key="rucni_odgovori",
            )
        if st.button("➕ Dodaj ručni zadatak"):
            if rucni_tekst.strip():
                st.session_state.odabrani.append({
                    "id": None, "tekst": rucni_tekst, "video_url": rucni_video,
                    "bodovi": rucni_bodovi, "izvor": "ad_hoc",
                    "tip_zadatka": "visestruki_izbor" if rucni_je_mc else "",
                    "ponudjeni_odgovori": [
                        o.strip() for o in rucni_odgovori_raw.split(";") if o.strip()
                    ] if rucni_je_mc else [],
                })
                st.rerun()
            else:
                st.warning("Upiši tekst zadatka.")

with col_odabrano:
    st.subheader(f"2. Odabrani zadaci ({len(st.session_state.odabrani)})")

    if not st.session_state.odabrani:
        st.info("Još nema odabranih zadataka — dodaj ih s lijeve strane.")

    for idx, z in enumerate(st.session_state.odabrani):
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**Zadatak {idx + 1}** · izvor: {z['izvor']}")
                st.markdown(
                    (z["tekst"][:220] + "…") if len(z["tekst"]) > 220 else z["tekst"]
                )
                z["bodovi"] = st.text_input("Bodovi", value=z["bodovi"], key=f"bod_{idx}")
            with c2:
                if st.button("⬆️", key=f"up_{idx}", disabled=(idx == 0)):
                    pomakni(idx, -1)
                    st.rerun()
                if st.button("⬇️", key=f"down_{idx}", disabled=(idx == len(st.session_state.odabrani) - 1)):
                    pomakni(idx, 1)
                    st.rerun()
                if st.button("🗑️", key=f"del_{idx}"):
                    ukloni(idx)
                    st.rerun()

st.divider()

# ---------------------------------------------------------------
# 3. Metapodaci + generiranje
# ---------------------------------------------------------------

st.subheader("3. Metapodaci i generiranje")

mc1, mc2, mc3 = st.columns(3)
naslov = mc1.text_input("Naslov dokumenta", value="Test — Kvadratna jednadžba")
datum = mc2.date_input("Datum", value=datetime.date.today())
tip_dok = mc3.selectbox("Tip dokumenta", ["Test", "Skripta / radni listić"])

je_test = tip_dok == "Test"
ukupno_bodova = ""
if je_test:
    try:
        ukupno_bodova = str(sum(int(z["bodovi"]) for z in st.session_state.odabrani if str(z["bodovi"]).strip().isdigit()))
    except Exception:
        ukupno_bodova = ""
    st.caption(f"Ukupno bodova (automatski zbroj): **{ukupno_bodova or '—'}**")

prikazi_rjesenja = st.checkbox("Uključi rješenja na kraju dokumenta", value=True)


def izgradi_opcije_blok(ponudjeni_odgovori):
    """Gradi LaTeX za prikaz ponuđenih odgovora (A/B/C/D...) ispod teksta zadatka.
    Koristi postojeće \\mcFourOptions/\\mcFiveOptions naredbe iz caki-style.sty za
    4 ili 5 opcija (najčešći slučaj); za bilo koji drugi broj opcija koristi
    jednostavan A)/B)/C)... popis (\\begin{itemize}) da ne pukne na rubnim slučajevima.
    VAŽNO: ovaj blok se NE smije propuštati kroz escape_outside_math - dodaje se
    NAKON escapiranja teksta zadatka, jer sadrži prave LaTeX naredbe (\\mcFourOptions...),
    a ne slobodni tekst profesora."""
    opcije = [escape_outside_math(o.strip()) for o in ponudjeni_odgovori if o.strip()]
    if not opcije:
        return ""
    slova = ["A", "B", "C", "D", "E", "F"]
    if len(opcije) == 4:
        return "\n\\mcFourOptions{" + "}{".join(opcije) + "}"
    if len(opcije) == 5:
        return "\n\\mcFiveOptions{" + "}{".join(opcije) + "}"
    # Fallback za 2, 3, 6+ opcija - jednostavan popis, i dalje unutar taskbox okvira
    stavke = "\n".join(f"\\item[{slova[j]})] {opc}" for j, opc in enumerate(opcije))
    return "\n\\begin{itemize}\n" + stavke + "\n\\end{itemize}"


def izgradi_tex(zadaci_odabrani, ukljuci_rjesenja):
    zad_lines = []
    rjes_lines = []
    for i, z in enumerate(zadaci_odabrani, start=1):
        tekst = escape_outside_math(z["tekst"].strip())
        video = (z["video_url"] or "").strip()
        bodovi = (z["bodovi"] or "").strip() if je_test else ""

        if z.get("tip_zadatka") == "visestruki_izbor" and z.get("ponudjeni_odgovori"):
            tekst += izgradi_opcije_blok(z["ponudjeni_odgovori"])

        zad_lines.append(f"\\zadatakbod{{{tekst}}}{{{video}}}{{{bodovi}}}")
        zad_lines.append("")
        if ukljuci_rjesenja:
            rjes_lines.append(f"\\rjesenje{{{i}}}{{\\textit{{Rješenje se dodaje naknadno.}}}}{{}}")
            rjes_lines.append("")
    return "\n".join(zad_lines), "\n".join(rjes_lines)


if st.button("🖨️ Generiraj PDF", type="primary", disabled=not st.session_state.odabrani):
    zadaci_tex, rjesenja_tex = izgradi_tex(st.session_state.odabrani, prikazi_rjesenja)

    rjesenja_sekcija = ""
    if prikazi_rjesenja:
        rjesenja_sekcija = (
            "\\newpage\n"
            "{\\color{MathSecondary}\\sffamily\\bfseries\\Large Rješenja}\\par\n"
            "\\vspace{2mm}\\hrule height 1pt \\color{MathSecondary}\\vspace{4mm}\n"
            "\\input{generated/rjesenja_body}"
        )

    with open(os.path.join(TEMPLATE_DIR, "main_test_template.tex"), encoding="utf-8") as f:
        main_tex = f.read()
    main_tex = (
        main_tex
        .replace("{{NASLOV}}", escape_outside_math(naslov))
        .replace("{{DATUM}}", datum.strftime("%d.%m.%Y."))
        .replace("{{TIP}}", tip_dok)
        .replace("{{UKUPNO_BODOVA}}", ukupno_bodova)
        .replace("{{RJESENJA_SEKCIJA}}", rjesenja_sekcija)
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "generated"), exist_ok=True)
        with open(os.path.join(tmpdir, "main.tex"), "w", encoding="utf-8") as f:
            f.write(main_tex)
        with open(os.path.join(tmpdir, "generated", "zadaci_body.tex"), "w", encoding="utf-8") as f:
            f.write(zadaci_tex)
        with open(os.path.join(tmpdir, "generated", "rjesenja_body.tex"), "w", encoding="utf-8") as f:
            f.write(rjesenja_tex)
        with open(os.path.join(TEMPLATE_DIR, "caki-style.sty"), encoding="utf-8") as f:
            style_content = f.read()
        with open(os.path.join(tmpdir, "caki-style.sty"), "w", encoding="utf-8") as f:
            f.write(style_content)

        with st.spinner("Kompajliram PDF..."):
            ok = True
            log_tail = ""
            for _ in range(2):  # dva prolaza (breakable okviri, fancyhdr)
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                    cwd=tmpdir, capture_output=True, text=True, timeout=60,
                )
                if result.returncode != 0:
                    ok = False
                    log_tail = "\n".join(result.stdout.splitlines()[-40:])
                    break

        if not ok:
            st.error("Kompajliranje nije uspjelo. Najčešći uzrok: neuparen `$` u tekstu zadatka.")
            st.code(log_tail, language="text")
        else:
            pdf_path = os.path.join(tmpdir, "main.pdf")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            st.success("PDF generiran!")
            st.download_button(
                "⬇️ Preuzmi PDF", data=pdf_bytes,
                file_name=f"{naslov.replace(' ', '_')}.pdf", mime="application/pdf",
            )
