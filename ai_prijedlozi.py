"""
CAKI — ai_prijedlozi.py
Zajednička logika AI prijedloga ispravaka (tab "AI_kontrola_prijedlozi"), koju koriste:
  - pages/7_ai_kontrola.py           (brzi skupni pregled: prihvati/odbij puno prijedloga zaredom)
  - baza_zadataka_app.py             (stranica "Provjera i uređivanje": okvir "🤖 AI prijedlozi"
                                      uz cijeli zadatak + filter "samo s AI prijedlozima")
Obje stranice čitaju/pišu ISTI tab, pa se odluka donesena na jednoj odmah vidi na drugoj.

VAŽNO (lekcija 15.9.2026.): ova datoteka mora biti pushana u ISTOM commitu kao
baza_zadataka_app.py i pages/7_ai_kontrola.py koji je importaju.
"""

import difflib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import streamlit as st

PRIJEDLOZI_TAB = "AI_kontrola_prijedlozi"
CACHE_KLJUC = "ai_prijedlozi_cache"  # st.session_state: (header, redovi) - dijele obje stranice
TZ = ZoneInfo("Europe/Zagreb")


def sada():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def slovo_stupca(idx0: int) -> str:
    idx = idx0 + 1
    s = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


# ---------------------------------------------------------------
# Učitavanje prijedloga (s cacheom u sesiji)
# ---------------------------------------------------------------

def ucitaj_prijedloge(spreadsheet, osvjezi=False):
    """Vraća (header, redovi) iz taba AI_kontrola_prijedlozi; redovi su dictovi s '_redak'.
    Ako tab još ne postoji (AI kontrola nikad nije pokrenuta) -> ([], [])."""
    if not osvjezi and CACHE_KLJUC in st.session_state:
        return st.session_state[CACHE_KLJUC]
    try:
        vrijednosti = spreadsheet.worksheet(PRIJEDLOZI_TAB).get_all_values()
    except gspread.WorksheetNotFound:
        vrijednosti = []
    if not vrijednosti:
        rez = ([], [])
    else:
        header = [h.strip() for h in vrijednosti[0]]
        redovi = []
        for i, r in enumerate(vrijednosti[1:], start=2):
            d = {h: (r[j] if j < len(r) else "") for j, h in enumerate(header)}
            d["_redak"] = i
            redovi.append(d)
        rez = (header, redovi)
    st.session_state[CACHE_KLJUC] = rez
    return rez


def ponisti_cache():
    st.session_state.pop(CACHE_KLJUC, None)


def otvoreni_prijedlozi(spreadsheet):
    _, redovi = ucitaj_prijedloge(spreadsheet)
    return [p for p in redovi if p.get("status") == "novo"]


# ---------------------------------------------------------------
# Pregledan prikaz razlika
# ---------------------------------------------------------------
# Usporedba po "tokenima" (LaTeX naredba, broj, riječ, pojedini znak) umjesto po cijelim
# retcima - vidi se točno ŠTO se mijenja (npr. samo "+6" -> "-6"), a dugi nepromijenjeni
# dijelovi skraćuju se na "…". Crveno precrtano = briše se, zeleno = dodaje se.

_TOKEN_RE = re.compile(r"\\[A-Za-z]+|\d+(?:[.,]\d+)?|[A-Za-zČĆŠĐŽčćšđž]+|\s+|.", re.S)
_HTML_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "$": "&#36;", "\\": "&#92;", "*": "&#42;",
             "_": "&#95;", "`": "&#96;", "\n": "<br>", "#": "&#35;", "[": "&#91;", "]": "&#93;"}


def _esc(t):
    return "".join(_HTML_ESC.get(c, c) for c in t)


def _html_kutija(sadrzaj):
    return ('<div style="font-family:monospace;font-size:0.95rem;line-height:1.7;'
            'white-space:pre-wrap;padding:8px 10px;border:1px solid #ddd;border-radius:6px;">'
            f"{sadrzaj}</div>")


def html_diff_inline(staro, novo, kontekst=40):
    a, b = _TOKEN_RE.findall(staro or ""), _TOKEN_RE.findall(novo or "")
    dijelovi = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            t = "".join(a[i1:i2])
            if len(t) > 2 * kontekst:
                t = (t[:kontekst] if dijelovi else "") + " … " + t[-kontekst:]
            dijelovi.append(_esc(t))
            continue
        if i2 > i1:
            dijelovi.append('<span style="background:#ffd1d1;color:#a00000;text-decoration:line-through;'
                            f'border-radius:3px;padding:0 2px;">{_esc("".join(a[i1:i2]))}</span>')
        if j2 > j1:
            dijelovi.append('<span style="background:#c8f2c8;color:#005a00;font-weight:700;'
                            f'border-radius:3px;padding:0 2px;">{_esc("".join(b[j1:j2]))}</span>')
    return "".join(dijelovi)


