"""
CAKI Matematika - baza_zadataka_pipeline.py

Jezgra pipelinea (Mathpix OCR, Claude strukturiranje, Google Sheets upis s
detekcijom duplikata, upload slika na Drive). Logika je identična onoj u
Colab notebooku (Koraci 1-4) - jedina razlika je autentifikacija: umjesto
interaktivne Google prijave (google.colab.auth), ovdje se koristi Google
Service Account, jer server (Streamlit) nema interaktivnu sesiju.
"""
import os
import re
import io
import json
import time
import shutil
import difflib
import requests
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from teorija_markup import teorija_u_ptx_odlomke
from filtriraj_zadatke_za_skriptu import (
    filtriraj_zadatke_za_skriptu, filtriraj_zadatke, normaliziraj_filtre, opis_filtara,
)
from skupine_zadataka import NOVI_STUPCI, pripremi_jedinice

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ZADACI_HEADERS = [
    "id", "izvor_tip", "izvor_naziv", "godina", "broj_pdf_ulaza",
    "razina", "razred", "kategorija", "cjelina", "potpoglavlje", "kljucne_rijeci",
    "tekst_zadatka_latex", "tekst_zadatka_mathjax",
    "rjesenje", "rjesenje_status", "tip_rjesenja_izvor",
    "slika_putanja", "video_url",
    "vizualni_potencijal", "geogebra_komande", "geogebra_material_id",
    "tezina", "max_bodovi", "slicni_zadaci",
    "status_provjere", "skenirano", "pretext_permalink",
    "tip_zadatka", "slika_zadana", "ponudjeni_odgovori", "konacan_odgovor",
    "uputa",
    # 🆕 Ručni redoslijed zadatka UNUTAR svog potpoglavlja, za PreTeXt izlaz (Korak 3.1) -
    # broj (preporučeno u razmacima od 10: 10, 20, 30... da se kasnije da ubaciti zadatak
    # između dva postojeća bez pretipkavanja svih brojeva). Prazno = ide na kraj svoje
    # tezina-grupe (vidi _redoslijed_u_potpoglavlju_sort_key). DODAN NA KRAJU popisa (ne
    # umetnut u sredinu) da se ne pomakne stupac postojećim retcima u već popunjenom
    # Sheetu - fizički dodaj kao NOVI zadnji stupac u tabu 'Zadaci', ne umeći ga.
    "redoslijed_u_potpoglavlju",
    # 🆕 (§27.3) "da"/"ne" (prazno = "ne") - zadatak koji profesor rješava UŽIVO na satu kao
    # demonstraciju (rješenje odmah vidljivo kao dio izlaganja), NE kao vježbu za samostalno
    # rješavanje. U PreTeXt izlazu (Korak 3.1) takvi zadaci idu u <example> blok, prikazan
    # PRIJE <exercises> unutar istog potpoglavlja, i izostavljeni su iz <exercises> (ne
    # dupliciraju se na oba mjesta). DODAN NA KRAJU popisa (isti razlog kao
    # redoslijed_u_potpoglavlju gore) - fizički dodaj kao NOVI zadnji stupac u tabu 'Zadaci'.
    "koristi_kao_primjer_na_satu",
    # 🆕 (§27.5, 15.9.2026.) "DA" (prazno = ne ulazi) - zadatak za SAMOSTALAN rad učenika na
    # satu koji ulazi u TISKANU skriptu, kao FIKSNI skup (isti zadaci na istom mjestu svaki
    # put kad se skripta printa). Koristi ga filtriraj_zadatke_za_skriptu() SAMO na
    # print/skripta grani builda (Korak 3.1b) - web/HTML (praksa.cakipoduka.com) i redovni
    # PDF (Korak 3.1) uvijek prikazuju CIJELI fond, neovisno o ovom stupcu. Razlikuje se od
    # koristi_kao_primjer_na_satu iznad (koji profesor rješava uživo, ne učenik samostalno).
    # Uređuje se kvačicom "🖨️ Skripta" na stranici "📑 Redoslijed zadataka po potpoglavlju".
    # DODAN NA KRAJU popisa (isti razlog kao gornja dva polja) - fizički dodaj kao NOVI
    # zadnji stupac u tabu 'Zadaci'.
    "u_skriptu",
    # 🆕 (prijedlog, 8.10.2026.) Naziv konkretne zbirke/udžbenika iz kojeg zadatak dolazi
    # (npr. "zbirka-Dakić-pismeni", "udzbenik-Element-Žitko") - za brzo filtriranje u Test
    # Builderu kad profesor traži zadatke iz određenog izvora. Kontroliran, ali OTVOREN
    # popis - vidi get_biblioteke_izvora()/tab 'Sifrarnik_biblioteka_izvora' niže. NAMJERNO
    # odvojeno od izvor_naziv (identifikator PARTIJE/dokumenta uploada, npr. broj serije ili
    # naziv PDF-a, ne naziv zbirke) i od izvor_tip (grubi tip: matura/zbirka/udzbenik/
    # vlastiti_materijal). NIKAD se ne smije koristiti u _oznaka_izvor_tezina() ili bilo kojoj
    # _build_* funkciji niže - ne smije procuriti u PreTeXt/PDF ispis, isključivo interno za
    # pretragu/organizaciju baze. DODAN NA KRAJU popisa (isti razlog kao gornja tri polja) -
    # fizički dodaj kao NOVI zadnji stupac u tabu 'Zadaci'.
    "biblioteka_izvora",
    # 🆕 (10.10.2026.) SKUPINE ZADATAKA - zadatak s podzadacima 1), 2), 3)... sprema se kao JEDAN redak
    # skupine (uloga="skupina", u tekst_zadatka_latex samo zajednički uvod) + po jedan redak za SVAKU
    # stavku (uloga="stavka", roditelj_id = id skupine, oznaka_stavke = "1", "2", "a"...). Prazna uloga =
    # samostalan zadatak (svi postojeći redci). DODANA NA KRAJU popisa (isti razlog kao gornja polja) -
    # fizički dodaj kao NOVE ZADNJE stupce u tabu 'Zadaci', TIM REDOSLIJEDOM, odmah iza biblioteka_izvora.
    # Vidi skupine_zadataka.py.
    "uloga", "roditelj_id", "oznaka_stavke",
    # 🆕 (13.10.2026.) Slike koje idu u RJEŠENJE (npr. skica/graf uz postupak) - nazivi datoteka u
    # 02_SLIKE odvojeni znakom "|" (isto kao slika_putanja, vidi razdvoji_slike). Ispisuju se u
    # <solution> NAKON teksta rješenja (PreTeXt/skripta). U Test Builderu se ne ispisuju jer on
    # u odjeljku rješenja prikazuje samo konačan odgovor. NEOBAVEZAN stupac, DODAN NA KRAJU (iza
    # oznaka_stavke): ako ga Sheet nema, sve radi kao prije. Fizički dodaj kao NOVI ZADNJI stupac
    # u tabu 'Zadaci' (zaglavlje točno: slika_rjesenje_putanja), tek NAKON uloga/roditelj_id/oznaka_stavke.
    "slika_rjesenje_putanja",
    # 🆕 (15.10.2026.) PRIJEVOD zadatka na engleski (za Test Builder / PDF za print). Svi stupci su NEOBAVEZNI i
    # DODANI NA KRAJU (iza slika_rjesenje_putanja): ako ih Sheet nema, sve radi kao prije (uvoz zadataka ih ne
    # dira). Fizički dodaj kao NOVE ZADNJE stupce u tabu 'Zadaci' svakog predmeta, TIM REDOSLIJEDOM, zaglavlja
    # točno kako piše. Pišu ih samo prijevod_zadataka.py / Test Builder, nikad uvoz. prijevod_status je
    # nepregledan | pregledan | provjeri; prijevod_otisak = md5 hrvatskog izvornika (promijeni li se izvornik,
    # prijevod je zastario). U PDF smije samo status "pregledan". Vidi prijevod_zadataka.py.
    "tekst_zadatka_latex_en", "ponudjeni_odgovori_en", "rjesenje_en", "konacan_odgovor_en",
    "prijevod_status", "prijevod_otisak",
]

SLOVA_PONUDJENIH_ODGOVORA = ["A", "B", "C", "D", "E", "F", "G", "H"]

def prikazi_opcije_markdown(ponudjeni_odgovori) -> str:
    """Vraća Markdown string za PREGLED ponuđenih odgovora (višestruki izbor) u Streamlit
    sučelju (ne za LaTeX!) - Streamlitov st.markdown zna renderirati $...$ preko KaTeX-a.
    Baza sprema opcije BEZ $ omotača (čist LaTeX), pa ih ovdje samo omatamo radi prikaza -
    isto načelo kao formatiraj_opciju() u pages/2_test_builder.py, ali za Streamlit prikaz,
    ne za LaTeX izlaz. Zajednička funkcija za baza_zadataka_app.py (stranica 'Uredi zadatak')
    i pages/2_test_builder.py (pregled u pretrazi/odabiru) - da se prikaz opcija ne dupllicira
    na dva mjesta i ne razmimoiđe (npr. broj podržanih slova A-?).

    POPRAVAK (11.9.2026.): opcija se više NE omata bezuvjetno u $...$ kad nema eksplicitnog
    $ znaka - to je uzrokovalo da običan tekst (npr. "ne postoji rješenje") KaTeX renderira
    kao matematiku, gdje se razmaci između riječi ignoriraju (riječi se prikazuju spojene i
    kurzivom - vidi prijavljeni bug, 11.9.2026.). Umjesto toga koristi se ista heuristika kao
    _pretext_math_or_text/_izgleda_kao_recenica niže u ovoj datoteci (PreTeXt izlaz): ako
    opcija izgleda kao rečenica (ima razmak i pretežno je od slova), tretira se kao OBIČAN
    TEKST, bez $...$ omota; inače (kratak matematički izraz, npr. "3x-9" ili "√2") i dalje se
    omata u $...$ kao dosad. Ovo je heuristika, ne savršena - za rubne slučajeve gdje
    heuristika promaši, autor može ručno upisati $ znakove izravno u opciju (grana "$" in
    opcija iznad uvijek ima prednost)."""
    dijelovi = []
    for i, opcija in enumerate(ponudjeni_odgovori):
        opcija = (opcija or "").strip()
        if not opcija:
            continue
        if "$" in opcija:
            prikaz = opcija
        elif _izgleda_kao_recenica(opcija):
            prikaz = opcija
        else:
            prikaz = f"${opcija}$"
        slovo = SLOVA_PONUDJENIH_ODGOVORA[i] if i < len(SLOVA_PONUDJENIH_ODGOVORA) else str(i + 1)
        dijelovi.append(f"**{slovo})** {prikaz}")
    return "  ".join(dijelovi)

def _col_letter(field_name: str, headers=ZADACI_HEADERS) -> str:
    """Pretvori naziv polja u slovo(a) Sheet stupca (0-indeksirano -> A, B, ... Z, AA, AB, ...).
    Računa se dinamički iz ZADACI_HEADERS, umjesto hardkodiranih slova - tako da
    dodavanje/premještanje kolone (npr. `potpoglavlje`) ne pomakne sve nakon nje neopaženo."""
    idx = headers.index(field_name)
    letters = ""
    idx += 1  # 1-indeksirano za standardni algoritam pretvorbe
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters

EXTRACTION_SYSTEM_PROMPT = """Ti si asistent koji strukturira zadatke iz hrvatske državne mature i drugih matematičkih materijala.
Dobit ćeš OCR tekst (Mathpix Markdown) ispita, i po mogućnosti tekst s rješenjima/bodovanjem.

Tvoj zadatak:
1. Razdvoji ispit na pojedinačne zadatke (zadrži izvorni redni broj u polju privremeni_broj).
1b. SKUPINE I STAVKE. AKO jedan zadatak ima VIŠE PODZADATAKA ili NUMERIRANIH VARIJANTI koje dijele zajednički uvod
(npr. 'Izračunaj: 1) ... 2) ... 3) ...', 'Riješi pravokutni trokut ako je: 1) a=3, b=4  2) c=5, b=3', zadatak s a), b), c)
dijelovima nad istom funkcijom ili slikom, ili dva neovisna pitanja u istom zadatku), NEMOJ ponavljati uvod u svakom
podzadatku. Umjesto toga vrati JEDAN objekt SKUPINE (uloga="skupina") i ODMAH iza njega po jedan objekt za SVAKU STAVKU
(uloga="stavka"), redoslijedom kojim su u materijalu:
 - SKUPINA: privremeni_broj = izvorni broj zadatka (npr. '8'); tekst_zadatka_latex = SAMO zajednički uvod/kontekst
   (npr. 'Koliko znamenki ima broj:'; ako uvoda nema, prazan string ""); kategorija, cjelina, potpoglavlje, kljucne_rijeci,
   tezina (težina većine stavki) popuni kao za svaki drugi zadatak; slika_zadana/slika_url popuni ako je slika zajednička
   za sve stavke (točka 12). Skupina NEMA rjesenje ni konacan_odgovor.
 - STAVKA: privremeni_broj = broj skupine + '.' + izvorna oznaka (npr. '8.1', '7.b'); roditelj_privremeni_broj =
   privremeni_broj skupine; oznaka_stavke = izvorna oznaka podzadatka BEZ zagrade (npr. '1', '2', 'a', 'b');
   tekst_zadatka_latex = SAMO tekst te stavke, BEZ uvoda (npr. '$2^{11} \\cdot 5^{11}$'); tezina TE stavke; te rjesenje,
   tip_rjesenja_izvor, konacan_odgovor, max_bodovi, uputa, status_provjere, tip_zadatka i ponudjeni_odgovori po točkama
   3, 8, 9, 10, 11, 13 i 14. Rješenja stavki traži po broju zadatka I oznaci stavke (npr. '8. 1) ...'). NE ponavljaj
   kategoriju, cjelinu, potpoglavlje ni ključne riječi na stavci - nasljeđuje ih od skupine (izostavi ta polja).
 - Ako podzadatak b) ovisi o brojčanom rezultatu podzadatka a), ipak ih ostavi kao stavke iste skupine, ali u tekstu
   stavke b) eksplicitno navedi taj rezultat kao zadanu vrijednost (izračunaj ga sam samo ako je jednoznačno moguće).
 - Skupina mora imati BAREM 2 stavke. Zadatak sa SAMO JEDNIM pitanjem (čak i ako ima dugačak uvod sa zadanim podacima,
   npr. 'Ako je m=..., n=..., koliko je ...?') je običan zadatak: uloga="samostalan".
 - Svaki običan zadatak ima uloga="samostalan".
2. Za svaki zadatak izvuci ČIST TEKST PITANJA u polje tekst_zadatka_latex (LaTeX matematika unutar $...$, bez naredbi za formatiranje cijelog dokumenta). VAŽNO: NE uključuj ponuđene odgovore A/B/C/D u ovo polje - oni idu zasebno, vidi točku 13.
3. Ako je u ovoj poruci dan odjeljak 'TEKST RJEŠENJA/BODOVANJA', pronađi odgovarajuće rješenje za svaki zadatak po broju i uključi puni postupak ako postoji, inače samo finalni rezultat. AKO TAJ ODJELJAK NIJE DAN I rješenje nije ni ugrađeno izravno u tekst ispita (vidi točku 3a), OBAVEZNO ostavi polje rjesenje prazno ("") - NE smiješ sam rješavati zadatak niti nagađati odgovor, čak i ako znaš rješenje.
3a. RJEŠENJE UGRAĐENO ISPOD ZADATKA (čest slučaj u zbirkama i na ispitima s fakulteta): ako u SAMOM tekstu ispita odmah ispod zadatka, a prije sljedećeg zadatka, stoji rješenje označeno s 'RJ:', 'Rj.:', 'Rješenje:' ili 'R:' (npr. 'RJ: a = 3 m/s²'), to JE službeno rješenje tog zadatka. Prepiši ga doslovno u polje rjesenje (puni postupak ako je naveden, inače samo rezultat), izvuci kratki odgovor u konacan_odgovor i NE uključuj taj dio u tekst_zadatka_latex. Ovo vrijedi i kad odjeljak 'TEKST RJEŠENJA/BODOVANJA' nije dan; ako je dan i sadrži rješenje za isti zadatak, prednost ima odjeljak. Oznaku 'Odgovor: ____' s praznom crtom NIKAD ne smatraj rješenjem (to je mjesto za upis učenika). Ako ispod zadatka nema takve oznake, vrijedi točka 3 - rješenje ostaje prazno.
4. Dodijeli TOČNO JEDNU kategoriju i cjelinu IZ DANOG ŠIFRARNIKA — ne izmišljaj nove nazive, koristi postojeće doslovno.
4b. Dodijeli TOČNO JEDNO potpoglavlje IZ DANOG ŠIFRARNIKA POTPOGLAVLJA, isključivo od onih navedenih za dodijeljenu cjelinu — ne izmišljaj nove nazive. Ako niti jedno ponuđeno potpoglavlje za tu cjelinu ne odgovara (rijetko), ostavi polje potpoglavlje prazno ("") umjesto nagađanja.
4c. Ako izvorni materijal sadrži EKSPLICITNU uputu/naznaku za rješavanje odvojenu od punog rješenja (npr. "Uputa: ..." ili "Naznaka: ..." prije samog rješenja), izvuci je doslovno u polje uputa. NIKAD ne izmišljaj uputu koje nema u izvoru - ako je nema, polje uputa ostaje prazno ("").
5. Procijeni težinu: "lako", "srednje" ili "tesko".
6. Predloži 3-6 ključnih riječi/pojmova (kljucne_rijeci, odvojene zarezom).
7. vizualni_potencijal: "da" SAMO ako zadatak NEMA zadanu sliku ali bi GeoGebra vizualizacija pomogla razumijevanju (npr. tekstualni zadatak o funkciji bez priloženog grafa), inače "ne".
8. Ako pronađeš broj bodova za zadatak u tekstu bodovanja, upiši u max_bodovi (samo broj), inače ostavi prazno.
9. tip_rjesenja_izvor: "puni_postupak" ako rješenje sadrži korake, "samo_rezultat" ako je samo finalni odgovor, inače prazno.
10. Ako nisi siguran u OCR neke formule/rješenja, kratko napomeni u status_provjere (npr. "OCR nesiguran kod zadatka 5, provjeriti simbol"), inače ostavi prazno.
11. tip_zadatka: "visestruki_izbor" (ima ponuđene odgovore A/B/C/D), "kratki_odgovor" (traži se kratak numerički/simbolički odgovor, npr. "Odgovor: ____"), ili "prosireni_odgovor" (traži se prikaz cijelog postupka rješavanja).
12. slika_zadana: "da" ako je u tekstu ispita (Mathpix Markdown) uz ovaj zadatak priložena slika/graf/dijagram koji je DIO zadatka (student mora pročitati podatke sa slike da riješi zadatak) - PREPOZNAJ TO PO MARKDOWN REFERENCI NA SLIKU (oblika ![](url) ili slično) koja se nalazi neposredno uz tekst tog zadatka. Ako je slika_zadana="da", OBAVEZNO u polje slika_url upiši TOČAN URL te slike, prekopiran iz Mathpix Markdown teksta (ne izmišljaj URL). Ako uz isti zadatak stoji VIŠE slika (npr. "slika 1." i "slika 2." ili sheme uz svaku ponuđenu opciju), upiši SVE njihove URL-ove u slika_url odvojene znakom | (okomita crta), redoslijedom kojim se pojavljuju u materijalu, i ne izostavi nijednu. Ako nema takve slike, slika_zadana="ne" i slika_url prazan.
VAŽNO: slika_zadana i vizualni_potencijal se međusobno isključuju - zadatak sa zadanom slikom NIKAD ne dobiva vizualni_potencijal="da" (ne rekonstruiramo zadanu sliku preko GeoGebre, samo je izrežemo iz originala).
13. ponudjeni_odgovori: SAMO za tip_zadatka="visestruki_izbor" - JSON lista ponuđenih odgovora BEZ oznaka A/B/C/D, redoslijedom kako se pojavljuju (npr. ["5", "4.6", "4.58", "4.573"]). Za sve ostale tipove zadataka, prazna lista [].
14. konacan_odgovor: KRATAK, čist finalni odgovor, odvojen od punog postupka u polju rjesenje. Za visestruki_izbor: samo slovo točnog odgovora (npr. "C"). Za kratki_odgovor/prosireni_odgovor: kratka vrijednost (npr. "3", "1/2", "x=5"). Ako rjesenje nije dano (vidi točku 3), ostavi prazno.

VAŽNO: Odgovori ISKLJUČIVO JSON listom objekata, bez ikakvog teksta prije/poslije, bez markdown ograda (bez ```). Čak i ako ne možeš povezati rješenja s numeracijom zadataka, svejedno vrati JSON listu zadataka (polje rjesenje ostavi prazno) - NIKAD ne odgovaraj objašnjenjem umjesto JSON-a. Svaki objekt neka ima ova polja:
privremeni_broj, uloga, tekst_zadatka_latex, kategorija, cjelina, potpoglavlje, kljucne_rijeci, tezina, vizualni_potencijal, rjesenje, tip_rjesenja_izvor, max_bodovi, status_provjere, tip_zadatka, slika_zadana, slika_url, ponudjeni_odgovori, konacan_odgovor, uputa
(uloga je "samostalan", "skupina" ili "stavka" - vidi točku 1b). Objekti uloge "stavka" imaju DODATNO roditelj_privremeni_broj i oznaka_stavke, a od ostalih polja SMIJU imati samo: tekst_zadatka_latex, tezina, rjesenje, tip_rjesenja_izvor, max_bodovi, status_provjere, tip_zadatka, ponudjeni_odgovori, konacan_odgovor, uputa, slika_zadana, slika_url (sve ostalo izostavi - odgovor ostaje kraći).

KRITIČNO za ispravnost JSON-a: ako bilo koje polje sadrži navodnik (npr. zapis kuta u stupnjevima/minutama/sekundama poput 12°34'56", oznaka inča, ili citat unutar teksta zadatka), TAJ NAVODNIK MORAŠ escapeati kao \" unutar JSON stringa. Isto vrijedi za obrnutu kosu crtu (\\ -> \\\\) i nove retke unutar stringa (koristi \\n, ne stvarni prijelom retka). Jedan neescapean navodnik ili obrnuta kosa crta učini CIJELI JSON odgovor neispravnim i cijela obrada zadataka propadne - budi posebno pažljiv kod zapisa kutova i LaTeX izraza.
"""

