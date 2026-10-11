"""
CAKI Matematika - filtriraj_zadatke_za_skriptu.py

Odluka (14.9.2026): "zadaci za rad na satu" u tiskanoj skripti su FIKSAN skup - isti
zadaci na istom mjestu svaki put kad se skripta printa, ne izvlače se iznova iz cijelog
fonda. Ostatak fonda (svi ostali zadaci koji NISU u tom fiksnom skupu) i dalje ide na
web (praksa.cakipoduka.com) kao i dosad - taj build se uopce ne dira, ostaje potpun.
Filtriranje se dogadja SAMO za granu koja gradi PDF skriptu.

Nacin obiljezavanja: u tabu sa zadacima (isti Google Sheet gdje zive zadaci - tocan naziv
taba ne znam iz ove sesije, prilagodi) dodaj NOVI stupac, npr. "u_skriptu", i u njega upisi
"DA" za tocno one zadatke koji idu u tiskanu skriptu kao "zadaci za rad na satu". Prazno
polje (bilo koja druga vrijednost) = zadatak NIJE u skripti, i dalje je dostupan na webu i
u fondu za Test Builder (DZ testovi) bez ikakve promjene.

Ova datoteka namjerno NE zna nista o Google Sheetsu ni o PreTeXt generiranju - prima obicnu
listu rjecnika (kakvu vec vjerojatno vraca tvoja postojeca funkcija za citanje zadataka,
npr. worksheet.get_all_records()) i vraca filtriranu listu. Poziva se JEDNOM, neposredno
prije koraka koji tu listu pretvara u PreTeXt XML za PRINT/skripta build - HTML/web build
poziva staru, nefiltriranu listu kao i dosad.
"""


def filtriraj_zadatke_za_skriptu(zadaci: list, stupac: str = "u_skriptu", vrijednost_da: str = "DA") -> list:
    """zadaci: lista rjecnika (jedan zadatak = jedan rjecnik s kljucevima = nazivima
    stupaca iz Sheeta). Vraca NOVU listu koja sadrzi samo zadatke gdje je
    zadatak[stupac] jednako vrijednost_da (usporedba bez obzira na velika/mala slova i
    visak razmaka, da manji tipfeleri pri upisu u Sheet ne izbace zadatak iz skripte)."""
    vrijednost_da_norm = vrijednost_da.strip().lower()
    return [
        z for z in zadaci
        if str(z.get(stupac, "")).strip().lower() == vrijednost_da_norm
    ]


# ---------------------------------------------------------------------------
# 11.10.2026. - VISESTRUKI FILTRI za skriptu (razina A/B, cjelina, vrsta izvora, biblioteka,
# godina, u_skriptu). Sve je OPCIONALNO: prazan filtar = ne filtrira po tom kriteriju.
# Kriteriji se kombiniraju s I (AND); vrijednosti unutar jednog kriterija s ILI (OR).
# ---------------------------------------------------------------------------

FILTRI_KLJUCEVI = ("razine", "cjeline", "izvori", "biblioteke", "godina_od", "godina_do", "samo_u_skriptu")


def normaliziraj_filtre(filtri) -> dict:
    """Vraca ocisceni dict filtara sa SVIM kljucevima iz FILTRI_KLJUCEVI (nepoznati se
    odbacuju, liste se ocisti od praznih/duplikata, godine postaju int ili None)."""
    filtri = filtri or {}

    def _lista(k, velika=False):
        izlaz = []
        for v in (filtri.get(k) or []):
            t = str(v).strip()
            if velika:
                t = t.upper()
            if t and t not in izlaz:
                izlaz.append(t)
        return izlaz

    def _godina(k):
        try:
            return int(str(filtri.get(k)).strip())
        except (TypeError, ValueError):
            return None

    return {
        "razine": _lista("razine", velika=True),
        "cjeline": _lista("cjeline"),
        "izvori": [v.lower() for v in _lista("izvori")],
        "biblioteke": _lista("biblioteke"),
        "godina_od": _godina("godina_od"),
        "godina_do": _godina("godina_do"),
        "samo_u_skriptu": bool(filtri.get("samo_u_skriptu", False)),
    }


