"""
CAKI Matematika - baza_zadataka_app.py
Streamlit sučelje za obradu PDF ispita: upload -> Mathpix OCR -> Claude
strukturiranje -> upis u centralnu Google Sheets bazu (s detekcijom
duplikata). Zamišljeno za suradnike koji ne trebaju koristiti Colab.

Stranice (navigacija u sidebaru):
- 📄 Obradi novi ispit  - originalni pipeline (PDF -> baza)
- ✏️ Uredi zadatak - pretraga + ispravak teksta/rješenja/upute, kategorije/cjeline/
  potpoglavlja i slike za postojeći zadatak, sve na jednom mjestu
- 🔍 Zadaci za provjeru - pregled zadataka koje je Claude označio za ručnu provjeru
"""
import json
import mimetypes
import os

import streamlit as st

from baza_zadataka_pipeline import (
    _col_letter,
    build_sifrarnik_potpoglavlja_text,
    build_sifrarnik_text,
    extract_zadaci_with_claude,
    get_drive_service,
    get_gspread_client,
    get_potpoglavlja_po_cjelini,
    get_sifrarnik_cjelina,
    mathpix_ocr_vise_datoteka,
    nadopuni_ili_dodaj_zadatke,
    preuzmi_i_spremi_slike,
    upload_image_to_drive,
)

# Tipovi datoteka koje uploaderi za OCR ulaz prihvaćaju - PDF i uobičajeni formati slika
# (npr. screenshot zaslona zadataka/rješenja). Mathpix OCR grana se automatski po ekstenziji
# u pipeline.mathpix_ocr_datoteka() - ovdje samo dopuštamo oba u Streamlit file_upload widgetu.
OCR_TIPOVI_DATOTEKA = ["pdf", "png", "jpg", "jpeg", "gif", "webp"]

st.set_page_config(page_title="CAKI Matematika — Obrada ispita", page_icon="📚", layout="centered")


# --- Jednostavna zaštita lozinkom (protiv slučajnih posjetitelja s interneta, ne protiv suradnika) ---

def provjeri_lozinku() -> bool:
    def na_unos():
        if st.session_state.get("lozinka_unos") == st.secrets.get("APP_PASSWORD"):
            st.session_state["autoriziran"] = True
        else:
            st.session_state["autoriziran"] = False

    if st.session_state.get("autoriziran"):
        return True

    st.title("📚 CAKI Matematika")
    st.text_input("Lozinka", type="password", key="lozinka_unos", on_change=na_unos)
    if st.session_state.get("autoriziran") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


# --- Google klijenti (keširano - ne spaja se iznova na svaki rerun) ---

@st.cache_resource
def init_google_clients():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    drive_service = get_drive_service(sa_info)
    sheet = gc.open_by_key(st.secrets["SHEET_ID"])
    return drive_service, sheet


drive_service, sheet = init_google_clients()
ws_zadaci = sheet.worksheet("Zadaci")


# ============================================================
# Stranica 1: Obradi novi ispit (PDF -> OCR -> Claude -> baza)
# ============================================================