# --- Dodaci prompta po predmetu (12.10.2026.) ---
# EXTRACTION_SYSTEM_PROMPT gore je napisan za matematiku. Za ostale predmete mu se dodaje
# odjeljak koji mijenja samo ono što se razlikuje (jedinice, tipovi zadataka, crteži...).
# Matematika (zadani predmet) NE dobiva ništa: ponašanje je isto kao prije.
PREDMET_PROMPT_DODACI = {
    "fizika": """
=== PREDMET: FIZIKA ===
Ovaj materijal je iz FIZIKE (državna matura iz fizike, zbirka zadataka iz fizike ili ispit s fakulteta), a ne iz matematike. Sve gore navedeno vrijedi, uz sljedeće dodatke:
F1. Fizikalne veličine i mjerne jedinice piši u LaTeX matematici unutar $...$: veličine kurzivom, jedinice uspravno (\\mathrm{...}) i s tankim razmakom između broja i jedinice, npr. $v = 3{,}5\\,\\mathrm{m/s}$, $F = 12\\,\\mathrm{N}$, $T = 300\\,\\mathrm{K}$, $a = 2\\,\\mathrm{m/s^2}$. Brojeve i decimalni zarez/točku prepiši točno kako piše u izvoru, jedinice nemoj pretvarati ni brojeve zaokruživati.
F2. konacan_odgovor za zadatke s brojčanim odgovorom UKLJUČUJE jedinicu (npr. "3,5 m/s"); za višestruki izbor je samo slovo.
F3. Ispitna knjižica iz fizike ima 1. dio (višestruki izbor s četiri odgovora -> tip_zadatka="visestruki_izbor") i 2. dio (zadaci produženog odgovora s postupkom i mjernom jedinicom -> "prosireni_odgovor"). "kratki_odgovor" koristi samo kad se traži samo broj ili jedinica bez postupka.
F4. Crteži, skice pokusa, grafovi (npr. v-t graf), strujni krugovi i zrake kod leća i zrcala su DIO zadatka: slika_zadana="da" i slika_url prema točki 12 (kad zadatak ima više crteža, npr. "slika 1." i "slika 2.", u slika_url idu SVI URL-ovi odvojeni znakom |). NIKAD ne izmišljaj vrijednosti koje se vide samo na slici i ne možeš ih pročitati iz teksta. vizualni_potencijal je za fiziku uvijek "ne".
F5. Popis konstanti i formula na početku ispita (npr. g, c, h, e, konstante plina) NIJE zadatak - ne pretvaraj ga u zadatke i ne dodaji konstante koje u tekstu zadatka ne stoje.
F6. 'cjelina' i njezina 'kategorija' isključivo su iz danog šifrarnika (kategorija je grupa kojoj cjelina pripada, npr. Mehanika, Termodinamika). Potpoglavlje upiši samo ako je za tu cjelinu navedeno u šifrarniku potpoglavlja; ako za cjelinu nema potpoglavlja, ostavi polje potpoglavlje prazno.
""",
    "matematika_os": """
=== PREDMET: MATEMATIKA ZA OSNOVNU ŠKOLU (5.-8. razred) ===
Ovaj materijal je iz MATEMATIKE ZA OSNOVNU ŠKOLU (udžbenik, zbirka zadataka, ispit ili radni list za 5.-8. razred), a ne iz državne mature. Sve gore navedeno vrijedi, uz sljedeće dodatke:
O1. 'kategorija', 'cjelina' i 'potpoglavlje' isključivo su iz danih šifrarnika. Cjelina odgovara POGLAVLJU udžbenika, a potpoglavlje LEKCIJI. Potpoglavlje upiši uvijek kad ijedno ponuđeno za tu cjelinu odgovara temi zadatka (to je finija klasifikacija od srednje škole, pa ne ostavljaj prazno bez razloga).
O2. Dijelovi lekcije kao što su 'Zadatci za ponavljanje', 'Jednostavniji zadatci', 'Složeniji zadatci', 'Zabavni kutak' i 'Semafor' NISU potpoglavlja. Zadatak iz takvog dijela dobiva potpoglavlje LEKCIJE kojoj tematski pripada. Ako je dio označen kao 'Jednostavniji' težina je "lako", a ako je 'Složeniji' težina je "tesko" (inače težinu procijeni sam).
O3. Zadaci su često kratki i brojčani. tip_zadatka="kratki_odgovor" koristi za zadatke u kojima se traži samo rezultat, dopunjavanje ili jedan odgovor, a "prosireni_odgovor" za konstrukcije, tekstualne zadatke i zadatke koji traže postupak. Zadatke dopunjavanja (praznine, tablice) zadrži u tekstu zadatka tako da praznine pišeš kao $\\ldots$, a zadatke spajanja ili zaokruživanja pretvori u višestruki izbor samo ako su ponuđeni odgovori jasno odvojeni.
O4. Crteži, geometrijske konstrukcije, brojevni pravci, koordinatne mreže, grafikoni i tablice podataka koje je potrebno čitati su DIO zadatka: slika_zadana="da" i slika_url prema točki 12 (više crteža odvoji znakom |). Za zadatke tipa 'konstruiraj' rješenje je opis postupka iz izvora, a ako izvor ima samo crtež rješenja, rjesenje ostavi prazno i u status_provjere napiši "rješenje je crtež".
O5. Decimalne brojeve piši s decimalnim zarezom u LaTeXu ($3{,}5$), postotke kao $15\\%$, a mjerne jedinice uspravno ($12\\,\\mathrm{cm}$, $3\\,\\mathrm{kg}$). Brojeve i tekst prepiši točno kao u izvoru; nemoj pojednostavljivati formulaciju zadatka.
""",
}


def sastavi_extraction_prompt(predmet="matematika"):
    """Cijeli system prompt za Claudeovo strukturiranje zadataka za dani predmet."""
    return EXTRACTION_SYSTEM_PROMPT + PREDMET_PROMPT_DODACI.get((predmet or "matematika").strip().lower(), "")


# --- Google auth (Service Account) ---

def get_credentials(service_account_info: dict):
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

def get_gspread_client(service_account_info: dict):
    return gspread.authorize(get_credentials(service_account_info))

def get_drive_service(service_account_info: dict):
    return build("drive", "v3", credentials=get_credentials(service_account_info))

# --- Mathpix ---

def mathpix_process_pdf(pdf_bytes: bytes, filename: str, app_id: str, app_key: str) -> str:
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.post(
        "https://api.mathpix.com/v3/pdf",
        headers=headers,
        files={"file": (filename, pdf_bytes)},
        data={"options_json": '{"conversion_formats": {"md": true}}'},
    )
    response.raise_for_status()
    return response.json()["pdf_id"]

def mathpix_check_status(pdf_id: str, app_id: str, app_key: str) -> dict:
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.get(f"https://api.mathpix.com/v3/pdf/{pdf_id}", headers=headers)
    response.raise_for_status()
    return response.json()

def mathpix_get_markdown(pdf_id: str, app_id: str, app_key: str) -> str:
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.get(f"https://api.mathpix.com/v3/pdf/{pdf_id}.md", headers=headers)
    response.raise_for_status()
    return response.text

def mathpix_wait_and_get(pdf_id, app_id, app_key, poll_seconds=3, timeout_seconds=300, log=None) -> str:
    waited = 0
    while waited < timeout_seconds:
        status = mathpix_check_status(pdf_id, app_id, app_key)
        state = status.get("status")
        if log:
            log(f"⏳ Status: {state} ({waited}s)")
        if state == "completed":
            return mathpix_get_markdown(pdf_id, app_id, app_key)
        if state == "error":
            raise RuntimeError(f"Mathpix greška: {status}")
        time.sleep(poll_seconds)
        waited += poll_seconds
    raise TimeoutError("Mathpix obrada nije završila u zadanom vremenu.")

SLIKA_EKSTENZIJE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

def je_slika(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in SLIKA_EKSTENZIJE

def mathpix_process_image(image_bytes: bytes, filename: str, app_id: str, app_key: str) -> str:
    """OCR JEDNE slike preko Mathpixovog /v3/text endpointa. Za razliku od /v3/pdf,
    ovo je SINKRONI poziv - odgovor (Mathpix Markdown) stiže odmah u istom pozivu,
    bez pdf_id-a i bez pollinga (mathpix_wait_and_get ovdje nije potreban)."""
    headers = {"app_id": app_id, "app_key": app_key}
    response = requests.post(
        "https://api.mathpix.com/v3/text",
        headers=headers,
        files={"file": (filename, image_bytes)},
        data={"options_json": '{"math_inline_delimiters": ["$", "$"], "rm_spaces": true}'},
    )
    response.raise_for_status()
    return response.json().get("text", "")

def mathpix_ocr_datoteka(file_bytes: bytes, filename: str, app_id: str, app_key: str, log=None) -> str:
    """Jedinstvena ulazna točka za OCR JEDNE datoteke, PDF ILI slika - grana se
    automatski po ekstenziji imena datoteke. PDF ide na asinkroni /v3/pdf (pošalji
    pa čekaj), slika na sinkroni /v3/text (gotovo u istom pozivu)."""
    if je_slika(filename):
        if log:
            log(f"🖼️ Šaljem sliku na Mathpix ({filename})...")
        return mathpix_process_image(file_bytes, filename, app_id, app_key)
    if log:
        log(f"📄 Šaljem PDF na Mathpix ({filename})...")
    pdf_id = mathpix_process_pdf(file_bytes, filename, app_id, app_key)
    return mathpix_wait_and_get(pdf_id, app_id, app_key, log=log)

def mathpix_ocr_vise_datoteka(datoteke, app_id, app_key, log=None):
    """OCR liste uploadanih datoteka (bilo koja kombinacija PDF-ova i slika) i
    spajanje rezultata u jedan Mathpix Markdown tekst, razdvojen s '---' (isti
    obrazac kao dosadašnje spajanje rjesenja_pdf_1/rjesenja_pdf_2). Svaki element
    liste mora imati .getvalue() i .name (Streamlit UploadedFile objekti).
    Vraća None za praznu listu, da pozivatelj ne mora provjeravati posebno."""
    dijelovi = []
    for f in datoteke:
        tekst = mathpix_ocr_datoteka(f.getvalue(), f.name, app_id, app_key, log=log)
        dijelovi.append(tekst)
        if log:
            log(f"✅ OCR gotov ({f.name}, {len(tekst)} znakova)")
    return "\n\n---\n\n".join(dijelovi) if dijelovi else None

# --- Šifrarnik ---

def build_sifrarnik_text(sheet) -> str:
    ws = sheet.worksheet("Sifrarnik_cjelina")
    rows = ws.get_all_values()[1:]
    return "\n".join(f"- Kategorija: {r[0]} | Cjelina: {r[1]}" for r in rows if len(r) >= 2 and r[0])

def get_sifrarnik_cjelina(sheet) -> dict:
    """Vraća {cjelina: kategorija}, čitano iz taba 'Sifrarnik_cjelina' (stupci: kategorija,
    cjelina, razred_tipican, mathify_link), redoslijedom kako se pojavljuju u Sheetu. Koristi
    se za padajući izbornik "Cjelina" kod ručnog ispravka klasifikacije u aplikaciji - isti
    šifrarnik kojim se Claude već vodi kod klasifikacije pri unosu novog ispita (vidi
    build_sifrarnik_text), samo kao strukturirani rječnik umjesto teksta za AI prompt."""
    ws = sheet.worksheet("Sifrarnik_cjelina")
    rows = ws.get_all_values()[1:]
    kategorija_po_cjelini = {}
    for r in rows:
        if len(r) < 2 or not r[1]:
            continue
        kategorija_po_cjelini[r[1].strip()] = r[0].strip()
    return kategorija_po_cjelini

def get_potpoglavlja_po_cjelini(sheet) -> dict:
    """Vraća {cjelina: [(potpoglavlje, redoslijed), ...]} sortirano po redoslijedu,
    čitano iz taba 'Sifrarnik_potpoglavlja' (stupci: cjelina, potpoglavlje, redoslijed)."""
    ws = sheet.worksheet("Sifrarnik_potpoglavlja")
    rows = ws.get_all_values()[1:]
    po_cjelini = {}
    for r in rows:
        if len(r) < 2 or not r[0] or not r[1]:
            continue
        cjelina, potpoglavlje = r[0].strip(), r[1].strip()
        try:
            redoslijed = float(r[2]) if len(r) > 2 and r[2] else 999
        except ValueError:
            redoslijed = 999
        po_cjelini.setdefault(cjelina, []).append((potpoglavlje, redoslijed))
    for cjelina in po_cjelini:
        po_cjelini[cjelina].sort(key=lambda t: t[1])
    return po_cjelini

def build_sifrarnik_potpoglavlja_text(sheet) -> str:
    po_cjelini = get_potpoglavlja_po_cjelini(sheet)
    lines = []
    for cjelina, stavke in po_cjelini.items():
        popis = ", ".join(p for p, _ in stavke)
        lines.append(f"- Cjelina: {cjelina} | Potpoglavlja: {popis}")
    return "\n".join(lines)

# --- Biblioteka izvora (prijedlog, 8.10.2026.) ---
#
# Kontroliran, ali OTVOREN popis konkretnih zbirki/udžbenika (npr. "zbirka-Dakić-pismeni",
# "udzbenik-Element-Žitko") - vidi biblioteka_izvora u ZADACI_HEADERS gore. Tab 'Sifrarnik_
# biblioteka_izvora' auto-kreira se prazan preko get_or_create_worksheet-logike (isti obrazac
# kao Teorija_potpoglavlja niže) i pri PRVOM čitanju seedira se početnim popisom ispod ako je
# tek kreiran - kasnije dodane vrijednosti (preko dodaj_biblioteku_izvora) ostaju trajne u
# tabu i šire se na sve stranice koje ovo polje koriste (Test Builder, obje forme u
# baza_zadataka_app.py).

BIBLIOTEKA_IZVORA_HEADERS = ["naziv"]

_BIBLIOTEKA_IZVORA_POCETNI_SEED = [
    "zbirka-ŠK-stara",
    "zbirka-Dakić-pismeni",
    "zbirka-Dakić-udžbenik",
    "zbirka-Element-Žitko",
    "zbirka-Dakić-višestruki izbor",
]

def get_biblioteke_izvora(sheet) -> list:
    """Vraća popis poznatih vrijednosti za biblioteka_izvora, iz taba
    'Sifrarnik_biblioteka_izvora' (jedan stupac: naziv). Ako tab ne postoji, kreira ga prazan
    i ODMAH ga seedira početnim popisom (_BIBLIOTEKA_IZVORA_POCETNI_SEED) - ako tab već
    postoji ali je prazan (npr. korisnik ručno obrisao sve retke), NE seedira ponovno,
    poštuje prazno stanje kao namjerno."""
    try:
        ws = sheet.worksheet("Sifrarnik_biblioteka_izvora")
        novo_kreiran = False
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title="Sifrarnik_biblioteka_izvora", rows=100, cols=1)
        ws.append_row(BIBLIOTEKA_IZVORA_HEADERS)
        novo_kreiran = True

    rows = ws.get_all_values()[1:]
    popis = [r[0].strip() for r in rows if r and r[0].strip()]

    if novo_kreiran:
        ws.append_rows([[v] for v in _BIBLIOTEKA_IZVORA_POCETNI_SEED])
        popis = list(_BIBLIOTEKA_IZVORA_POCETNI_SEED)

    return popis

def dodaj_biblioteku_izvora(sheet, naziv: str):
    """Dodaje novu vrijednost u Sifrarnik_biblioteka_izvora (ako već ne postoji) - poziva se
    kad profesor u Streamlit izborniku odabere "➕ Nova..." i upiše naziv koji dosad nije bio
    u popisu, da se od tog trenutka pojavljuje kao opcija za SVE buduće zadatke/sesije."""
    naziv = (naziv or "").strip()
    if not naziv:
        return
    try:
        ws = sheet.worksheet("Sifrarnik_biblioteka_izvora")
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title="Sifrarnik_biblioteka_izvora", rows=100, cols=1)
        ws.append_row(BIBLIOTEKA_IZVORA_HEADERS)
    postojeci = [r[0].strip() for r in ws.get_all_values()[1:] if r and r[0].strip()]
    if naziv not in postojeci:
        ws.append_row([naziv])

# --- Teorija po potpoglavlju (§27.2, 9.9.2026.) ---
#
# Jedan redak = jedna (cjelina, potpoglavlje) - tekst se prikazuje kao <introduction> na
# početku sekcije tog potpoglavlja u PreTeXt izlazu (v. _build_introduction_lines niže,
# poziva se iz _build_inner_content). Unos/uređivanje: pages/3_teorija.py.

TEORIJA_HEADERS = [
    "cjelina", "potpoglavlje", "tekst_teorije_latex", "video_url",
    "geogebra_material_id", "zadnja_izmjena","veza_vjezbaj",
]

def get_or_create_worksheet(sheet, title: str, headers: list, rows: int = 500):
    """Generička verzija _get_or_create_log_worksheet niže u ovoj datoteci - otvara tab po
    nazivu, ili ga sama kreira (prazan, sa zaglavljem) ako još ne postoji. Koristi je i
    pages/3_teorija.py (Streamlit) i Colab (Korak 3.1 bootstrap ćelija) - isti kod, dva pozivatelja.

    30.10.2026.: postojeći tab može imati MANJE stupaca od novog zaglavlja (npr.
    'Sifrarnik_poglavlja_knjige' dobio je 4. stupac odabir_json i 5. ukljuceno) - upis bi tada
    pao na "exceeds grid limits". Zato mrežu proširimo, ali PODATKE ne diramo."""
    try:
        ws = sheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=rows, cols=len(headers))
        ws.append_row(headers)
        return ws
    try:
        if getattr(ws, "col_count", 0) < len(headers):
            ws.add_cols(len(headers) - ws.col_count)
    except Exception:  # noqa: BLE001 - ako mrezu ne mozemo prosiriti, upis ce javiti svoju gresku
        pass
    return ws

def get_teorija_po_potpoglavlju(sheet) -> dict:
    """Vraća {(cjelina, potpoglavlje): {stupac: vrijednost, ...}} za sve retke u tabu
    'Teorija_potpoglavlja' (auto-kreiran ako ne postoji - tad vraća {}, bez greške).
    Retci bez i cjeline i potpoglavlja se preskaču (ne mogu se pridijeliti nijednoj sekciji)."""
    ws = get_or_create_worksheet(sheet, "Teorija_potpoglavlja", TEORIJA_HEADERS)
    all_values = ws.get_all_values()
    if not all_values:
        return {}
    headers = all_values[0]
    idx = {h: i for i, h in enumerate(headers)}

    def _get(row, col):
        i = idx.get(col)
        return row[i] if i is not None and i < len(row) else ""

    rezultat = {}
    for row in all_values[1:]:
        cjelina = _get(row, "cjelina").strip()
        potpoglavlje = _get(row, "potpoglavlje").strip()
        if not cjelina or not potpoglavlje:
            continue
        rezultat[(cjelina, potpoglavlje)] = {h: _get(row, h) for h in TEORIJA_HEADERS}
    return rezultat

# --- Zahtjevi za "skriptu" (§27.5, 15.9.2026.) ---
#
# Odluka 15.9.2026.: sam PDF build (PreTeXt -> xelatex) OSTAJE u Colabu (kao i dosad) -
# xelatex/TeX Live je pretezka/prespora infrastruktura za lagani Streamlit Cloud hosting
# koji SVAKODNEVNO koriste profesori (Test Builder) i Caki (unos zadataka), pa bi njeno
# ubacivanje u tu istu aplikaciju riskiralo usporiti ili srusiti je za sve. Umjesto toga,
# Streamlit stranica (pages/4_skripta.py) SAMO bira parametre (cjelina, verzija_teorije,
# filtriraj_u_skriptu) i zapisuje ih ovdje kao "zahtjev" - poput poštanskog sandučića.
# Colab (Korak 3.1) prije poziva build_pretext_article ucita POSLJEDNJI zahtjev preko
# ucitaj_zadnji_zahtjev_skripte() i proslijedi ta tri parametra u build_pretext_article -
# vidi UPUTA_skripta_streamlit_colab.md za tocan redak koji treba dodati u tu celiju.
# Ova stranica NIKAD sama ne pokrece build - samo priprema, Caki i dalje rucno pokrece
# Colab kad zeli, isto kao dosad za obicni build.

SKRIPTA_ZAHTJEVI_HEADERS = ["cjelina", "verzija_teorije", "filtriraj_u_skriptu", "vrijeme", "filtri_json",
                            "zahtjev_id", "status", "poruka", "pdf_drive_id", "naslov", "podnaslov",
                            # 30.10.2026.: "ucenik"/"profesor" za skriptu iz knjige (stranica Skripta,
                            # kartica "Iz knjige"). Prazno = staro ponasanje (samo teorija).
                            "verzija_sadrzaja"]
# naslov/podnaslov (12.10.2026.): neobavezni, upisuje ih korisnik; prazan naslov = automatski iz filtara.
# status: "" (stari zahtjev) | "cekanje" | "u_radu" | "gotovo" | "greska"
# 12.10.2026.: zahtjev_id/status/poruka/pdf_drive_id sluze za automatsku gradnju PDF-a na GitHub Actions
# (radnik azurira status, Streamlit ga cita i nudi PDF) - Colab ih ignorira.

def _osiguraj_zaglavlje_zahtjeva(ws):
    """Dodaje u zaglavlje taba Skripta_zahtjevi stupce koji nedostaju (stari tab), redom."""
    zaglavlje = ws.row_values(1)
    nedostaje = [h for h in SKRIPTA_ZAHTJEVI_HEADERS if h not in zaglavlje]
    # Google tab ima fiksnu mrezu (stari tab: samo 4 stupca) - upis izvan nje daje
    # "exceeds grid limits", pa PRVO prosirimo mrezu.
    potrebno = len(zaglavlje) + len(nedostaje)
    trenutno = getattr(ws, "col_count", potrebno)
    if nedostaje and trenutno < potrebno:
        ws.add_cols(potrebno - trenutno)
    for h in nedostaje:
        ws.update_cell(1, len(zaglavlje) + 1, h)
        zaglavlje = zaglavlje + [h]
    return zaglavlje

