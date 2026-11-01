"""CAKI — tema i stil za Streamlit portale  (v2, 31.10.2026.)

JEDNA datoteka za sve CAKI aplikacije. Ako nova verzija Streamlita nešto pokvari,
briše se jedan `import` i sve se vraća na staro.

v2 (31.10.2026., Cakijev nalaz „jako je blijedo i naporno za oči"):
  - tamniji tekst i jače crte (kontrast je bio prenizak),
  - bijele kartice na plavkastoj podlozi (prije: bijelo na gotovo bijelom),
  - tabovi kao vidljiva segmentirana traka, ne blijeda crta,
  - kompaktniji unosi i labele (obrasci su bili rastegnuti u prazno).

KAKO SE KORISTI (set_page_config mora biti prvi Streamlit poziv):

    import caki_stil as stil
    stil.primijeni()          # u aplikacijama koje već imaju svoj set_page_config
    ...
    st.markdown(stil.statistike([
        {"oznaka": "Dolasci", "vrijednost": "92 %", "pod": "11 od 12 sati", "boja": "zeleno"},
    ]), unsafe_allow_html=True)

NIŠTA OVDJE NE DIRA PODATKE ni Sheet — ovo je isključivo prikaz.
"""

from __future__ import annotations

from contextlib import contextmanager

import streamlit as st

# --------------------------------------------------------------------------- boje
BOJE = {
    "plava": "#227AFF",
    "plava_tamna": "#1461E0",
    "plava_svijetla": "#E8F1FF",
    "tinta": "#0B1437",        # naslovi — gotovo crno-plavo, jak kontrast
    "tinta_2": "#1D2939",      # tijelo teksta
    "tekst": "#475467",        # sekundarno
    "tekst_slabi": "#667085",
    "crta": "#DDE3EE",
    "crta_slaba": "#EDF1F7",   # mekša crta
    "pozadina": "#EEF2F9",
    "bijela": "#FFFFFF",
    "zeleno": "#0E9F6E",
    "zeleno_poz": "#E6F7EF",
    "narancasto": "#B54708",
    "narancasto_poz": "#FEF0C7",
    "crveno": "#D92D20",
    "crveno_poz": "#FEE4E2",
    "ljubicasto": "#5925DC",
    "ljubicasto_poz": "#F4EBFF",
}

_VRSTA = {
    "neutralno": ("#F2F4F8", "#475467"),
    "plavo": ("#E8F1FF", "#1461E0"),
    "zeleno": ("#E6F7EF", "#067647"),
    "narancasto": ("#FEF0C7", "#B54708"),
    "crveno": ("#FEE4E2", "#B42318"),
    "ljubicasto": ("#F4EBFF", "#5925DC"),
}


def postavi_stranicu(naslov: str, ikona: str = "📘", siroko: bool = False,
                     sidebar: str = "auto") -> None:
    """st.set_page_config s CAKI postavkama. Mora biti PRVI Streamlit poziv.

    PAZI: aplikacije koje već imaju svoj `st.set_page_config` (a sve CAKI aplikacije ga
    imaju) NE smiju zvati ovu funkciju — njima treba samo `primijeni()`.
    `sidebar`: "auto" ostavlja Streamlitovo zadano ponašanje — bitno za višestranične
    aplikacije (baza zadataka ima 16 stranica u bočnom izborniku).
    """
    if sidebar not in ("auto", "collapsed", "expanded"):
        sidebar = "auto"
    st.set_page_config(
        page_title=naslov,
        page_icon=ikona,
        layout="wide" if siroko else "centered",
        initial_sidebar_state=sidebar,
    )


