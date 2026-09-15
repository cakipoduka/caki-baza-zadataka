"""
CAKI Matematika - teorija_markup.py

Lagana konvencija za pisanje teorije u tekst_teorije_latex polju (Teorija_potpoglavlja
sheet), koja se pretvara u PreTeXt oznake pri generiranju (Korak 3.1, vidi
_build_introduction_lines u baza_zadataka_pipeline.py) i koristi se i za preview u
Streamlit stranici (pages/3_teorija.py). Cilj: Caki i dalje samo tipka tekst u jedno
polje, bez posebnog sučelja za svaku značajku.

KONVENCIJE ZA TIPKANJE (koriste se izravno u textarea polju, mogu se slobodno miješati):

    !!vazan tekst ili formula!!
        -> <alert>vazan tekst ili formula</alert>
           Isticanje (npr. crvenom bojom). Boja/stil se definira JEDNOM u PreTeXt CSS-u
           (css theme override, isto mjesto gdje su vec definirane primary/secondary
           boje), ne ovdje - ovaj modul samo stavlja ispravnu PreTeXt oznaku.

    \\pojam{Naziv pojma}
        -> <term>Naziv pojma</term>
           PreTeXt native oznaka za definiran pojam. Ista oznaka se koristi i za
           automatsko generiranje pojmovnika - vidi generiraj_pojmovnik.py. VAZNO: omotaj
           SAM NAZIV pojma, ne formulu iza njega (npr. \\pojam{Nultočka funkcije} je ...,
           ne \\pojam{f(x)=0}).

    [RJESENJE]
    ... postupak rjesavanja (moze imati vise odlomaka) ...
    [/RJESENJE]
        Markeri MORAJU biti na svom vlastitom retku. Blok se u "ucenik" verziji u
        POTPUNOSTI izbacuje. U "profesor" verziji ostaje prikazan, umotan u
        <remark><title>Rjesenje</title>...</remark>.

Sve tri konvencije rade neovisno i mogu se kombinirati u istom odlomku, pa i unutar
[RJESENJE] bloka (npr. istaknuta formula unutar rjesenja).

VAZNO O REDOSLIJEDU OBRADE (14.9.2026., ispravak): ova datoteka NAMJERNO ne radi XML
escaping niti $...$ -> <m>...</m> konverziju sama - to i dalje radi POSTOJECA
_pretext_text funkcija u baza_zadataka_pipeline.py. Razlog: kad bi ovaj modul prvo umetnuo
<alert>/<term> oznake, a _pretext_text se PRIMIJENIO NAKNADNO na cijeli rezultat,
_xml_escape bi te vec ispravne '<' i '>' znakove ponovno eskejpao (dobili bismo vidljivi
"&lt;alert&gt;" u izlazu umjesto stvarnog isticanja). Zato svaka funkcija ovdje prima
`render` - funkciju koja se primjenjuje ISKLJUCIVO na OBICAN tekst (izvan markera), a
<alert>/<term>/<remark> omoti se umecu KAO GOTOVA XML OZNAKA, nakon sto je unutarnji
tekst vec proso kroz render(). Pozivatelj u pipelineu prosljeduje _pretext_text kao
render; Streamlit preview (ukloni_markup_za_pregled) render uopce ne treba (zadano:
identity funkcija), jer prikazuje obican tekst, ne PreTeXt XML.
"""
import re

_KOMBINIRANI_INLINE_RE = re.compile(r"!!(?P<alert>.+?)!!|\\pojam\{(?P<pojam>[^}]+)\}", re.DOTALL)
_RJESENJE_BLOCK_RE = re.compile(r"\[RJESENJE\]\s*\n(.*?)\n\[/RJESENJE\]", re.DOTALL)

VERZIJE = ("ucenik", "profesor")


def _provjeri_verziju(verzija: str) -> None:
    if verzija not in VERZIJE:
        raise ValueError(f"verzija mora biti jedna od {VERZIJE}, dobiveno: {verzija!r}")


def _zamijeni_inline_oznake(tekst: str, render=lambda s: s) -> str:
    """!!...!! -> <alert>render(...)</alert>, \\pojam{...} -> <term>render(...)</term>.
    render() se primjenjuje na SVAKI komad obicnog teksta (izmedju/oko markera) i na
    sadrzaj unutar markera - NIKAD na same <alert>/<term> oznake koje ova funkcija umece."""
    dijelovi = []
    zadnji = 0
    for m in _KOMBINIRANI_INLINE_RE.finditer(tekst):
        dijelovi.append(render(tekst[zadnji:m.start()]))
        if m.group("alert") is not None:
            dijelovi.append(f"<alert>{render(m.group('alert'))}</alert>")
        else:
            dijelovi.append(f"<term>{render(m.group('pojam'))}</term>")
        zadnji = m.end()
    dijelovi.append(render(tekst[zadnji:]))
    return "".join(dijelovi)


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


def teorija_u_ptx_odlomke(tekst: str, verzija: str = "ucenik", render=lambda s: s) -> list:
    """Pretvara sirovi tekst_teorije_latex u listu PreTeXt sadržaja (obicni odlomci kao
    goli <p> sadržaj bez omota - taj dio ostaje pozivatelju (_build_introduction_lines) da
    doda <p>...</p>; <remark> blokovi za rješenja dolaze već potpuno omotani, s <p>
    tagovima za svaki svoj odlomak, spremni za izravno umetanje BEZ dodatnog <p> omota).

    render: funkcija primijenjena na obican tekst prije umetanja markera - proslijedi
    _pretext_text iz baza_zadataka_pipeline.py za stvaran PreTeXt izlaz (XML escape +
    $...$ -> <m>...</m>). Zadano: identity (korisno za testove/preview bez PreTeXt-a).

    verzija="ucenik"   (zadano) - [RJESENJE] blokovi se PRESKAČU u cijelosti.
    verzija="profesor"           - [RJESENJE] blokovi ostaju, umotani u <remark>.
    """
    _provjeri_verziju(verzija)
    rezultat = []
    for vrsta, sadrzaj in _segmentiraj(tekst):
        if vrsta == "tekst":
            rezultat.extend(_zamijeni_inline_oznake(o, render) for o in _odlomci(sadrzaj))
        elif verzija == "profesor":
            unutarnji_p = "\n".join(
                f"<p>{_zamijeni_inline_oznake(o, render)}</p>" for o in _odlomci(sadrzaj)
            )
            if unutarnji_p:
                rezultat.append(f"<remark><title>Rjesenje</title>\n{unutarnji_p}\n</remark>")
        # verzija == "ucenik" i vrsta == "rjesenje" -> namjerno se ništa ne dodaje
    return rezultat


def ukloni_markup_za_pregled(tekst: str, verzija: str = "ucenik") -> str:
    """Čitljiv preview BEZ generiranja PreTeXt-a - koristi se u Streamlit stranici da
    Caki odmah vidi kako će tekst izgledati za odabranu verziju, prije spremanja.
    !! -> **, \\pojam{} -> *naziv*, [RJESENJE] blok (u profesor prikazu) dobiva prefiks.
    Namjerno NE koristi render (identity je dovoljan - ovo je obican tekstualni prikaz,
    ne PreTeXt XML)."""
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
    odlomak = re.sub(r"!!(.+?)!!", r"**\1**", odlomak, flags=re.DOTALL)
    odlomak = re.sub(r"\\pojam\{([^}]+)\}", r"*\1*", odlomak)
    return odlomak