def spremi_zahtjev_skripte(sheet, cjelina: str = "", verzija_teorije: str = "ucenik",
                            filtriraj_u_skriptu: bool = True, filtri: dict = None,
                            naslov: str = "", podnaslov: str = "",
                            verzija_sadrzaja: str = "") -> str:
    """Dodaje NOV redak u tab 'Skripta_zahtjevi' (uvijek append, nikad prepisivanje - stari
    zahtjevi ostaju kao povijest, Colab uvijek cita samo POSLJEDNJI, v.
    ucitaj_zadnji_zahtjev_skripte). Vraca zahtjev_id (kratki jedinstveni kod).

    11.10.2026.: parametar `filtri` (dict, v. filtriraj_zadatke_za_skriptu.normaliziraj_filtre:
    razine, cjeline, izvori, biblioteke, godina_od, godina_do, samo_u_skriptu) sprema se kao JSON
    u stupac 'filtri_json'. Ako filtri nije zadan, ponasa se kao prije (cjelina + filtriraj_u_skriptu).
    Stari tab dobiva nove stupce u zaglavlju automatski."""
    import uuid
    from datetime import datetime
    ws = get_or_create_worksheet(sheet, "Skripta_zahtjevi", SKRIPTA_ZAHTJEVI_HEADERS)
    zaglavlje = _osiguraj_zaglavlje_zahtjeva(ws)
    if filtri is not None:
        f = normaliziraj_filtre(filtri)
        cjelina = f["cjeline"][0] if len(f["cjeline"]) == 1 else cjelina
        filtriraj_u_skriptu = f["samo_u_skriptu"]
        filtri_json = json.dumps(f, ensure_ascii=False)
    else:
        filtri_json = ""
    zahtjev_id = uuid.uuid4().hex[:10]
    vrijednosti = {
        "cjelina": cjelina, "verzija_teorije": verzija_teorije,
        "filtriraj_u_skriptu": "DA" if filtriraj_u_skriptu else "NE",
        "vrijeme": datetime.now().strftime("%Y-%m-%d %H:%M"), "filtri_json": filtri_json,
        "zahtjev_id": zahtjev_id, "status": "cekanje", "poruka": "", "pdf_drive_id": "",
        "naslov": " ".join((naslov or "").split())[:150],
        "podnaslov": " ".join((podnaslov or "").split())[:200],
        # Samo "ucenik"/"profesor" imaju smisla; sve ostalo = prazno (staro ponasanje).
        "verzija_sadrzaja": ("profesor" if str(verzija_sadrzaja).strip().lower() == "profesor"
                             else "ucenik" if str(verzija_sadrzaja).strip() else ""),
    }
    ws.append_row([vrijednosti.get(h, "") for h in zaglavlje])
    return zahtjev_id

def _zahtjev_iz_retka(headers, redak, broj_retka=None):
    idx = {h: i for i, h in enumerate(headers)}

    def _get(col):
        i = idx.get(col)
        return redak[i] if i is not None and i < len(redak) else ""

    cjelina = _get("cjelina")
    filtriraj = _get("filtriraj_u_skriptu").strip().upper() == "DA"
    sirovi = _get("filtri_json").strip()
    filtri = None
    if sirovi:
        try:
            filtri = normaliziraj_filtre(json.loads(sirovi))
        except (ValueError, TypeError):
            filtri = None
    if filtri is None:
        filtri = normaliziraj_filtre({"cjeline": [cjelina] if cjelina else [], "samo_u_skriptu": filtriraj})
    return {
        "cjelina": cjelina,
        "verzija_teorije": _get("verzija_teorije") or "ucenik",
        "filtriraj_u_skriptu": filtriraj,
        "vrijeme": _get("vrijeme"),
        "filtri": filtri,
        "zahtjev_id": _get("zahtjev_id"),
        "status": _get("status"),
        "poruka": _get("poruka"),
        "pdf_drive_id": _get("pdf_drive_id"),
        "naslov": _get("naslov"),
        "podnaslov": _get("podnaslov"),
        # 30.10.2026.: verzija sadrzaja za skriptu iz knjige ("ucenik"/"profesor"); stari
        # zahtjevi nemaju taj stupac pa vracamo prazno (staro ponasanje).
        "verzija_sadrzaja": _get("verzija_sadrzaja"),
        "redak": broj_retka,
    }

def ucitaj_zadnji_zahtjev_skripte(sheet):
    """Vraca dict {cjelina, verzija_teorije, filtriraj_u_skriptu (bool), vrijeme, filtri (dict),
    zahtjev_id, status, poruka, pdf_drive_id, redak} za POSLJEDNJI zapisan zahtjev, ili None ako
    tab ne postoji/je prazan. `filtri` je UVIJEK normaliziran dict: ako zahtjev nema filtri_json
    (stari zahtjev), izvodi se iz cjelina + filtriraj_u_skriptu - stari zahtjevi rade kao prije."""
    ws = get_or_create_worksheet(sheet, "Skripta_zahtjevi", SKRIPTA_ZAHTJEVI_HEADERS)
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return None
    return _zahtjev_iz_retka(all_values[0], all_values[-1], len(all_values))

def nadji_zahtjev_skripte(sheet, zahtjev_id: str):
    """Zahtjev s danim zahtjev_id (isti oblik kao ucitaj_zadnji_zahtjev_skripte) ili None."""
    ws = get_or_create_worksheet(sheet, "Skripta_zahtjevi", SKRIPTA_ZAHTJEVI_HEADERS)
    vr = ws.get_all_values()
    if len(vr) < 2 or "zahtjev_id" not in vr[0]:
        return None
    k = vr[0].index("zahtjev_id")
    for n in range(len(vr) - 1, 0, -1):  # od najnovijeg
        if k < len(vr[n]) and vr[n][k] == zahtjev_id:
            return _zahtjev_iz_retka(vr[0], vr[n], n + 1)
    return None

def azuriraj_status_zahtjeva(sheet, zahtjev_id: str, status: str, poruka: str = "", pdf_drive_id: str = ""):
    """Postavlja status/poruka/pdf_drive_id retka s danim zahtjev_id. Vraca True ako je nasao redak.
    `poruka` neka je KRATKA i bez sadrzaja zadataka (cuva se u Sheetu, ne u logu)."""
    ws = get_or_create_worksheet(sheet, "Skripta_zahtjevi", SKRIPTA_ZAHTJEVI_HEADERS)
    zahtjev = nadji_zahtjev_skripte(sheet, zahtjev_id)
    if not zahtjev:
        return False
    zaglavlje = ws.row_values(1)
    for naziv, vrijednost in (("status", status), ("poruka", poruka[:300]), ("pdf_drive_id", pdf_drive_id)):
        ws.update_cell(zahtjev["redak"], zaglavlje.index(naziv) + 1, vrijednost)
    return True

GITHUB_REPO = "cakipoduka/caki-baza-zadataka"
GITHUB_WORKFLOW_SKRIPTA = "skripta.yml"

def pokreni_github_build_skripte(token: str, zahtjev_id: str, repo: str = GITHUB_REPO,
                                  workflow: str = GITHUB_WORKFLOW_SKRIPTA, ref: str = "main",
                                  post=None):
    """Pokrece GitHub Actions workflow koji gradi PDF skripte za dani zahtjev_id.
    Vraca (ok: bool, poruka: str). `token` je GitHub fine-grained token SAMO s pravom
    'Actions: write' na ovaj repo (u Streamlit Secrets kao GITHUB_DISPATCH_TOKEN). Poruka greske
    nikad ne sadrzi token. `post` je zamjenjiv radi testiranja (zadano requests.post)."""
    post = post or requests.post
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    try:
        r = post(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"},
                 json={"ref": ref, "inputs": {"zahtjev_id": zahtjev_id}}, timeout=20)
    except Exception as e:  # noqa: BLE001
        return False, f"Nije moguce kontaktirati GitHub ({type(e).__name__})."
    if r.status_code == 204:
        return True, "Gradnja pokrenuta."
    if r.status_code in (401, 403):
        return False, "GitHub je odbio token (istekao ili bez prava 'Actions: write')."
    if r.status_code == 404:
        return False, "Workflow ili repo nije pronadjen (je li skripta.yml na grani main?)."
    return False, f"GitHub je vratio gresku {r.status_code}."

def preuzmi_datoteku_iz_drivea(drive_service, file_id: str) -> bytes:
    """Sadrzaj Drive datoteke (npr. izgradjeni PDF skripte) kao bytes - za st.download_button."""
    from googleapiclient.http import MediaIoBaseDownload
    zahtjev = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    preuzimac = MediaIoBaseDownload(buf, zahtjev)
    gotovo = False
    while not gotovo:
        _, gotovo = preuzimac.next_chunk()
    return buf.getvalue()

def popis_zahtjeva_skripte(sheet, najvise: int = 8) -> list:
    """Zadnjih `najvise` zahtjeva (najnoviji prvi) u istom obliku kao ucitaj_zadnji_zahtjev_skripte."""
    ws = get_or_create_worksheet(sheet, "Skripta_zahtjevi", SKRIPTA_ZAHTJEVI_HEADERS)
    vr = ws.get_all_values()
    izlaz = []
    for n in range(len(vr) - 1, 0, -1):
        izlaz.append(_zahtjev_iz_retka(vr[0], vr[n], n + 1))
        if len(izlaz) >= najvise:
            break
    return izlaz

# --- PreTeXt XML generiranje (Korak 3.1) ---
#
# Prebačeno iz Colab bilježnice (Faza 1, 1.9.2026.) da postoji JEDAN izvor istine za ovu
# logiku (i za ZADACI_HEADERS shemu koju koristi) umjesto dvije ručno sinkronizirane kopije.
# Colab sad UVOZI ove funkcije iz ovog javnog repoa (vidi bootstrap ćeliju u Koraku 3.1) i
# lokalno drži samo pokreni_pretext_build() - taj dio ostaje Colab-only jer čita/piše na
# disk montiran preko Google Drivea (LATEX_BAZA_ROOT) i poziva pravi `pretext` CLI/xelatex
# u kasnijim koracima (3.2, 3.3), što ne pripada lagano hostanoj Streamlit aplikaciji.
#
# VAŽNO ako mijenjaš ove funkcije: nakon push-a na GitHub, Colab mora ponovno pokrenuti
# bootstrap ćeliju (pip install --force-reinstall) da povuče novu verziju - pip inače
# može zadržati već instaliranu (staru) verziju iz iste sesije.

def _sanitize_id(text):
    text = re.sub(r"[^a-zA-Z0-9_\-]", "-", text)
    if not text or not text[0].isalpha():
        text = "z-" + text
    return text

def _sanitize_filename(text):
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", text.strip())
    return text.strip("_")

def _normalizuj_ostatke_ocr_escapinga(text):
    r"""Mathpix/LaTeX OCR često ostavlja stray backslash-escape za obične tekstualne znakove
    (\% umjesto %, \_ umjesto _) koji NISU LaTeX naredbe - samo su ostatak sirovog OCR-a.
    PreTeXt sam ispravno eskejpa % i _ za LaTeX izlaz, pa ako mu proslijedimo VEĆ eskejpanu
    verziju, dobijemo dupli/vidljivi backslash u izlazu. Očisti prije daljnje obrade."""
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"\\%", "%", text)
    text = re.sub(r"\\_", "_", text)
    return text

def _xml_escape(text):
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))

def _escape_postotak_u_matematici(math):
    r"""U LaTeX-u % pocinje komentar: '\(7.847%\)' ostavi formulu nezatvorenu ('Missing $ inserted').
    Normalizacija OCR-a mice \% -> %, sto je ispravno u TEKSTU (PreTeXt ga tamo sam escapea), ali
    unutar matematike PreTeXt prosljedjuje sadrzaj doslovno, pa % mora biti \%."""
    return re.sub(r"(?<!\\)%", r"\\%", math)

def _latex_to_pretext_math(text):
    # Zamijeni $...$ (inline LaTeX) u <m>...</m> (PreTeXt inline math oznaka).
    # Osnovna konverzija - ne hvata ugniježđene $ znakove unutar $...$.
    return re.sub(r"\$([^$]+)\$", lambda m: "<m>" + _escape_postotak_u_matematici(m.group(1)) + "</m>", text)

def _pretext_text(raw_text):
    return _latex_to_pretext_math(_xml_escape(_normalizuj_ostatke_ocr_escapinga(raw_text)))

def _izgleda_kao_recenica(raw):
    """Heuristika: ako sadrži razmak I ima više slova nego brojeva/simbola, vjerojatno je
    obična rečenica (npr. 'ne može se odrediti'), a ne matematički izraz."""
    if " " not in raw:
        return False
    slova = sum(c.isalpha() for c in raw)
    ostalo = len(raw) - slova
    return slova > ostalo

def _pretext_math_or_text(raw):
    r"""Za polja poput ponudjeni_odgovori/konacan_odgovor koja NISU dosljedno omotana u
    $...$ (za razliku od tekst_zadatka_latex): ako već sadrži $, ponašaj se kao _pretext_text.
    INAČE: DEFAULT je matematika (čak i jednostavan izraz poput '3x-9' bez ^/_/\ znakova -
    ranija verzija je to promašila kao 'obični tekst', što je u PDF izlazu gubilo prijelom
    retka u <ol> listi), OSIM ako izraz 'izgleda kao rečenica' (ima razmake, pretežno slova) -
    npr. 'ne može se odrediti' - tada ostaje običan tekst."""
    if raw is None:
        return ""
    raw = _normalizuj_ostatke_ocr_escapinga(str(raw))
    if "$" in raw:
        return _pretext_text(raw)
    if _izgleda_kao_recenica(raw):
        return _xml_escape(raw)
    return f"<m>{_escape_postotak_u_matematici(_xml_escape(raw))}</m>"

# ------------------------------------------------------- markdown pipe-tablice u tekstu zadatka
# 29.10.2026.: zadaci ciji tekst_zadatka_latex sadrzi markdown pipe-tablicu ("| $x$ | -3 | ... |"
# + separator redak "| :--- | :--- |" + redovi podataka) do sada su u PDF skriptu isli DOSLOVNO,
# sa sirovim "|" znakovima, jer cijeli tekst ide u JEDAN <p>. Streamlit pregled ih je prikazivao
# lijepo (st.markdown sam renderira GFM tablice), pa je greska bila nevidljiva sve do pravog PDF-a.
# PreTeXt <tabular> je BLOK element i NE SMIJE stajati unutar <p>, pa se tekst prvo razlomi na niz
# segmenata (tekst / tablica) i svaki dobije svoj blok. Zadatak BEZ tablice prolazi kroz tocno isti
# jedan <p> kao prije - v. _statement_tekst_lines i testovi/test_tablice_u_skripti.py.
# OPSEG: samo skripta (PreTeXt). Test Builder (pages/2_test_builder.py, pdflatex) ima isti
# nedostatak, ali je svjesno odgodjen za zaseban zadatak.

_PIPE_RED_RE = re.compile(r"^[ \t]*\|(.*)\|[ \t]*$")
_SEPARATOR_CELIJA_RE = re.compile(r":?-+:?")


def _podijeli_pipe_redak(sadrzaj):
    r"""Dijeli unutrasnjost jednog retka markdown tablice (bez vodeceg i zavrsnog "|") na popis
    celija. NE dijeli na "|" koji je unutar $...$ - bez toga bi matematika s apsolutnom
    vrijednosti ($|z-i|=2$, uobicajeno kod kompleksnih brojeva) bila razlomljena na pola i
    tablica bi dobila kriv broj stupaca. Znak iza "\" preuzima se doslovno, pa ni escapeani
    pipe (\|) ni escapeani dolar (\$) ne zavaraju podjelu."""
    stanice, buf, u_matematici = [], [], False
    i, n = 0, len(sadrzaj)
    while i < n:
        c = sadrzaj[i]
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(sadrzaj[i + 1])
            i += 2
            continue
        if c == "$":
            u_matematici = not u_matematici
        if c == "|" and not u_matematici:
            stanice.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    stanice.append("".join(buf).strip())
    return stanice


def _je_separator_redak(stanice):
    """Separator redak markdown tablice (drugi redak, npr. "| :--- | ---: |"): SVE celije su
    samo crtice i eventualne dvotocke (oznaka poravnanja), bez ikakvog sadrzaja."""
    return bool(stanice) and all(
        _SEPARATOR_CELIJA_RE.fullmatch(s.replace(" ", "")) for s in stanice)


def _pronadji_pipe_tablice(tekst):
    """Razlomi tekst na segmente [("t", tekst), ("tab", [[celija, ...], ...]), ...].

    Blok se priznaje kao tablica SAMO ako zaglavlje ima ODMAH ispod separator redak s ISTIM
    brojem stupaca i ako svaki sljedeci redak podataka ima taj isti broj stupaca. Cim nesto
    odstupa (AI ekstrakcija je izostavila celiju, zaglavlje bez separatora, tablica bez ijednog
    retka podataka), cijeli blok ostaje OBICAN TEKST - siguran fallback koji ne rusi build i ne
    gradi krivu tablicu, isto nacelo kao fallback za slike-opcije od 28.10.2026."""
    retci = (tekst or "").split("\n")
    segmenti, buf, i, n = [], [], 0, len(retci)

    def isprazni():
        if buf:
            segmenti.append(("t", "\n".join(buf)))
            buf.clear()

    while i < n:
        m = _PIPE_RED_RE.match(retci[i])
        if m and i + 1 < n:
            zaglavlje = _podijeli_pipe_redak(m.group(1))
            m2 = _PIPE_RED_RE.match(retci[i + 1])
            sep = _podijeli_pipe_redak(m2.group(1)) if m2 else None
            if (sep and len(sep) == len(zaglavlje) and _je_separator_redak(sep)
                    and not _je_separator_redak(zaglavlje)):
                j = i + 2
                redovi, ispravno = [], True
                while j < n:
                    mj = _PIPE_RED_RE.match(retci[j])
                    if not mj:
                        break
                    redak = _podijeli_pipe_redak(mj.group(1))
                    if len(redak) != len(zaglavlje):
                        ispravno = False
                        break
                    redovi.append(redak)
                    j += 1
                if ispravno and redovi:
                    isprazni()
                    segmenti.append(("tab", [zaglavlje] + redovi))
                    i = j
                    continue
        buf.append(retci[i])
        i += 1
    isprazni()
    return segmenti


_CELIJA_MATEMATICKI_ZNAK_RE = re.compile(r"[0-9+\-*/^_=<>\\(){}\[\]]")


def _celija_je_tekst(raw):
    """True ako je celija RIJEC ("disk", "kruznica", "Mjesec"), a ne matematicki izraz.

    Zasto posebno od _pretext_math_or_text: ta funkcija golu rijec BEZ razmaka salje u <m>
    (ispravno za "3x-9" u ponudjenim odgovorima), ali u tablici su jednoclane rijeci ceste kao
    zaglavlje ili vrijednost - a u matematickom fontu NEMA hrvatskih slova, pa xelatex tiho
    ispusti znak ("Missing character: There is no z in font cmmi9", uhvaceno pravim PDF
    buildom 29.10.2026.). Redoslijed provjera: recenica -> rijec s dijakritikom -> ima
    brojeva/operatora/zagrada (= matematika) -> cista slovna rijec od barem 2 slova."""
    if _izgleda_kao_recenica(raw):
        return True
    if any(c.isalpha() and ord(c) > 127 for c in raw):
        return True
    if _CELIJA_MATEMATICKI_ZNAK_RE.search(raw):
        return False
    slova = sum(c.isalpha() for c in raw)
    return slova >= 2 and slova == len(raw.replace(" ", ""))


def _pretext_celija(raw):
    r"""Jedna celija tablice. PRAZNA celija daje prazan sadrzaj (<cell></cell>), a ne <m></m> -
    to bi u LaTeX izlazu bila prazna formula \( \). Celija koja je RIJEC ostaje obican tekst
    (v. _celija_je_tekst), a sve ostalo ide kroz _pretext_math_or_text kao i ponudjeni
    odgovori: $ znaci matematiku, a goli izraz ("-3", "f(x)") ide u <m> da brojevi u tablici
    budu u matematickom fontu."""
    if raw is None or not str(raw).strip():
        return ""
    raw = _normalizuj_ostatke_ocr_escapinga(str(raw))
    if "$" not in raw and _celija_je_tekst(raw):
        return _xml_escape(raw)
    return _pretext_math_or_text(raw)


def _pretext_tabular_xml(redovi, uvlaka="          "):
    """Gradi PreTeXt <tabular> iz popisa redaka (PRVI redak je zaglavlje, kako markdown i
    definira). Tri tanke vodoravne crte: iznad tablice, ispod zaglavlja i ispod zadnjeg retka
    (izgled kao booktabs); okomitih crta nema, PreTeXt ih ionako ne preporucuje. <tabular> se
    ispisuje kao SAMOSTALAN blok (bez <table> omota) jer tablica unutar zadatka nije
    numerirana figura s naslovom, vec dio teksta zadatka.

    PAZI: bottom="minor" NA <tabular> se u PreTeXtu nasljeđuje na SVAKI redak (crta ispod
    svakog retka, izgled resetke) - provjereno pravim PDF buildom 29.10.2026. Zato donja crta
    ide na ZADNJI <row>, a ne na <tabular>."""
    if not redovi:
        return []
    zadnji = len(redovi) - 1
    out = [f'{uvlaka}<tabular top="minor">']
    for idx, redak in enumerate(redovi):
        atributi = ' header="yes"' if idx == 0 else ''
        if idx in (0, zadnji):
            atributi += ' bottom="minor"'
        out.append(f'{uvlaka}  <row{atributi}>')
        for celija in redak:
            out.append(f'{uvlaka}    <cell>{_pretext_celija(celija)}</cell>')
        out.append(f'{uvlaka}  </row>')
    out.append(f'{uvlaka}</tabular>')
    return out


# 30.10.2026. (PDF v1): AI uvoz za tablice vrijednosti katkad vrati PRAVI LaTeX tabular
# ("\begin{tabular}{|c|c|}\hline x \& f(x) \\ ...") umjesto markdown pipe tablice. PDF ga je
# ispisivao doslovno (prvi primjer i jos 3 mjesta u v1). Ove funkcije ga pretvore u pipe
# tablicu koju _pronadji_pipe_tablice vec zna pretvoriti u PreTeXt <tabular>.
_TABULAR_BLOK_RE = re.compile(
    r"\\begin\{tabular\}(?:\{(?:[^{}]|\{[^{}]*\})*\})?(.*?)\\end\{tabular\}", re.S)
_TABULAR_NAREDBA_RE = re.compile(
    r"\\(?:hline|toprule|midrule|bottomrule|arrayrulecolor\{[^}]*\}|"
    r"cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\})")
