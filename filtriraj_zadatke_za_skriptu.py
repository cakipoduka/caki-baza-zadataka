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