def html_diff(staro, novo, kontekst=40):
    return _html_kutija(html_diff_inline(staro, novo, kontekst))


def prikazi_promjenu(p):
    """Glavni prikaz jednog prijedloga, prilagođen vrsti polja."""
    staro, novo, polje = p.get("staro", ""), p.get("novo", ""), p.get("polje", "")
    if polje == RAZDVOJI:
        prikazi_razdvajanje(p)
        return
    if polje in ("konacan_odgovor", "tip_zadatka", "max_bodovi", "broj_u_izvoru"):
        st.markdown(
            _html_kutija(f'<span style="color:#a00000;text-decoration:line-through;">{_esc(staro) or "(prazno)"}</span>'
                         f'&nbsp;&nbsp;➜&nbsp;&nbsp;<span style="color:#005a00;font-weight:700;font-size:1.15rem;">'
                         f'{_esc(novo) or "(prazno)"}</span>'),
            unsafe_allow_html=True)
    elif polje == "ponudjeni_odgovori":
        so = [o.strip() for o in staro.split("||")]
        no = [o.strip() for o in novo.split("||")]
        redovi = []
        for i in range(max(len(so), len(no))):
            o1 = so[i] if i < len(so) else ""
            o2 = no[i] if i < len(no) else ""
            slovo = chr(65 + i)
            if o1 == o2:
                redovi.append(f"<b>{slovo}</b>&nbsp; {_esc(o1)}")
            else:
                redovi.append(f"<b>{slovo}</b>&nbsp; ⚠️ {html_diff_inline(o1, o2)}")
        st.markdown(_html_kutija("<br>".join(redovi)), unsafe_allow_html=True)
    else:
        st.markdown(html_diff(staro, novo), unsafe_allow_html=True)


# ---------------------------------------------------------------
# RAZDVAJANJE: jedan redak u bazi sadrži više podzadataka (npr. 25.1, 25.2, 25.3) -> prvi dio
# zamjenjuje postojeći redak, ostali postaju NOVI redci (isti izvor/cjelina/slika...), svaki
# samostalan s ponovljenim zajedničkim uvodom (isto pravilo kao točka 1c EXTRACTION prompta, §31).
# Ništa se ne gubi: rješenja/odgovori dijelova dolaze iz ključa.
# ---------------------------------------------------------------

RAZDVOJI = "RAZDVOJI"
# Polja koja se NE kopiraju iz izvornog retka u nove dijelove (specifična za pojedini zadatak).
_NE_KOPIRAJ = {
    "tekst_zadatka_mathjax", "rjesenje", "rjesenje_status", "tip_rjesenja_izvor", "konacan_odgovor",
    "ponudjeni_odgovori", "max_bodovi", "video_url", "geogebra_komande", "geogebra_material_id",
    "slicni_zadaci", "pretext_permalink", "uputa", "redoslijed_u_potpoglavlju",
    "koristi_kao_primjer_na_satu", "u_skriptu", "status_provjere",
}


def dijelovi_razdvajanja(p):
    try:
        d = json.loads(p.get("novo") or "[]")
        return d if isinstance(d, list) else []
    except json.JSONDecodeError:
        return []


def prikazi_razdvajanje(p):
    dijelovi = dijelovi_razdvajanja(p)
    st.markdown(f"**✂️ Zadatak se razdvaja na {len(dijelovi)} zasebna zadatka** "
                "(prvi zamjenjuje postojeći redak, ostali se dodaju kao novi):")
    for i, d in enumerate(dijelovi):
        with st.container(border=True):
            oznaka = d.get("oznaka", "")
            st.caption(f"{'Postojeći redak' if i == 0 else 'NOVI redak'} · {oznaka} · "
                       f"{d.get('tip_zadatka', '')} · bodovi: {d.get('max_bodovi', '') or '—'}")
            st.markdown(d.get("tekst_zadatka_latex", "") or "*(prazno)*")
            if d.get("konacan_odgovor"):
                st.markdown(f"**Odgovor:** {d['konacan_odgovor']}")
            if d.get("rjesenje"):
                st.caption("Rješenje:")
                st.markdown(d["rjesenje"])


