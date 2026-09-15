"""
CAKI Matematika - teorija_markup.py

Lagana konvencija za pisanje teorije u tekst_teorije_latex polju (Teorija_potpoglavlja
sheet), koja se pretvara u PreTeXt oznake pri generiranju (Korak 3.1) i koristi se i za
preview u Streamlit stranici (pages/3_teorija.py). Cilj: Caki i dalje samo tipka tekst u
jedno polje, bez posebnog sučelja za svaku značajku.

KONVENCIJE ZA TIPKANJE (koriste se izravno u textarea polju, mogu se slobodno miješati):

    !!vazan tekst ili formula!!
        -> <alert>vazan tekst ili formula</alert>
           Isticanje (npr. crvenom bojom). Boja/stil se definira JEDNOM u PreTeXt CSS-u
           (css theme override, isto mjesto gdje su vec definirane primary/secondary
           boje), ne ovdje - ovaj modul samo stavlja ispravnu PreTeXt oznaku.

    \\pojam{Naziv pojma}
        -> <term>Naziv pojma</term>
           PreTeXt native oznaka za definiran pojam. Ista oznaka se koristi i za
           automatsko generiranje pojmovnika - vidi generiraj_pojmovnik.py.

    [RJESENJE]
    ... postupak rjesavanja (moze imati vise odlomaka) ...
    [/RJESENJE]
        Markeri MORAJU biti na svom vlastitom retku (prazan redak prije/poslije nije
        obavezan). Blok se u "ucenik" verziji u POTPUNOSTI izbacuje. U "profesor"
        verziji ostaje prikazan, umotan u <remark><title>Rjesenje</title>...</remark>.

Sve tri konvencije rade neovisno i mogu se kombinirati u istom odlomku, pa i unutar
[RJESENJE] bloka (npr. istaknuta formula unutar rjesenja).
"""
import re

_ALERT_RE = re.compile(r"!!(.+?)!!", re.DOTALL)
_POJAM_RE = re.compile(r"\\pojam\{(.+?)\}")
_RJESENJE_BLOCK_RE = re.compile(r"\[RJESENJE\]\s*\n(.*?)\n\[/RJESENJE\]", re.DOTALL)

VERZIJE = ("ucenik", "profesor")


def _provjeri_verziju(verzija: str) -> None:
    if verzija not in VERZIJE:
        raise ValueError(f"verzija mora biti jedna od {VERZIJE}, dobiveno: {verzija!r}")


def _zamijeni_inline_oznake(tekst: str) -> str:
    """!!...!! -> <alert>...</alert>, \\pojam{...} -> <term>...</term>."""
    tekst = _ALERT_RE.sub(r"<alert>\1</alert>", tekst)
    tekst = _POJAM_RE.sub(r"<term>\1</term>", tekst)
    return tekst


def _segmentiraj(tekst: str):
    """Rastavlja sirovi tekst na naizmjenične segmente ('tekst', sadržaj) i
    ('rjesenje', sadržaj), redoslijedom kojim se pojavljuju u izvoru."""
    segmenti = []
    pozicija = 0
    for match in _RJESENJE_BLOCK_RE.finditer(tekst):
        if match.start() > pozicija:
            segmenti.append(("tekst", tekst[pozicija:match.start()]))
        segmenti.append(("rjesenje", match.group(1)))
        pozicija = match.end()
    if pozicija < len(tekst):
        segmenti.append(("tekst", tekst[pozicija:]))
    return segmenti


def _odlomci(fragment: str):
    """Dijeli fragment na odlomke po praznom retku (isto pravilo kao dosad)."""
    return [o.strip() for o in fragment.split("\n\n") if o.strip()]


def teorija_u_ptx_odlomke(tekst: str, verzija: str = "ucenik") -> list:
    """Pretvara sirovi tekst_teorije_latex u listu PreTeXt sadržaja (odlomci kao goli
    <p> sadržaj bez omota - taj dio ostaje postojećoj _build_introduction_lines funkciji
    da se ništa što već radi ne dira; <remark> blokovi za rješenja dolaze već potpuno
    omotani, spremni za izravno umetanje).

    verzija="ucenik"   (zadano) - [RJESENJE] blokovi se PRESKAČU u cijelosti.
    verzija="profesor"           - [RJESENJE] blokovi ostaju, umotani u <remark>.
    """
    _provjeri_verziju(verzija)
    rezultat = []
    for vrsta, sadrzaj in _segmentiraj(tekst):
        if vrsta == "tekst":
            rezultat.extend(_zamijeni_inline_oznake(o) for o in _odlomci(sadrzaj))
        elif verzija == "profesor":
            unutarnji_p = "\n".join(
                f"<p>{_zamijeni_inline_oznake(o)}</p>" for o in _odlomci(sadrzaj)
            )
            if unutarnji_p:
                rezultat.append(f"<remark><title>Rjesenje</title>\n{unutarnji_p}\n</remark>")
        # verzija == "ucenik" i vrsta == "rjesenje" -> namjerno se ništa ne dodaje
    return rezultat


def ukloni_markup_za_pregled(tekst: str, verzija: str = "ucenik") -> str:
    """Čitljiv preview BEZ generiranja PreTeXt-a - koristi se u Streamlit stranici da
    Caki odmah vidi kako će tekst izgledati za odabranu verziju, prije spremanja.
    !! -> **, \\pojam{} -> *naziv*, [RJESENJE] blok (u profesor prikazu) dobiva prefiks."""
    _provjeri_verziju(verzija)
    dijelovi = []
    for vrsta, sadrzaj in _segmentiraj(tekst):
        if vrsta == "tekst":
            dijelovi.extend(_citljivo(o) for o in _odlomci(sadrzaj))
        elif verzija == "profesor":
            for o in _odlomci(sadrzaj):
                dijelovi.append(f"🔒 RJEŠENJE: {_citljivo(o)}")
        # ucenik + rjesenje segment -> preskace se, isto kao u stvarnom PreTeXt izlazu
    return "\n\n".join(dijelovi)


def _citljivo(odlomak: str) -> str:
    odlomak = _ALERT_RE.sub(r"**\1**", odlomak)
    odlomak = _POJAM_RE.sub(r"*\1*", odlomak)
    return odlomak