def stranica_obradi_ispit():
    st.title("📚 CAKI Matematika — Obrada ispita")
    st.caption("Upload PDF-ova → OCR → Claude strukturiranje → upis u bazu")

    with st.form("obrada_form", clear_on_submit=False):
        st.subheader("1. Datoteke")
        st.caption(
            "Prihvaćeni su PDF-ovi i slike (npr. screenshotovi zaslona). Može se priložiti "
            "više datoteka odjednom u svakom polju - sve se OCR-aju zasebno i spoje u jedan tekst, "
            "istim redoslijedom kojim su dodane. Za screenshotove: veća rezolucija = bolji OCR "
            "(izbjegavaj jako komprimirane JPEG-ove sitnih formula)."
        )
        ispit_datoteke = st.file_uploader(
            "Zadatci (PDF i/ili slike) — obavezno",
            type=OCR_TIPOVI_DATOTEKA, accept_multiple_files=True,
        )
        rjesenja_datoteke = st.file_uploader(
            "Rješenja (PDF i/ili slike) — opcionalno",
            type=OCR_TIPOVI_DATOTEKA, accept_multiple_files=True,
        )

        st.subheader("2. Metapodaci")
        col1, col2, col3 = st.columns(3)
        izvor_tip = col1.selectbox("Izvor", ["matura", "zbirka", "udzbenik", "vlastiti_materijal"])
        razina = col2.selectbox("Razina", ["A", "B", "-"])
        godina = col3.text_input("Godina", "")

        posalji = st.form_submit_button("🚀 Obradi")

    if not posalji:
        return

    if not ispit_datoteke:
        st.error("Moraš priložiti barem jednu datoteku sa zadatcima (PDF ili slika).")
        st.stop()

    log_prostor = st.empty()
    log_redovi = []

    def log(poruka: str):
        log_redovi.append(poruka)
        log_prostor.text("\n".join(log_redovi))

    mathpix_id = st.secrets["MATHPIX_APP_ID"]
    mathpix_key = st.secrets["MATHPIX_APP_KEY"]
    anthropic_key = st.secrets["ANTHROPIC_API_KEY"]
    slike_folder_id = st.secrets["SLIKE_FOLDER_ID"]

    izvor_naziv = os.path.splitext(ispit_datoteke[0].name)[0]
    broj_pdf_ulaza = len(ispit_datoteke) + len(rjesenja_datoteke)

    with st.spinner("Obrada u tijeku — ovo može potrajati 1-3 minute..."):
        log(f"📄 Obrađujem: {izvor_naziv} ({broj_pdf_ulaza} datoteka)")

        try:
            # 1. Mathpix OCR zadataka (PDF i/ili slike, spojeno u jedan tekst)
            ispit_md = mathpix_ocr_vise_datoteka(ispit_datoteke, mathpix_id, mathpix_key, log=log)
            log(f"✅ OCR zadataka gotov (ukupno {len(ispit_md)} znakova)")

            # 2. Mathpix OCR rješenja (ako postoje, PDF i/ili slike)
            rjesenja_md = mathpix_ocr_vise_datoteka(rjesenja_datoteke, mathpix_id, mathpix_key, log=log) \
                if rjesenja_datoteke else None

            # 3. Claude strukturiranje (uključujući klasifikaciju potpoglavlja iz šifrarnika)
            log("🤖 Claude strukturira zadatke...")
            sifrarnik_text = build_sifrarnik_text(sheet)
            sifrarnik_potpoglavlja_text = build_sifrarnik_potpoglavlja_text(sheet)
            zadaci = extract_zadaci_with_claude(
                ispit_md, rjesenja_md, sifrarnik_text, anthropic_key,
                sifrarnik_potpoglavlja_text, log=log,
            )
            log(f"✅ Claude vratio {len(zadaci)} zadataka")

            # 4. Preuzmi/spremi slike (zadatci sa slika_zadana=da)
            log("🖼️ Provjeravam zadatke sa zadanom slikom...")
            zadaci = preuzmi_i_spremi_slike(
                zadaci, izvor_naziv, mathpix_id, mathpix_key, drive_service, slike_folder_id, log=log
            )

            # 5. Upis u Sheet (s detekcijom duplikata)
            broj_dodanih, broj_azuriranih = nadopuni_ili_dodaj_zadatke(
                ws_zadaci, zadaci, izvor_tip, izvor_naziv, godina, razina, broj_pdf_ulaza, log=log
            )
            log(f"✅ {broj_dodanih} novih zadataka, {broj_azuriranih} nadopunjeno (duplikat)")

        except Exception as e:
            st.error(f"Greška tijekom obrade: {e}")
            st.stop()

    st.success(f"Gotovo! {broj_dodanih} novih zadataka dodano, {broj_azuriranih} nadopunjeno.")

    za_provjeru = [z for z in zadaci if z.get("status_provjere")]
    if za_provjeru:
        st.warning(f"⚠️ {len(za_provjeru)} zadataka označeno za ručnu provjeru:")
        for z in za_provjeru:
            st.write(f"- #{z.get('privremeni_broj')}: {z.get('status_provjere')}")

    st.markdown(f"[🔗 Otvori bazu u Google Sheets]({sheet.url})")


# ============================================================
# Stranica 2: Uredi zadatak (tekst/rješenje/uputa, kategorizacija, slika)
# ============================================================