_TABULAR_RED_RE = re.compile(r"(?<!\\)\\\\")
_TABULAR_CELIJA_RE = re.compile(r"(?<!\\)&|\\&")


def _tabular_redovi(sadrzaj):
    """Razdvoji tijelo LaTeX tabulara na retke i celije (lista redaka, svaki lista stringova).
    Tolerira \\hline, \\multicolumn, escapeani \\& i prazne retke; redove poravna na istu
    sirinu (prazna celija umjesto kraja retka)."""
    sadrzaj = _TABULAR_NAREDBA_RE.sub("", sadrzaj or "")
    redovi = []
    for sirovi in _TABULAR_RED_RE.split(sadrzaj):
        sirovi = sirovi.strip()
        if not sirovi:
            continue
        sirovi = re.sub(r"\\multicolumn\{[^}]*\}\{[^}]*\}\{([^{}]*)\}", r"\1", sirovi)
        celije = [c.strip() for c in _TABULAR_CELIJA_RE.split(sirovi)]
        if any(celije):
            redovi.append(celije)
    if not redovi:
        return []
    sirina = max(len(r) for r in redovi)
    return [r + [""] * (sirina - len(r)) for r in redovi]


def _latex_tabular_u_tekst(tekst):
    """Tablicu pretvori u jedan citljiv redak ("x, f(x); -1, 7; 2, 1") - za rjesenja i kratke
    odgovore, gdje blok-tablica nije dopustena."""
    def _zamijeni(m):
        redovi = _tabular_redovi(m.group(1))
        if not redovi:
            return ""
        return "; ".join(", ".join(c for c in r if c) for r in redovi)

    return _TABULAR_BLOK_RE.sub(_zamijeni, tekst or "")


def _latex_tabular_u_pipe(tekst):
    """LaTeX tabular -> markdown pipe tablica (pa je _pronadji_pipe_tablice pretvori u
    <tabular>). Ako se iz tabulara ne izvuku barem 2 retka, vraca citljiv tekst - NIKAD
    sirovi \\begin{tabular}."""
    def _zamijeni(m):
        redovi = _tabular_redovi(m.group(1))
        if len(redovi) < 2:
            return _latex_tabular_u_tekst(m.group(0))
        zaglavlje = redovi[0]
        linije = ["| " + " | ".join(zaglavlje) + " |",
                  "| " + " | ".join(["---"] * len(zaglavlje)) + " |"]
        for redak in redovi[1:]:
            linije.append("| " + " | ".join(redak) + " |")
        return "\n" + "\n".join(linije) + "\n"

    return _TABULAR_BLOK_RE.sub(_zamijeni, tekst or "")


def _statement_tekst_lines(raw_tekst, oznaka, uvlaka="          "):
    """Niz <p>/<tabular> blokova za pocetak <statement> - zamjena za stari jedan
    <p>{oznaka}{tekst}</p>.

    oznaka ("[matura 2013, L] ") ide na PRVI <p>. Ako tekst POCINJE tablicom, oznaka dobije
    vlastiti <p> ispred tablice da se ne izgubi (ako je oznaka prazna, taj <p> se preskace -
    prazan <p> nije valjan sadrzaj). Prazan tekstualni segment IZA tablice se preskace (da ne
    nastane prazan <p> od praznog retka koji je u markdownu odvajao tablicu od teksta).

    REGRESIJA: kad u tekstu NEMA tablice, _pronadji_pipe_tablice vrati jedan jedini segment s
    nepromijenjenim tekstom, pa je izlaz znak-za-znak identican staroj verziji - to je ono sto
    stiti 17.000+ postojecih zadataka bez tablice (eksplicitno pokriveno testom)."""
    # 30.10.2026.: prvo LaTeX tabular -> pipe tablica (v. _latex_tabular_u_pipe iznad).
    raw_tekst = _latex_tabular_u_pipe(raw_tekst)
    segmenti = _pronadji_pipe_tablice(raw_tekst) if raw_tekst else []
    if not segmenti:
        return [f'{uvlaka}<p>{oznaka}{_pretext_text(raw_tekst)}</p>']
    izlaz, prvi = [], True
    for tip, sadrzaj in segmenti:
        if tip == "tab":
            if prvi and oznaka:
                izlaz.append(f'{uvlaka}<p>{oznaka}</p>')
            izlaz.extend(_pretext_tabular_xml(sadrzaj, uvlaka))
            prvi = False
        else:
            obradjen = _pretext_text(sadrzaj)
            if not obradjen.strip() and not prvi:
                continue
            izlaz.append(f'{uvlaka}<p>{oznaka if prvi else ""}{obradjen}</p>')
            prvi = False
    return izlaz

# Težina: sortiranje unutar potpoglavlja (lako -> srednje -> tesko) + vizualna oznaka
# [izvor, boja+težina] na početku svakog zadatka. Nepoznata/prazna težina ide na KRAJ
# grupe (99) da ne poremeti poredak lakši->teži, umjesto da nasumično upadne u sredinu.
_TEZINA_REDOSLIJED = {"lako": 0, "srednje": 1, "tesko": 2, "teško": 2}

def _tezina_sort_key(row):
    t = (row.get("tezina") or "").strip().lower()
    return _TEZINA_REDOSLIJED.get(t, 99)

# Ručni redoslijed UNUTAR svake tezina-grupe (30+ zadataka po potpoglavlju se više ne
# slažu proizvoljnim redoslijedom unosa u bazu - vidi polje redoslijed_u_potpoglavlju i
# stranicu "Redoslijed zadataka po potpoglavlju" u baza_zadataka_app.py). Prazna/nevaljana
# vrijednost ide na KRAJ svoje tezina-grupe (velik broj) umjesto da nasumično upadne u sredinu.
def _redoslijed_u_potpoglavlju_sort_key(row):
    v = (row.get("redoslijed_u_potpoglavlju") or "").strip()
    if not v:
        return 1_000_000.0
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return 1_000_000.0

def _puni_sort_key(row):
    """Kombinirani ključ za sortiranje zadataka unutar jedne (pot)sekcije: prvo težina
    (lako -> srednje -> tesko), PA unutar iste težine ručni redoslijed_u_potpoglavlju."""
    return (_tezina_sort_key(row), _redoslijed_u_potpoglavlju_sort_key(row))

_TEZINA_OZNAKA = {
    # 12.10.2026.: slova umjesto emoji kruzica (fontovi u PDF-u nemaju emoji). Legenda je u
    # naslovnom dijelu skripte (TEZINA_LEGENDA).
    "lako": "L",
    "lagano": "L",
    "srednje": "S",
    "tesko": "T",
    "teško": "T",
}
TEZINA_LEGENDA = "Oznake težine: L – lagano, S – srednje, T – teško."

def _oznaka_izvor_tezina(row):
    """Gradi prefiks '[izvor, L] ' ispred teksta zadatka (L/S/T = lagano/srednje/teško,
    vidi TEZINA_LEGENDA). Slova umjesto emoji kružića jer ih PDF fontovi ne ispisuju.

    Naziv izvora ovisi o izvor_tip (4 moguće vrijednosti u Sheetu: matura, zbirka,
    udzbenik, vlastiti_materijal):
    - "matura"            -> "matura <godina>" (npr. "matura 2010")
    - "zbirka"            -> BEZ naziva izvora (samo težina) - od 30.10.2026., Cakijev PDF v1
    - "udzbenik" / "vlastiti_materijal" (i sve ostalo/nepoznato) -> BEZ naziva izvora,
      prikazuje se samo težina."""
    izvor_tip = (row.get("izvor_tip") or "").strip().lower()
    godina = (row.get("godina") or "").strip()
    tezina_raw = (row.get("tezina") or "").strip().lower()
    tezina_txt = _TEZINA_OZNAKA.get(tezina_raw, tezina_raw)

    izvor_txt = ""
    if izvor_tip == "matura":
        izvor_txt = f"matura {godina}".strip() if godina else "matura"
    # 30.10.2026. (Caki, PDF v1): "zbirka" se NE ispisuje - oznaka je samo težina, npr. "[S]".
    # Naziv konkretne zbirke je ionako u biblioteka_izvora (interno), a ponavljanje "zbirka"
    # na svakom zadatku samo troši prostor.
    # "udzbenik", "vlastiti_materijal" i sve ostalo -> izvor_txt ostaje prazan (samo težina)

    dijelovi = [d for d in [izvor_txt, tezina_txt] if d]
    if not dijelovi:
        return ""
    return f"[{', '.join(dijelovi)}] "

_PRIMJERI_SERIJA_RE = re.compile(r"(?i)(?:^|[_\s\-])primjeri?(?:[_\s\-]?\d+)?\s*$")


def _je_primjer_na_satu(row):
    """True ako je zadatak označen kao 'primjer na satu' (koristi_kao_primjer_na_satu="da") -
    ide u <example> blok umjesto u <exercises>, vidi _build_inner_content.

    30.10.2026.: osim kvačice, priznaje i NAZIV SERIJE ('..._primjeri', '..._Primjeri_016') -
    materijal uvezen preko 'Uvoz iz foldera' nosi to u izvor_naziv, pa primjer ostaje primjer
    i ako kvačica na pojedinom retku iz nekog razloga nije upisana. Redak iz serije '_zadaci'
    time NIKAD ne postaje primjer."""
    if (row.get("koristi_kao_primjer_na_satu") or "").strip().lower() == "da":
        return True
    return bool(_PRIMJERI_SERIJA_RE.search(str(row.get("izvor_naziv") or "")))


_SLIKA_OPCIJA_RE = re.compile(r"(?i)^slika\s*[A-H]$")


def _build_statement_hint_solution_video(row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=True):
    """Zajednička jezgra za <exercise> I <example>: <statement> (tekst + opcionalna slika +
    opcije za visestruki_izbor), <hint>, <solution>, <video>. Vraća (lines, slika_ok) BEZ
    vanjskog <exercise>/<example> omota - pozivatelj (_build_exercise_lines ili
    _build_example_lines) dodaje xml:id i ispravan naziv taga. Izdvojeno iz stare
    _build_exercise_lines (§27.3) da <example> ne duplicira istu logiku ručno.

    30.10.2026.: ukljuci_rjesenje=False NE upisuje <solution> (niti kopira slike rješenja) -
    koristi ga skripta iz knjige za primjere u učeničkoj verziji. Zadano True = identično
    staro ponašanje za sve postojeće pozive."""
    raw_tekst = str(row.get('tekst_zadatka_latex', '') or '')
    oznaka = _xml_escape(_oznaka_izvor_tezina(row))
    rjesenje = _latex_tabular_u_tekst((row.get('rjesenje') or '').strip())
    video_url = (row.get('video_url') or '').strip()
    slika_putanja = (row.get('slika_putanja') or '').strip()
    tip_zadatka = (row.get('tip_zadatka') or '').strip()
    ponudjeni_odgovori_raw = (row.get('ponudjeni_odgovori') or '').strip()
    konacan_odgovor = _latex_tabular_u_tekst((row.get('konacan_odgovor') or '').strip())
    uputa = (row.get('uputa') or '').strip()

    lines = []
    lines.append(f'        <statement>')
    lines.extend(_statement_tekst_lines(raw_tekst, oznaka))

    opcije = []
    if tip_zadatka == "visestruki_izbor" and ponudjeni_odgovori_raw:
        opcije = [o.strip() for o in ponudjeni_odgovori_raw.split("||") if o.strip()]

    # 28.10.2026.: OPCIJE VIŠESTRUKOG IZBORA koje su same slike/crteži/grafovi (ne tekst) - v. D6
    # u sistemskom promptu uvoz_foldera.py ("Ako su same opcije slike..."). AI tad sprema
    # ponudjeni_odgovori kao placeholder "slika A"/"slika B"/... (redoslijedom A,B,C...), a
    # STVARNE slike idu u slika_url/slika_putanja istim redoslijedom - uz JOŠ JEDNU sliku ISPRED
    # (slika samog PITANJA) kad pitanje I opcije imaju slike (D6: "prvo slika pitanja, zatim
    # slike opcija"). Prepoznaje se ISKLJUČIVO kad SVE opcije odgovaraju obrascu "slika <slovo>"
    # (case-insensitive) - običan tekst/brojčane opcije ovo nikad ne pogode (provjereno uživo
    # 28.10.2026.: 0 od 1105 trenutnih visestruki_izbor redaka u bazi ima ovaj obrazac - nema
    # rizika regresije na postojeće zadatke). Broj slika koji se ne poklapa s brojem opcija (ni
    # jednako, ni +1) je siguran FALLBACK na staro ponašanje (generička galerija slika + tekstualna
    # lista opcija) - ne pucamo, samo gubimo "slika uz slovo" prikaz za taj rub slučaj.
    opcije_su_slike = bool(opcije) and len(opcije) >= 2 and all(_SLIKA_OPCIJA_RE.match(o) for o in opcije)

    slika_ok = False
    # slika_putanja je SAMO naziv datoteke (ili više njih odvojenih "|", vidi razdvoji_slike) -
    # puni izvor je 02_SLIKE/<naziv>, kopiramo u 03_PRETEXT_IZVOR/images/<naziv>.
    nazivi_slika = [os.path.basename(x) for x in razdvoji_slike(slika_putanja)]
    slika_pitanja = None
    slike_opcija = {}
    if opcije_su_slike and len(nazivi_slika) == len(opcije):
        slike_opcija = dict(enumerate(nazivi_slika))
    elif opcije_su_slike and len(nazivi_slika) == len(opcije) + 1:
        slika_pitanja = nazivi_slika[0]
        slike_opcija = dict(enumerate(nazivi_slika[1:]))
    else:
        opcije_su_slike = False  # broj slika ne odgovara broju opcija - sigurni fallback na staro

    def _kopiraj_i_oznaci(naziv_datoteke):
        izvorna = os.path.join(slike_izvor_dir, naziv_datoteke)
        if os.path.exists(izvorna):
            shutil.copyfile(izvorna, os.path.join(images_dir_abs, naziv_datoteke))
            return f'<image source="images/{_xml_escape(naziv_datoteke)}" width="70%"/>'
        print(f"    ⚠️ Slika nije pronađena na disku za zadatak #{row.get('id', '')}: {izvorna}")
        return None

    if opcije_su_slike:
        if slika_pitanja:
            tag = _kopiraj_i_oznaci(slika_pitanja)
            if tag:
                slika_ok = True
                lines.append(f'          {tag}')
    else:
        for naziv_datoteke in nazivi_slika:
            tag = _kopiraj_i_oznaci(naziv_datoteke)
            if tag:
                slika_ok = True
                lines.append(f'          {tag}')

    if opcije:
        lines.append('          <ol marker="A.">')
        for i, opcija in enumerate(opcije):
            sadrzaj = None
            if opcije_su_slike:
                naziv_datoteke = slike_opcija.get(i)
                tag = _kopiraj_i_oznaci(naziv_datoteke) if naziv_datoteke else None
                if tag:
                    slika_ok = True
                    sadrzaj = tag
            if sadrzaj is None:
                sadrzaj = _pretext_math_or_text(opcija)  # tekst, ili fallback kad slika opcije nedostaje na disku
            lines.append(f'            <li><p>{sadrzaj}</p></li>')
        lines.append('          </ol>')

    lines.append(f'        </statement>')

    if uputa:
        # <hint> mora doći NAKON </statement> i PRIJE <solution> po PreTeXt shemi.
        lines.append(f'        <hint>')
        lines.append(f'          <p>{_pretext_math_or_text(uputa)}</p>')
        lines.append(f'        </hint>')

    # Slike rješenja (stupac slika_rjesenje_putanja): kopiraju se u images/ i ispisuju u <solution>
    # iza teksta rješenja. Nedostajuća datoteka se preskače uz upozorenje (kao kod slike zadatka).
    # 30.10.2026.: kad rješenje NE ide u ovaj dokument (učenička verzija primjera), ne kopiramo
    # ni njegove slike - inače bi u PDF-u ostale visjeti bez teksta.
    if ukljuci_rjesenje:
        slike_rjesenja_linije = []
        for naziv_datoteke in (os.path.basename(x) for x in razdvoji_slike(row.get('slika_rjesenje_putanja'))):
            izvorna = os.path.join(slike_izvor_dir, naziv_datoteke)
            if os.path.exists(izvorna):
                shutil.copyfile(izvorna, os.path.join(images_dir_abs, naziv_datoteke))
                slike_rjesenja_linije.append(f'          <image source="images/{_xml_escape(naziv_datoteke)}" width="70%"/>')
            else:
                print(f"    ⚠️ Slika rješenja nije pronađena na disku za zadatak #{row.get('id', '')}: {izvorna}")

        if rjesenje or slike_rjesenja_linije:
            lines.append(f'        <solution>')
            if tip_zadatka == "visestruki_izbor" and konacan_odgovor:
                lines.append(f'          <p>Točan odgovor: {_pretext_math_or_text(konacan_odgovor)}</p>')
            if rjesenje:
                lines.append(f'          <p>{_pretext_math_or_text(rjesenje)}</p>')
            lines.extend(slike_rjesenja_linije)
            lines.append(f'        </solution>')
        elif konacan_odgovor:
            lines.append(f'        <solution>')
            lines.append(f'          <p>Odgovor: {_pretext_math_or_text(konacan_odgovor)}</p>')
            lines.append(f'        </solution>')

    if video_url:
        # Napomena §27.4 (sljedeći korak, NE dio ove izmjene): ovdje se video_url i dalje
        # koristi sirovo - ekstrakcija YouTube ID-a iz pune URL adrese dolazi u §27.4.
        lines.append(f'        <video youtube="{_xml_escape(video_url)}"/>')

    return lines, slika_ok


def _konacan_odgovor_za_prikaz(row) -> str:
    """Konačan odgovor za VERZIJU ZA PROFESORA (na kraju skripte, skupina „Primjeri
    rješenja”): prvo 'konacan_odgovor', a ako je prazan, uzima se 'rjesenje' (u bazi je za
    dio primjera cijeli postupak upisan tu). Vraća prazno ako nema nijednog - tada se u
    popisu ispisuje „—”. Tablice se spljošte u čitljiv tekst (v. _latex_tabular_u_tekst)."""
    for polje in ("konacan_odgovor", "rjesenje"):
        vrijednost = _latex_tabular_u_tekst(str(row.get(polje) or "").strip())
        if vrijednost:
            return vrijednost
    return ""


def _build_exercise_lines(row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=True):
    """Gradi <exercise> XML za jedan redak - VJEŽBA koju učenik rješava sam (rješenje
    sakriveno/na klik u HTML izlazu). Vraća (lines, slika_kopirana_bool).
    ukljuci_rjesenje=False -> bez <solution> (v. _build_statement_hint_solution_video)."""
    zid = _sanitize_id(f"zad-{row.get('id', '')}")
    body_lines, slika_ok = _build_statement_hint_solution_video(
        row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=ukljuci_rjesenje)
    lines = [f'      <exercise xml:id="{zid}">'] + body_lines + ['      </exercise>']
    return lines, slika_ok


def _build_example_lines(row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=True,
                         prikazi_odgovor=False):
    """Gradi <example> XML za jedan redak - riješen PRIMJER koji profesor demonstrira NA SATU
    (rješenje se prikazuje kao dio izlaganja, ne kao skriveni odgovor). Semantički odvojeno od
    <exercise>. Ide direktno kao dijete <section>, BEZ <exercises> omota (PreTeXt shema:
    <example> ne treba wrapper, može ih biti više uzastopnih). Zaseban ID-prefiks ('prim-'
    umjesto 'zad-') da isti redak, ako se ikad pojavi na oba mjesta greškom, ne izazove
    xml:id sudar. Vraća (lines, slika_kopirana_bool).

    30.10.2026. (skripta iz knjige): učenička verzija zove s ukljuci_rjesenje=False (primjer
    bez rješenja - profesor ga rješava na satu), a verzija za profesora s
    prikazi_odgovor=True (samo konačan odgovor uz primjer, NE cijeli postupak)."""
    zid = _sanitize_id(f"prim-{row.get('id', '')}")
    body_lines, slika_ok = _build_statement_hint_solution_video(
        row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=ukljuci_rjesenje)
    if prikazi_odgovor:
        odgovor = _konacan_odgovor_za_prikaz(row)
        if odgovor:
            body_lines = body_lines + [
                f'        <p><em>Rješenje: {_pretext_math_or_text(odgovor)}</em></p>']
    lines = [f'      <example xml:id="{zid}">'] + body_lines + ['      </example>']
    return lines, slika_ok

def _build_introduction_lines(teorija_row, verzija="ucenik"):
    """Gradi <introduction> blok (§27.2) iz jednog retka Teorija_potpoglavlja (dict s
    TEORIJA_HEADERS ključevima), ili None ako nema teksta (izostavlja se, bez greške).

    Odlomci se dijele preko teorija_markup.teorija_u_ptx_odlomke (14.9.2026., §27.5) -
    ta funkcija prepoznaje tri konvencije koje se tipkaju izravno u tekst_teorije_latex:
    !!isticanje!! (-> <alert>), \\pojam{Naziv} (-> <term>), i [RJESENJE]...[/RJESENJE]
    blokove (postupak koji profesor pokazuje uživo, NE ide u učeničku verziju). $...$
    matematika i XML-escaping i dalje idu kroz POSTOJEĆU _pretext_text - prosljeđuje se
    kao `render` callback, primjenjuje se SAMO na običan tekst (nikad na već umetnute
    <alert>/<term> oznake, da se one ne dvostruko-eskejpaju).

    verzija="ucenik" (zadano) - [RJESENJE] blokovi se u potpunosti izbacuju iz izlaza.
    verzija="profesor"        - [RJESENJE] blokovi ostaju, umotani u <remark>.

    Ako je veza_vjezbaj popunjena, dodaje se poveznica "Vježbaj ovo" na kraju uvoda.
    Ako je video_url popunjen, dodaje se <video> na kraju (isto sirovo kao kod zadataka -
    ekstrakcija ID-a je §27.4)."""
    if not teorija_row:
        return None
    tekst = (teorija_row.get("tekst_teorije_latex") or "").strip()
    if not tekst:
        return None
    video_url = (teorija_row.get("video_url") or "").strip()
    veza_vjezbaj = (teorija_row.get("veza_vjezbaj") or "").strip()

    lines = ['      <introduction>']
    for sadrzaj in teorija_u_ptx_odlomke(tekst, verzija=verzija, render=_pretext_text):
        if sadrzaj.startswith("<remark>"):
            # <remark> blok (rjesenje, samo verzija="profesor") stiže VEC potpuno
            # omotan iz teorija_u_ptx_odlomke, s <p> tagovima oko svakog odlomka -
            # ne dodavati jos jedan <p> omot oko cijelog bloka.
            lines.append(f'        {sadrzaj}')
        else:
            lines.append(f'        <p>{sadrzaj}</p>')
    if veza_vjezbaj:
        lines.append(f'        <p>Vježbaj ovo: <url href="{_xml_escape(veza_vjezbaj)}">praksa.cakipoduka.com</url></p>')
    if video_url:
        lines.append(f'        <video youtube="{_xml_escape(video_url)}"/>')
    lines.append('      </introduction>')
    return lines