# --------------------------------------------------------------------------- CSS
CSS = """
<style>
/* ============================================================
   CAKI tema v2 — kontrast, bijele kartice, vidljiva navigacija
   ============================================================ */
:root{
  --ck-plava:#227AFF; --ck-plava-t:#1461E0; --ck-plava-p:#E8F1FF;
  --ck-ink:#0B1437; --ck-ink2:#1D2939; --ck-tekst:#475467; --ck-slabi:#667085;
  --ck-crta:#DDE3EE; --ck-crta-s:#EDF1F7; --ck-poz:#EEF2F9;
  --ck-sh:0 1px 3px rgba(16,24,40,.07), 0 10px 24px -18px rgba(16,24,40,.35);
}

/* ---------- podloga i tipografija ---------- */
.stApp{
  background:linear-gradient(180deg,#F5F8FD 0%,#E9EFF9 60%,#E4EBF7 100%) fixed;
}
header[data-testid="stHeader"]{ background:transparent; }
[data-testid="stAppDeployButton"]{ display:none !important; }

html, body, [class*="css"]{
  font-family:"Inter","Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,Arial,sans-serif;
  color:var(--ck-ink2);
}
.block-container, [data-testid="stMainBlockContainer"]{
  padding-top:1.5rem; padding-bottom:3rem; max-width:1120px;
}

h1,h2,h3,h4{ color:var(--ck-ink) !important; letter-spacing:-.025em; }
h1{ font-weight:800 !important; font-size:1.85rem !important; }
h2{ font-weight:750 !important; font-size:1.3rem !important; }
h3{ font-weight:700 !important; font-size:1.08rem !important; }
p, li{ color:var(--ck-ink2); }
[data-testid="stCaptionContainer"] p, .stCaption p{ color:var(--ck-slabi) !important; }
[data-testid="stMarkdownContainer"] strong{ color:var(--ck-ink); }

/* ---------- gumbi ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
[data-testid^="stBaseButton-secondary"]{
  border-radius:10px !important;
  font-weight:600 !important;
  font-size:.9rem !important;
  padding:.5rem 1rem !important;
  border:1px solid var(--ck-crta) !important;
  background:#fff !important;
  color:var(--ck-ink2) !important;
  box-shadow:0 1px 2px rgba(16,24,40,.06) !important;
  transition:transform .12s ease, box-shadow .12s ease, border-color .12s ease;
}
.stButton > button:hover, [data-testid^="stBaseButton-secondary"]:hover{
  border-color:#C3CEE0 !important; transform:translateY(-1px);
  box-shadow:0 4px 10px -4px rgba(16,24,40,.18) !important;
}
button[kind="primary"], button[kind="primaryFormSubmit"],
[data-testid^="stBaseButton-primary"]{
  background:var(--ck-plava) !important;
  border:1px solid #1867E8 !important;
  color:#fff !important;
  box-shadow:0 2px 4px rgba(20,97,224,.25), 0 10px 20px -12px rgba(34,122,255,.9) !important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
[data-testid^="stBaseButton-primary"]:hover{
  background:var(--ck-plava-t) !important; border-color:var(--ck-plava-t) !important;
}
[data-testid^="stBaseButton-primary"] p{ color:#fff !important; }

/* ---------- kartice ---------- */
[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-caki-"]{
  border-radius:20px !important;
  border:1px solid rgba(16,24,40,.06) !important;
  background:#fff !important;
  box-shadow:0 1px 3px rgba(16,24,40,.07), 0 18px 36px -26px rgba(16,24,40,.45) !important;
  padding:.3rem .45rem;
}
/* obrasci = kartice */
[data-testid="stForm"]{
  border:1px solid rgba(16,24,40,.06) !important;
  border-radius:20px !important;
  background:#fff !important;
  box-shadow:0 1px 3px rgba(16,24,40,.07), 0 18px 36px -26px rgba(16,24,40,.45) !important;
  padding:1.25rem 1.3rem 1.4rem !important;
}
/* u obrascu su razmaci manji — polja ne smiju „plivati" u praznom */
[data-testid="stForm"] [data-testid="stVerticalBlock"]{ gap:.45rem !important; }
[data-testid="stForm"] [data-testid="stElementContainer"]{ margin-bottom:0 !important; }

/* ---------- oznake polja (labele) ---------- */
[data-testid="stWidgetLabel"] p, .stSelectbox label p, .stTextInput label p,
.stTextArea label p, .stNumberInput label p, .stRadio label p, .stMultiSelect label p{
  font-size:.78rem !important; font-weight:600 !important; color:#344054 !important;
  letter-spacing:.01em; margin-bottom:2px !important;
}
[data-testid="stWidgetLabel"]{ margin-bottom:.15rem !important; }

/* ---------- unosi ---------- */
/* Streamlit 1.65 drži okvir na *RootElement omotaču (ne na <input>), a omotač ima
   overflow:hidden — zato okvir mora biti na omotaču, a samo polje bez okvira. */
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputRootElement"],
[data-testid="stDateInputRootElement"],
[data-testid="stTimeInputRootElement"],
[data-testid="stTextAreaRootElement"]{
  border:1px solid #CBD6E6 !important;
  border-radius:10px !important;
  background:#fff !important;
  min-height:42px;
  overflow:visible !important;
  transition:border-color .15s ease, box-shadow .15s ease;
}
[data-testid="stTextInputRootElement"]:hover, [data-testid="stNumberInputRootElement"]:hover,
[data-testid="stDateInputRootElement"]:hover, [data-testid="stTextAreaRootElement"]:hover{
  border-color:#A9BBD6 !important;
}
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stNumberInputRootElement"]:focus-within,
[data-testid="stDateInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within{
  border-color:var(--ck-plava) !important;
  box-shadow:0 0 0 3px rgba(34,122,255,.16) !important;
}
.stTextInput input, .stNumberInput input, .stDateInput input{
  border:0 !important; background:transparent !important; box-shadow:none !important;
  height:40px !important; min-height:40px !important;
  padding:.3rem .7rem !important; font-size:.9rem !important; color:var(--ck-ink2) !important;
}
.stTextArea textarea{
  border:0 !important; background:transparent !important; box-shadow:none !important;
  padding:.55rem .7rem !important; font-size:.9rem !important; color:var(--ck-ink2) !important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus{
  outline:none !important;
}
/* selectbox i multiselect */
[data-baseweb="select"] > div{
  border-radius:10px !important;
  border:1px solid #CBD6E6 !important;
  background:#fff !important;
  min-height:42px;
  transition:border-color .15s ease, box-shadow .15s ease;
}
[data-baseweb="select"] > div:hover{ border-color:#A9BBD6 !important; }
[data-baseweb="select"] > div:focus-within{
  border-color:var(--ck-plava) !important;
  box-shadow:0 0 0 3px rgba(34,122,255,.16) !important;
}
[data-baseweb="select"] span, [data-baseweb="select"] div[role="button"]{
  font-size:.9rem !important; color:var(--ck-ink2);
}
div[data-baseweb="popover"] li{ font-size:.88rem !important; }

/* ---------- tabovi = segmentirana traka ---------- */
[data-testid="stTabs"] > div:first-child,
[data-testid="stTabs"] [data-baseweb="tab-list"]{
  gap:4px; background:#DEE6F3; padding:5px; border-radius:14px;
  border:1px solid #CBD6E8; overflow-x:auto; scrollbar-width:none;
  box-shadow:inset 0 1px 2px rgba(16,24,40,.06);
}
[data-testid="stTabs"] > div:first-child::-webkit-scrollbar{ display:none; }
[data-testid="stTab"], [data-testid="stTabs"] button[data-baseweb="tab"]{
  border-radius:9px !important; padding:0 !important; background:transparent;
}
[data-testid="stTab"] p{
  font-size:.85rem !important; font-weight:600 !important; color:#475467 !important;
  padding:8px 14px !important; margin:0 !important; white-space:nowrap;
}
[data-testid="stTab"]:hover p{ color:var(--ck-ink) !important; }
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][data-selected="true"]{
  background:#fff !important;
  box-shadow:0 1px 2px rgba(16,24,40,.10), 0 1px 1px rgba(16,24,40,.06) !important;
}
[data-testid="stTab"][aria-selected="true"] p, [data-testid="stTab"][data-selected="true"] p{
  color:#0B1437 !important; font-weight:700 !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"]{ display:none !important; }
[data-testid="stTabs"] [role="tablist"]{ border-bottom:0 !important; gap:4px !important; }
[data-testid="stTabs"] [role="tablist"] > div:not([data-testid]){ display:none !important; }
[data-testid="stTab"]{ border-bottom:0 !important; }
[data-testid="stTab"]::after, [data-testid="stTab"]::before,
[data-testid="stTabs"] [role="tablist"] > div:not([data-testid]),
[data-testid="stTabs"] [role="tablist"]::after,
[data-testid="stTabs"] [role="tablist"]::before{ display:none !important; content:none !important; }

/* ---------- tablice ---------- */
[data-testid="stDataFrame"]{
  border:1px solid var(--ck-crta); border-radius:14px; overflow:hidden;
  box-shadow:0 1px 2px rgba(16,24,40,.05); background:#fff;
}

/* ---------- poruke, expander, ostalo ---------- */
[data-testid="stAlert"]{
  border-radius:12px !important; border:1px solid rgba(16,24,40,.07) !important;
  font-size:.88rem;
}
[data-testid="stExpander"]{
  border-radius:14px !important; border:1px solid var(--ck-crta) !important;
  background:#fff !important; box-shadow:0 1px 2px rgba(16,24,40,.05);
}
[data-testid="stExpander"] summary{ font-weight:600; color:var(--ck-ink2); }
hr{ border-color:var(--ck-crta); margin:1.1rem 0; }
.stSlider [data-baseweb="slider"] div[role="slider"]{ border-color:var(--ck-plava); }

/* ---------- metrike ---------- */
[data-testid="stMetric"]{
  background:#fff; border:1px solid var(--ck-crta); border-radius:14px;
  padding:12px 14px; box-shadow:0 1px 2px rgba(16,24,40,.05);
}
[data-testid="stMetricLabel"] p{
  font-size:.68rem !important; font-weight:700 !important; letter-spacing:.07em;
  text-transform:uppercase; color:var(--ck-slabi) !important;
}
[data-testid="stMetricValue"]{ font-size:1.45rem !important; font-weight:750 !important;
  color:var(--ck-ink) !important; }
[data-testid="stMetricValue"] > div{ white-space:normal; overflow:visible; text-overflow:clip;
  line-height:1.2; }

/* ============================================================
   CAKI komponente (vlastiti HTML)
   ============================================================ */
.caki-sekcija{
  display:flex; align-items:center; justify-content:space-between;
  margin:1.5rem 0 .55rem; font-size:.7rem; font-weight:700; letter-spacing:.09em;
  text-transform:uppercase; color:var(--ck-slabi);
}
.caki-grid{ display:grid; gap:10px; margin:.3rem 0 .2rem; }
.caki-grid.k3{ grid-template-columns:repeat(3,minmax(0,1fr)); }
.caki-grid.k2{ grid-template-columns:repeat(2,minmax(0,1fr)); }
.caki-stat{
  background:#fff; border:1px solid var(--ck-crta); border-radius:14px; padding:13px 14px;
  box-shadow:0 1px 2px rgba(16,24,40,.05); min-width:0;
}
.caki-stat .l{ display:block; font-size:.66rem; font-weight:700; letter-spacing:.07em;
  text-transform:uppercase; color:var(--ck-slabi); }
.caki-stat .v{ display:block; font-size:1.35rem; font-weight:750; color:var(--ck-ink);
  letter-spacing:-.02em; font-variant-numeric:tabular-nums; margin-top:5px; line-height:1.1; }
.caki-stat .p{ display:block; font-size:.72rem; font-weight:600; margin-top:4px; color:var(--ck-slabi); }
.caki-stat .p.zeleno{ color:#0E9F6E; } .caki-stat .p.narancasto{ color:#B54708; }

.caki-hero{
  border-radius:18px; padding:20px 22px; color:#fff; position:relative; overflow:hidden;
  background:linear-gradient(135deg,#3B8CFF 0%,#1A5FE0 52%,#0F42A6 100%);
  box-shadow:0 3px 6px rgba(20,97,224,.18), 0 16px 30px -20px rgba(20,97,224,.9);
}
.caki-hero .top{ display:flex; align-items:center; justify-content:space-between; }
.caki-hero .pill{ font-size:.63rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase;
  background:rgba(255,255,255,.20); border:1px solid rgba(255,255,255,.32);
  border-radius:99px; padding:5px 11px; }
.caki-hero .day{ font-size:.78rem; opacity:.9; font-weight:600; }
.caki-hero .big{ font-size:1.95rem; font-weight:800; letter-spacing:-.03em; margin:10px 0 4px;
  font-variant-numeric:tabular-nums; line-height:1; }
.caki-hero .meta{ font-size:.82rem; opacity:.95; line-height:1.45; }

.caki-oznaka{
  display:inline-block; font-size:.72rem; font-weight:700; line-height:1;
  padding:6px 10px; border-radius:8px; white-space:nowrap; letter-spacing:.005em;
}
.caki-red{ display:flex; align-items:center; gap:12px; padding:12px 0; }
.caki-red + .caki-red{ border-top:1px solid var(--ck-crta-s); }
.caki-red .ic{ width:36px; height:36px; flex:0 0 36px; border-radius:11px; display:grid;
  place-items:center; background:var(--ck-plava-p); font-size:.95rem; }
.caki-red .b{ flex:1; min-width:0; }
.caki-red .t{ font-size:.88rem; font-weight:650; color:var(--ck-ink); line-height:1.3; }
.caki-red .s{ font-size:.75rem; color:var(--ck-slabi); margin-top:2px; }

.caki-prazno{
  text-align:center; padding:28px 18px; border:1px dashed #C9D4E5; border-radius:16px;
  background:#FBFCFE;
}
.caki-prazno .e{ font-size:1.55rem; }
.caki-prazno .t{ font-size:.92rem; font-weight:700; color:var(--ck-ink); margin-top:9px; }
.caki-prazno .s{ font-size:.8rem; color:var(--ck-slabi); margin-top:5px; line-height:1.5; }

/* ---------- tablica u CAKI izgledu (za stil.tabela()) ---------- */
.caki-tabela-wrap{
  background:#fff; border:1px solid var(--ck-crta); border-radius:18px;
  box-shadow:var(--ck-sh); overflow:hidden;
}
table.caki-tabela{ width:100%; border-collapse:collapse; font-size:.86rem; }
table.caki-tabela thead th{
  text-align:left; font-size:.68rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase;
  color:var(--ck-slabi); background:#F7F9FC; padding:12px 16px;
  border-bottom:1px solid var(--ck-crta-s); white-space:nowrap;
}
table.caki-tabela tbody td{
  padding:13px 16px; color:var(--ck-ink2); border-bottom:1px solid var(--ck-crta-s);
  vertical-align:middle;
}
table.caki-tabela tbody tr:last-child td{ border-bottom:0; }
table.caki-tabela tbody tr:hover{ background:#F8FAFE; }

/* ---------- mobitel ---------- */
@media (max-width:640px){
  .block-container, [data-testid="stMainBlockContainer"]{
    padding-left:.8rem !important; padding-right:.8rem !important; padding-top:.9rem;
  }
  h1{ font-size:1.45rem !important; }
  .caki-grid.k3{ grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
  .caki-stat{ padding:10px 11px; }
  .caki-stat .v{ font-size:1.1rem; }
  .caki-hero .big{ font-size:1.55rem; }
  [data-testid="stMetricValue"]{ font-size:1.2rem !important; }
  [data-testid="stHorizontalBlock"]{ gap:.5rem !important; }
  .caki-red{ padding:10px 0; }
}
</style>
"""