@st.cache_data(ttl=300)
def _ucitaj_zadatke_za_pretragu():
    """Učitava sve zadatke (za pretragu/odabir) - keširano 5 min da ne udara
    Sheets API na svaki keystroke u polju za pretragu."""
    all_values = ws_zadaci.get_all_values()
    headers = all_values[0]
    return headers, all_values[1:]


def _get_polje(row, idx, col):
    i = idx.get(col)
    return row[i] if i is not None and i < len(row) else ""


@st.cache_data(ttl=600)
def _ucitaj_sifrarnik():
    """Šifrarnik cjelina (s pripadajućom kategorijom) i potpoglavlja po cjelini, za padajuće
    izbornike u sekciji kategorizacije na stranici 'Uredi zadatak' - keširano 10 min (šifrarnik
    se mijenja mnogo rjeđe nego sama baza zadataka, otud dulji ttl nego kod _ucitaj_zadatke_za_pretragu)."""
    return get_sifrarnik_cjelina(sheet), get_potpoglavlja_po_cjelini(sheet)


def _pretrazi_zadatke(headers, redovi, upit, max_rezultata=30):
    """Traži podudaranja po ID-u ili tekstu zadatka - koristi ga i stranica za slike
    i stranica za uređivanje teksta, da ne dupliciramo istu logiku pretrage."""
    idx = {h: i for i, h in enumerate(headers)}
    upit_lower = upit.strip().lower()
    podudaranja = [
        (broj_retka, row) for broj_retka, row in enumerate(redovi, start=2)
        if upit_lower in _get_polje(row, idx, "id").lower()
        or upit_lower in _get_polje(row, idx, "tekst_zadatka_latex").lower()
    ][:max_rezultata]
    return idx, podudaranja


def _oznaci_zadatak(par, idx):
    _, row = par
    ima_sliku = "🖼️ " if _get_polje(row, idx, "slika_putanja").strip() else "　 "
    fragment = _get_polje(row, idx, "tekst_zadatka_latex")[:70]
    return f"{ima_sliku}#{_get_polje(row, idx, 'id')} ({_get_polje(row, idx, 'cjelina')}) — {fragment}..."


def _odaberi_zadatak_pretragom(headers, redovi, kljuc_sufiks):
    """Pretraga + selectbox s jedinstvenim key-jevima (kljuc_sufiks) - koristi se kad na istoj
    stranici trebamo DVA neovisna birača zadatka (npr. usporedba A/B)."""
    upit = st.text_input("🔍 Pretraga", "", key=f"upit_{kljuc_sufiks}")
    if not upit.strip():
        return None, None, None
    idx, podudaranja = _pretrazi_zadatke(headers, redovi, upit)
    if not podudaranja:
        st.warning("Nema podudaranja.")
        return idx, None, None
    par = st.selectbox(
        "Odaberi", podudaranja, format_func=lambda p: _oznaci_zadatak(p, idx), key=f"odabir_{kljuc_sufiks}"
    )
    broj_retka, row = par
    return idx, broj_retka, row


_POLJA_ZA_KOPIRANJE = [
    "tekst_zadatka_latex", "tekst_zadatka_mathjax", "rjesenje", "rjesenje_status",
    "tip_rjesenja_izvor", "konacan_odgovor", "uputa", "slika_putanja", "slika_zadana",
    "ponudjeni_odgovori", "tip_zadatka", "video_url",
]


def _kopiraj_jedno_polje(polje, vrijednost, cilj_broj_retka):
    """Kopira SAMO JEDNO polje u ciljani redak. Za tekst_zadatka_latex usput uskladi i
    tekst_zadatka_mathjax (isti obrazac kao kod ostalih skripti za čišćenje)."""
    c = _col_letter(polje)
    ws_zadaci.update(range_name=f"{c}{cilj_broj_retka}", values=[[vrijednost]])
    if polje == "tekst_zadatka_latex":
        c_mj = _col_letter("tekst_zadatka_mathjax")
        novi_mathjax = vrijednost.replace("\\\\", "<br>")
        ws_zadaci.update(range_name=f"{c_mj}{cilj_broj_retka}", values=[[novi_mathjax]])