def _godina_retka(z):
    try:
        return int(str(z.get("godina", "")).strip()[:4])
    except ValueError:
        return None


def filtriraj_zadatke(zadaci: list, filtri=None) -> list:
    """Vraca NOVU listu zadataka koji zadovoljavaju SVE zadane filtre (v. gore).
    Zadaci bez godine NE prolaze ako je zadan godina_od/godina_do. Usporedbe su bez obzira
    na velika/mala slova i visak razmaka. filtri=None ili {} -> vraca cijelu listu."""
    f = normaliziraj_filtre(filtri)
    cjeline = {c.lower() for c in f["cjeline"]}
    biblioteke = {b.lower() for b in f["biblioteke"]}
    izlaz = []
    for z in zadaci:
        if f["razine"] and str(z.get("razina", "")).strip().upper() not in f["razine"]:
            continue
        if cjeline and str(z.get("cjelina", "")).strip().lower() not in cjeline:
            continue
        if f["izvori"] and str(z.get("izvor_tip", "")).strip().lower() not in f["izvori"]:
            continue
        if biblioteke and str(z.get("biblioteka_izvora", "")).strip().lower() not in biblioteke:
            continue
        if f["godina_od"] is not None or f["godina_do"] is not None:
            g = _godina_retka(z)
            if g is None:
                continue
            if f["godina_od"] is not None and g < f["godina_od"]:
                continue
            if f["godina_do"] is not None and g > f["godina_do"]:
                continue
        if f["samo_u_skriptu"] and str(z.get("u_skriptu", "")).strip().lower() != "da":
            continue
        izlaz.append(z)
    return izlaz


def opis_filtara(filtri) -> str:
    """Kratak citljiv opis (za naslov skripte / prikaz zahtjeva)."""
    f = normaliziraj_filtre(filtri)
    dijelovi = []
    if f["razine"]:
        dijelovi.append("razina " + "/".join(f["razine"]))
    if f["cjeline"]:
        dijelovi.append(", ".join(f["cjeline"]))
    if f["izvori"]:
        dijelovi.append("izvor: " + ", ".join(f["izvori"]))
    if f["biblioteke"]:
        dijelovi.append("biblioteka: " + ", ".join(f["biblioteke"]))
    if f["godina_od"] is not None or f["godina_do"] is not None:
        dijelovi.append(f"godine {f['godina_od'] or '...'}-{f['godina_do'] or '...'}")
    if f["samo_u_skriptu"]:
        dijelovi.append("samo oznaceni za skriptu")
    return "; ".join(dijelovi) or "svi zadaci"


if __name__ == "__main__":
    # Brz test bez Google Sheetsa - samo da se vidi da filtriranje radi kako treba.
    primjer_zadaci = [
        {"id": 1, "cjelina": "Linearna funkcija", "u_skriptu": "DA"},
        {"id": 2, "cjelina": "Linearna funkcija", "u_skriptu": ""},
        {"id": 3, "cjelina": "Linearna funkcija", "u_skriptu": "da"},   # malim slovima - i dalje uhvaceno
        {"id": 4, "cjelina": "Linearna funkcija", "u_skriptu": " DA "},  # visak razmaka - i dalje uhvaceno
        {"id": 5, "cjelina": "Kvadratna funkcija"},                     # stupac uopce ne postoji za ovaj redak
    ]
    rezultat = filtriraj_zadatke_za_skriptu(primjer_zadaci)
    print("Za skriptu ulaze id-evi:", [z["id"] for z in rezultat])
    assert [z["id"] for z in rezultat] == [1, 3, 4]
    print("OK")