def _build_inner_content(zadaci_redovi, xml_id_root, potpoglavlja_redoslijed, images_dir_abs, slike_izvor_dir,
                          cjelina=None, teorija_po_potpoglavlju=None, verzija_teorije="ucenik",
                          filtriraj_u_skriptu=False, filtri=None):
    """Vraća (lines, broj_slika) - unutrašnji sadržaj BEZ vanjskog <article>/<title> omota:
    ako je potpoglavlja_redoslijed zadan, grupira zadatke u <section> po potpoglavlju
    (redoslijedom iz šifrarnika; zadaci bez prepoznatog potpoglavlja idu u 'Ostalo' na kraju);
    inače stavlja sve ravno u jedan <exercises> blok (plus eventualni <example> blokovi ispred).

    §27.3: unutar svake grupe (cijela baza BEZ sekcija, ili jedno potpoglavlje), zadaci s
    koristi_kao_primjer_na_satu="da" idu KAO <example> blokovi PRIJE <exercises>, i NISU
    ponovljeni unutar <exercises> - svaki zadatak je ili primjer ILI vježba, nikad oboje.

    §27.2: ako su OBA cjelina i teorija_po_potpoglavlju zadana, svaka sekcija potpoglavlja
    dobiva <introduction> na početku (prije <example>/<exercises>) AKO postoji unesena
    teorija za taj par. Izostavljanje ovih parametara (stari pozivi) ponaša se identično
    kao prije - unatrag kompatibilno. Vrijedi SAMO za sekcionirani slučaj (po potpoglavlju),
    ne za neskecionirani blok niti za grupu bez potpoglavlja ("Ostalo").

    §27.5 (14.9.2026., "skripta"): filtriraj_u_skriptu=True ograničava zadaci_redovi SAMO na
    retke gdje je stupac 'u_skriptu' = "DA" (vidi filtriraj_zadatke_za_skriptu.py) - za PDF
    "skriptu" (tiskano, fiksan skup "zadaci za rad na satu"). Web/HTML build i dalje poziva
    bez ovog parametra (zadano False) i prikazuje CIJELI fond, bez ikakve promjene ponašanja.
    verzija_teorije se prosljeđuje u _build_introduction_lines (v. ondje) - zadano "ucenik"
    je neutralno za postojeći sadržaj koji još ne koristi [RJESENJE] konvenciju."""
    if filtriraj_u_skriptu:
        zadaci_redovi = filtriraj_zadatke_za_skriptu(zadaci_redovi)
    if filtri:  # 11.10.2026.: visestruki filtri (razina, cjelina, izvor, godina...)
        zadaci_redovi = filtriraj_zadatke(zadaci_redovi, filtri)

    lines = []
    broj_slika = 0

    def _dodaj_primjere_i_vjezbe(redovi, base_indent):
        """Za jednu grupu redaka: prvo <example> blokovi (primjeri na satu, sortirano po
        _puni_sort_key kao i sve ostalo), pa <exercises> blok s ostatkom (isto sortirano).
        Vraća (lines, broj_slika)."""
        unutra = []
        slika_brojac = 0
        primjeri = sorted([r for r in redovi if _je_primjer_na_satu(r)], key=_puni_sort_key)
        vjezbe = sorted([r for r in redovi if not _je_primjer_na_satu(r)], key=_puni_sort_key)

        for row in primjeri:
            ex_lines, slika_ok = _build_example_lines(row, images_dir_abs, slike_izvor_dir)
            unutra.extend(ex_lines)
            slika_brojac += 1 if slika_ok else 0

        unutra.append(f'{base_indent}<exercises>')
        for row in vjezbe:
            ex_lines, slika_ok = _build_exercise_lines(row, images_dir_abs, slike_izvor_dir)
            unutra.extend(ex_lines)
            slika_brojac += 1 if slika_ok else 0
        unutra.append(f'{base_indent}</exercises>')
        return unutra, slika_brojac

    if not potpoglavlja_redoslijed:
        dio, s = _dodaj_primjere_i_vjezbe(zadaci_redovi, '    ')
        lines.extend(dio)
        broj_slika += s
        return lines, broj_slika

    po_potpoglavlju = {}
    for row in zadaci_redovi:
        potpoglavlje = (row.get('potpoglavlje') or '').strip()
        po_potpoglavlju.setdefault(potpoglavlje, []).append(row)

    poznati = [p for p, _ in potpoglavlja_redoslijed]
    redoslijed_kljuceva = [p for p in poznati if p in po_potpoglavlju]
    for p in po_potpoglavlju:  # potpoglavlja koja postoje u zadacima, ali NISU u šifrarniku
        if p and p not in redoslijed_kljuceva:
            redoslijed_kljuceva.append(p)
    if "" in po_potpoglavlju:  # zadaci bez ikakvog potpoglavlja - uvijek zadnji
        redoslijed_kljuceva.append("")

    for potpoglavlje in redoslijed_kljuceva:
        grupa = po_potpoglavlju[potpoglavlje]
        naslov_sekcije = potpoglavlje if potpoglavlje else "Ostalo (bez dodijeljenog potpoglavlja)"
        sec_id = _sanitize_id(f"{xml_id_root}-{potpoglavlje or 'ostalo'}")
        lines.append(f'    <section xml:id="{sec_id}">')
        lines.append(f'      <title>{_xml_escape(naslov_sekcije)}</title>')
        if cjelina and potpoglavlje and teorija_po_potpoglavlju:
            intro_lines = _build_introduction_lines(
                teorija_po_potpoglavlju.get((cjelina, potpoglavlje)), verzija=verzija_teorije)
            if intro_lines:
                lines.extend(intro_lines)
        dio, s = _dodaj_primjere_i_vjezbe(grupa, '      ')
        lines.extend(dio)
        broj_slika += s
        lines.append('    </section>')

    return lines, broj_slika

def build_pretext_article(naslov, zadaci_redovi, xml_id_root, images_dir_abs, slike_izvor_dir, potpoglavlja_redoslijed=None,
                           cjelina=None, teorija_po_potpoglavlju=None, verzija_teorije="ucenik",
                           filtriraj_u_skriptu=False, filtri=None):
    """Gradi samostalan PreTeXt dokument: <pretext><article>...</article></pretext>
    (root mora biti <pretext> po PreTeXt shemi - ranija verzija je to preskakala).
    cjelina/teorija_po_potpoglavlju: v. _build_inner_content (§27.2, opcionalno).
    verzija_teorije/filtriraj_u_skriptu: v. _build_inner_content (§27.5, opcionalno,
    zadano ponašanje = identično prijašnjem, bez promjene za postojeće pozive)."""
    inner_lines, broj_slika = _build_inner_content(
        zadaci_redovi, xml_id_root, potpoglavlja_redoslijed, images_dir_abs, slike_izvor_dir,
        cjelina=cjelina, teorija_po_potpoglavlju=teorija_po_potpoglavlju,
        verzija_teorije=verzija_teorije, filtriraj_u_skriptu=filtriraj_u_skriptu, filtri=filtri)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<pretext>',
             f'  <article xml:id="{_sanitize_id(xml_id_root)}">',
             f'    <title>{_xml_escape(naslov)}</title>']
    lines.extend(inner_lines)
    lines.append('  </article>')
    lines.append('</pretext>')
    return "\n".join(lines), broj_slika

# 12.10.2026. - izgled PDF-a skripte: hrvatski nazivi blokova (PreTeXt nema hr-HR lokalizaciju,
# pa ih docinfo/rename prepisuje), naslovni dio i legenda tezine.
SKRIPTA_AUTOR = "Caki Centar"
SKRIPTA_WEB = "cakipoduka.com"
_SKRIPTA_RENAME = {
    "exercises": "Zadaci", "exercise": "Zadatak", "example": "Primjer", "hint": "Uputa",
    "solution": "Rješenje", "solutions": "Rješenja", "answer": "Odgovor",
    "toc": "Sadržaj", "figure": "Slika", "table": "Tablica",
}

def _skripta_docinfo_lines():
    lines = ['  <docinfo>']
    lines.append('    <directories external="../external"/>')
    for element, naziv in _SKRIPTA_RENAME.items():
        lines.append(f'    <rename element="{element}">{_xml_escape(naziv)}</rename>')
    lines.append('  </docinfo>')
    return lines

def _skripta_frontmatter_lines():
    """Naslovni podaci (autor, web) u bibinfo; legenda tezine se ispisuje u LaTeX naslovu
    (skripta_build.STIL_PREAMBULA)."""
    return [
        '    <frontmatter>',
        '      <bibinfo>',
        f'        <author><personname>{_xml_escape(SKRIPTA_AUTOR)}</personname>'
        f'<affiliation><institution>{_xml_escape(SKRIPTA_WEB)}</institution></affiliation></author>',
        '      </bibinfo>',
        '      <titlepage><titlepage-items/></titlepage>',
        '    </frontmatter>',
    ]

def _skripta_backmatter_lines(primjeri_rjesenja=None):
    """Rješenja na kraju skripte, u DVIJE skupine (Cakijev PDF v1, 30.10.2026.):
    „Primjeri rješenja” (samo u verziji za profesora - konačni odgovori uz primjere) i
    „Zadaci rješenja” (puna rješenja zadataka; PreTeXt ih tamo premješta iz <exercises>).

    primjeri_rjesenja: lista {"naslov": naziv poglavlja, "stavke": [(oznaka, odgovor), ...]}
    ili None/[] za učeničku verziju (tada je naslov samo „Rješenja zadataka”).

    30.10.2026. (VAŽNO): primjeri rješenja idu u ZASEBNU <solutions> diviziju BEZ
    @divisional - PreTeXt u diviziju s @divisional="solution" ubacuje rješenja zadataka
    (dokazano u pretext-common.xsl: contains(@divisional,'solution')). Da su primjeri u
    istoj diviziji, PreTeXt bi u nju ubacio i rješenja zadataka pa bi redoslijed/uvod bili
    nepredvidivi. Ovako je prva divizija isključivo „Primjeri rješenja”, druga isključivo
    „Zadaci rješenja”."""
    if not primjeri_rjesenja:
        return [
            '    <backmatter>',
            '      <solutions divisional="solution">',
            '        <title>Rješenja zadataka</title>',
            '      </solutions>',
            '    </backmatter>',
        ]
    lines = [
        '    <backmatter>',
        '      <solutions>',
        '        <title>Rješenja</title>',
        '        <introduction>',
        '          <title>Primjeri rješenja</title>',
    ]
    for grupa in primjeri_rjesenja:
        lines.append(f'          <p><strong>{_xml_escape(grupa["naslov"])}</strong></p>')
        # 30.10.2026.: NAMJERNO obicni <p> po primjeru, NE <ul>/<li> - PreTeXt shema u
        # <introduction> dopusta samo BlockDivision (Paragraph, Tabular, ...), a lista nije
        # BlockDivision. <ul> bi srusio validaciju/build.
        for oznaka, odgovor in grupa["stavke"]:
            lines.append(
                f'          <p><strong>{_xml_escape(oznaka)}</strong> '
                f'{_pretext_math_or_text(odgovor or "—")}</p>')
    lines += [
        '        </introduction>',
        '      </solutions>',
        '      <solutions divisional="solution">',
        '        <title>Zadaci rješenja</title>',
        '      </solutions>',
        '    </backmatter>',
    ]
    return lines

def izgradi_skriptu_xml(rows, zahtjev, potpoglavlja_po_cjelini, images_dir_abs, slike_izvor_dir,
                         teorija_po_potpoglavlju=None):
    """11.10.2026. - JEDNA funkcija koju Colab zove za skriptu: uzme SVE retke taba 'Zadaci'
    (list rjecnika) i zahtjev iz ucitaj_zadnji_zahtjev_skripte(), primijeni filtre i vrati
    (xml_string, broj_slika, broj_zadataka, naslov).
    - jedna cjelina u rezultatu -> <article> s potpoglavljima (+ teorija ako postoji)
    - vise cjelina -> svaka cjelina je <section> (redoslijed iz sifrarnika, ostale abecedno)
    - 0 zadataka nakon filtriranja -> xml je None (pozivatelj ispisuje poruku)."""
    filtri = normaliziraj_filtre(zahtjev.get("filtri"))
    verzija = zahtjev.get("verzija_teorije") or "ucenik"
    odabrani = filtriraj_zadatke(rows, filtri)
    # 12.10.2026.: naslov i podnaslov mogu doci iz zahtjeva (polja na stranici Skripta);
    # bez naslova ostaje automatski "Skripta - <opis filtara>".
    naslov = " ".join((zahtjev.get("naslov") or "").split()) or ("Skripta - " + opis_filtara(filtri))
    podnaslov = " ".join((zahtjev.get("podnaslov") or "").split())
    if not odabrani:
        return None, 0, 0, naslov

    po_cjelini = {}
    for r in odabrani:
        c = (r.get("cjelina") or "").strip() or "Nekategorizirano"
        po_cjelini.setdefault(c, []).append(r)
    redoslijed = [c for c in potpoglavlja_po_cjelini if c in po_cjelini]
    redoslijed += sorted(c for c in po_cjelini if c not in redoslijed)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<pretext>']
    lines += _skripta_docinfo_lines()
    lines += ['  <article xml:id="skripta">', f'    <title>{_xml_escape(naslov)}</title>']
    if podnaslov:
        lines.append(f'    <subtitle>{_xml_escape(podnaslov)}</subtitle>')
    lines += _skripta_frontmatter_lines()
    broj_slika = 0
    jedna = len(redoslijed) == 1
    for c in redoslijed:
        if not jedna:
            lines.append(f'    <section xml:id="{_sanitize_id("skripta-" + c)}">')
            lines.append(f'      <title>{_xml_escape(c)}</title>')
        inner, s_ = _build_inner_content(
            po_cjelini[c], f"skripta-{c}", potpoglavlja_po_cjelini.get(c),
            images_dir_abs, slike_izvor_dir, cjelina=c,
            teorija_po_potpoglavlju=teorija_po_potpoglavlju, verzija_teorije=verzija)
        if not jedna:
            # cjelina je <section>, pa su potpoglavlja unutar nje <subsection> (PreTeXt ne
            # dopusta <section> unutar <section>; bez ovoga je numeracija ravna 1,2,3...
            # umjesto 1, 1.1, 1.2 i poglavlje "Rjesenja" ostaje prazno).
            inner = [l.replace("<section ", "<subsection ").replace("</section>", "</subsection>")
                     for l in inner]
        lines.extend(inner)
        broj_slika += s_
        if not jedna:
            lines.append('    </section>')
    lines += _skripta_backmatter_lines()
    lines += ['  </article>', '</pretext>']
    return "\n".join(lines), broj_slika, len(odabrani), naslov

# --- "Skripta" KRONOLOSKI po poglavlju izvora (28.10.2026., na Cakijev zahtjev) ---
#
# Za skriptu sastavljenu IZ JEDNOG udzbenika/materijala ("Uvoz iz foldera", nazivlje
# PoglavljeX.Y_Primjeri / PoglavljeX.Y_zadaci) poredak po kurikulumskoj cjelina/potpoglavlje
# (izgradi_skriptu_xml iznad) NE odgovara - treba ici REDOSLIJEDOM KNJIGE, poglavlje po
# poglavlje, Primjeri prije Zadataka unutar svakog poglavlja, BEZ sortiranja po tezini (to bi
# razbilo redoslijed materijala). Ne dira NISTA postojece (izgradi_skriptu_xml,
# _build_inner_content, _dodaj_primjere_i_vjezbe ostaju netaknuti) - ovo je ZASEBAN,
# PARALELAN put koji iznova koristi iste niskorazinske graditelje (_build_example_lines,
# _build_exercise_lines - genericki, ne znaju nista o cjelini/potpoglavlju).
#
# Redoslijed zadataka UNUTAR poglavlja = redoslijed redaka u tabu 'Zadaci' (NE sortira se) -
# to vec odgovara redoslijedu skeniranja JER "Uvoz iz foldera" (nadopuni_ili_dodaj_zadatke)
# dodaje retke append_rows() redoslijedom AI izlaza = redoslijedom privremeni_broj iz skena,
# POD UVJETOM da se poglavlja upisuju jedno za drugim (normalan tijek rada), bez naknadnog
# premetanja redaka u Sheetu.

_POGLAVLJE_SUFIKS_RE = re.compile(r"(?i)[_\s\-]+(primjeri?|zada(?:ci|tci|tak))(?:[_\s\-]?\d+)?\s*$")

def parsiraj_poglavlje_iz_izvora(izvor_naziv: str) -> str:
    """'Poglavlje3.1_zadaci' -> 'Poglavlje3.1'; 'Poglavlje3.1_Primjeri' -> 'Poglavlje3.1' -
    tako se Primjeri i Zadaci istog poglavlja spoje u ISTU skripta-sekciju. Ako naziv ne
    zavrsava poznatim sufiksom, vraca se NETAKNUT (siguran fallback - u najgorem slucaju
    Primjeri/Zadaci ostanu kao dvije odvojene sekcije, nista ne puca).

    30.10.2026.: sufiks smije imati i redni broj ('Poglavlje2.14_primjeri_016') - Caki tako
    naziva stavke u bazi. Bez toga bi svaka stavka postala svoje poglavlje."""
    naziv = (izvor_naziv or "").strip()
    novi = _POGLAVLJE_SUFIKS_RE.sub("", naziv).strip()
    return novi or naziv


_POGLAVLJE_BROJ_RE = re.compile(r"^(\D*)(\d+(?:\.\d+)*)\s*$")

def _poglavlje_sort_key(naziv: str):
    """Prirodni poredak za nazive oblika 'Poglavlje3.1'/'Poglavlje3.10'/'Poglavlje4.2' -
    brojevi odvojeni tockom usporedjuju se KOMPONENTA PO KOMPONENTU kao verzije (3.10 poslije
    3.9), NE kao decimalni razlomak (3.10 == 3.1 kao float - bila bi pogresna usporedba).
    Nazivi koji ne odgovaraju obrascu idu na kraj (abecedno medju sobom), ne nasumicno u sredinu."""
    m = _POGLAVLJE_BROJ_RE.match((naziv or "").strip())
    if not m:
        return (1, (naziv or "").lower(), ())
    prefiks, broj = m.groups()
    komponente = tuple(int(x) for x in broj.split("."))
    return (0, prefiks.lower(), komponente)


NASLOVI_POGLAVLJA_HEADERS = ["poglavlje_kljuc", "naslov_prikaz", "redoslijed",
                              # 30.10.2026. (skripta iz knjige): JSON s pojedinačno
                              # označenim stavkama {"primjeri": [...], "zadaci": [...]};
                              # prazno = svi. Vidi get_odabir_poglavlja.
                              "odabir_json",
                              # "da"/"ne" - je li poglavlje uopće u skripti; prazno = da.
                              "ukljuceno"]

def get_naslovi_poglavlja(sheet) -> dict:
    """Vraca {poglavlje_kljuc: naslov_prikaz} iz tab 'Sifrarnik_poglavlja_knjige' (isti
    obrazac kao get_biblioteke_izvora - auto-kreira prazan tab ako ne postoji, NE seedira
    nicim; od 29.10.2026. Caki to pretezno upisuje kroz UI u pages/4_skripta.py preko
    spremi_naslove_poglavlja, rucno u Google Sheetu i dalje radi isto). Poglavlje bez
    upisa u ovom tabu prikazuje se pod svojim sirovim kljucem (npr. 'Poglavlje3.1') -
    ovo je cisto KOZMETICKO, build ne puca ako je tab prazan ili ne postoji."""
    try:
        ws = sheet.worksheet("Sifrarnik_poglavlja_knjige")
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title="Sifrarnik_poglavlja_knjige", rows=200,
                                 cols=len(NASLOVI_POGLAVLJA_HEADERS))
        ws.append_row(NASLOVI_POGLAVLJA_HEADERS)
        return {}
    rows = ws.get_all_values()[1:]
    return {r[0].strip(): r[1].strip() for r in rows if len(r) >= 2 and r[0].strip() and r[1].strip()}


def get_redoslijed_poglavlja(sheet) -> dict:
    """Vraca {poglavlje_kljuc: redoslijed} (float) iz 3. stupca ISTOG tab-a kao
    get_naslovi_poglavlja ('redoslijed', dodano 29.10.2026. na Cakijev zahtjev - rucni
    poredak poglavlja u kronoloskoj skripti, kad prirodni brojcani poredak
    (_poglavlje_sort_key) ne odgovara sto treba). Poglavlje bez upisanog/valjanog broja ovdje
    NIJE u rjecniku - _poglavlje_sort_key_s_redoslijedom tad pada natrag na prirodni poredak,
    nista ne puca ako je tab prazan, ne postoji, ili redoslijed stupac nedostaje/sadrzi
    neispravan unos (npr. tekst umjesto broja)."""
    try:
        ws = sheet.worksheet("Sifrarnik_poglavlja_knjige")
    except gspread.exceptions.WorksheetNotFound:
        return {}
    rows = ws.get_all_values()[1:]
    izlaz = {}
    for r in rows:
        if len(r) < 3 or not r[0].strip() or not r[2].strip():
            continue
        try:
            izlaz[r[0].strip()] = float(r[2].strip().replace(",", "."))
        except ValueError:
            continue
    return izlaz


