"""CAKI — tema i stil za Streamlit portale.

JEDNA datoteka. Namjerno: ako nova verzija Streamlita nešto pokvari, briše se jedan
`include` u portalu i sve se vraća na staro izgled (v. TRACKER §9 „Rizici" u
Claude outputs/CAKI_PLAN_UX-2026-10-26.md).

ŠTO OVA DATOTEKA RADI
  1. Postavlja CAKI boje i tipografiju preko CSS-a (Streamlit tema u
     .streamlit/config.toml radi isto, ali ne može fontove, radijuse, sjenčanje).
  2. Pretvara st.tabs u „pilule" (segmentiranu navigaciju) bez promjene koda.
  3. Pretvara st.metric u kartice, a st.container(border=True) u CAKI kartice.
  4. Daje gotove komponente za dijelove koje Streamlit ne može sam:
     statistike(), oznaka(), red(), prazno_stanje(), hero().

KAKO SE KORISTI (redoslijed je važan — set_page_config mora biti prvi):

    import caki_stil as stil
    stil.postavi_stranicu("Moj CAKI", "📘")
    stil.primijeni()
    ...
    st.markdown(stil.statistike([
        {"oznaka": "Dolasci",   "vrijednost": "92 %",     "pod": "11 od 12 sati", "boja": "zeleno"},
        {"oznaka": "Za uplatu", "vrijednost": "45,00 €",  "pod": "1 otvoreno",    "boja": "narancasto"},
    ]), unsafe_allow_html=True)

NIŠTA OVDJE NE DIRA PODATKE ni Sheet — ovo je isključivo prikaz.
"""

from __future__ import annotations

from contextlib import contextmanager

import streamlit as st

# --------------------------------------------------------------------------- boje
BOJE = {
    "plava": "#227AFF",
    "plava_tamna": "#1A63D8",
    "plava_svijetla": "#EAF2FF",
    "tinta": "#0F172A",
    "tinta_2": "#273044",       # Cakijeva osnovna boja teksta iz MASTER-a
    "tekst": "#5B6577",
    "tekst_slabi": "#8A93A6",
    "crta": "#E8ECF3",
    "pozadina": "#F5F7FB",
    "bijela": "#FFFFFF",
    "zeleno": "#0B9E6A",
    "zeleno_poz": "#E6F7F0",
    "narancasto": "#C2740A",
    "narancasto_poz": "#FEF4E4",
    "crveno": "#D92D20",
    "crveno_poz": "#FDECEC",
    "ljubicasto": "#6D4AFF",
    "ljubicasto_poz": "#F0ECFF",
}