def _prikazi_usporedbu(headers, redovi):
    st.caption("Odaberi dva zadatka za vizualnu usporedbu - korisno za pronađene duplikate.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Zadatak A")
        idx, broj_a, row_a = _odaberi_zadatak_pretragom(headers, redovi, "usporedi_a")
    with col_b:
        st.subheader("Zadatak B")
        idx, broj_b, row_b = _odaberi_zadatak_pretragom(headers, redovi, "usporedi_b")

    if not (broj_a and broj_b):
        st.info("Odaberi oba zadatka (A i B) da vidiš usporedbu.")
        return

    if broj_a == broj_b:
        st.warning("Odabrao si isti zadatak na obje strane.")
        return

    def get(row, col):
        return _get_polje(row, idx, col)

    st.divider()
    st.caption(
        f"**A:** #{get(row_a, 'id')} ({get(row_a, 'cjelina')} / {get(row_a, 'potpoglavlje') or '—'})  "
        f"·  **B:** #{get(row_b, 'id')} ({get(row_b, 'cjelina')} / {get(row_b, 'potpoglavlje') or '—'})"
    )

    st.divider()
    st.subheader("Sadržajna polja — kopiraj pojedinačno strelicom")
    st.caption("Polja koja su prazna na obje strane se ne prikazuju. Klik na strelicu odmah upisuje u Sheet.")

    for polje in _POLJA_ZA_KOPIRANJE:
        vrijednost_a = get(row_a, polje)
        vrijednost_b = get(row_b, polje)
        if not vrijednost_a and not vrijednost_b:
            continue

        st.markdown(f"**{polje}**")
        c1, c2, c3 = st.columns([5, 1, 5])
        with c1:
            st.write(vrijednost_a if vrijednost_a else "—")
        with c2:
            if st.button("→", key=f"copy_ab_{polje}", help=f"Kopiraj {polje} iz A u B"):
                _kopiraj_jedno_polje(polje, vrijednost_a, broj_b)
                st.success(f"✅ {polje}: A → B")
                _ucitaj_zadatke_za_pretragu.clear()
                st.rerun()
            if st.button("←", key=f"copy_ba_{polje}", help=f"Kopiraj {polje} iz B u A"):
                _kopiraj_jedno_polje(polje, vrijednost_b, broj_a)
                st.success(f"✅ {polje}: B → A")
                _ucitaj_zadatke_za_pretragu.clear()
                st.rerun()
        with c3:
            st.write(vrijednost_b if vrijednost_b else "—")
        st.divider()

    st.subheader("Brisanje")
    c3, c4 = st.columns(2)
    if c3.button("🗑️ Obriši Zadatak A", key="obrisi_a"):
        st.session_state["potvrdi_brisanje"] = ("A", broj_a)
    if c4.button("🗑️ Obriši Zadatak B", key="obrisi_b"):
        st.session_state["potvrdi_brisanje"] = ("B", broj_b)

    if st.session_state.get("potvrdi_brisanje"):
        oznaka, broj_retka = st.session_state["potvrdi_brisanje"]
        st.warning(
            f"⚠️ Sigurno trajno obrisati Zadatak {oznaka} (redak {broj_retka})? "
            "Ova radnja se ne može poništiti iz aplikacije (Sheet ima Version History kao zadnju liniju obrane)."
        )
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ Da, obriši", key="potvrdi_obrisi", type="primary"):
            ws_zadaci.delete_rows(broj_retka)
            st.success(f"✅ Redak {broj_retka} obrisan.")
            st.session_state["potvrdi_brisanje"] = None
            _ucitaj_zadatke_za_pretragu.clear()
            st.rerun()
        if cc2.button("❌ Odustani", key="odustani_obrisi"):
            st.session_state["potvrdi_brisanje"] = None
            st.rerun()


