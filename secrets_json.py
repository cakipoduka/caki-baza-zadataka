"""
CAKI — secrets_json.py  (21.10.2026., ojačano 25.10.2026.)
ČITANJE JSON-a IZ STREAMLIT SECRETS — tolerantno na sve što ljudi stvarno zalijepe.

Zašto postoji: kad se servisni račun zalijepi u Secrets, najčešće se pokvari na jedan od ovih načina:
  · `private_key` zadrži STVARNE prijelome redaka umjesto `\\n` (JSON to ne dopušta),
  · navodnici se pretvore u „pametne" (U+201C, U+201D, U+201E) jer su kopirani iz Worda/Docsa,
  · uz JSON ostane `=` ili trostruki navodnici iz TOML-a,
  · ostane zarez prije `}` (JSON to ne dopušta).

Sve to ovaj modul popravi **prije** nego `json.loads` baci nerazumljivu grešku — a ako ne može,
greška imenuje ključ i kaže **što je točno nađeno**.

Korištenje:  `import secrets_json as _sj`  →  `_sj.ucitaj(st)`  ili  `_sj.ucitaj(st, "MOJ_KLJUC")`.
"""
import json
import re

# „pametni" navodnici → pravi (najčešći uzrok greške „line 1 column 3")
_PAMETNI = {
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2018": "'", "\u2019": "'", "\u00ab": '"', "\u00bb": '"',
}
_PAMETNI_ZNAKOVI = ("\u201c", "\u201d", "\u201e", "\u201f", "\u00ab", "\u00bb")


def _poruka(naziv_kljuca: str, sto: str) -> str:
    return (
        f"`{naziv_kljuca}` u Streamlit Secrets {sto}.\n\n"
        "**Kako popraviti:** otvori Secrets → taj ključ → mora biti JSON servisnog računa "
        '(`{"type": "service_account", ...}`). Najčešće greške: (1) `private_key` sadrži STVARNE '
        "prijelome redaka — u JSON-u mora stajati `\\n`; (2) navodnici su pametni umjesto pravih; "
        "(3) cijeli JSON je u navodnicima. **Najlakše:** kopiraj isti ključ iz aplikacije koja već "
        "radi (npr. `caki-baza-zadataka` → Settings → Secrets)."
    )


def _dijagnostika(tekst: str) -> str:
    """Kratko objasni ŠTO je nađeno — da Caki ne mora pogađati."""
    nac = []
    if any(z in tekst for z in _PAMETNI_ZNAKOVI):
        nac.append("pametni navodnici (tipografski) → moraju biti obični")
    if re.search(r"[^\\]\n", tekst):
        nac.append("stvarni prijelomi redaka unutar teksta → u JSON-u mora biti \\n")
    if tekst.strip().startswith("="):
        nac.append("na početku stoji `=` (TOML ostatak)")
    if re.search(r",\s*[}\]]", tekst):
        nac.append("zarez prije `}` ili `]`")
    if not tekst.strip().startswith("{"):
        nac.append("ne počinje s `{`")
    return "; ".join(nac) if nac else "sadržaj nije valjan JSON"


def _ocisti(tekst) -> str:
    """Popravi ono što se popraviti može, prije `json.loads`."""
    t = str(tekst or "").replace("\ufeff", "").strip()
    for lose, dobro in _PAMETNI.items():
        t = t.replace(lose, dobro)
    t = re.sub(r"^=+\s*", "", t)                       # TOML ostatak „= {"
    for trojka in ('"""', "'''"):
        if t.startswith(trojka):
            t = t[3:]
        if t.endswith(trojka):
            t = t[:-3]
    t = t.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"') and t[1:2] in ("{", "["):
        t = t[1:-1].strip()                            # navodnici oko cijelog JSON-a
    t = re.sub(r",\s*([}\]])", r"\1", t)               # zarez prije } ili ]
    return t


def ucitaj(st, kljuc: str = "GOOGLE_SERVICE_ACCOUNT_JSON") -> dict:
    """JSON iz `st.secrets[kljuc]` kao dict — popravlja česte pogreške pri lijepljenju.

    Baca `ValueError` s porukom koja imenuje ključ i kaže što je nađeno (bolje od
    „ne može se otvoriti Sheet").
    """
    try:
        sirovo = st.secrets[kljuc]
    except Exception:                                  # noqa: BLE001 — nema ključa
        raise ValueError(f"U Secrets nedostaje `{kljuc}`.")
    t = _ocisti(sirovo)
    podaci, zadnja = None, None
    for strogo in (True, False):                       # False dopušta stvarne \n u stringu
        try:
            podaci = json.loads(t, strict=strogo)
            break
        except json.JSONDecodeError as e:
            zadnja = e
    if podaci is None:
        raise ValueError(_poruka(kljuc, f"nije ispravan JSON ({zadnja}).\n\n"
                                        f"**Nađeno:** {_dijagnostika(t)}"))
    if not isinstance(podaci, dict):
        raise ValueError(_poruka(kljuc, "nije JSON objekt (mora biti od `{` do `}`)"))
    return podaci