def primijeni() -> None:
    """Ubaci CAKI CSS. Zovi jednom, odmah nakon st.set_page_config()."""
    st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- komponente
def _esc(t: object) -> str:
    return (
        str(t if t is not None else "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def naslov_sekcije(tekst: str) -> str:
    return f'<div class="caki-sekcija"><span>{_esc(tekst)}</span></div>'


def statistike(stavke: list[dict], kolone: int = 3) -> str:
    """Kartice s brojkama. stavke=[{oznaka, vrijednost, pod, boja}]"""
    celije = []
    for s in stavke:
        boja = s.get("boja", "")
        pod = s.get("pod", "")
        pod_html = f'<span class="p {boja}">{_esc(pod)}</span>' if pod else ""
        celije.append(
            f'<div class="caki-stat"><span class="l">{_esc(s.get("oznaka", ""))}</span>'
            f'<span class="v">{_esc(s.get("vrijednost", "—"))}</span>{pod_html}</div>'
        )
    return f'<div class="caki-grid k{kolone}">{"".join(celije)}</div>'


def hero(oznaka: str, vrijednost: str, detalj: str, desno: str = "") -> str:
    """Istaknuta plava kartica (sljedeći sat / dug / rok)."""
    desno_html = f'<span class="day">{_esc(desno)}</span>' if desno else ""
    detalj_html = _esc(detalj).replace("\n", "<br>")
    return (
        f'<div class="caki-hero"><div class="top"><span class="pill">{_esc(oznaka)}</span>'
        f'{desno_html}</div><div class="big">{_esc(vrijednost)}</div>'
        f'<div class="meta">{detalj_html}</div></div>'
    )


def oznaka(tekst: str, vrsta: str = "neutralno") -> str:
    """Mala obojena oznaka stanja: potvrđeno / poslano / plaćeno / čeka."""
    poz, tek = _VRSTA.get(vrsta, _VRSTA["neutralno"])
    return f'<span class="caki-oznaka" style="background:{poz};color:{tek}">{_esc(tekst)}</span>'


def red(ikona: str, naslov: str, podnaslov: str = "") -> str:
    """Redak popisa (umjesto tablice)."""
    pod = f'<div class="s">{_esc(podnaslov)}</div>' if podnaslov else ""
    return (
        f'<div class="caki-red"><div class="ic">{_esc(ikona)}</div>'
        f'<div class="b"><div class="t">{_esc(naslov)}</div>{pod}</div></div>'
    )


def prazno_stanje(naslov: str, tekst: str, emoji: str = "📭") -> str:
    """Prazno stanje MORA reći što dalje, ne samo da nema podataka."""
    return (
        f'<div class="caki-prazno"><div class="e">{_esc(emoji)}</div>'
        f'<div class="t">{_esc(naslov)}</div><div class="s">{_esc(tekst)}</div></div>'
    )


def nav(stavke: list[str], kljuc: str = "caki_nav", zadano: int = 0):
    """Glavna navigacija kao pilule. Vraća odabranu stavku."""
    if hasattr(st, "segmented_control"):
        izbor = st.segmented_control(
            "Navigacija", stavke, default=stavke[zadano], key=kljuc,
            label_visibility="collapsed",
        )
        return izbor or stavke[zadano]
    return st.radio(
        "Navigacija", stavke, index=zadano, key=kljuc, horizontal=True,
        label_visibility="collapsed",
    )


@contextmanager
def kartica(kljuc: str):
    """Bijela CAKI kartica (radi isto na starijim i novijim Streamlitima).

        with stil.kartica("sljedeci_sat"):
            st.markdown("**Matematika A**")
    """
    with st.container(border=True, key=f"caki-{kljuc}"):
        yield


def tabela(redovi: list[list], stupci: list[str], oznake: dict | None = None) -> str:
    """Tablica u CAKI izgledu (bijela kartica, siva traka zaglavlja, tanke crte).

    `st.dataframe` je canvas koji se ne može oblikovati CSS-om, pa se tablice koje
    roditelj gleda crtaju ovako. Vratiti kao HTML:

        st.markdown(stil.tabela(
            [["Ponuda 2026-118", "45,00 €", ("Poslano", "narancasto")]],
            ["Dokument", "Iznos", "Status"],
        ), unsafe_allow_html=True)

    Ćelija koja je tuple (tekst, vrsta) crta se kao obojena oznaka.
    """
    zag = "".join(f"<th>{_esc(s)}</th>" for s in stupci)
    tijelo = []
    for r in redovi:
        celije = []
        for c in r:
            if isinstance(c, (tuple, list)) and len(c) == 2:
                celije.append(f"<td>{oznaka(c[0], c[1])}</td>")
            else:
                celije.append(f"<td>{_esc(c)}</td>")
        tijelo.append("<tr>" + "".join(celije) + "</tr>")
    return (
        '<div class="caki-tabela-wrap"><table class="caki-tabela">'
        f"<thead><tr>{zag}</tr></thead><tbody>{''.join(tijelo)}</tbody></table></div>"
    )