def stranica_uredi_zadatak():
    st.title("✏️ Uredi zadatak")
    st.caption(
        "Pronađi zadatak i sve na jednom mjestu ispravi: tekst pitanja, rješenje, kratki "
        "odgovor, uputu (hint), kategoriju/cjelinu/potpoglavlje ako je zadatak pogrešno "
        "klasificiran, i sliku - bez pisanja posebnih skripti za rubne slučajeve."
    )

    if st.button("🔄 Osvježi popis zadataka", key="osvjezi_uredi"):
        _ucitaj_zadatke_za_pretragu.clear()

    headers, redovi = _ucitaj_zadatke_za_pretragu()

    usporedi = st.checkbox("🔀 Usporedi dva zadatka (npr. za pronalazak/spajanje duplikata)")
    if usporedi:
        _prikazi_usporedbu(headers, redovi)
        return

    upit = st.text_input("🔍 Pretraži po ID-u ili tekstu zadatka", "", key="upit_uredi")

    if not upit.strip():
        st.info("Upiši dio ID-a ili dio teksta zadatka da pronađeš zadatak koji želiš urediti.")
        return

    idx, podudaranja = _pretrazi_zadatke(headers, redovi, upit)

    def get(row, col):
        return _get_polje(row, idx, col)

    if not podudaranja:
        st.warning("Nema podudaranja. Pokušaj drugi pojam za pretragu.")
        return

    if len(podudaranja) == 30:
        st.caption("Prikazano prvih 30 podudaranja - suzi pretragu ako ne vidiš traženi zadatak.")

    broj_retka, row = st.selectbox(
        "Odaberi zadatak", podudaranja, format_func=lambda par: _oznaci_zadatak(par, idx), key="odabir_uredi"
    )

    st.caption(
        f"Kategorija: {get(row, 'kategorija') or '—'} · Cjelina: {get(row, 'cjelina') or '—'} · "
        f"Potpoglavlje: {get(row, 'potpoglavlje') or '—'} · Tip: {get(row, 'tip_zadatka') or '—'}"
    )

    with st.expander("👁️ Puni tekst zadatka (renderirano, ne sirovi LaTeX)", expanded=True):
        st.write(get(row, "tekst_zadatka_latex") or "*(prazno)*")
        if get(row, "rjesenje"):
            st.markdown("**Rješenje:**")
            st.write(get(row, "rjesenje"))
        if get(row, "konacan_odgovor"):
            st.markdown(f"**Konačan odgovor:** {get(row, 'konacan_odgovor')}")
        if get(row, "uputa"):
            st.markdown("**Uputa:**")
            st.write(get(row, "uputa"))

    # ------------------------------------------------------------------
    # Sekcija 1: Tekst / rješenje / uputa
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("📝 Tekst / rješenje / uputa")

    # key=f"..._{broj_retka}" - kad se promijeni odabrani zadatak, Streamlit tretira polja kao
    # NOVA (drugi key), pa se ispravno ponovno pune trenutnim vrijednostima iz Sheeta umjesto
    # da zadrže tekst ostavljen u polju za PRETHODNO odabrani zadatak.
    novi_tekst = st.text_area(
        "Tekst zadatka (tekst_zadatka_latex)", value=get(row, "tekst_zadatka_latex"),
        height=150, key=f"tekst_{broj_retka}",
    )
    st.caption(
        "✏️ Za uređivanje/provjeru LaTeX matematike: "
        "[CodeCogs Equation Editor](https://editor.codecogs.com/) — "
        "formula mora biti unutar `$...$` (npr. `$x^2-5x+6=0$`), inače se neće prikazati kao matematika."
    )
    novo_rjesenje = st.text_area(
        "Rješenje - puni postupak (rjesenje)", value=get(row, "rjesenje"),
        height=150, key=f"rjesenje_{broj_retka}",
    )
    novi_konacan_odgovor = st.text_input(
        "Konačan odgovor - kratka vrijednost (konacan_odgovor)", value=get(row, "konacan_odgovor"),
        key=f"konacan_{broj_retka}",
    )
    nova_uputa = st.text_area(
        "Uputa / naznaka za rješavanje (uputa - PreTeXt <hint>)", value=get(row, "uputa"),
        height=100, key=f"uputa_{broj_retka}",
        help="Prikazuje se kao poseban 'hint' blok u PreTeXt izlazu, odvojeno od punog rješenja.",
    )

    if st.button("💾 Spremi tekst/rješenje/uputu", type="primary", key=f"spremi_tekst_{broj_retka}"):
        novi_mathjax = novi_tekst.replace("\\\\", "<br>")
        c_tekst = _col_letter("tekst_zadatka_latex")
        c_mathjax = _col_letter("tekst_zadatka_mathjax")
        c_rjesenje = _col_letter("rjesenje")
        c_konacan = _col_letter("konacan_odgovor")
        c_uputa = _col_letter("uputa")
        c_status = _col_letter("rjesenje_status")

        azuriranja = [
            {"range": f"{c_tekst}{broj_retka}", "values": [[novi_tekst]]},
            {"range": f"{c_mathjax}{broj_retka}", "values": [[novi_mathjax]]},
            {"range": f"{c_rjesenje}{broj_retka}", "values": [[novo_rjesenje]]},
            {"range": f"{c_konacan}{broj_retka}", "values": [[novi_konacan_odgovor]]},
            {"range": f"{c_uputa}{broj_retka}", "values": [[nova_uputa]]},
        ]
        if novo_rjesenje.strip() and get(row, "rjesenje_status") != "sluzbeno":
            azuriranja.append({"range": f"{c_status}{broj_retka}", "values": [["sluzbeno"]]})

        with st.spinner("Spremam izmjene..."):
            try:
                ws_zadaci.batch_update(azuriranja)
            except Exception as e:
                st.error(f"Greška: {e}")
                st.stop()

        st.success(f"✅ Tekst/rješenje/uputa spremljeni za zadatak #{get(row, 'id')}.")
        _ucitaj_zadatke_za_pretragu.clear()
        st.markdown(f"[🔗 Otvori bazu u Google Sheets]({sheet.url})")

    # ------------------------------------------------------------------
    # Sekcija 2: Kategorija / cjelina / potpoglavlje (šifrarnik)
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🗂️ Kategorija / cjelina / potpoglavlje")
    st.caption(
        "Za slučaj kad je zadatak kod unosa svrstan u krivu cjelinu ili potpoglavlje - popisi "
        "ispod dolaze izravno iz šifrarnika (isti onaj kojim se Claude vodi kod klasifikacije "
        "novih zadataka), pa ispravak ostaje usklađen s ostatkom baze."
    )

    sifrarnik_kategorija_po_cjelini, sifrarnik_potpoglavlja_po_cjelini = _ucitaj_sifrarnik()

    cjelina_trenutna = get(row, "cjelina")
    cjelina_opcije = list(sifrarnik_kategorija_po_cjelini.keys())
    if cjelina_trenutna and cjelina_trenutna not in cjelina_opcije:
        # Stariji/ručni unos koji ne postoji (više) u šifrarniku - ubaci ga kao opciju da se ne
        # izgubi tiho, ali ga jasno označi upozorenjem ispod.
        cjelina_opcije = [cjelina_trenutna] + cjelina_opcije

    nova_cjelina = st.selectbox(
        "Cjelina", cjelina_opcije,
        index=cjelina_opcije.index(cjelina_trenutna) if cjelina_trenutna in cjelina_opcije else 0,
        key=f"cjelina_{broj_retka}",
    )
    if nova_cjelina not in sifrarnik_kategorija_po_cjelini:
        st.warning(
            f"⚠️ Cjelina '{nova_cjelina}' nije pronađena u šifrarniku (tab Sifrarnik_cjelina) - "
            "vjerojatno stariji/ručni unos. Odaberi ispravnu cjelinu iz popisa ako je ovo greška, "
            "ili je po potrebi prvo dodaj u šifrarnik."
        )

    nova_kategorija = sifrarnik_kategorija_po_cjelini.get(nova_cjelina, get(row, "kategorija"))
    st.caption(f"Kategorija (automatski prema šifrarniku): **{nova_kategorija or '—'}**")

    potpoglavlje_trenutno = get(row, "potpoglavlje")
    promijenjena_cjelina = nova_cjelina != cjelina_trenutna
    potpoglavlja_lista = [p for p, _ in sifrarnik_potpoglavlja_po_cjelini.get(nova_cjelina, [])]
    BEZ_POTPOGLAVLJA = "— (bez potpoglavlja)"
    potpoglavlje_opcije = [BEZ_POTPOGLAVLJA] + potpoglavlja_lista
    if not promijenjena_cjelina and potpoglavlje_trenutno and potpoglavlje_trenutno not in potpoglavlja_lista:
        potpoglavlje_opcije = [BEZ_POTPOGLAVLJA, potpoglavlje_trenutno] + potpoglavlja_lista

    if promijenjena_cjelina:
        potpoglavlje_index = 0
    elif potpoglavlje_trenutno and potpoglavlje_trenutno in potpoglavlje_opcije:
        potpoglavlje_index = potpoglavlje_opcije.index(potpoglavlje_trenutno)
    else:
        potpoglavlje_index = 0

    # key uključuje nova_cjelina - kod promjene cjeline Streamlit tretira ovaj selectbox kao
    # nov widget, pa se ne zadrži prijašnji odabir potpoglavlja koji možda ne pripada novoj cjelini.
    novo_potpoglavlje_odabir = st.selectbox(
        "Potpoglavlje", potpoglavlje_opcije, index=potpoglavlje_index,
        key=f"potpoglavlje_{broj_retka}_{nova_cjelina}",
    )
    if novo_potpoglavlje_odabir != BEZ_POTPOGLAVLJA and novo_potpoglavlje_odabir not in potpoglavlja_lista:
        st.warning(
            f"⚠️ Potpoglavlje '{novo_potpoglavlje_odabir}' nije u šifrarniku za cjelinu "
            f"'{nova_cjelina}' - vjerojatno stariji/ručni unos."
        )
    if not potpoglavlja_lista:
        st.caption("Napomena: ova cjelina trenutno nema definirana potpoglavlja u šifrarniku.")

    if st.button(
        "💾 Spremi kategoriju/cjelinu/potpoglavlje", type="primary", key=f"spremi_kategorizaciju_{broj_retka}"
    ):
        novo_potpoglavlje = "" if novo_potpoglavlje_odabir == BEZ_POTPOGLAVLJA else novo_potpoglavlje_odabir
        c_kategorija = _col_letter("kategorija")
        c_cjelina = _col_letter("cjelina")
        c_potpoglavlje = _col_letter("potpoglavlje")

        azuriranja = [
            {"range": f"{c_kategorija}{broj_retka}", "values": [[nova_kategorija]]},
            {"range": f"{c_cjelina}{broj_retka}", "values": [[nova_cjelina]]},
            {"range": f"{c_potpoglavlje}{broj_retka}", "values": [[novo_potpoglavlje]]},
        ]

        with st.spinner("Spremam kategorizaciju..."):
            try:
                ws_zadaci.batch_update(azuriranja)
            except Exception as e:
                st.error(f"Greška: {e}")
                st.stop()

        st.success(
            f"✅ Zadatak #{get(row, 'id')} sada je: {nova_kategorija} › {nova_cjelina}"
            f"{' › ' + novo_potpoglavlje if novo_potpoglavlje else ''}."
        )
        _ucitaj_zadatke_za_pretragu.clear()
        st.markdown(f"[🔗 Otvori bazu u Google Sheets]({sheet.url})")

    # ------------------------------------------------------------------
    # Sekcija 3: Slika
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🖼️ Slika")

    trenutna_slika = get(row, "slika_putanja").strip()
    slike_folder_id = st.secrets["SLIKE_FOLDER_ID"]

    if trenutna_slika:
        st.info(f"Ovaj zadatak već ima sliku: **{trenutna_slika}** — upload ispod će je zamijeniti.")
        if st.button("👁️ Prikaži trenutnu sliku", key=f"prikazi_{broj_retka}"):
            try:
                rezultat = drive_service.files().list(
                    q=f"name='{trenutna_slika}' and '{slike_folder_id}' in parents and trashed=false",
                    fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
                ).execute()
                datoteke = rezultat.get("files", [])
                if datoteke:
                    sadrzaj = drive_service.files().get_media(fileId=datoteke[0]["id"], supportsAllDrives=True).execute()
                    st.image(sadrzaj, caption=trenutna_slika, width=400)
                else:
                    st.warning("Slika nije pronađena u 02_SLIKE folderu na Driveu (možda stari/neispravan zapis).")
            except Exception as e:
                st.error(f"Neuspjelo dohvaćanje slike: {e}")
    else:
        st.caption("Ovaj zadatak trenutno nema sliku.")

    nova_slika = st.file_uploader(
        "Nova slika", type=["png", "jpg", "jpeg", "gif", "webp"], key=f"upload_{broj_retka}"
    )

    if not nova_slika:
        return

    st.image(nova_slika, caption="Pregled prije spremanja", width=400)

    if st.button("💾 Spremi sliku za ovaj zadatak", type="primary", key=f"spremi_{broj_retka}"):
        ekstenzija = os.path.splitext(nova_slika.name)[1].lower() or ".png"
        naziv_datoteke = f"{get(row, 'id')}{ekstenzija}"
        mime, _ = mimetypes.guess_type(nova_slika.name)

        with st.spinner("Spremam sliku i ažuriram bazu..."):
            try:
                upload_image_to_drive(
                    drive_service, slike_folder_id, naziv_datoteke,
                    nova_slika.getvalue(), mimetype=mime or "image/png",
                )
                c_putanja = _col_letter("slika_putanja")
                c_zadana = _col_letter("slika_zadana")
                ws_zadaci.update(range_name=f"{c_putanja}{broj_retka}", values=[[naziv_datoteke]])
                ws_zadaci.update(range_name=f"{c_zadana}{broj_retka}", values=[["da"]])
            except Exception as e:
                st.error(f"Greška: {e}")
                st.stop()

        st.success(f"✅ Slika spremljena kao `{naziv_datoteke}` i povezana sa zadatkom #{get(row, 'id')}.")
        _ucitaj_zadatke_za_pretragu.clear()
        st.markdown(f"[🔗 Otvori bazu u Google Sheets]({sheet.url})")