def get_odabir_poglavlja(sheet) -> dict:
    """Vraca {poglavlje_kljuc: {"primjeri": None|[...], "zadaci": None|[...],
    "ukljuceno": bool}} iz 4./5. stupca taba 'Sifrarnik_poglavlja_knjige' (dodano 30.10.2026.).

    None = SVI redci tog poglavlja (uključujući kasnije dodane), [] = nijedan, lista id-eva =
    točno ti. Prazan/neispravan JSON, tab koji ne postoji ili stari tab bez tih stupaca ->
    poglavlje se NE nalazi u rezultatu, a build ga tada tretira kao "svi" (staro ponašanje,
    nista ne puca)."""
    try:
        ws = sheet.worksheet("Sifrarnik_poglavlja_knjige")
    except gspread.exceptions.WorksheetNotFound:
        return {}
    redovi = ws.get_all_values()
    if len(redovi) < 2:
        return {}
    zaglavlje = [str(h).strip() for h in redovi[0]]
    i_odabir = zaglavlje.index("odabir_json") if "odabir_json" in zaglavlje else None
    i_uklj = zaglavlje.index("ukljuceno") if "ukljuceno" in zaglavlje else None
    izlaz = {}
    for r in redovi[1:]:
        kljuc = str(r[0]).strip() if r else ""
        if not kljuc:
            continue
        primjeri, zadaci = None, None
        if i_odabir is not None and i_odabir < len(r) and str(r[i_odabir]).strip():
            try:
                vrijednost = json.loads(r[i_odabir])
            except (ValueError, TypeError):
                vrijednost = None
            if isinstance(vrijednost, dict):
                for naziv in ("primjeri", "zadaci"):
                    x = vrijednost.get(naziv)
                    if isinstance(x, list):
                        if naziv == "primjeri":
                            primjeri = [str(y) for y in x if str(y).strip()]
                        else:
                            zadaci = [str(y) for y in x if str(y).strip()]
        ukljuceno = True
        if i_uklj is not None and i_uklj < len(r):
            ukljuceno = str(r[i_uklj]).strip().lower() not in ("ne", "no", "false", "0")
        izlaz[kljuc] = {"primjeri": primjeri, "zadaci": zadaci, "ukljuceno": ukljuceno}
    return izlaz


def spremi_naslove_poglavlja(sheet, zapisi: list):
    """Prepisuje CIJELI tab 'Sifrarnik_poglavlja_knjige' (mali tab, desetci redaka - sigurnije
    prepisati u cijelosti nego upsert po retku, isto nacelo kao get_biblioteke_izvora/
    Sifrarnik_biblioteka_izvora). zapisi: lista rjecnika
    {"poglavlje_kljuc", "naslov_prikaz", "redoslijed", "odabir_json", "ukljuceno"} (npr.
    izravno iz st.data_editor-a u pages/4_skripta.py). Redci bez poglavlje_kljuc se preskacaju;
    redoslijed se pise kao tekst (dozvoljava i decimalne vrijednosti radi umetanja izmedju dva
    postojeca cijela broja bez pretipkavanja svih ostalih).

    30.10.2026.: odabir_json/ukljuceno su NEOBAVEZNI u zapisu. Ako ih pozivatelj ne posalje,
    za taj kljuc se PREUZIMA postojeća vrijednost iz taba - staro sucelje (i stari testovi)
    tako ne moze slucajno obrisati Cakijev odabir zadataka."""
    ws = get_or_create_worksheet(sheet, "Sifrarnik_poglavlja_knjige", NASLOVI_POGLAVLJA_HEADERS,
                                 rows=200)
    postojeci = {}
    try:
        for r in ws.get_all_values()[1:]:
            if r and str(r[0]).strip():
                postojeci[str(r[0]).strip()] = {
                    "odabir_json": r[3] if len(r) > 3 else "",
                    "ukljuceno": r[4] if len(r) > 4 else "",
                }
    except Exception:  # noqa: BLE001 - prazan/neocekivan tab ne smije srusiti spremanje
        postojeci = {}
    redovi = []
    for z in zapisi:
        kljuc = str((z or {}).get("poglavlje_kljuc", "")).strip()
        if not kljuc:
            continue
        redoslijed = z.get("redoslijed")
        odabir = z.get("odabir_json", None)
        if odabir is None:
            odabir = postojeci.get(kljuc, {}).get("odabir_json", "")
        if isinstance(odabir, (dict, list)):
            odabir = json.dumps(odabir, ensure_ascii=False)
        ukljuceno = z.get("ukljuceno", None)
        if ukljuceno is None:
            ukljuceno = postojeci.get(kljuc, {}).get("ukljuceno", "")
        elif isinstance(ukljuceno, bool):
            ukljuceno = "da" if ukljuceno else "ne"
        redovi.append([
            kljuc,
            str(z.get("naslov_prikaz", "") or "").strip(),
            "" if redoslijed in (None, "") else str(redoslijed),
            str(odabir or ""),
            str(ukljuceno or ""),
        ])
    ws.clear()
    ws.update(range_name="A1", values=[NASLOVI_POGLAVLJA_HEADERS] + redovi)


def _poglavlje_sort_key_s_redoslijedom(naziv, redoslijed_poglavlja):
    """Isto kao _poglavlje_sort_key, ali RUCNI redoslijed (get_redoslijed_poglavlja) ima
    prednost kad postoji za taj naziv - poglavlja BEZ rucnog broja idu NAKON svih poglavlja
    S rucnim brojem, prirodno sortirana medju sobom (siguran fallback, 29.10.2026.)."""
    rucni = (redoslijed_poglavlja or {}).get(naziv)
    if rucni is not None:
        return (0, rucni, (naziv or "").lower())
    return (1,) + _poglavlje_sort_key(naziv)


def _filtriraj_po_odabiru(redovi, izbor):
    """Odabir pojedinačnih zadataka unutar jednog poglavlja (skripta iz knjige):
    izbor None = svi (uključujući kasnije dodane), [] = nijedan, lista id-eva = točno ti.
    REDOSLIJED REDOVA OSTAJE kakav je u Sheetu - odabir samo izbacuje, nikad ne premješta."""
    if izbor is None:
        return redovi
    skup = {str(x) for x in izbor}
    return [r for r in redovi if str(r.get("id", "")) in skup]


def filtriraj_odabir_poglavlja(redovi, odabir_poglavlja):
    """Vraca SAMO retke koje plan pusta u skriptu (poglavlje ukljuceno + pojedinacno
    oznaceni primjeri/zadaci). Koristi ga skripta_build prije skidanja slika da ne skida
    slike zadataka koje Caki nije oznacio. REDOSLIJED ovdje nije vazan (XML se gradi iz
    punog popisa) - vazan je samo skup redaka."""
    odabir_poglavlja = odabir_poglavlja or {}
    izlaz = []
    po_poglavlju = {}
    for row in redovi:
        poglavlje = parsiraj_poglavlje_iz_izvora(row.get("izvor_naziv", ""))
        po_poglavlju.setdefault(poglavlje, []).append(row)
    for poglavlje, grupa in po_poglavlju.items():
        odabir = odabir_poglavlja.get(poglavlje) or {}
        if odabir.get("ukljuceno") is False:
            continue
        izlaz.extend(_filtriraj_po_odabiru([r for r in grupa if _je_primjer_na_satu(r)],
                                           odabir.get("primjeri")))
        izlaz.extend(_filtriraj_po_odabiru([r for r in grupa if not _je_primjer_na_satu(r)],
                                           odabir.get("zadaci")))
    return izlaz


def _build_inner_content_kronoloski(zadaci_redovi, xml_id_root, images_dir_abs, slike_izvor_dir,
                                     naslovi_poglavlja=None, redoslijed_poglavlja=None,
                                     odabir_poglavlja=None, verzija_sadrzaja="ucenik",
                                     primjeri_rjesenja=None):
    """KRONOLOSKA inacica _build_inner_content - grupira po 'poglavlju' izvucenom iz
    izvor_naziv (parsiraj_poglavlje_iz_izvora), poglavlja prirodnim brojcanim redom
    (_poglavlje_sort_key), OSIM gdje je Caki rucno postavio drugaciji poredak
    (redoslijed_poglavlja, v. _poglavlje_sort_key_s_redoslijedom - dodano 29.10.2026.), a
    UNUTAR poglavlja zadaci OSTAJU u redoslijedu kako su u Sheetu (BEZ _puni_sort_key
    sortiranja po tezini - to bi razbilo redoslijed materijala). Primjeri
    (koristi_kao_primjer_na_satu='da' ili izvor_naziv '..._primjeri') idu kao <example>
    PRIJE <exercises>, isto kao u postojecem kodu. naslovi_poglavlja: v.
    get_naslovi_poglavlja - neobavezno, prazan dict ili None = svako poglavlje prikazuje
    svoj sirovi kljuc kao naslov sekcije.
    redoslijed_poglavlja: v. get_redoslijed_poglavlja - neobavezno, prazan dict ili None =
    cisto prirodni poredak (staro ponasanje, bez promjene).

    30.10.2026. (skripta iz knjige, PDF v1):
    odabir_poglavlja: v. get_odabir_poglavlja - {kljuc: {"primjeri": None|[...], "zadaci":
    None|[...], "ukljuceno": bool}}. None/prazno = svi redci (staro ponasanje). Poglavlje
    s ukljuceno=False ili bez ijednog odabranog retka se PRESKACE (ne ispisuje praznu sekciju).
    U svakom poglavlju sada postoje VIDLJIVI naslovi „Primjeri” i „Zadaci za vježbu”.
    Primjeri su BEZ rjesenja u tekstu (profesor ih rjesava na satu); u verziji za profesora
    njihovi konacni odgovori idu u primjeri_rjesenja (lista za backmatter, v.
    _skripta_backmatter_lines). Rjesenja ZADATAKA su u obje verzije na kraju skripte
    (PreTeXt ih tamo premjesta preko _skripta_backmatter_lines)."""
    naslovi_poglavlja = naslovi_poglavlja or {}
    odabir_poglavlja = odabir_poglavlja or {}
    je_profesor = str(verzija_sadrzaja or "").strip().lower() == "profesor"
    prikupljaj_rjesenja = primjeri_rjesenja is not None and je_profesor
    lines = []
    broj_slika = 0
    broj_poglavlja = 0

    po_poglavlju = {}
    for row in zadaci_redovi:
        poglavlje = parsiraj_poglavlje_iz_izvora(row.get("izvor_naziv", ""))
        po_poglavlju.setdefault(poglavlje, []).append(row)

    for poglavlje in sorted(po_poglavlju, key=lambda p: _poglavlje_sort_key_s_redoslijedom(p, redoslijed_poglavlja)):
        grupa = po_poglavlju[poglavlje]
        odabir = odabir_poglavlja.get(poglavlje) or {}
        if odabir.get("ukljuceno") is False:
            continue
        primjeri = _filtriraj_po_odabiru([r for r in grupa if _je_primjer_na_satu(r)], odabir.get("primjeri"))
        vjezbe = _filtriraj_po_odabiru([r for r in grupa if not _je_primjer_na_satu(r)], odabir.get("zadaci"))
        if not primjeri and not vjezbe:
            continue  # prazna sekcija nema smisla u PDF-u
        broj_poglavlja += 1
        naslov_sekcije = naslovi_poglavlja.get(poglavlje) or poglavlje
        sec_id = _sanitize_id(f"{xml_id_root}-{poglavlje}")
        lines.append(f'    <section xml:id="{sec_id}">')
        lines.append(f'      <title>{_xml_escape(naslov_sekcije)}</title>')

        if primjeri:
            # 30.10.2026.: jasan naslov iznad primjera (PDF v1 ih je samo nizao).
            lines.append('      <p><strong>Primjeri</strong></p>')
            stavke_rjesenja = []
            for redni, row in enumerate(primjeri, start=1):
                ex_lines, slika_ok = _build_example_lines(
                    row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=False)
                lines.extend(ex_lines)
                broj_slika += 1 if slika_ok else 0
                if prikupljaj_rjesenja:
                    stavke_rjesenja.append(
                        (f"{broj_poglavlja}.{redni}", _konacan_odgovor_za_prikaz(row) or "—"))
            if prikupljaj_rjesenja and stavke_rjesenja:
                primjeri_rjesenja.append({"naslov": naslov_sekcije, "stavke": stavke_rjesenja})

        if vjezbe:
            lines.append('      <p><strong>Zadaci za vježbu</strong></p>')
            lines.append('      <exercises>')
            for row in vjezbe:
                ex_lines, slika_ok = _build_exercise_lines(
                    row, images_dir_abs, slike_izvor_dir, ukljuci_rjesenje=True)
                lines.extend(ex_lines)
                broj_slika += 1 if slika_ok else 0
            lines.append('      </exercises>')

        lines.append('    </section>')

    return lines, broj_slika


def izgradi_skriptu_xml_kronoloski(rows, zahtjev, naslovi_poglavlja, images_dir_abs, slike_izvor_dir,
                                   redoslijed_poglavlja=None, odabir_poglavlja=None,
                                   verzija_sadrzaja="ucenik"):
    """KRONOLOSKA sestra izgradi_skriptu_xml (iznad) - ISTA vanjska forma (docinfo/
    frontmatter/backmatter s rjesenjima na kraju preko PreTeXt-ove divizijske mehanike,
    isti filtriraj_zadatke za odabir redaka), ali unutarnji sadrzaj grupira
    _build_inner_content_kronoloski umjesto po cjelina/potpoglavlje/tezina. Poziva se kad
    zahtjev['filtri']['grupiraj_po_poglavlju'] je istinit (v. skripta_build.izgradi).
    redoslijed_poglavlja: v. get_redoslijed_poglavlja - neobavezno (dodano 29.10.2026.).
    odabir_poglavlja/verzija_sadrzaja: v. _build_inner_content_kronoloski (dodano 30.10.2026.;
    prazno = identicno staro ponasanje).

    Vraca (xml, broj_slika, broj_zadataka, naslov); xml je None ako nakon svih odabira nema
    nijednog retka (pozivatelj tada javlja gresku, ne salje prazan PDF)."""
    filtri = normaliziraj_filtre(zahtjev.get("filtri"))
    odabrani = filtriraj_zadatke(rows, filtri)
    naslov = " ".join((zahtjev.get("naslov") or "").split()) or ("Skripta - " + opis_filtara(filtri))
    podnaslov = " ".join((zahtjev.get("podnaslov") or "").split())
    if not odabrani:
        return None, 0, 0, naslov

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<pretext>']
    lines += _skripta_docinfo_lines()
    lines += ['  <article xml:id="skripta">', f'    <title>{_xml_escape(naslov)}</title>']
    if podnaslov:
        lines.append(f'    <subtitle>{_xml_escape(podnaslov)}</subtitle>')
    lines += _skripta_frontmatter_lines()
    primjeri_rjesenja = []
    inner, broj_slika = _build_inner_content_kronoloski(
        odabrani, "skripta", images_dir_abs, slike_izvor_dir, naslovi_poglavlja=naslovi_poglavlja,
        redoslijed_poglavlja=redoslijed_poglavlja, odabir_poglavlja=odabir_poglavlja,
        verzija_sadrzaja=verzija_sadrzaja, primjeri_rjesenja=primjeri_rjesenja)
    if not inner:
        return None, 0, 0, naslov
    lines.extend(inner)
    je_profesor = str(verzija_sadrzaja or "").strip().lower() == "profesor"
    lines += _skripta_backmatter_lines(primjeri_rjesenja if je_profesor else None)
    lines += ['  </article>', '</pretext>']
    return "\n".join(lines), broj_slika, len(odabrani), naslov

# --- Log obrade (upisuje se u Sheet, NE samo u Streamlit session_state) ---
#
# st.session_state i on-screen log (st.empty().text(...)) žive samo dok proces same
# Streamlit aplikacije radi - ako se aplikacija nenadano ugasi/restarta usred obrade
# (npr. hosting je ubije zbog memorije/timeouta), sve to nestane bez traga i korisnik
# ostane bez ikakve informacije o tome dokle je obrada stigla. Zato se ključni koraci
# UZ TO upisuju i u zaseban tab "Log_obrade" u istom Google Sheetu - to je vanjski,
# trajan zapis koji preživi čak i potpuni pad/restart aplikacije.

LOG_OBRADE_HEADERS = ["vrijeme", "izvor_naziv", "faza", "status", "poruka"]

def _get_or_create_log_worksheet(sheet, naziv="Log_obrade"):
    try:
        return sheet.worksheet(naziv)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=naziv, rows=2000, cols=len(LOG_OBRADE_HEADERS))
        ws.append_row(LOG_OBRADE_HEADERS)
        return ws

def zapisi_log_obrade(sheet, izvor_naziv, faza, status, poruka="", log=None):
    """Upiši jedan redak u 'Log_obrade' tab - vidi obrazloženje gore. Namjerno je
    omotano u try/except koji SAMO upozori (preko `log`), a ne baca dalje: upis loga
    ne smije srušiti/prekinuti stvarnu obradu ako npr. Sheets API kratko zapne."""
    from datetime import datetime
    try:
        ws = _get_or_create_log_worksheet(sheet)
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), izvor_naziv, faza, status, poruka])
    except Exception as e:
        if log:
            log(f"⚠️ Upis u Log_obrade nije uspio (samo evidencija - obrada se nastavlja): {e}")

# --- Claude extrakcija (s automatskim dijeljenjem ako se odgovor odreže) ---

def _ocisti_zadatke(zadaci, log=None):
    """Zadrži SAMO elemente koji su zapravo JSON objekti (dict) - svaki pravi zadatak
    je objekt s poljima poput tekst_zadatka_latex, kategorija, itd. Ako je Claudeov
    odgovor (ili neka od strategija spašavanja iznad) proizveo listu u kojoj se
    zabunom našao string/broj/None umjesto objekta (npr. dio uvodnog teksta koji je
    slučajno bio valjan JSON, poput kratkog citata u navodnicima), takav element bi
    kasnije srušio obradu s "AttributeError: 'str' object has no attribute 'get'" -
    umjesto toga ga ovdje tiho izbacimo (uz upozorenje) i nastavimo sa stvarnim zadacima."""
    ocisceno = [z for z in zadaci if isinstance(z, dict)]
    odbaceno = len(zadaci) - len(ocisceno)
    if odbaceno and log:
        log(f"⚠️ Odbačeno {odbaceno} stavki iz Claudeovog odgovora koje nisu JSON objekt "
            f"zadatka (vjerojatno ostatak uvodnog teksta koji je slučajno valjan JSON) - "
            f"preostalih {len(ocisceno)} zadataka je u redu.")
    return ocisceno


def _parsiraj_uzastopne_json_vrijednosti(raw_text: str, log=None):
    """Pokušaj pročitati raw_text kao NIZ UZASTOPNIH JSON vrijednosti (jedna za drugom,
    bez zajedničke omotne liste), umjesto jedne JSON liste. Rješava slučaj kad Claude
    (najčešće kod vrlo malog dijela ispita, npr. nakon dijeljenja na pola pa pola) umjesto
    tražene JSON liste vrati jedan ili više ODVOJENIH objekata: '{...}\\n{...}' - takav
    odgovor json.loads() odbija s "Extra data", a POSTOJEĆI trik "odreži na zadnjem '}'
    prije greške i zatvori s ']'" ovdje ne pomaže (kandidat postaje "{...}]" - objekt s
    viškom uglate zagrade - i dalje neispravan JSON), pa je ovo zaseban, dodatni pokušaj.
    Koristi json.JSONDecoder().raw_decode() koji čita TOČNO jednu vrijednost i vraća poziciju
    gdje je stao, pa se to ponavlja dok ima još teksta. Zadatke koje Claude vrati kao listu
    proširujemo u rezultat, a pojedinačne objekte dodajemo jedan po jedan. Čim naiđemo na
    nešto što se uopće ne da parsirati kao JSON, stajemo i vraćamo što je do tad skupljeno
    (bolje spasiti dio nego ništa)."""
    decoder = json.JSONDecoder(strict=False)
    zadaci = []
    idx, n = 0, len(raw_text)
    while idx < n:
        while idx < n and raw_text[idx] in " \t\n\r":
            idx += 1
        if idx >= n:
            break
        try:
            obj, kraj = decoder.raw_decode(raw_text, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, list):
            zadaci.extend(obj)
        elif isinstance(obj, dict):
            zadaci.append(obj)
        else:
            break
        idx = kraj
    return zadaci


KLJUCEVI_ZADATKA = ("tekst_zadatka_latex", "privremeni_broj", "uloga", "tip_zadatka",
                    "konacan_odgovor", "ponudjeni_odgovori", "cjelina", "kategorija",
                    "rjesenje", "id")


def _izvuci_sve_json_objekte(raw_text: str) -> list:
    """Vrati SVE potpuno zatvorene JSON objekte koje uspiješ pročitati u tekstu, neovisno o
    tome što ih okružuje (uvodni tekst, liste stringova, pokvaren JSON, višak zagrada...).
    Čita se preko json.JSONDecoder().raw_decode() od SVAKOG znaka '{': gdje se pročita
    ispravan objekt, skoči se na njegov kraj (tako se unutrašnjost ne čita ponovno), a gdje
    se ne pročita, pomakne se jedan znak dalje. Zato ovo radi i kad se odgovor NE MOŽE
    pročitati kao cjelina - bolje spasiti nekoliko zadataka nego izgubiti cijeli ispit.

    Zašto treća strategija (22.10.2026., ispit SKM_22726102220490): Claude je vratio uvodni
    tekst, pa pomoćni JSON objekt, pa listu stringova ("[Linearna funkcija", ...), pa JOŠ
    teksta, a zadaci su došli tek poslije toga. json.loads() je pao s "Extra data", rezanje
    na zadnjem '}' nije pomoglo, a _parsiraj_uzastopne_json_vrijednosti stala je na prvom
    tekstu između vrijednosti (vratila je 4 stringa i ništa više) - cijeli ispit je propao
    iako su svi zadaci bili u odgovoru."""
    decoder = json.JSONDecoder(strict=False)
    objekti = []
    idx, n = 0, len(raw_text)
    while idx < n:
        idx = raw_text.find("{", idx)
        if idx == -1:
            break
        try:
            obj, idx = decoder.raw_decode(raw_text, idx)
        except json.JSONDecodeError:
            idx += 1                 # ovaj '{' nije početak ispravnog objekta - traži sljedeći
            continue
        if isinstance(obj, dict):
            objekti.append(obj)
    return objekti


