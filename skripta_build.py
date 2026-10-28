"""
CAKI Matematika - skripta_build.py (11.-12.10.2026.)

BEZGLAVNI (bez Streamlita/Colaba) radnik koji gradi PDF skripte. Pokrece ga GitHub Actions
(.github/workflows/skripta.yml) kad netko na stranici "Skripta" klikne "Izgradi PDF":

    python skripta_build.py --zahtjev-id <id>

Koraci: (1) procita zahtjev iz taba Skripta_zahtjevi, (2) ucita zadatke iz taba Zadaci i primijeni
filtre, (3) skine potrebne slike iz Drive foldera 02_SLIKE, (4) izgradi PreTeXt XML i PDF (xelatex),
(5) uploada PDF u Drive folder SKRIPTE_FOLDER_ID, (6) upise status u Sheet (cekanje -> u_radu ->
gotovo | greska). Streamlit cita status iz Sheeta i nudi PDF - GitHub NIKAD ne drzi PDF ni sadrzaj
zadataka (repo je javan, pa se u log ISPISUJE SAMO broj zadataka i status, nikad tekst zadatka).

Tajne dolaze ISKLJUCIVO iz varijabli okruzenja (GitHub Secrets): GOOGLE_SERVICE_ACCOUNT_JSON,
SHEET_ID, SLIKE_FOLDER_ID, SKRIPTE_FOLDER_ID.
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import baza_zadataka_pipeline as bp

# --- Izgled PDF-a (12.10.2026.) ---
# Namjena: OBOSTRANI ispis na A4, ZICANI uvez po DULJEM rubu, sto manje papira.
# - dva stupca, malo slovo (FONT_PT), uske margine osim UNUTARNJE (za uvez): inner veci od outer,
#   pa je uvez uvijek na pravoj strani i na prednjoj i na straznjoj strani lista
# - kompaktan naslovni blok (naslov + podnaslov lijevo, autor/datum/legenda desno), bez posebne
#   naslovnice; bez zaglavlja; podnozje s brojem stranice na VANJSKOM rubu
# - rjesenja na kraju (backmatter/solutions), tezina slovima L/S/T
# Stil se dodaje kroz vlastiti XSL (STIL_XSL) koji nadograduje standardni PreTeXt LaTeX XSL
# i samo upisuje dodatnu LaTeX preambulu (parametar latex.preamble.late).
STUPCI = 2     # 1 = jedan stupac, 2 = dva stupca (ako slike prave probleme, vrati na 1)
FONT_PT = 9    # velicina slova: 8, 9, 10, 11 ili 12 (10 = ugodnije za citanje, ~15% vise papira)
MARGINE = "a4paper,inner=1.9cm,outer=1.0cm,top=1.1cm,bottom=1.5cm,footskip=0.65cm,columnsep=0.5cm"

PUBLICATION_PTX = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<publication>\n  <source>\n'
    '    <directories generated="../generated-assets"/>\n'
    '  </source>\n'
    '  <common>\n'
    # zadaci u tekstu bez rjesenja (rjesenja idu u poglavlje "Rjesenja" na kraju)
    '    <exercise-divisional statement="yes" hint="yes" answer="no" solution="no"/>\n'
    '  </common>\n'
    f'  <latex font-size="{FONT_PT}" sides="two">\n'
    f'    <page><geometry>{MARGINE}</geometry></page>\n'
    '  </latex>\n'
    '  <html/>\n</publication>\n'
)
PROJECT_PTX = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<project ptx-version="2">\n  <targets>\n'
    '    <target name="html" format="html"/>\n'
    '    <target name="pdf" format="pdf" pdf-method="xelatex" xsl="skripta_stil.xsl"/>\n'
    '  </targets>\n</project>\n'
)

# LaTeX preambula (kasna, iza svih PreTeXt definicija pa ih smije prepisati).
# %%LEGENDA%% i %%STUPCI%% zamjenjuje stil_xsl().
STIL_PREAMBULA = r"""
%% ===== CAKI stil skripte (kompaktno, obostrani ispis) =====
\usepackage{xcolor}
\definecolor{cakiplava}{HTML}{1F4E79}
\definecolor{cakisiva}{HTML}{6B7280}
\usepackage{polyglossia}
\setmainlanguage{croatian}
\usepackage{fancyhdr}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
\fancypagestyle{plain}{\fancyhf{}%
  \fancyfoot[LE,RO]{\footnotesize\color{cakisiva}\thepage}%
  \fancyfoot[RE,LO]{\footnotesize\color{cakisiva}Caki Centar \textperiodcentered{} cakipoduka.com}}
