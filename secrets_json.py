"""
CAKI — secrets_json.py  (21.10.2026.)
ČITANJE JSON-a IZ STREAMLIT SECRETS — tolerantno na stvarne prijelome redaka.

Zašto postoji: kad se servisni račun zalijepi u Secrets iz tekstualnog editora, `private_key`
zadrži STVARNE prijelome redaka umjesto `\\n`. JSON to ne dopušta, pa `json.loads` baci
„Invalid control character at: line 5 column 46” i cijela aplikacija padne — iako je ključ ispravan.

Isti popravak (`testovi_online.sa_info_iz_teksta`) napravljen je 21.10.2026. u sustavu testova;
ovaj modul ga nosi u ostatak aplikacije, da ista greška ne padne negdje drugdje.

Korištenje:  `import secrets_json as _sj`  →  `_sj.ucitaj(st)`  ili  `_sj.ucitaj(st, "MOJ_KLJUC")`.
"""
import json


def _poruka(naziv_kljuca: str, sto: str) -> str:
    return (f"`{naziv_kljuca}` u Streamlit Secrets {sto}.\n\n"
            "**Kako popraviti:** otvori Secrets → taj ključ → mora biti JSON servisnog računa "
            "(`{\"type\": \"service_account\", …}`). Najčešća greška je da `private_key` sadrži "
            "STVARNE prijelome redaka — u JSON-u mora stajati `\\n` (jedna linija), ili se cijeli JSON "
            "zalijepi u TOML s trostrukim navodnicima. Ne stavljaj navodnike oko cijelog JSON-a.")


def ucitaj(st, kljuc: str = "GOOGLE_SERVICE_ACCOUNT_JSON") -> dict:
    """JSON iz `st.secrets[kljuc]` kao dict — prihvaća stvarne prijelome redaka i česte pogreške.

    Baca `ValueError` s porukom koja imenuje ključ (bolje od „ne može se otvoriti Sheet”).
    """
    tekst = str(st.secrets[kljuc] or "")
    t = tekst.replace("\ufeff", "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"') and t[1:2] == "{":
        t = t[1:-1].strip()                       # zalijepljen s navodnicima oko cijelog JSON-a
    podaci, zadnja = None, None
    for strogo in (True, False):                  # False dopušta stvarne \n unutar stringa
        try:
            podaci = json.loads(t, strict=strogo)
            break
        except json.JSONDecodeError as e:
            zadnja = e
    if podaci is None:
        raise ValueError(_poruka(kljuc, f"nije ispravan JSON ({zadnja})"))
    if not isinstance(podaci, dict):
        raise ValueError(_poruka(kljuc, "nije JSON objekt (mora biti od `{` do `}`)"))
    return podaci