def primijeni_razdvajanje(spreadsheet, ws_zadaci, p, odlucio):
    dijelovi = [d for d in dijelovi_razdvajanja(p) if (d.get("tekst_zadatka_latex") or "").strip()]
    if len(dijelovi) < 2:
        return _zapisi_status(spreadsheet, p, "greska_neispravno_razdvajanje", odlucio)
    header_z = ws_zadaci.row_values(1)
    if "id" not in header_z or "tekst_zadatka_latex" not in header_z:
        return _zapisi_status(spreadsheet, p, "greska_nema_retka_ili_stupca", odlucio)
    i_id = header_z.index("id")
    celija = ws_zadaci.find(p["id_zadatka"], in_column=i_id + 1)
    if celija is None:
        return _zapisi_status(spreadsheet, p, "greska_nema_retka_ili_stupca", odlucio)
    red = ws_zadaci.row_values(celija.row)
    red += [""] * (len(header_z) - len(red))
    if red[header_z.index("tekst_zadatka_latex")].strip() != (p.get("staro") or "").strip():
        return _zapisi_status(spreadsheet, p, "zastarjelo", odlucio)

    napomena = f"AI razdvajanje ({sada()}): provjeri dijelove i rješenja"

    def vrijednosti_dijela(d, osnova):
        v = list(osnova)
        for polje in ("tekst_zadatka_latex", "tip_zadatka", "konacan_odgovor", "rjesenje", "max_bodovi",
                      "ponudjeni_odgovori"):
            if polje in header_z and polje in d:
                v[header_z.index(polje)] = str(d.get(polje) or "")
        if "rjesenje_status" in header_z:
            v[header_z.index("rjesenje_status")] = "sluzbeno" if d.get("rjesenje") or d.get("konacan_odgovor") else "nedostaje"
        if "broj_u_izvoru" in header_z and d.get("oznaka"):
            v[header_z.index("broj_u_izvoru")] = str(d["oznaka"])
        if "status_provjere" in header_z:
            sp = v[header_z.index("status_provjere")].strip()
            v[header_z.index("status_provjere")] = f"{sp}; {napomena}" if sp else napomena
        return v

    # 1) prvi dio -> postojeći redak (pišu se SAMO promijenjene ćelije, ostale se ne diraju)
    prvi = vrijednosti_dijela(dijelovi[0], red)
    izmjene = [{"range": f"{slovo_stupca(j)}{celija.row}", "values": [[prvi[j]]]}
               for j in range(len(header_z)) if prvi[j] != red[j]]
    if izmjene:
        ws_zadaci.batch_update(izmjene, value_input_option="RAW")

    # 2) ostali dijelovi -> novi redci s jedinstvenim ID-em (<id>_2, <id>_3, ...)
    postojeci_id = set(ws_zadaci.col_values(i_id + 1))
    osnova_novih = [("" if h in _NE_KOPIRAJ else red[j]) for j, h in enumerate(header_z)]
    novi = []
    k = 2
    for d in dijelovi[1:]:
        while f"{p['id_zadatka']}_{k}" in postojeci_id:
            k += 1
        nid = f"{p['id_zadatka']}_{k}"
        postojeci_id.add(nid)
        v = vrijednosti_dijela(d, osnova_novih)
        v[i_id] = nid
        novi.append(v)
    ws_zadaci.append_rows(novi, value_input_option="RAW")
    return _zapisi_status(spreadsheet, p, "primijenjeno", odlucio)


def naslov_prijedloga(p):
    boja = {"visoka": "🟢", "srednja": "🟠", "niska": "🔴"}.get(p.get("sigurnost", ""), "⚪")
    return f"{boja} `{p.get('id_zadatka') or '—'}` · {p.get('polje', '')} · *{p.get('vrsta', '')}*"


def prikazi_kontekst_prijedloga(p):
    """Razlog + doslovni isječak originala (ako ga je DeepSeek dao)."""
    if p.get("razlog"):
        st.markdown(f"**💬 {p['razlog']}**")
    if p.get("isjecak_originala"):
        st.caption("📄 Original (iz PDF-a):")
        st.info(p["isjecak_originala"])


# ---------------------------------------------------------------
# Primjena JEDNOG prijedloga (stranica "Provjera i uređivanje")
# ---------------------------------------------------------------