\pagestyle{plain}
\setlength{\columnsep}{0.5cm}
\setlength{\columnseprule}{0.2pt}
\setlength{\medskipamount}{2pt plus 1pt minus 1pt}
\hypersetup{linkcolor=cakiplava,urlcolor=cakiplava,citecolor=cakiplava}
\renewcommand{\ptxtriangle}{}
\tcbset{exercisespacingstyle/.style={before skip={1.1ex plus 0.3ex}}}
\makeatletter
\renewcommand{\thispagestyle}[1]{}% PreTeXt gasi podnozje 1. stranice; ovdje ga zelimo
\newcommand{\cakipodnaslov}{\par\vspace{0.2ex}\normalfont\color{cakisiva}}
\renewcommand{\maketitle}{%
  \ifnum%%STUPCI%%=2 \twocolumn[{\fi
  \noindent\begin{minipage}[b]{0.58\linewidth}
    {\color{cakiplava}\Large\bfseries\let\\\cakipodnaslov\@title\par}
  \end{minipage}\hfill
  \begin{minipage}[b]{0.40\linewidth}\raggedleft\footnotesize\color{cakisiva}
    \@author\par\today\par {}%%LEGENDA%%\par
  \end{minipage}\par\vspace{0.3ex}
  {\color{cakiplava}\rule{\linewidth}{0.7pt}}\vspace{0.8ex}
  \ifnum%%STUPCI%%=2 }]\fi}