# ============================================================
# Stranica 3: Zadaci za provjeru (status_provjere nije prazan)
# ============================================================

def stranica_zadaci_za_provjeru():
    st.title("🔍 Zadaci za provjeru")
    st.caption(
        "Zadaci koje je Claude označio za ručnu provjeru tijekom OCR-a/strukturiranja "
        "(npr. nesiguran simbol, nečitko napisan broj). Nakon što provjeriš i po potrebi "
        "ispraviš zadatak (na stranici 'Uredi zadatak'), klikni '✅ Provjereno' da skineš oznaku."
    )

    if st.button("🔄 Osvježi popis", key="osvjezi_provjera"):
        _ucitaj_zadatke_za_pretragu.clear()

    headers, redovi = _ucitaj_zadatke_za_pretragu()
    idx = {h: i for i, h in enumerate(headers)}

    def get(row, col):
        return _get_polje(row, idx, col)

    za_provjeru = [
        (broj_retka, row) for broj_retka, row in enumerate(redovi, start=2)
        if get(row, "status_provjere").strip()
    ]

    if not za_provjeru:
        st.success("🎉 Trenutno nema zadataka za provjeru.")
        return

    st.info(f"Pronađeno **{len(za_provjeru)}** zadataka za provjeru.")

    for broj_retka, row in za_provjeru:
        naslov = f"⚠️ {get(row, 'id') or f'redak {broj_retka}'} — {get(row, 'status_provjere')}"
        with st.expander(naslov):
            st.caption(
                f"Cjelina: {get(row, 'cjelina') or '—'} · Potpoglavlje: {get(row, 'potpoglavlje') or '—'} · "
                f"Tip: {get(row, 'tip_zadatka') or '—'}"
            )
            st.write(get(row, "tekst_zadatka_latex") or "*(prazno)*")
            if get(row, "rjesenje"):
                st.markdown("**Rješenje:**")
                st.write(get(row, "rjesenje"))
            if get(row, "konacan_odgovor"):
                st.markdown(f"**Konačan odgovor:** {get(row, 'konacan_odgovor')}")

            st.caption(
                f"Za ispravak teksta/rješenja: kopiraj ID `{get(row, 'id')}` i pretraži ga "
                "na stranici '✏️ Uredi zadatak'."
            )

            if st.button("✅ Provjereno", type="primary", key=f"provjereno_{broj_retka}"):
                c_status = _col_letter("status_provjere")
                with st.spinner("Ažuriram..."):
                    try:
                        ws_zadaci.update(range_name=f"{c_status}{broj_retka}", values=[[""]])
                    except Exception as e:
                        st.error(f"Greška: {e}")
                        st.stop()
                st.success(f"✅ Označeno kao provjereno: {get(row, 'id')}")
                _ucitaj_zadatke_za_pretragu.clear()
                st.rerun()


# ============================================================
# Navigacija
# ============================================================

stranica = st.sidebar.radio(
    "Stranica",
    [
        "📄 Obradi novi ispit",
        "✏️ Uredi zadatak",
        "🔍 Zadaci za provjeru",
    ],
)

if stranica == "📄 Obradi novi ispit":
    stranica_obradi_ispit()
elif stranica == "✏️ Uredi zadatak":
    stranica_uredi_zadatak()
else:
    stranica_zadaci_za_provjeru()