_VRSTA_POZADINA = {
    "neutralno": ("#F2F5FA", "#5B6577"),
    "plavo": ("#EAF2FF", "#1A63D8"),
    "zeleno": ("#E6F7F0", "#07744E"),
    "narancasto": ("#FEF4E4", "#96590A"),
    "crveno": ("#FDECEC", "#B42318"),
    "ljubicasto": ("#F0ECFF", "#5433D6"),
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
/* ---------- osnova ---------- */
:root{
  --caki-plava:#227AFF; --caki-plava-t:#1A63D8; --caki-plava-p:#EAF2FF;
  --caki-tinta:#0F172A; --caki-tekst:#5B6577; --caki-slabi:#8A93A6;
  --caki-crta:#E8ECF3; --caki-poz:#F5F7FB;
  --caki-radijus:16px;
}
html, body, [class*="css"]{
  font-family:"Inter","Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,Arial,sans-serif;
}
.stApp{ background:var(--caki-poz); }
header[data-testid="stHeader"]{ background:transparent; }
[data-testid="stToolbar"]{ right:.6rem; }
/* „Deploy" i ⋮ ne pripadaju portalu za roditelje (isto radi i toolbarMode u config.toml) */
[data-testid="stAppDeployButton"]{ display:none !important; }

.block-container, [data-testid="stMainBlockContainer"]{
  padding-top:1.6rem; padding-bottom:3.2rem; max-width:1120px;
}

/* ---------- tipografija ---------- */
h1,h2,h3,h4{ color:var(--caki-tinta); letter-spacing:-.02em; }
h1{ font-weight:700; font-size:1.9rem; }
h2{ font-weight:700; font-size:1.35rem; }
h3{ font-weight:650; font-size:1.1rem; }
p, li, [data-testid="stMarkdownContainer"]{ color:#273044; }
[data-testid="stCaptionContainer"], .stCaption{ color:#8A93A6 !important; }
[data-testid="stMetricValue"]{ font-variant-numeric:tabular-nums; }

/* ---------- gumbi ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"]{
  border-radius:12px !important;
  font-weight:600 !important;
  padding:.5rem 1rem !important;
  border:1px solid var(--caki-crta) !important;
  box-shadow:0 1px 2px rgba(16,24,40,.05);
  transition:transform .12s ease, box-shadow .12s ease;
}
.stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover{
  border-color:#CBD6E6 !important; transform:translateY(-1px);
}
button[kind="primary"], [data-testid="stBaseButton-primary"]{
  background:var(--caki-plava) !important;
  border-color:var(--caki-plava) !important;
  color:#fff !important;
  box-shadow:0 10px 22px -12px rgba(34,122,255,.95) !important;
}
button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover{
  background:var(--caki-plava-t) !important; border-color:var(--caki-plava-t) !important;
}

/* ---------- kartice: st.container(border=True) ---------- */
/* Streamlit <= 1.4x ima omotač stVerticalBlockBorderWrapper.
   Streamlit >= 1.5x ga NEMA — tamo se kartica dobiva s ključem:
       with caki_stil.kartica("dolasci"):  ...   ->  .st-key-caki-dolasci
   Oba načina su pokrivena. */
[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-caki-"]{
  border-radius:18px !important;
  border:1px solid var(--caki-crta) !important;
  background:#fff !important;
  box-shadow:0 1px 2px rgba(16,24,40,.05);
}

/* ---------- st.metric -> kartica ---------- */
[data-testid="stMetric"]{
  background:#fff; border:1px solid var(--caki-crta); border-radius:14px;
  padding:12px 14px; box-shadow:0 1px 2px rgba(16,24,40,.05);
}
[data-testid="stMetricLabel"] p{
  font-size:.68rem !important; font-weight:650 !important; letter-spacing:.06em;
  text-transform:uppercase; color:#8A93A6 !important;
}
[data-testid="stMetricValue"]{ font-size:1.45rem !important; font-weight:700 !important; }
[data-testid="stMetricValue"] > div{ white-space:normal; overflow:visible; text-overflow:clip; line-height:1.25; }

/* ---------- st.tabs -> pilule ---------- */
/* 1.65: kartice tabova su [data-testid="stTab"], ne baseweb <button>.
   Držimo i stare selektore da tema radi i na starijim Streamlitima. */
[data-testid="stTabs"] > div:first-child{
  gap:4px; background:#EDF1F7; padding:4px; border-radius:12px;
  border:1px solid #E3E9F2; overflow-x:auto; scrollbar-width:none;
}
[data-testid="stTabs"] > div:first-child::-webkit-scrollbar{ display:none; }
[data-testid="stTabs"] [data-baseweb="tab-list"]{
  gap:4px; background:#EDF1F7; padding:4px; border-radius:12px;
  border:1px solid #E3E9F2; overflow-x:auto; scrollbar-width:none;
}
[data-testid="stTab"], [data-testid="stTabs"] button[data-baseweb="tab"]{
  border-radius:9px !important; padding:0 !important; font-size:.86rem; font-weight:600;
  color:#5B6577 !important; background:transparent;
}
[data-testid="stTabs"] button[data-baseweb="tab"]{
  padding:7px 13px !important; white-space:nowrap;
}
[data-testid="stTab"] p{
  font-size:.86rem !important; font-weight:600 !important; color:#5B6577 !important;
  padding:7px 13px !important; margin:0 !important; white-space:nowrap;
}
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][data-selected="true"]{
  background:#fff !important; box-shadow:0 1px 2px rgba(16,24,40,.07);
}
[data-testid="stTab"][aria-selected="true"] p, [data-testid="stTab"][data-selected="true"] p{
  color:#0F172A !important;
}
[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"]{
  background:#fff; color:#0F172A; box-shadow:0 1px 2px rgba(16,24,40,.07);
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"]{ display:none !important; }
[data-testid="stTabs"] [data-baseweb="tab-list"] > div[style*="height: 2px"]{ display:none !important; }
/* Streamlit 1.5x+ (react-aria): crta ispod reda i plava crta ispod aktivnog taba
   su dodatni elementi / pseudo-elementi — skidamo ih da ostane čista pilula. */
[data-testid="stTabs"] [role="tablist"]{ border-bottom:0 !important; gap:4px !important; }
[data-testid="stTabs"] [role="tablist"] > div:not([data-testid]){ display:none !important; }
[data-testid="stTab"]{ border-bottom:0 !important; }
[data-testid="stTab"]::after, [data-testid="stTab"]::before,
[data-testid="stTabs"] [role="tablist"]::after,
[data-testid="stTabs"] [role="tablist"]::before{ display:none !important; content:none !important; }

/* ---------- tablice ---------- */
[data-testid="stDataFrame"]{
  border:1px solid var(--caki-crta); border-radius:14px; overflow:hidden;
  box-shadow:0 1px 2px rgba(16,24,40,.05);
}

/* ---------- poruke, expander, unosi ---------- */
[data-testid="stAlert"]{ border-radius:14px; border:1px solid rgba(16,24,40,.06); }
[data-testid="stExpander"]{ border-radius:14px !important; border:1px solid var(--caki-crta) !important;
  background:#fff; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div{
  border-radius:11px !important;
}
.stTextInput input, .stNumberInput input, .stTextArea textarea{ border-radius:11px !important; }
[data-testid="stForm"]{ border:1px solid var(--caki-crta); border-radius:16px; padding:1rem; background:#fff; }
hr{ border-color:var(--caki-crta); }

/* ---------- CAKI komponente (vlastiti HTML) ---------- */
.caki-sekcija{
  display:flex; align-items:center; justify-content:space-between;
  margin:1.4rem 0 .5rem; font-size:.68rem; font-weight:700; letter-spacing:.08em;
  text-transform:uppercase; color:#8A93A6;
}
.caki-grid{ display:grid; gap:9px; margin:.35rem 0 .2rem; }
.caki-grid.k3{ grid-template-columns:repeat(3,minmax(0,1fr)); }
.caki-grid.k2{ grid-template-columns:repeat(2,minmax(0,1fr)); }
.caki-stat{
  background:#fff; border:1px solid var(--caki-crta); border-radius:14px; padding:12px 13px;
  box-shadow:0 1px 2px rgba(16,24,40,.05); min-width:0;
}
.caki-stat .l{ display:block; font-size:.66rem; font-weight:650; letter-spacing:.06em;
  text-transform:uppercase; color:#8A93A6; }
.caki-stat .v{ display:block; font-size:1.3rem; font-weight:700; color:#0F172A;
  letter-spacing:-.02em; font-variant-numeric:tabular-nums; margin-top:4px; line-height:1.1; }
.caki-stat .p{ display:block; font-size:.7rem; font-weight:600; margin-top:3px; color:#8A93A6; }
.caki-stat .p.zeleno{ color:#0B9E6A; } .caki-stat .p.narancasto{ color:#C2740A; }

.caki-hero{
  border-radius:24px; padding:18px 20px; color:#fff; position:relative; overflow:hidden;
  background:linear-gradient(135deg,#2E85FF 0%,#1B5EE0 55%,#164BC0 100%);
  box-shadow:0 14px 30px -18px rgba(34,122,255,.9);
}
.caki-hero .top{ display:flex; align-items:center; justify-content:space-between; }
.caki-hero .pill{ font-size:.62rem; font-weight:650; letter-spacing:.1em; text-transform:uppercase;
  background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.28);
  border-radius:99px; padding:4px 10px; }
.caki-hero .day{ font-size:.78rem; opacity:.85; font-weight:600; }
.caki-hero .big{ font-size:1.9rem; font-weight:700; letter-spacing:-.03em; margin:10px 0 3px;
  font-variant-numeric:tabular-nums; line-height:1; }
.caki-hero .meta{ font-size:.8rem; opacity:.92; line-height:1.45; }

.caki-oznaka{
  display:inline-block; font-size:.68rem; font-weight:600; line-height:1;
  padding:6px 9px; border-radius:8px; white-space:nowrap;
}
.caki-red{ display:flex; align-items:center; gap:11px; padding:11px 0; }
.caki-red + .caki-red{ border-top:1px solid #F1F4F9; }
.caki-red .ic{ width:34px; height:34px; flex:0 0 34px; border-radius:11px; display:grid;
  place-items:center; background:#EAF2FF; font-size:.95rem; }
.caki-red .b{ flex:1; min-width:0; }
.caki-red .t{ font-size:.86rem; font-weight:600; color:#0F172A; line-height:1.3; }
.caki-red .s{ font-size:.72rem; color:#8A93A6; margin-top:2px; }

.caki-prazno{
  text-align:center; padding:26px 16px; border:1px dashed #D8E0EC; border-radius:16px;
  background:#FBFCFE;
}
.caki-prazno .e{ font-size:1.5rem; }
.caki-prazno .t{ font-size:.9rem; font-weight:650; color:#273044; margin-top:8px; }
.caki-prazno .s{ font-size:.78rem; color:#8A93A6; margin-top:4px; line-height:1.45; }

/* ---------- mobitel ---------- */
@media (max-width:640px){
  .block-container{ padding-left:.85rem !important; padding-right:.85rem !important; padding-top:1rem; }
  h1{ font-size:1.5rem !important; }
  .caki-grid.k3{ grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; }
  .caki-stat{ padding:10px 11px; }
  .caki-stat .v{ font-size:1.12rem; }
  .caki-hero .big{ font-size:1.55rem; }
  [data-testid="stMetricValue"]{ font-size:1.25rem !important; }
  [data-testid="stHorizontalBlock"]{ gap:.5rem !important; }
}
</style>
"""


def primijeni() -> None:
    """Ubaci CAKI CSS. Zovi jednom, odmah nakon postavi_stranicu()."""
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
    poz, tek = _VRSTA_POZADINA.get(vrsta, _VRSTA_POZADINA["neutralno"])
    return f'<span class="caki-oznaka" style="background:{poz};color:{tek}">{_esc(tekst)}</span>'


def red(ikona: str, naslov: str, podnaslov: str = "") -> str:
    """Redak popisa (umjesto tablice). Nije klikabilan — za akciju koristi st.button uz njega."""
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
    """Glavna navigacija kao pilule. Vraća odabranu stavku.

    Streamlit nema pravu navigaciju; ovo je najbliže bez JS-a. Ako je dostupan
    st.segmented_control (Streamlit >= 1.40) koristi se on, inače st.radio.
    """
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
    """Bijela CAKI kartica (zaobilazi razliku između verzija Streamlita).

        with stil.kartica("sljedeci_sat"):
            st.markdown("**Matematika A**")

    `kljuc` mora biti jedinstven na stranici (kao i svaki drugi Streamlit key).
    """
    with st.container(border=True, key=f"caki-{kljuc}"):
        yield