\makeatother
\titleformat{\section}[hang]{\normalfont\large\bfseries\color{cakiplava}}{\thesection}{0.5em}{#1}
\titlespacing*{\section}{0pt}{1.4ex plus 0.4ex}{0.6ex}
\titleformat{\subsection}[hang]{\normalfont\normalsize\bfseries\color{cakiplava}}{\thesubsection}{0.5em}{#1}
\titlespacing*{\subsection}{0pt}{1.0ex plus 0.3ex}{0.2ex}
%% naslov "Zadaci" ispod svakog potpoglavlja je suvisan (svaki zadatak ima svoj naslov) - ne ispisuje se
\DeclareDocumentEnvironment{exercises-subsection-numberless}{mmmmmmm}{}{}
\DeclareDocumentEnvironment{exercises-subsubsection-numberless}{mmmmmmm}{}{}
%% rjesenja na kraju: sitnije slovo i gusto (to je referentni dio, ne gradivo)
\tcbset{divisionsolutionstyle/.style={bwminimalstyle, runintitlestyle, before skip={0.5ex plus 0.2ex}, after title={\space}, breakable, before upper app={\ptxsetparstyle}}}
\RenewDocumentEnvironment{solutions-section}{mmmmmmm}
{\renewcommand{\divisionnameptx}{#1}\renewcommand{\titleptx}{#2}\renewcommand{\subtitleptx}{#3}%
 \renewcommand{\shortitleptx}{#4}\renewcommand{\authorsptx}{#5}\renewcommand{\epigraphptx}{#6}%
 \section[{#4}]{#2}\label{#7}\footnotesize}{}
\tcbset{divisionexercisestyle/.style={bwminimalstyle, runintitlestyle, exercisespacingstyle, left=0pt, breakable, before upper app={\ptxsetparstyle}}}
\renewtcolorbox{divisionexercise}[4]{divisionexercisestyle,
  before title={\textbf{\color{cakiplava}Zadatak \ifnum\value{subsection}>0 \thesubsection\else\thesection\fi.#1.}\enspace},
  title={\notblank{#2}{#2}{}}, after title={\notblank{#2}{\space}{}},
  phantom={\hypertarget{#4}{}},
  after={\notblank{#3}{\par\rule{\ptxworkspacestrutwidth}{#3}\par\vfill}{\par}}}
"""

STIL_XSL = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">\n'
    '  <xsl:import href="./core/pretext-latex.xsl"/>\n'
    '  <xsl:param name="latex.preamble.late"><xsl:text>%%PREAMBULA%%</xsl:text></xsl:param>\n'
    '</xsl:stylesheet>\n'
)


def stil_xsl(stupci: int = None) -> str:
    """Vraca sadrzaj custom XSL-a sa stilom (legenda i broj stupaca umetnuti, XML-escapeano)."""
    from xml.sax.saxutils import escape
    n = STUPCI if stupci is None else stupci
    preambula = STIL_PREAMBULA.replace("%%LEGENDA%%", bp.TEZINA_LEGENDA).replace("%%STUPCI%%", str(int(n)))
    return STIL_XSL.replace("%%PREAMBULA%%", escape(preambula))


class SkriptaGreska(Exception):
    """Greska s KRATKOM porukom sigurnom za upis u Sheet (bez sadrzaja zadataka)."""


def napisi_pretext_projekt(korijen: str, xml: str, slike_dir: str) -> None:
    """Postavlja mini PreTeXt projekt (isti obrazac kao Colab 3.2.1b/3.2.6)."""
    for d in ("source", "publication", "external", "generated-assets"):
        os.makedirs(os.path.join(korijen, d), exist_ok=True)
    with open(os.path.join(korijen, "source", "main.ptx"), "w", encoding="utf-8") as f:
        f.write(xml)
    with open(os.path.join(korijen, "publication", "publication.ptx"), "w", encoding="utf-8") as f:
        f.write(PUBLICATION_PTX)
    with open(os.path.join(korijen, "project.ptx"), "w", encoding="utf-8") as f:
        f.write(PROJECT_PTX)
    os.makedirs(os.path.join(korijen, "xsl"), exist_ok=True)
    with open(os.path.join(korijen, "xsl", "skripta_stil.xsl"), "w", encoding="utf-8") as f:
        f.write(stil_xsl())
    cilj = os.path.join(korijen, "external", "images")
    if os.path.exists(cilj):
        shutil.rmtree(cilj)
    shutil.copytree(slike_dir, cilj)


def skini_slike(drive, folder_id: str, nazivi, odrediste: str) -> int:
    """Skida iz Drive foldera `folder_id` samo slike s danim nazivima. Vraca broj skinutih.
    Slika koje nema u folderu nema smisla prekidati zbog njih - samo se preskoce (PreTeXt build
    ih ionako ne ukljucuje, isto kao u Colabu)."""
    from googleapiclient.http import MediaIoBaseDownload
    os.makedirs(odrediste, exist_ok=True)
    skinuto = 0
    for naziv in sorted({n for n in nazivi if n}):
        q_naziv = naziv.replace("\\", "\\\\").replace("'", "\\'")
        odgovor = drive.files().list(
            q=f"name='{q_naziv}' and '{folder_id}' in parents and trashed=false",
            fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        datoteke = odgovor.get("files", [])
        if not datoteke:
            continue
        zahtjev = drive.files().get_media(fileId=datoteke[0]["id"], supportsAllDrives=True)
        buf = io.BytesIO()
        preuzimac = MediaIoBaseDownload(buf, zahtjev)
        gotovo = False
        while not gotovo:
            _, gotovo = preuzimac.next_chunk()
        with open(os.path.join(odrediste, os.path.basename(naziv)), "wb") as f:
            f.write(buf.getvalue())
        skinuto += 1
    return skinuto


def izvuci_latex_greske(tekst: str, najvise: int = 8) -> str:
    """Iz izlaza `pretext build pdf` izvuce samo LaTeX greske ('! ...') i broj retka ('l.NNN'),
    bez teksta izvora (da javni log ne sadrzi sadrzaj zadataka)."""
    greske, zadnja = [], None
    for linija in (tekst or "").splitlines():
        if linija.startswith("! "):
            zadnja = linija[:120]
        elif zadnja is not None:
            m = re.match(r"l\.(\d+)", linija)
            if m:
                greske.append(zadnja + "  (main.tex, redak " + m.group(1) + ")")
                zadnja = None
    if zadnja is not None:
        greske.append(zadnja)
    if not greske:
        greske = [l[:160] for l in (tekst or "").strip().splitlines()[-4:]]
    return "LaTeX greske:\n" + "\n".join(greske[:najvise])


def pokreni_pretext_pdf(korijen: str, izvrsi=subprocess.run) -> str:
    """Pokrece `pretext build pdf` i vraca putanju do PDF-a (SkriptaGreska ako ne uspije).
    `izvrsi` je zamjenjiv radi testiranja."""
    r = izvrsi(["pretext", "build", "pdf"], cwd=korijen, capture_output=True, text=True, timeout=1500)
    pdfovi = glob.glob(os.path.join(korijen, "output", "pdf", "*.pdf"))
    if r.returncode != 0 or not pdfovi:
        # u log (javan na GitHubu) idu samo LaTeX poruke o greskama + broj retka u main.tex,
        # NIKAD sadrzaj zadataka
        print(izvuci_latex_greske((r.stdout or "") + "\n" + (r.stderr or "")))
        raise SkriptaGreska("Gradnja PDF-a nije uspjela (pogledaj log GitHub Actions).")
    return pdfovi[0]


def uploadaj_pdf(drive, folder_id: str, putanja_pdf: str, naziv: str) -> str:
    from googleapiclient.http import MediaIoBaseUpload
    with open(putanja_pdf, "rb") as f:
        media = MediaIoBaseUpload(io.BytesIO(f.read()), mimetype="application/pdf")
    kreirano = drive.files().create(
        body={"name": naziv, "parents": [folder_id]}, media_body=media,
        fields="id", supportsAllDrives=True,
    ).execute()
    return kreirano["id"]


def naziv_pdfa(zahtjev: dict) -> str:
    opis = (zahtjev.get("naslov") or "").strip() or bp.opis_filtara(zahtjev.get("filtri"))
    opis = opis.translate(str.maketrans("\u010d\u0107\u017e\u0161\u0111\u010c\u0106\u017d\u0160\u0110", "cczsdCCZSD"))
    sigurno = re.sub(r"[^A-Za-z0-9_-]+", "_", opis).strip("_")[:60] or "skripta"
    return f"skripta_{zahtjev.get('zahtjev_id', '')}_{sigurno}.pdf"


def izgradi(zahtjev_id: str, sheet, drive, slike_folder_id: str, skripte_folder_id: str,
            radni_dir: str, pdf_builder=pokreni_pretext_pdf) -> str:
    """Cijeli tijek za jedan zahtjev. Vraca Drive ID uploadanog PDF-a. Statuse upisuje u Sheet."""
    zahtjev = bp.nadji_zahtjev_skripte(sheet, zahtjev_id)
    if not zahtjev:
        raise SkriptaGreska(f"Zahtjev {zahtjev_id} nije pronadjen u Skripta_zahtjevi.")
    bp.azuriraj_status_zahtjeva(sheet, zahtjev_id, "u_radu")
    try:
        vr = sheet.worksheet("Zadaci").get_all_values()
        redovi = [dict(zip(vr[0], r)) for r in vr[1:]]
        odabrani = bp.filtriraj_zadatke(redovi, zahtjev["filtri"])
        if not odabrani:
            raise SkriptaGreska("Nijedan zadatak ne zadovoljava filtre.")
        slike_dir = os.path.join(radni_dir, "slike_izvor")
        # Slike zadatka (slika_putanja) I slike rješenja (slika_rjesenje_putanja, neobavezan stupac).
        potrebne_slike = [x for r in odabrani
                          for polje in ("slika_putanja", "slika_rjesenje_putanja")
                          for x in bp.razdvoji_slike(r.get(polje))]
        skinuto = skini_slike(drive, slike_folder_id, potrebne_slike, slike_dir)
        images_izlaz = os.path.join(radni_dir, "images_izlaz")
        os.makedirs(images_izlaz, exist_ok=True)
        # 28.10.2026.: kronoloski build (po poglavlju izvora, za materijal uvezen preko
        # "Uvoz iz foldera" - Caki) umjesto standardnog, po kurikulumskoj cjelini - v.
        # grupiraj_po_poglavlju u filtriraj_zadatke_za_skriptu.normaliziraj_filtre i
        # bp.izgradi_skriptu_xml_kronoloski. Zahtjev bira granu, sve ostalo (slike, upload,
        # status u Sheetu) ostaje identicno za oba puta.
        if bp.normaliziraj_filtre(zahtjev.get("filtri")).get("grupiraj_po_poglavlju"):
            xml, _, n, _ = bp.izgradi_skriptu_xml_kronoloski(
                redovi, zahtjev, bp.get_naslovi_poglavlja(sheet), images_izlaz, slike_dir)
        else:
            xml, _, n, _ = bp.izgradi_skriptu_xml(
                redovi, zahtjev, bp.get_potpoglavlja_po_cjelini(sheet), images_izlaz, slike_dir,
                teorija_po_potpoglavlju=bp.get_teorija_po_potpoglavlju(sheet))
        print(f"Zadataka: {n}, slika skinuto: {skinuto}")
        projekt = os.path.join(radni_dir, "pretext")
        napisi_pretext_projekt(projekt, xml, images_izlaz)
        pdf = pdf_builder(projekt)
        pdf_id = uploadaj_pdf(drive, skripte_folder_id, pdf, naziv_pdfa(zahtjev))
        bp.azuriraj_status_zahtjeva(sheet, zahtjev_id, "gotovo", f"{n} zadataka", pdf_id)
        print("Gotovo.")
        return pdf_id
    except SkriptaGreska as e:
        bp.azuriraj_status_zahtjeva(sheet, zahtjev_id, "greska", str(e))
        raise
    except Exception as e:  # noqa: BLE001 - u Sheet ide samo tip greske, ne detalji
        bp.azuriraj_status_zahtjeva(sheet, zahtjev_id, "greska", f"Neocekivana greska ({type(e).__name__}).")
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zahtjev-id", required=True)
    args = ap.parse_args(argv)
    # Jasna poruka ako tajna nedostaje (ispisuje se SAMO ime, nikad vrijednost)
    potrebne = ["GOOGLE_SERVICE_ACCOUNT_JSON", "SHEET_ID", "SLIKE_FOLDER_ID", "SKRIPTE_FOLDER_ID"]
    # Cesta greska pri unosu GitHub tajni: razmak/novi red/navodnici oko ID-a -> ocisti
    for n in potrebne:
        v = os.environ.get(n, "").strip()
        if n != "GOOGLE_SERVICE_ACCOUNT_JSON":
            v = v.strip("'\" ")
        os.environ[n] = v
    nedostaju = [n for n in potrebne if not os.environ.get(n, "").strip()]
    if nedostaju:
        print("GRESKA: nedostaju GitHub tajne: " + ", ".join(nedostaju))
        return 1
    try:
        sa_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    except ValueError:
        print("GRESKA: GOOGLE_SERVICE_ACCOUNT_JSON nije ispravan JSON (zalijepi samo dio od { do }, bez navodnika).")
        return 1
    print(f"Zahtjev: {args.zahtjev_id}")
    try:
        sheet = bp.get_gspread_client(sa_info).open_by_key(os.environ["SHEET_ID"])
        drive = bp.get_drive_service(sa_info)
        with tempfile.TemporaryDirectory() as radni:
            izgradi(args.zahtjev_id, sheet, drive, os.environ["SLIKE_FOLDER_ID"],
                    os.environ["SKRIPTE_FOLDER_ID"], radni)
    except SkriptaGreska as e:
        print(f"GRESKA: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 - tip greske pomaze, detalji mogu sadrzavati podatke
        print(f"GRESKA: neocekivana greska ({type(e).__name__}): {str(e)[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