def _zadaci_iz_objekata(objekti, log=None):
    """Iz liste pročitanih JSON objekata zadrži one koji STVARNO liče na zadatak i izbaci
    objekte koji se u odgovoru ponavljaju dva puta. Redoslijed je namjeran:
      1. objekti s poljem `tekst_zadatka_latex` - svaki pravi zadatak ga ima (obavezno je u
         shemi), pa je to najpouzdaniji znak;
      2. ako takvih nema, objekti s BILO Kojim poljem zadatka iz KLJUCEVI_ZADATKA (model je
         možda promijenio ime polja);
      3. ako ni toga nema, svi objekti - bolje sačuvati nešto nego ništa.
    Bez ovog filtra bi pomoćni objekti iz uvodnog teksta (npr. {"privremeni_broj": "0",
    "napomena": "prvo provjeravam numeraciju"}) ušli u bazu kao zadaci bez teksta zadatka."""
    jedinstveni, vidjeni = [], set()
    for o in objekti:
        if not isinstance(o, dict):
            continue
        kljuc = json.dumps(o, sort_keys=True, ensure_ascii=False, default=str)
        if kljuc in vidjeni:
            continue
        vidjeni.add(kljuc)
        jedinstveni.append(o)
    zadaci = [o for o in jedinstveni if "tekst_zadatka_latex" in o]
    if not zadaci:
        zadaci = [o for o in jedinstveni if any(k in o for k in KLJUCEVI_ZADATKA)]
    if not zadaci:
        zadaci = jedinstveni
    odbaceno = len(jedinstveni) - len(zadaci)
    if odbaceno and log:
        log(f"ℹ️ Preskočeno {odbaceno} JSON objekata koji ne liče na zadatak (nemaju polje "
            f"tekst_zadatka_latex ni drugo polje zadatka) - spašeno {len(zadaci)} zadataka.")
    return zadaci


def _spasi_djelomican_json_popis(raw_text: str, log=None):
    """Pokušaj standardni json.loads(); ako Claudeov odgovor NIJE ispravan JSON
    (najčešće: odgovor je odrezan zbog max_tokens čak i nakon što je iscrpljen
    budžet automatskog dijeljenja, ili je negdje u tekstu ostao neescapean
    navodnik, npr. u zapisu kuta 12°34'56"), ne bacamo cijeli rezultat - umjesto
    toga odrežemo odgovor na mjestu ZADNJEG potpuno zatvorenog objekta PRIJE
    mjesta greške i spasimo te zadatke. Bolje spasiti npr. 18 od 20 zadataka
    nego izgubiti svih 20 zbog jednog pokvarenog znaka na kraju odgovora.
    Ako niti to ne upali (tipično kod greške "Extra data" - Claude je vratio jedan ili
    više ODVOJENIH JSON objekata umjesto jedne liste), probamo drugu strategiju:
    _parsiraj_uzastopne_json_vrijednosti - vidi njezin docstring.
    Ako i to propadne (odgovor je mješavina uvodnog teksta, listi stringova i objekata,
    pa niz "pukne" na prvom tekstu između vrijednosti - slučaj s ispita SKM_22726102220490,
    22.10.2026.), ide treća, krajnja strategija: _izvuci_sve_json_objekte - izvuče SVE
    potpuno zatvorene objekte iz cijelog odgovora, bez obzira na to što stoji između njih.
    Vraća (zadaci, je_li_potpuno: bool). Ako se ništa ne može spasiti, ponovno
    baca originalnu json.JSONDecodeError (isto ponašanje kao prije - poziv
    gore u lancu i dalje mora znati da je obrada za ovaj dio propala)."""
    try:
        rezultat = json.loads(raw_text, strict=False)
        if isinstance(rezultat, dict):
            # Claude je (unatoč uputi da odgovori JSON LISTOM) vratio jedan JEDINI
            # objekt bez omotne liste - čest slučaj kod vrlo malog dijela ispita
            # (npr. samo 1 preostali zadatak nakon dijeljenja). Ne odbacujemo ga -
            # samo ga omotamo u listu od jednog elementa.
            if log:
                log("⚠️ Claudeov odgovor je JEDAN objekt bez omotne JSON liste - tretiram ga kao listu od 1 zadatka.")
            rezultat = [rezultat]
        if isinstance(rezultat, list):
            rezultat = _ocisti_zadatke(rezultat, log=log)
        return rezultat, True
    except json.JSONDecodeError as e:
        if log:
            log(f"⚠️ Claudeov odgovor nije ispravan JSON ({e}) - pokušavam spasiti "
                f"zadatke parsirane prije mjesta greške...")
        granica = e.pos
        kraj_objekta = raw_text.rfind("}", 0, granica)
        while kraj_objekta != -1:
            kandidat = raw_text[:kraj_objekta + 1]
            # Gruba provjera ravnoteže zagrada - dovoljno za ovaj slučaj uporabe
            # (izbjegava da probamo parsirati na mjestu "}" koji je dio stringa).
            if kandidat.count("{") == kandidat.count("}"):
                try:
                    zadaci = json.loads(kandidat + "]", strict=False)
                    zadaci = _ocisti_zadatke(zadaci, log=log)
                except json.JSONDecodeError:
                    zadaci = []
                if zadaci:
                    if log:
                        log(f"✅ Spašeno {len(zadaci)} zadataka prije mjesta greške "
                            f"(ostatak ovog Claude odgovora je odbačen kao nepouzdan).")
                    return zadaci, False
                # kandidat je valjan JSON, ali u njemu nema nijednog zadatka (npr. lista
                # stringova) - nije uspjeh, nego se nastavlja s kraćim kandidatom niže.
            kraj_objekta = raw_text.rfind("}", 0, kraj_objekta)

        # Prvi pokušaj (gore) ne pomaže kad raw_text nije "lista koja je odrezana", nego
        # jedan ili više ODVOJENIH JSON objekata (npr. "{...}\n{...}") - tipičan uzrok
        # greške "Extra data". Probaj drugu strategiju prije nego potpuno odustanemo.
        # _zadaci_iz_objekata tu još izbaci pomoćne objekte (npr. {"napomena": ...}) koji bi
        # u bazu ušli kao zadaci bez teksta - vidi njezin docstring.
        zadaci_iz_niza = _ocisti_zadatke(
            _zadaci_iz_objekata(_parsiraj_uzastopne_json_vrijednosti(raw_text, log=log), log=log),
            log=log,
        )
        if zadaci_iz_niza:
            if log:
                log(f"✅ Spašeno {len(zadaci_iz_niza)} zadataka čitanjem kao niz odvojenih "
                    f"JSON vrijednosti (Claudeov odgovor nije bio omotan u jednu JSON listu).")
            return zadaci_iz_niza, False

        # Treća (krajnja) strategija: izvuci SVE potpuno zatvorene objekte iz cijelog odgovora,
        # bez obzira na to što stoji između njih. Ovo je jedino što pomaže kad je odgovor
        # mješavina uvodnog teksta, listi stringova i objekata - vidi _izvuci_sve_json_objekte.
        zadaci_iz_teksta = _zadaci_iz_objekata(_izvuci_sve_json_objekte(raw_text), log=log)
        if zadaci_iz_teksta:
            if log:
                log(f"✅ Spašeno {len(zadaci_iz_teksta)} zadataka izvlačenjem svih potpunih JSON "
                    f"objekata iz odgovora (Claudeov odgovor nije bila jedna ispravna JSON lista).")
            return zadaci_iz_teksta, False

        if log:
            log("❌ Nije uspjelo spasiti nijedan zadatak iz ovog odgovora - obrada ovog dijela propada.")
        raise


# Najveći broj tokena koje Claude smije vratiti u JEDNOM odgovoru pri strukturiranju ispita
# (10.10.2026.: podignuto sa 16000 na 40000 - ispit od ~17 zadataka s ~50 podzadataka nije stao
# u 16000 pa se odgovor stalno rezao). Plaća se SAMO stvarno generirano, ne ovaj limit.
# Ako je 40000 previše/prespor, slobodno smanji (npr. 32000) - promijeni SAMO ovaj broj.
# VAŽNO: preko ~21000 tokena Anthropic SDK ODBIJA obični (ne-streaming) poziv s pogreškom
# "Streaming is required for operations that may take longer than 10 minutes" - zato se
# niže koristi client.messages.stream(...), ne client.messages.create(...).
EXTRACTION_MAX_TOKENS = 40000


def extract_zadaci_with_claude(ispit_md, rjesenja_md, sifrarnik_text, anthropic_api_key,
                                sifrarnik_potpoglavlja_text="", model="claude-sonnet-5",
                                _preostala_dubina=2, log=None, _preostali_pokusaji_praznog=2,
                                predmet="matematika"):
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    user_content = f"""ŠIFRARNIK (koristi isključivo ove kategorije/cjeline, doslovno):
{sifrarnik_text}

ŠIFRARNIK POTPOGLAVLJA (za svaku cjelinu, koristi isključivo navedena potpoglavlja, doslovno):
{sifrarnik_potpoglavlja_text}

=== TEKST ISPITA (Mathpix Markdown) ===
{ispit_md}
"""
    if rjesenja_md:
        user_content += f"\n=== TEKST RJEŠENJA/BODOVANJA (Mathpix Markdown) ===\n{rjesenja_md}\n"

    with client.messages.stream(
        model=model,
        max_tokens=EXTRACTION_MAX_TOKENS,
        system=sastavi_extraction_prompt(predmet),
        messages=[{"role": "user", "content": user_content}],
        # Claude Sonnet 5 po defaultu koristi "adaptive thinking" (effort "high"), a tokeni
        # potrošeni na razmišljanje broje se u ISTI max_tokens budžet kao i sam odgovor -
        # kod složenijih/dužih ispita to zna pojesti cijeli budžet PRIJE nego što Claude
        # uopće počne pisati JSON (stop_reason=max_tokens, sadržaj=samo "thinking" blok, bez
        # teksta - vidljivo u logovima kao "prazan odgovor" čak i nakon ponovnih pokušaja).
        # Za ovaj strukturirani JSON zadatak razmišljanje ne donosi korist, pa ga isključujemo
        # da cijelih 16000 tokena ide na stvarni odgovor.
        #
        # NAPOMENA (14.9.2026.): pokušaj dodavanja "assistant prefill" poruke (da Claude
        # nastavi izravno od otvorene '[') OVDJE JE ODBAČEN - potvrđeno testom da ovaj
        # model/API setup NE podržava prefill: "anthropic.BadRequestError: This model does
        # not support assistant message prefill. The conversation must end with a user
        # message." Umjesto toga, zaštita od uvodnog teksta prije JSON liste rješava se
        # post-hoc, nakon što odgovor stigne - v. blok "if raw_text and not raw_text.
        # startswith(...)" niže.
        thinking={"type": "disabled"},
    ) as stream:
        # Isti Message objekt kakav je vraćao create() (content, stop_reason...) - ostatak
        # funkcije ostaje NEPROMIJENJEN.
        response = stream.get_final_message()

    if response.stop_reason == "max_tokens":
        if _preostala_dubina > 0 and len(ispit_md) > 1000:
            if log:
                log(f"⚠️ Odgovor odrezan (max_tokens) - dijelim ispit na dva dijela "
                    f"(preostalo dubina: {_preostala_dubina}) i ponovno pokušavam...")
            polovica = len(ispit_md) // 2
            prijelom = ispit_md.rfind("\n", 0, polovica)
            if prijelom == -1:
                prijelom = polovica
            dio1 = extract_zadaci_with_claude(ispit_md[:prijelom], rjesenja_md, sifrarnik_text,
                                               anthropic_api_key, sifrarnik_potpoglavlja_text,
                                               model, _preostala_dubina - 1, log, predmet=predmet)
            dio2 = extract_zadaci_with_claude(ispit_md[prijelom:], rjesenja_md, sifrarnik_text,
                                               anthropic_api_key, sifrarnik_potpoglavlja_text,
                                               model, _preostala_dubina - 1, log, predmet=predmet)
            return dio1 + dio2
        elif log:
            log("⚠️ UPOZORENJE: odgovor odrezan čak i nakon maksimalnog dijeljenja - rezultat je vjerojatno nepotpun.")

    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
    raw_text = re.sub(r"```$", "", raw_text).strip()
    # Ukloni "nevidljive" unicode znakove (BOM, zero-width space i sl.) koje obično .strip()
    # NE smatra whitespaceom - jedan takav znak na samom početku dovoljan je da json.loads
    # padne s "Expecting value: line 1 column 1 (char 0)" iako raw_text izgleda neprazan.
    raw_text = raw_text.strip("﻿‌‍")

    # Zapamti odgovor PRIJE rezanja uvodnog teksta. Ako se iz odrezanog dijela ne uspije spasiti
    # nijedan zadatak, niže se pokušava još jednom iz CIJELOG odgovora - rezanje uvoda zna
    # promašiti početak (npr. uzme kratku listu iz uvodnog teksta) pa se tako izgube zadaci koji
    # su u odgovoru stajali PRIJE tog mjesta (ispit SKM_22726102220490, 22.10.2026.).
    izvorni_tekst = raw_text

    if raw_text and not raw_text.startswith(("[", "{")):
        # Claude je (unatoč uputi da odgovori ISKLJUČIVO JSON-om) ipak dodao neki uvodni tekst
        # prije same JSON liste (npr. "Evo JSON odgovora:\n[...]") - potraži POČETAK PRAVE JSON
        # liste zadataka, ne bilo koju '[' u tekstu.
        #
        # 🐛 BUG otkriven 14.9.2026. i OVDJE POPRAVLJEN: naivno raw_text.find("[") uzima PRVU
        # '[' bilo gdje u tekstu. Ako Claude u uvodnom komentaru spomene npr. "prazna lista []"
        # (citirajući primjer iz točke 13 EXTRACTION_SYSTEM_PROMPT-a) ili kratku listu poput
        # "[5, 4.6]", ta '[' je PRVA u tekstu, ali NIJE početak stvarne JSON liste zadataka -
        # rezanje na tom mjestu ostavlja pokvaren tekst (npr. "[](jer...)"), što json.loads
        # odmah odbija ("Extra data: line 1 column 3 (char 2)") i cijeli dio ispita propadne
        # bez pravog razloga (potvrđeno na obradi zadatka 15 s a)/b)/c) podzadacima).
        #
        # ISPRAVAK: tražimo prvu '[' iza koje (uz eventualni whitespace) slijedi '{' - naša
        # shema UVIJEK vraća listu OBJEKATA, nikad listu golih brojeva/stringova, pa je to
        # pouzdan znak stvarnog početka. Fallback na staro ponašanje ako regex ne nađe ništa
        # (rubni slučaj), da se ne pogorša postojeće ponašanje.
        match = re.search(r"\[\s*\{", raw_text)
        if not match and "{" not in raw_text:
            # Claude je za ovaj dio vratio SAMO objašnjenje (nema nijednog JSON objekta) - npr. "numeracija
            # u rješenjima ne odgovara...". Prije se tu uzimala prva '[' iz teksta ("[]"), json.loads je
            # padao s "Extra data" i rušio CIJELU obradu, uključujući uspješne dijelove. Sad se samo ovaj
            # dio preskače, uz GLASNO upozorenje (u logu i u Log_obrada), a ostali dijelovi se spremaju.
            if log:
                log("❌ DIO ISPITA NIJE OBRAĐEN: Claude je vratio tekst umjesto JSON-a "
                    f"('{raw_text[:120].strip()}...'). Taj dio je preskočen - provjeri koji zadaci nedostaju "
                    "i ponovi obradu samo za njih.")
            return []
        prvi_zagrada = match.start() if match else raw_text.find("[")
        if prvi_zagrada > 0:
            if log:
                log(f"⚠️ Claudeov odgovor sadrži tekst prije JSON liste "
                    f"('{raw_text[:prvi_zagrada].strip()[:80]}') - odbacujem taj uvod.")
            raw_text = raw_text[prvi_zagrada:]

    if not raw_text:
        # "Expecting value: line 1 column 1 (char 0)" iz json.loads() uvijek znači BAŠ ovo -
        # Claude je vratio 0 znakova teksta (različito od odrezanog/pokvarenog JSON-a, koje
        # rješava _spasi_djelomican_json_popis niže). Bilježimo stop_reason i tipove content
        # blokova radi dijagnoze, i pokušavamo ponovno prije nego odustanemo - prazan odgovor
        # je tipično prolazna stvar (API hiccup), ne stvarni problem sa sadržajem ispita.
        broj_blokova = len(response.content)
        tipovi_blokova = [b.type for b in response.content]
        if log:
            log(f"⚠️ Claude je vratio PRAZAN odgovor (stop_reason={response.stop_reason}, "
                f"broj_blokova={broj_blokova}, tipovi={tipovi_blokova}).")
        if _preostali_pokusaji_praznog > 0:
            if log:
                log(f"🔁 Prazan odgovor je često prolazna greška - pokušavam ponovno "
                    f"(preostalo pokušaja: {_preostali_pokusaji_praznog})...")
            return extract_zadaci_with_claude(
                ispit_md, rjesenja_md, sifrarnik_text, anthropic_api_key,
                sifrarnik_potpoglavlja_text, model, _preostala_dubina, log,
                _preostali_pokusaji_praznog - 1, predmet=predmet,
            )
        raise ValueError(
            f"Claude je vratio prazan odgovor i nakon ponovnih pokušaja "
            f"(stop_reason={response.stop_reason}, broj_blokova={broj_blokova})."
        )

    try:
        zadaci, potpuno = _spasi_djelomican_json_popis(raw_text, log=log)
        greska = None
    except json.JSONDecodeError as e:
        zadaci, potpuno, greska = [], True, e

    # Ako iz odrezanog dijela nema NIJEDNOG zadatka, a prije rezanja je bilo uvodnog teksta,
    # rezanje je vjerojatno promašilo početak zadataka (npr. uzelo je kratku listu iz uvoda) i
    # pravi zadaci su ostali IZREZANI. Zato se tada ide još jedan pokušaj iz CIJELOG odgovora -
    # tamo ih _izvuci_sve_json_objekte nađe neovisno o ostatku teksta. Time se rješava i tihi
    # slučaj "json.loads je uspio, ali to nije bila lista zadataka" (0 zadataka, a zadaci postoje).
    if not zadaci and izvorni_tekst and izvorni_tekst != raw_text:
        if log:
            log("⚠️ Iz odrezanog dijela (bez uvodnog teksta) nema nijednog zadatka - pokušavam "
                "još jednom iz CIJELOG Claudeovog odgovora, uključujući uvodni tekst...")
        try:
            zadaci, potpuno = _spasi_djelomican_json_popis(izvorni_tekst, log=log)
            greska = None
        except json.JSONDecodeError:
            pass          # ni cijeli odgovor ne daje zadatke - ostaje gore zabilježena greška

    if greska is not None:
        raise greska

    if not zadaci and log:
        # Nula zadataka nije nužno greška (namjerno prazan dio ispita), ali češće znači da je
        # odgovor bio neupotrebljiv - zato se početak odgovora ispiše u log za dijagnozu.
        log(f"⚠️ Iz ovog Claudeovog odgovora nije izvučen NIJEDAN zadatak "
            f"('{raw_text[:120].strip()}...'). Provjeri je li ispit stvarno prazan ili ponovi obradu.")

    if not potpuno and log:
        log("⚠️ POZOR: gornji zadaci su spašeni iz NEPOTPUNOG Claude odgovora - "
            "preporučamo nakon obrade provjeriti bazu (zadnji zadatak u ovom dijelu "
            "ispita je vjerojatno izostavljen) i po potrebi ručno dodati/ponoviti obradu.")

    for z in zadaci:
        latex_text = z.get("tekst_zadatka_latex", "")
        z["tekst_zadatka_mathjax"] = latex_text.replace("\\\\", "<br>")
    return zadaci


# --- Slike (preuzimanje s Mathpixa, upload na Drive) ---

def upload_image_to_drive(drive_service, folder_id: str, filename: str, image_bytes: bytes, mimetype: str = "image/png"):
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype=mimetype, resumable=False)
    file_metadata = {"name": filename, "parents": [folder_id]}
    created = drive_service.files().create(
        body=file_metadata, media_body=media, fields="id,webViewLink", supportsAllDrives=True
    ).execute()
    return created.get("id"), created.get("webViewLink")


def upload_image_to_drive_with_retry(sa_info: dict, folder_id: str, filename: str, image_bytes: bytes,
                                      mimetype: str = "image/png", pokusaji: int = 2):
    """Isto kao upload_image_to_drive(), ali otporno na 'Greška: [Errno 32] Broken pipe'
    (11.9.2026., §25.8). Uzrok tog buga NIJE nasumican: 'drive_service' u
    baza_zadataka_app.py je izgrađen JEDNOM po pokretanju servera preko
    @st.cache_resource i zatim se ponovno koristi na svaki upload, satima/danima.
    googleapiclient/httplib2 interno drži TCP vezu prema Google API-ju otvorenu i
    kešira je za ponovnu upotrebu; ako je zadatak "spremi sliku" dulje vrijeme
    neaktivan, Google server sa svoje strane zatvori tu vezu, a httplib2 to ne
    primijeti unaprijed - sljedeći upisni poziv (upload slike) pokuša pisati na
    već zatvoren socket i OS baca BrokenPipeError. Vidljivo je zašto se čini
    "nasumično": pojavljuje se tek nakon perioda mirovanja te konkretne akcije,
    ne odmah nakon deploya kad je veza svježa - baš kako je korisnik i opisao
    ("sad je prošlo, vidjet ćemo hoće li se ponoviti").
    Rješenje ovdje: kod BrokenPipeError/ConnectionError izgradi POTPUNO NOVI
    drive_service (svježa httplib2 veza, ne diramo globalni keširani objekt) i
    pokušaj upload još jednom prije nego se preda. `sa_info` (service account
    dict) mora biti dostupan pozivatelju da može sam izgraditi svjež servis."""
    zadnja_greska = None
    for _ in range(max(1, pokusaji)):
        try:
            svjez_servis = get_drive_service(sa_info)
            return upload_image_to_drive(svjez_servis, folder_id, filename, image_bytes, mimetype)
        except (BrokenPipeError, ConnectionError, OSError) as e:
            zadnja_greska = e
            continue
    raise zadnja_greska

# --- Više slika uz jedan zadatak (13.10.2026.) ---
# Stupci slika_putanja (nazivi datoteka u 02_SLIKE) i slika_url (URL-ovi iz Mathpixa, samo pri uvozu)
# mogu sadržavati VIŠE vrijednosti odvojenih znakom "|", redoslijedom kojim slike stoje uz zadatak
# (npr. fizika: "slika 1." i "slika 2." uz isti zadatak). Jedna vrijednost = stari oblik, bez ikakve
# promjene. Sve što čita slike mora proći kroz razdvoji_slike().
SLIKE_RAZDJELNIK = "|"