def primijeni_jedan(spreadsheet, ws_zadaci, p, prihvati: bool, novo_val: str, odlucio: str):
    """Prihvati/odbij jedan prijedlog. Kod prihvaćanja čita SVJEŽ redak iz baze i provjerava
    da se vrijednost u međuvremenu nije promijenila (inače 'zastarjelo', ništa se ne piše).
    Vraća novi status."""
    status = "odbijeno"
    if prihvati and p.get("polje") == RAZDVOJI:
        return primijeni_razdvajanje(spreadsheet, ws_zadaci, p, odlucio)
    if prihvati:
        if p["polje"] == "-":
            status = "pregledano"
        else:
            header_z = ws_zadaci.row_values(1)
            if "id" not in header_z or p["polje"] not in header_z:
                status = "greska_nema_retka_ili_stupca"
            else:
                celija = ws_zadaci.find(p["id_zadatka"], in_column=header_z.index("id") + 1)
                if celija is None:
                    status = "greska_nema_retka_ili_stupca"
                else:
                    red = ws_zadaci.row_values(celija.row)
                    i = header_z.index(p["polje"])
                    trenutno = red[i] if i < len(red) else ""
                    upis = novo_val
                    if p["polje"] == "status_provjere":  # napomena se DOPISUJE na postojeću
                        upis = f"{trenutno.strip()}; {novo_val}" if trenutno.strip() else novo_val
                    elif trenutno.strip() != (p.get("staro") or "").strip():
                        return _zapisi_status(spreadsheet, p, "zastarjelo", odlucio)
                    ws_zadaci.update(range_name=f"{slovo_stupca(i)}{celija.row}", values=[[upis]],
                                     value_input_option="RAW")
                    status = "primijenjeno"
    return _zapisi_status(spreadsheet, p, status, odlucio,
                          novo_val if status == "primijenjeno" and novo_val != p.get("novo") else None)


def _zapisi_status(spreadsheet, p, status, odlucio, uredeno_novo=None):
    ws_p = spreadsheet.worksheet(PRIJEDLOZI_TAB)
    header_p = ws_p.row_values(1)
    rr = p["_redak"]
    izmjene = [
        {"range": f"{slovo_stupca(header_p.index('status'))}{rr}", "values": [[status]]},
        {"range": f"{slovo_stupca(header_p.index('odlucio'))}{rr}", "values": [[odlucio]]},
        {"range": f"{slovo_stupca(header_p.index('vrijeme_odluke'))}{rr}", "values": [[sada()]]},
    ]
    if uredeno_novo is not None:
        izmjene.append({"range": f"{slovo_stupca(header_p.index('novo'))}{rr}", "values": [[uredeno_novo]]})
    ws_p.batch_update(izmjene, value_input_option="RAW")
    ponisti_cache()
    return status


def prikazi_ai_prijedloge_za_zadatak(spreadsheet, ws_zadaci, id_zadatka, nakon_izmjene=None, odlucio="caki"):
    """Okvir '🤖 AI prijedlozi' iznad formulara za uređivanje jednog zadatka. Ne prikazuje
    ništa ako zadatak nema otvorenih prijedloga."""
    if not id_zadatka:
        return
    moji = [p for p in otvoreni_prijedlozi(spreadsheet) if p.get("id_zadatka") == id_zadatka]
    if not moji:
        return
    with st.container(border=True):
        st.markdown(f"### 🤖 AI prijedlozi za ovaj zadatak ({len(moji)})")
        st.caption("Crveno precrtano = briše se, zeleno = dodaje se. Prihvaćanje odmah upisuje u bazu.")
        poruka = st.session_state.pop("ai_ed_poruka", None)
        if poruka:
            st.warning(poruka)
        for p in moji:
            pid = p["prijedlog_id"]
            st.markdown(f"#### {naslov_prijedloga(p)}")
            prikazi_kontekst_prijedloga(p)
            novo_val = p.get("novo", "")
            if p["polje"] == RAZDVOJI:
                prikazi_promjenu(p)
            elif p["polje"] not in ("-", "status_provjere"):
                prikazi_promjenu(p)
                with st.expander("Ručno doradi prijedlog prije prihvaćanja"):
                    novo_val = st.text_area("Nova vrijednost", novo_val, key=f"ai_ed_tx_{pid}", height=90)
            c1, c2, _ = st.columns([1, 1, 3])
            prihvati = c1.button("✅ Prihvati", key=f"ai_ed_da_{pid}", type="primary")
            odbij = c2.button("❌ Odbij", key=f"ai_ed_ne_{pid}")
            if prihvati or odbij:
                with st.spinner("Spremam..."):
                    status = primijeni_jedan(spreadsheet, ws_zadaci, p, bool(prihvati), novo_val, odlucio)
                if status == "zastarjelo":
                    st.session_state["ai_ed_poruka"] = (
                        "Vrijednost u bazi se u međuvremenu promijenila - prijedlog nije primijenjen "
                        "(označen kao 'zastarjelo'). Ako je potrebno, ispravi ručno u formularu ispod.")
                if nakon_izmjene:
                    nakon_izmjene()
                st.rerun()
            st.divider()