def razdvoji_slike(vrijednost) -> list:
    """'a.png | b.png' -> ['a.png', 'b.png']; prazno/None -> []. Zadržava redoslijed, bez duplikata."""
    rezultat = []
    for dio in str(vrijednost or "").split(SLIKE_RAZDJELNIK):
        dio = dio.strip()
        if dio and dio not in rezultat:
            rezultat.append(dio)
    return rezultat


def spoji_slike(popis) -> str:
    return SLIKE_RAZDJELNIK.join(x for x in (str(p).strip() for p in popis or []) if x)


def preuzmi_i_spremi_slike(zadaci, izvor_naziv, mathpix_app_id, mathpix_app_key,
                            drive_service, slike_folder_id, log=None):
    """
    Preuzima slike i sprema ih u 02_SLIKE folder na Driveu (isti folder koji je u
    Colabu mountan na LATEX_BAZA_ROOT/02_SLIKE). U `slika_putanja` upisuje SAMO
    naziv datoteke (npr. "A2010_ljetni_zad17.png") - IZRAVNU, prenosivu referencu,
    a ne Drive "view" link (koji je krhak i beskoristan za PreTeXt build, koji
    slike čita izravno s diska). Puna putanja se sastavlja pri PreTeXt buildu kao
    os.path.join(LATEX_BAZA_ROOT, "02_SLIKE", slika_putanja).
    """
    broj_preuzetih = 0
    for z in zadaci:
        if z.get("slika_zadana") == "da" and z.get("slika_url"):
            urlovi = razdvoji_slike(z["slika_url"])
            osnova = f"{izvor_naziv}_zad{z.get('privremeni_broj', '0')}".replace(" ", "_")
            spremljene = []
            for n, url in enumerate(urlovi, 1):
                # Jedna slika zadržava stari naziv (<osnova>.png); više slika ide kao <osnova>_1.png, _2.png...
                naziv = f"{osnova}.png" if len(urlovi) == 1 else f"{osnova}_{n}.png"
                try:
                    headers = {"app_id": mathpix_app_id, "app_key": mathpix_app_key}
                    resp = requests.get(url, headers=headers, timeout=30)
                    resp.raise_for_status()
                    upload_image_to_drive(drive_service, slike_folder_id, naziv, resp.content)
                    spremljene.append(naziv)
                    broj_preuzetih += 1
                    if log:
                        log(f"🖼️ Slika spremljena za zadatak #{z.get('privremeni_broj')}: {naziv}")
                except Exception as e:
                    if log:
                        log(f"⚠️ Neuspjelo preuzimanje slike {n}/{len(urlovi)} za zadatak #{z.get('privremeni_broj')}: {e}")
            z["slika_putanja"] = spoji_slike(spremljene)
        else:
            z["slika_putanja"] = z.get("slika_putanja", "")
    return zadaci

# --- Upis u Sheet (s detekcijom duplikata po sličnosti teksta) ---

def _normalize_za_usporedbu(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())

# Minimalna duljina normaliziranog teksta (znakova) ISPOD koje se automatska
# usporedba SequenceMatcher-om smatra NEPOUZDANOM za zadatke koji imaju sliku
# (11.9.2026., §25.9 - prijavio korisnik). Kratak, generički tekst poput "Na
# slici je graf funkcije. Odredi..." gotovo uvijek prijeđe prag_slicnosti (ili
# niži prag_slicnosti_isti_naziv unutar istog ispita) prema BILO KOJEM drugom
# grafičkom zadatku sličnog tipa pitanja, iako je stvarni razlikovni sadržaj
# (drugačiji graf, drugačiji geometrijski lik) u SLICI koju ovaj algoritam
# uopće ne vidi - usporeduje se samo tekst. Prije ovog popravka takav lažni
# pozitivan pogodak nije samo "preskočio" novi zadatak - POSTOJEĆI redak bi
# dobio PREPISANU sliku/rješenje/odgovor novog zadatka, pa bi stari podaci
# bili TIHO PREBRISANI (stvaran gubitak podataka, ne samo duplikat).
MIN_DULJINA_ZA_POUZDANU_USPOREDBU = 60


def _ima_sliku(z: dict) -> bool:
    return bool((z.get("slika_putanja") or "").strip()) or (z.get("vizualni_potencijal") == "da")

def backup_sheet(drive_service, sheet_id: str, backup_folder_id: str, log=None):
    """
    Napravi potpunu, vremenski označenu kopiju cijelog Google Sheeta u
    zaseban backup folder. Poziva se nakon svake uspješne obrade - dodatna
    zaštita uz Google Sheetsov ugrađeni "Version history" (koji štiti
    unutar iste datoteke, ali ne i od brisanja same datoteke).
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    try:
        original = drive_service.files().get(fileId=sheet_id, fields="name", supportsAllDrives=True).execute()
        naziv_backupa = f"{original['name']}_backup_{timestamp}"
        drive_service.files().copy(
            fileId=sheet_id,
            body={"name": naziv_backupa, "parents": [backup_folder_id]},
            supportsAllDrives=True,
        ).execute()
        if log:
            log(f"💾 Backup baze spremljen: {naziv_backupa}")
    except Exception as e:
        if log:
            log(f"⚠️ Backup nije uspio (baza je i dalje sigurna, samo bez dodatne kopije): {e}")

# Strožа provjera duplikata za KRATKE stavke skupina (10.10.2026.): kod kratkih formula poput
# "Pomnoži: $3^5 \cdot 3^7$" SequenceMatcher daje visoku sličnost i za RAZLIČITE zadatke
# (zamijenjeni su samo brojevi), pa bi prag 0.85 tiho prebrisao tuđi redak. Za stavke čiji je
# puni tekst (uvod + stavka) kraći od MIN_DULJINA_ZA_POUZDANU_USPOREDBU zato tražimo praktički
# identičan tekst. Ne vrijedi za samostalne zadatke (njihovo ponašanje je ostalo isto kao prije).
PRAG_SLICNOSTI_KRATKA_STAVKA = 0.98


def nadopuni_ili_dodaj_zadatke(ws_zadaci, zadaci, izvor_tip, izvor_naziv, godina, razina, broj_pdf_ulaza,
                                skenirano="ne", prag_slicnosti=0.85, prag_slicnosti_isti_naziv=0.75, log=None,
                                ogranici_po_cjelini=False, biblioteka_izvora="", koristi_kao_primjer_na_satu=""):
    """
    Upisuje zadatke u tab 'Zadaci' s detekcijom duplikata (isto ponašanje kao i prije za
    samostalne zadatke) i, od 10.10.2026., podržava SKUPINE ZADATAKA:
      - Claudeov izlaz se prvo složi u jedinice (skupina + stavke, ili samostalan) -
        vidi pripremi_jedinice() u skupine_zadataka.py.
      - Skupina = jedan redak (uloga='skupina') sa zajedničkim uvodom; stavke = zasebni retci
        (uloga='stavka', roditelj_id = ID skupine, oznaka_stavke) s kopiranom cjelinom/potpoglavljem.
      - Duplikati se traže PO STAVCI, uspoređujući "uvod + stavka" (retci skupina nikad nisu
        kandidati, a postojeće stavke se uspoređuju s uvodom svoje skupine).
      - Redak skupine se dodaje SAMO ako je barem jedna njezina stavka nova (inače bi ponovni
        upload istog ispita stvarao prazne skupine).
      - Ako tab 'Zadaci' nema stupce uloga/roditelj_id/oznaka_stavke (točno iza biblioteka_izvora),
        a uvoz sadrži skupine, upis se PRIJE bilo kakvog pisanja prekida jasnom porukom. Bez skupina
        sve radi kao prije.
    Vraća (broj_dodanih, broj_azuriranih): broj_dodanih broji zadatke i stavke, ne retke skupina.

    ogranici_po_cjelini=False (zadano): usporedba svakog novog zadatka sa SVIM postojećim
    zadacima u bazi, kao dosad - najsigurnije, ali kod baze od 20-30 tisuća zadataka
    najsporije. ogranici_po_cjelini=True: usporedba samo s postojećim zadacima iz ISTE cjeline
    (+ onima bez upisane cjeline) - brže, uz mali rizik opisan u ranijim verzijama.
    """
    all_values = ws_zadaci.get_all_values()
    headers = all_values[0] if all_values else []
    data_rows = all_values[1:]

    jedinice = pripremi_jedinice(zadaci, log=log)
    ima_skupine = any(j["tip"] == "skupina" for j in jedinice)
    ima_nove_stupce = all(c in headers for c in NOVI_STUPCI)
    if ima_nove_stupce:
        for c in NOVI_STUPCI:
            if headers.index(c) != ZADACI_HEADERS.index(c):
                raise RuntimeError(
                    f"Stupac '{c}' u tabu 'Zadaci' nije na očekivanom mjestu (očekivano: stupac broj "
                    f"{ZADACI_HEADERS.index(c) + 1}, nađeno: {headers.index(c) + 1}). Stupci uloga, roditelj_id i "
                    "oznaka_stavke moraju biti NOVI ZADNJI stupci, odmah iza 'biblioteka_izvora', tim redoslijedom."
                )
    elif ima_skupine:
        raise RuntimeError(
            "Ovaj ispit sadrži zadatke s podzadacima (skupine), a u tabu 'Zadaci' nedostaju stupci "
            "uloga, roditelj_id i oznaka_stavke. Dodaj ih kao NOVE ZADNJE stupce (odmah iza 'biblioteka_izvora', "
            "tim redoslijedom, zaglavlja točno kako piše) pa ponovi obradu. Ništa nije upisano."
        )

    # Neobavezni stupac slika_rjesenje_putanja (13.10.2026.): mora biti ZADNJI stupac, iza oznaka_stavke.
    ima_stupac_slika_rj = "slika_rjesenje_putanja" in headers
    if ima_stupac_slika_rj:
        if not ima_nove_stupce:
            raise RuntimeError(
                "U tabu 'Zadaci' postoji stupac 'slika_rjesenje_putanja', a nedostaju uloga, roditelj_id i "
                "oznaka_stavke. Redoslijed zadnjih stupaca mora biti: uloga, roditelj_id, oznaka_stavke, "
                "slika_rjesenje_putanja. Ništa nije upisano."
            )
        if headers.index("slika_rjesenje_putanja") != ZADACI_HEADERS.index("slika_rjesenje_putanja"):
            raise RuntimeError(
                "Stupac 'slika_rjesenje_putanja' u tabu 'Zadaci' nije na očekivanom mjestu (mora biti odmah "
                f"iza 'oznaka_stavke', stupac broj {ZADACI_HEADERS.index('slika_rjesenje_putanja') + 1}). Ništa nije upisano."
            )

    _idx_naziv = ZADACI_HEADERS.index("izvor_naziv")
    _idx_latex = ZADACI_HEADERS.index("tekst_zadatka_latex")
    _idx_cjelina = ZADACI_HEADERS.index("cjelina")
    _idx_id = ZADACI_HEADERS.index("id")
    _i_uloga = headers.index("uloga") if "uloga" in headers else None
    _i_rod = headers.index("roditelj_id") if "roditelj_id" in headers else None

    def _celija(row, i):
        return (row[i] if i is not None and len(row) > i else "") or ""

    # Uvodi postojećih skupina (za usporedbu postojećih stavki u obliku "uvod + stavka").
    uvod_skupine = {}
    if _i_uloga is not None:
        for row in data_rows:
            if _celija(row, _i_uloga).strip().lower() == "skupina":
                uvod_skupine[_celija(row, _idx_id).strip()] = _celija(row, _idx_latex)

    existing_lookup = []
    grupe_po_cjelini = {}
    for i, row in enumerate(data_rows):
        uloga_r = _celija(row, _i_uloga).strip().lower()
        if uloga_r == "skupina":
            continue  # redak skupine sadrži samo uvod - nikad kandidat za duplikat
        existing_naziv = row[_idx_naziv] if len(row) > _idx_naziv else ""
        existing_latex = row[_idx_latex] if len(row) > _idx_latex else ""
        if uloga_r == "stavka":
            existing_latex = f"{uvod_skupine.get(_celija(row, _i_rod).strip(), '')} {existing_latex}".strip()
        existing_cjelina = (row[_idx_cjelina] if len(row) > _idx_cjelina else "").strip()
        norm_existing = _normalize_za_usporedbu(existing_latex)
        stavka = (i + 2, existing_naziv, norm_existing, len(norm_existing))
        existing_lookup.append(stavka)
        grupe_po_cjelini.setdefault(existing_cjelina, []).append(stavka)
    bez_cjeline = grupe_po_cjelini.get("", [])

    id_prefix = izvor_naziv.replace(" ", "_")
    # Sljedeći broj ID-a iz STVARNO postojećih brojeva (max + 1), NE brojanjem redaka -
    # brojanje je krhko (brisanje redaka može generirati ID koji se poklapa s postojećim).
    _broj_id_re = re.compile(rf"^{re.escape(id_prefix)}_(\d+)$")
    _postojeci_brojevi = []
    for r in data_rows:
        if r and r[0]:
            m = _broj_id_re.match(r[0])
            if m:
                _postojeci_brojevi.append(int(m.group(1)))
    stanje = {
        "sljedeci": (max(_postojeci_brojevi) + 1) if _postojeci_brojevi else 1,
        "dodanih": 0, "azuriranih": 0, "skupina": 0,
    }
    novi_redovi = []
    # Sve izmjene POSTOJEĆIH redaka (duplikata) idu u JEDAN batch_update() na kraju
    # (Google Sheets limit "Write requests per minute"). gspread SAM dodaje naziv sheeta
    # ispred raspona, pa range ostaje gol ("N74:P74").
    sva_azuriranja_polja = []

    def _novi_id():
        zid = f"{id_prefix}_{stanje['sljedeci']:03d}"
        stanje["sljedeci"] += 1
        return zid

    def _podudaranje(z, tekst_za_usporedbu, je_stavka):
        norm_novi = _normalize_za_usporedbu(tekst_za_usporedbu)
        duljina_novi = len(norm_novi)
        najbolji_redak, najbolja_slicnost, najbolji_naziv = None, 0.0, None

        if ogranici_po_cjelini:
            nova_cjelina = (z.get("cjelina") or "").strip()
            kandidati = grupe_po_cjelini.get(nova_cjelina, [])
            if nova_cjelina and bez_cjeline:
                kandidati = kandidati + bez_cjeline
        else:
            kandidati = existing_lookup

        for row_number, existing_naziv, norm_existing, duljina_existing in kandidati:
            if duljina_novi and abs(duljina_existing - duljina_novi) / duljina_novi > 0.4:
                continue
            omjer = difflib.SequenceMatcher(None, norm_novi, norm_existing).ratio()
            if omjer > najbolja_slicnost:
                najbolja_slicnost, najbolji_redak, najbolji_naziv = omjer, row_number, existing_naziv

        isti_naziv = najbolji_redak and najbolji_naziv == izvor_naziv
        prag = prag_slicnosti_isti_naziv if isti_naziv else prag_slicnosti
        if je_stavka and duljina_novi < MIN_DULJINA_ZA_POUZDANU_USPOREDBU:
            prag = max(prag, PRAG_SLICNOSTI_KRATKA_STAVKA)

        # §25.9: kratak/generički tekst + slika -> usporedba teksta nepouzdana: NIKAD tiho
        # ne prepiši postojeći redak, dodaj kao nov i označi za ručnu provjeru.
        nesiguran = duljina_novi < MIN_DULJINA_ZA_POUZDANU_USPOREDBU and _ima_sliku(z)
        return {
            "redak": najbolji_redak, "slicnost": najbolja_slicnost, "isti_naziv": isti_naziv, "prag": prag,
            "nesiguran": nesiguran,
            "duplikat": bool(najbolji_redak and najbolja_slicnost >= prag and not nesiguran),
        }

    def _primijeni_duplikat(z, m):
        najbolji_redak = m["redak"]
        # Slova stupaca DINAMIČKI iz ZADACI_HEADERS (_col_letter).
        rjesenje_novo = z.get("rjesenje", "")
        if rjesenje_novo:
            c1, c2 = _col_letter("rjesenje"), _col_letter("tip_rjesenja_izvor")
            sva_azuriranja_polja.append({
                "range": f"{c1}{najbolji_redak}:{c2}{najbolji_redak}",
                "values": [[rjesenje_novo, "sluzbeno", z.get("tip_rjesenja_izvor", "")]],
            })
        for polje in ("potpoglavlje", "slika_putanja", "max_bodovi", "tip_zadatka", "slika_zadana",
                      "konacan_odgovor", "uputa"):
            if z.get(polje, ""):
                c = _col_letter(polje)
                sva_azuriranja_polja.append({"range": f"{c}{najbolji_redak}", "values": [[z.get(polje, "")]]})
        if z.get("ponudjeni_odgovori"):
            c = _col_letter("ponudjeni_odgovori")
            sva_azuriranja_polja.append({
                "range": f"{c}{najbolji_redak}", "values": [[" || ".join(z.get("ponudjeni_odgovori", []))]],
            })
        if log:
            znak = "📄" if m["isti_naziv"] else "🔤"
            log(f"🔁 Zadatak #{z.get('privremeni_broj')} = duplikat retka {najbolji_redak} "
                f"({znak}{m['slicnost']:.0%}, prag {m['prag']:.0%}) - nadopunjen.")
        stanje["azuriranih"] += 1

    def _napravi_redak(z, zid, status_provjere_novi, uloga="", roditelj_id="", oznaka=""):
        je_skupina = uloga == "skupina"
        redak = [
            zid, izvor_tip, izvor_naziv, godina, broj_pdf_ulaza,
            razina, "",
            z.get("kategorija", ""), z.get("cjelina", ""), z.get("potpoglavlje", ""), z.get("kljucne_rijeci", ""),
            z.get("tekst_zadatka_latex", ""), z.get("tekst_zadatka_mathjax", ""),
            z.get("rjesenje", ""),
            "" if je_skupina else ("sluzbeno" if z.get("rjesenje") else "nedostaje"),
            z.get("tip_rjesenja_izvor", ""),
            z.get("slika_putanja", ""), "",
            z.get("vizualni_potencijal", ""),
            "", "",
            z.get("tezina", ""), z.get("max_bodovi", ""),
            "",
            status_provjere_novi, skenirano,
            "",
            z.get("tip_zadatka", ""), z.get("slika_zadana", ""),
            " || ".join(z.get("ponudjeni_odgovori", []) or []), z.get("konacan_odgovor", ""),
            z.get("uputa", ""),
            "",  # redoslijed_u_potpoglavlju - postavlja se ručno kasnije (stranica u appu)
            # 26.10.2026.: koristi_kao_primjer_na_satu smije doći iz parametra batcha (npr. "Uvoz iz
            # foldera" kad je cijela serija jedan "Primjeri" izvor) - default "" (ne) kao i prije.
            koristi_kao_primjer_na_satu,
            "",  # u_skriptu - postavlja se ručno kasnije
            biblioteka_izvora,
        ]
        if ima_nove_stupce:
            redak += [uloga, roditelj_id, oznaka]
            if ima_stupac_slika_rj:
                redak.append(z.get("slika_rjesenje_putanja", ""))
        return redak

    def _dodaj_novi(z, m, uloga="", roditelj_id="", oznaka=""):
        zid = _novi_id()
        status_provjere_novi = z.get("status_provjere", "") or ""
        if m["nesiguran"] and m["redak"] and m["slicnost"] >= m["prag"]:
            napomena = (
                f"MOGUĆI duplikat retka {m['redak']} ({m['slicnost']:.0%}) - tekst prekratak/"
                "generički za pouzdanu automatsku usporedbu (zadatak sa slikom), provjeri ručno je li slika ista."
            )
            status_provjere_novi = f"{status_provjere_novi}; {napomena}" if status_provjere_novi else napomena
            if log:
                log(f"⚠️ Zadatak #{z.get('privremeni_broj')} - MOGUĆI duplikat retka {m['redak']} "
                    f"({m['slicnost']:.0%}), ali tekst je prekratak/generički (zadatak sa slikom) - "
                    "DODAN kao NOV zadatak i označen za ručnu provjeru, umjesto tihog spajanja s postojećim retkom.")
        novi_redovi.append(_napravi_redak(z, zid, status_provjere_novi, uloga, roditelj_id, oznaka))
        stanje["dodanih"] += 1
        return zid

    for j in jedinice:
        if j["tip"] == "samostalan":
            z = j["z"]
            m = _podudaranje(z, z.get("tekst_zadatka_latex", ""), False)
            if m["duplikat"]:
                _primijeni_duplikat(z, m)
            else:
                _dodaj_novi(z, m)
            continue

        skupina, stavke = j["skupina"], j["stavke"]
        uvod = skupina.get("tekst_zadatka_latex", "") or ""
        podudaranja = [
            _podudaranje(s, f"{uvod} {s.get('tekst_zadatka_latex', '')}".strip(), True) for s in stavke
        ]
        if all(m["duplikat"] for m in podudaranja):
            for s, m in zip(stavke, podudaranja):
                _primijeni_duplikat(s, m)
            if log:
                log(f"🔁 Skupina #{skupina.get('privremeni_broj')}: sve stavke već postoje u bazi - "
                    "redak skupine nije dodan.")
            continue
        id_skupine = _novi_id()
        novi_redovi.append(_napravi_redak(
            skupina, id_skupine, skupina.get("status_provjere", "") or "", uloga="skupina"))
        stanje["skupina"] += 1
        for s, m in zip(stavke, podudaranja):
            if m["duplikat"]:
                _primijeni_duplikat(s, m)
                if log:
                    log(f"ℹ️ Stavka #{s.get('privremeni_broj')} već postoji (redak {m['redak']}) i ostaje uz "
                        f"svoju staru skupinu; ostale stavke iz #{skupina.get('privremeni_broj')} dodane su "
                        f"u novu skupinu {id_skupine}.")
            else:
                _dodaj_novi(s, m, uloga="stavka", roditelj_id=id_skupine,
                            oznaka=str(s.get("oznaka_stavke", "") or ""))

    if novi_redovi:
        ws_zadaci.append_rows(novi_redovi)

    if sva_azuriranja_polja:
        # JEDAN poziv za SVE izmjene duplikata iz ove obrade (rješava "Quota exceeded" grešku).
        ws_zadaci.batch_update(sva_azuriranja_polja)

    if stanje["skupina"] and log:
        log(f"📚 Dodano {stanje['skupina']} skupina zadataka (retci skupina nisu ubrojeni u broj novih zadataka).")
    return stanje["dodanih"], stanje["azuriranih"]
