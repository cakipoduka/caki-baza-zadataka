# -*- coding: utf-8 -*-
"""
CAKI - uvoz_foldera.py (15.10.2026.)

UVOZ ZADATAKA IZ FOLDERA NA DRIVEU (slike i PDF-ovi) -> Mathpix OCR -> AI (Claude ILI DeepSeek) -> pregled -> baza.

Ovaj modul je SAMO LOGIKA (bez Streamlita), da se može testirati bez mreže. Sučelje je u pages/8_uvoz_iz_foldera.py.
NE mijenja nijednu postojeću datoteku: za sam upis u tab 'Zadaci' koristi POSTOJEĆE funkcije iz
baza_zadataka_pipeline.py (nadopuni_ili_dodaj_zadatke, sastavi_extraction_prompt, build_sifrarnik_text...) i
skupine_zadataka.py (pripremi_jedinice), tako da se detekcija duplikata, skupine/stavke i stupci ponašaju isto kao
kod ručnog uploada na stranici "Obradi novi ispit".

TOK (i zašto je tako):
  1. Popis datoteka iz foldera (Shared Drive) + grupiranje u IZVORE (npr. list_03_001.png, list_03_002.png, list_03_rj.png
     -> jedan izvor "list_03" sa zadacima i rješenjima).
  2. OCR (Mathpix) SAMO JEDNOM po datoteci: rezultat i sve slike iz njega spremaju se u podfolder _uvoz_cache na Driveu.
     Slike se preuzimaju ODMAH (Mathpix poveznice na slike isteknu), a AI ne vidi dugačke URL-ove nego kratke oznake
     SLIKA_01, SLIKA_02... (LLM-ovi često pokvare dugačke URL-ove).
  3. AI strukturira zadatke (isti prompt + isti šifrarnik kao postojeći uvoz, plus DODATAK_UVOZ s pravilima za rubne slučajeve).
     Dugi ulazi režu se na dijelove na granicama zadataka.
  4. Programska obrada odgovora (bez AI-ja): normalizacija LaTeX-a, provjera uparenosti, opcije, ključ, slike, numeracija...
     Sve što se ne može sigurno popraviti NE popravlja se tiho nego se upisuje u status_provjere.
  5. Rezultat se sprema kao JSON u _uvoz_cache (po modelu) - NIŠTA još nije u bazi. Dva modela = dva JSON-a = usporedba.
  6. Pregled na stranici, pa tek na klik upis (kopiranje slika u 02_SLIKE + nadopuni_ili_dodaj_zadatke).
  7. Evidencija u tabu 'Uvoz_izvori' (kvačice: što je obrađeno, kojim modelom, što je uneseno).
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import re
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zagreb")
PROMPT_VERZIJA = "uvoz-2026-10-15"
CACHE_FOLDER_NAZIV = "_uvoz_cache"
IZVOR_TIPOVI = ["matura", "zbirka", "udzbenik", "vlastiti_materijal", "fakultet"]

# ---------------------------------------------------------------------------------------------------------------
# 1. MODELI (isti nazivi kao u AI asistentu u Rasporedu Matura)
# ---------------------------------------------------------------------------------------------------------------

MODELI = {
    "Claude (claude-sonnet-5)": {"pruzatelj": "claude", "model": "claude-sonnet-5",
                                 "max_izlaz": 40000, "dio_znakova": 40000},
    "DeepSeek V4 Pro": {"pruzatelj": "deepseek", "model": "deepseek-v4-pro",
                        "max_izlaz": 24000, "dio_znakova": 18000},
    "DeepSeek Flash": {"pruzatelj": "deepseek", "model": "deepseek-flash",
                       "max_izlaz": 24000, "dio_znakova": 18000},
}
KLJUC_SECRETS = {"claude": "ANTHROPIC_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
ZADANI_MODELI = ["Claude (claude-sonnet-5)"]
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def kratki_naziv_modela(naziv: str) -> str:
    """'DeepSeek V4 Pro' -> 'deepseek-v4-pro' (za nazive datoteka i evidenciju)."""
    return re.sub(r"[^a-z0-9]+", "-", naziv.lower()).strip("-")[:40]


def pozovi_claude(kljuc, model, system, user, max_tokens):
    import anthropic  # lijeni uvoz: testovi ga ne trebaju
    client = anthropic.Anthropic(api_key=kljuc)
    # thinking isključen: za strukturirani JSON razmišljanje samo troši max_tokens (isto kao u postojećem uvozu)
    with client.messages.stream(model=model, max_tokens=max_tokens, system=system,
                                messages=[{"role": "user", "content": user}],
                                thinking={"type": "disabled"}) as stream:
        odg = stream.get_final_message()
    tekst = "".join(getattr(b, "text", "") for b in odg.content if getattr(b, "type", "") == "text")
    return {"tekst": tekst, "tokeni_ulaz": odg.usage.input_tokens, "tokeni_izlaz": odg.usage.output_tokens,
            "odrezano": odg.stop_reason == "max_tokens"}


def pozovi_deepseek(kljuc, model, system, user, max_tokens, json_nacin=True, log=None):
    import requests
    headers = {"Authorization": f"Bearer {kljuc}", "Content-Type": "application/json"}
    tijelo = {"model": model, "max_tokens": max_tokens, "temperature": 0,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_nacin:
        tijelo["response_format"] = {"type": "json_object"}
    greska = None
    for pokusaj in range(1, 7):
        try:
            r = requests.post(DEEPSEEK_URL, headers=headers, json=tijelo, timeout=900)
        except requests.exceptions.Timeout:
            greska = "timeout"
            if log:
                log(f"⏳ DeepSeek timeout, pokušaj {pokusaj}/6...")
            continue
        if r.status_code == 400:
            # Neki modeli ne prihvaćaju JSON mode / temperaturu / ovako velik max_tokens: skidaj jedno po jedno.
            if "response_format" in tijelo:
                tijelo.pop("response_format")
            elif "temperature" in tijelo:
                tijelo.pop("temperature")
            elif tijelo["max_tokens"] > 8192:
                tijelo["max_tokens"] = 8192
            else:
                r.raise_for_status()
            if log:
                log(f"ℹ️ DeepSeek je odbio zahtjev (400: {r.text[:120]}), ponavljam s blažim postavkama...")
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            greska = f"HTTP {r.status_code}: {r.text[:200]}"
            if log:
                log(f"⏳ DeepSeek zauzet ({r.status_code}), pokušaj {pokusaj}/6...")
            time.sleep(min(60, 8 * pokusaj))
            continue
        r.raise_for_status()
        odg = r.json()
        izbor = odg["choices"][0]
        kor = odg.get("usage", {})
        return {"tekst": izbor["message"].get("content", "") or "", "tokeni_ulaz": kor.get("prompt_tokens", 0),
                "tokeni_izlaz": kor.get("completion_tokens", 0), "odrezano": izbor.get("finish_reason") == "length"}
    raise RuntimeError(f"DeepSeek nije odgovorio: {greska}")


def napravi_pozivatelja(naziv_modela: str, kljuc: str, log=None):
    """Vraća pozovi(system, user, json_lista=True) -> dict(tekst, tokeni_ulaz, tokeni_izlaz, odrezano)."""
    m = MODELI[naziv_modela]
    if m["pruzatelj"] == "claude":
        return lambda system, user, max_tokens=None: pozovi_claude(
            kljuc, m["model"], system, user, max_tokens or m["max_izlaz"])
    return lambda system, user, max_tokens=None: pozovi_deepseek(
        kljuc, m["model"], system, user, max_tokens or m["max_izlaz"], json_nacin=True, log=log)


# ---------------------------------------------------------------------------------------------------------------
# 2. PROMPT: postojeći EXTRACTION_SYSTEM_PROMPT + DODATAK_UVOZ (pravila za rubne slučajeve)
# ---------------------------------------------------------------------------------------------------------------

DODATAK_UVOZ = r"""

=== DODATAK ZA UVOZ IZ FOLDERA (vrijedi uz SVE gore navedeno; kod sukoba vrijedi ovaj dodatak) ===
Ulaz dolazi iz fotografija, skenova i PDF-ova radnih listića, zbirki i ispita (i s fakulteta). OCR (Mathpix) griješi.
Tvoj posao je da NIŠTA ne izmisliš i da svaku nesigurnost učiniš VIDLJIVOM u polju status_provjere. Bolje je označiti
10 zadataka za provjeru nego tiho upisati jedan pogrešan. Znanje koje imaš ne smije popuniti ono što u ulazu ne piše.

D1. STRUKTURA ULAZA
- Ulaz može biti spojen iz više datoteka (stranica/slika). Granice su označene retkom [[DATOTEKA k/n: naziv]].
  Taj redak NIKAD ne ide u tekst zadatka, rješenje ni ponuđene odgovore.
- Zadatak može početi na kraju jedne datoteke i nastaviti se na početku sljedeće (odrezana rečenica, opcije A i B na jednoj,
  C i D na drugoj, podzadatak b) na sljedećoj). To je JEDAN zadatak: spoji ga i u status_provjere upiši
  "SPOJENO: zadatak se nastavlja iz druge datoteke". Ne stvaraj dva zadatka od jednog niti pola zadatka.
- Ako je ulaz označen kao dio većeg dokumenta ([[DIO k/m]]), obradi SAMO zadatke koji u ovom dijelu počinju.
- Zadatak odrezan na samom kraju ulaza ipak vrati, uz "ODREZAN: zadatak je nepotpun na kraju ulaza".

D2. ŠTO NIJE ZADATAK (izostavi; ne pretvaraj u zadatke i ne stavljaj u tekst zadatka)
- naslovi i upute za cijeli list, zaglavlja, podnožja, brojevi stranica, imena škola/autora/nakladnika, datumi, "Ime i prezime",
  razred, tablice bodovanja i ocjenjivanja, URL-ovi, QR kodovi, napomene o autorskim pravima, popisi konstanti i formula;
- rukom pisane bilješke, ispravke i zaokruženi, podcrtani ili označeni odgovori učenika: NE ulaze u tekst i iz njih NIKAD ne
  zaključuj točan odgovor (konacan_odgovor smije doći samo iz TISKANOG ključa/rješenja). Ako je odgovor označen rukom,
  upiši "OZNAČEN ODGOVOR: vidi se označeno X (nije ključ)".

D3. NUMERACIJA
- privremeni_broj = izvorni tiskani broj ("7", "7.", "Zadatak 7" -> "7"). Mora biti JEDINSTVEN u cijelom odgovoru.
- Ako se brojevi ponavljaju jer dokument ima dijelove (npr. "A dio: 1-10", "B dio: 1-5"), privremeni_broj = oznaka dijela + broj
  ("A1", "B1"). Oznaku dijela koristi samo ako je tiskana u izvoru.
- Zadatak bez broja: privremeni_broj "bez-broja-1", "bez-broja-2"... i "NUMERACIJA: nema izvornog broja".
- Preskočen ili udvojen broj u izvoru (1, 2, 4 ili 3, 3): prepiši kako piše, NE izmišljaj zadatke kojih nema, i uz zadatak iza
  praznine upiši "NUMERACIJA: ...".

D4. SKUPINE, PODZADACI I SETOVI (dopuna točke 1b)
Odluči ovim redom:
(a) JEDAN broj s oznakama a), b), c) ili 1), 2), 3) koje se rješavaju zasebno -> SKUPINA + STAVKE (uvod u skupini, stavke bez uvoda).
    oznaka_stavke = oznaka bez zagrade.
(b) SET: zajednički uvod (tekst, tablica, graf, slika; npr. "Za zadatke 5. do 8. koristi graf") i VIŠE ZASEBNO NUMERIRANIH zadataka
    (5, 6, 7, 8) s vlastitim bodovima -> jedna SKUPINA (privremeni_broj = raspon "5-8"; tekst_zadatka_latex = zajednički uvod;
    slika uvoda na skupini) i po jedna STAVKA za svaki numerirani zadatak (privremeni_broj = tiskani broj, oznaka_stavke =
    tiskani broj, roditelj_privremeni_broj = "5-8"). Svaka stavka sama određuje svoj tip_zadatka (stavka seta SMIJE biti
    visestruki_izbor s ponudjeni_odgovori) i svoje max_bodovi. Ako zajednički uvod ima samo JEDNO pitanje, to je običan zadatak
    (samostalan) s uvodom u tekstu.
(c) Dvije razine (a) i unutar njega i), ii)): spljošti u jednu razinu - tekst stavke = tekst oznake a) + tekst oznake i),
    oznaka_stavke = "a.i" - i upiši "SKUPINA: dvije razine podzadataka spljoštene".
(d) Zajednički uvod koji se ponavlja uz svaki podzadatak NE kopiraj u stavke.
(e) Rješenja stavki traži po broju I oznaci stavke. Ako postoji samo JEDNO zajedničko rješenje za cijelu skupinu, stavi ga u
    rjesenje PRVE stavke i toj stavci dodaj "RJESENJE: zajedničko za cijelu skupinu, podijeli ručno". Ne ponavljaj ga u svim stavkama.
(f) Ako nisi siguran je li nešto skupina ili niz zasebnih zadataka, napravi zasebne samostalne zadatke s kompletnim tekstom
    (uvod ponovljen) i upiši "SKUPINA: nejasno je li skupina".

D5. TIPOVI ZADATAKA (tip_zadatka smije biti SAMO visestruki_izbor, kratki_odgovor ili prosireni_odgovor)
- visestruki_izbor: ponuđeno je barem 2 odgovora označena A-E, a)-e), (A) ili 1.-4.
- točno/netočno: svaka tvrdnja je stavka skupine, tip kratki_odgovor; konacan_odgovor "T" ili "N" SAMO ako je tiskano u ključu.
- spajanje, nizanje, tablica za popunjavanje: prosireni_odgovor uz "TIP: spajanje/popunjavanje, provjeri".
- dopunjavanje praznina: kratki_odgovor; praznine kao $\ldots$. Konstrukcije i crtanje: prosireni_odgovor.

D6. VIŠESTRUKI IZBOR - DETALJI
- Opcije NIKAD ne ostaju u tekstu zadatka (tekst_zadatka_latex završava pitanjem). Svaka opcija je JEDAN element liste
  ponudjeni_odgovori, redoslijedom, BEZ oznake (A), a), 1.) i BEZ $ (čist LaTeX; običan tekst ostaje običan tekst).
- OCR često spoji opcije u jedan redak ("A) 5 B) 6 C) 7 D) 8") ili ih razlomi u dva retka: rastavi ih po oznakama.
- Obično ima 4 opcije (rijetko 3 ili 5). Ako ih nađeš manje od 3 ili više od 5, ili oznake preskaču slovo (A, B, D), NE popunjavaj
  izmišljeno: na to mjesto stavi "[NEJASNO]" i upiši "OPCIJE: ...".
- Dvije opcije koje su nakon čitanja identične gotovo sigurno su OCR greška: "OPCIJE: opcije X i Y izgledaju jednake".
- konacan_odgovor = SAMO jedno veliko slovo (A-E) i samo iz tiskanog ključa. Ako ključ daje vrijednost umjesto slova
  (npr. "Odgovor: 12"), nađi opciju s tom vrijednošću i upiši njezino slovo; ako takve opcije nema, konacan_odgovor ostaje prazan
  i upiši "KLJUC: ...".
- Ako su same opcije slike/crteži/grafovi: tip visestruki_izbor, slika_zadana "da", slika_url sadrži SVE oznake slika redoslijedom
  opcija (A, B, C, D), ponudjeni_odgovori = ["slika A", "slika B", ...] i "OPCIJE-SLIKE: opcije su slike, redoslijed A, B, C, D, provjeri".
- Ako je slika u pitanju, a opcije su tekst/brojevi: slika_url = slika pitanja, ponudjeni_odgovori normalno.
- Ako je slika u pitanju I opcije su slike: prvo slika pitanja, zatim slike opcija, uz "OPCIJE-SLIKE: prva slika je u pitanju".
- Oznake točaka s crteža (A B C D E F...) koje stoje u zasebnom retku bez rečenice NISU opcije ni tekst zadatka (Mathpix ih ispiše
  kad čita crtež): izostavi ih.

D7. SLIKE I CRTEŽI
- U ulazu su slike zamijenjene oznakama oblika ![](SLIKA_07). U slika_url i slika_rjesenje_url smiješ upisati SAMO oznake koje
  doista postoje u ulazu (npr. SLIKA_07; više njih odvoji znakom |). NIKAD ne izmišljaj oznaku ni URL.
- Slika iz dijela RJEŠENJA/ključa ide u NOVO polje slika_rjesenje_url (ne u slika_url). Rješenje bez slike: polje prazno.
- Logo, ukras ili fotografija bez informacije za zadatak: slika_zadana "ne".
- Ako zadatak upućuje na sliku/graf/skicu/tablicu ("na slici", "prikazano", "graf funkcije") a u ulazu NEMA oznake slike
  (OCR slike iz fotografije ne prenosi): slika_zadana "da", slika_url "" i "SLIKA: zadatak ovisi o slici koje nema u ulazu,
  treba ručno dodati". Ne rješavaj zadatak i ne izmišljaj podatke sa slike.

D8. RJEŠENJA I KLJUČ
- Rješenje upisuješ samo ako je TISKANO u ulazu (odjeljak RJEŠENJA ili 'RJ:' ispod zadatka), i to doslovno. Nikad ga ne računaj, ne
  provjeravaj i ne ispravljaj. Ako ti se tiskano rješenje čini pogrešno, ostavi ga netaknuto i dodaj "RJESENJE: sumnjivo - razlog".
- Ključ u obliku tablice ili niza ("1-B, 2-D", "1. C 2. A") -> konacan_odgovor odgovarajućeg zadatka (slovo). Spajaj po TISKANOM BROJU
  zadatka, ne po redoslijedu pojavljivanja. Rješenje bez zadatka ili zadatak bez rješenja: ništa ne izmišljaj, upiši "KLJUC: ...".
- Rješenje s dijelovima a), b), c) u samostalnom zadatku zadrži s oznakama unutar teksta rješenja; u skupini svaka stavka dobiva svoj dio.
- Bodovanje ("1 bod", "[2]", "(0,5 b)") -> max_bodovi (samo broj) i makni iz teksta zadatka.
- konacan_odgovor je kratak (broj, izraz, slovo); puni postupak ide samo u rjesenje.

D9. ZAPIS (LaTeX) - pravila baze
- Sva matematika UNUTAR $...$ (u retku). NE koristi $$...$$, \(...\), \[...\] ni \begin{equation}. Višeretčane formule:
  $\begin{aligned} ... \end{aligned}$.
- Decimalni zarez piše se {,}: $2{,}5$. Tisućice tankim razmakom: $12\,500$. Broj s jedinicom: $12\,\mathrm{cm}$, $3\,\mathrm{dm}^3$, $25\%$.
- Množenje \cdot (ili \times ako je u izvoru ×). Dijeljenje: ostavi dvotočku ":" ako je u izvoru dvotočka, inače \div. Ne mijenjaj oblik iz izvora.
- Samo LaTeX naredbe, nikad Unicode matematički znakovi (≤ ≥ ≠ × ÷ √ ² ³ ½ ∞ π ∈ ∪ ∩ → °): \leq \geq \neq \times \div \sqrt{} ^2 ^3
  \frac{1}{2} \infty \pi \in \cup \cap \to ^\circ.
- \frac{a}{b}; mješoviti broj $2\frac{1}{3}$; \sqrt{5}, \sqrt[3]{x}; kut $45^\circ$, \angle ABC, \triangle ABC, \overline{AB}, \perp, \parallel.
- Hrvatska slova č ć š đ ž piši izravno (ne \v{c}). U običnom tekstu (izvan $) posebni znakovi se escapeaju: \% \& \# \_ \$.
- Redni brojevi i godine ("5. razred", "2026.") ostaju običan tekst. Brojevi koji su podatak zadatka (mjere, količine, računi) idu u $...$.
- Tablice: \begin{tabular}{...} s točnim brojem stupaca; formule u ćelijama u $...$; ako ne možeš sigurno rekonstruirati: "TABLICA: provjeri".
- Svaki $ mora imati par, svaka { svoju }, svaki \left svoj \right, svaki \begin svoj \end.
- NE prepisuj u tekst zadatka: broj zadatka na početku, bodove u zagradi, "Odgovor: ____", crte za upis, oznake opcija, rješenje.
- Ne mijenjaj redoslijed riječi, ne skraćuj, ne dopunjuj, ne "poboljšavaj" formulaciju i ne ispravljaj sumnjive brojeve: vjerno prepiši.
  Sumnju zapiši u status_provjere.

D10. NEJASNO I status_provjere
- Što ne možeš pročitati ili je odrezano: ne pogađaj. Na to mjesto upiši [NEJASNO] ili [NEJASNO: što se vidi] i dodaj "NEJASNO: ..."
  u status_provjere.
- Tipične OCR zamjene koje moraš aktivno tražiti (označi ako nisi siguran): l/1/I, O/0, S/5, Z/2, B/8, x/×, v/√, nestali minus ili
  zagrada, a2 umjesto a^2, 1/2 umjesto \frac{1}{2}, ćirilična slova umjesto latiničnih.
- status_provjere je kratak popis odvojen sa "; ", a svaka stavka počinje jednom od riječi: OCR, NEJASNO, SLIKA, OPCIJE, OPCIJE-SLIKE,
  KLJUC, RJESENJE, NUMERACIJA, SKUPINA, TIP, TABLICA, SPOJENO, ODREZAN, OZNAČEN ODGOVOR. Zadatak bez ikakve sumnje: prazan string.

D11. POTPUNOST
- Svaki tiskani zadatak iz ulaza MORA biti u odgovoru, čak i ako je nečitljiv (tada s [NEJASNO] i objašnjenjem). Ne preskači zadatke i
  ne spajaj dva zadatka u jedan.
- Dodatno NEOBAVEZNO polje: slika_rjesenje_url (vidi D7).

PRIMJERI (prikazana su samo bitna polja; ostala popuni kao inače)

Primjer 1 - višestruki izbor sa slikom u pitanju. Ulaz: "5. Na slici je kocka $ABCDEFGH$. ![](SLIKA_03) A B C D E F G H Kolika je duljina
prostorne dijagonale kocke ako je brid $a=5$? A) 5 B) $5 \sqrt{2}$ C) $5 \sqrt{3}$ D) 25" i u ključu "5. C". Izlaz:
{"privremeni_broj": "5", "uloga": "samostalan", "tekst_zadatka_latex": "Na slici je kocka $ABCDEFGH$. Kolika je duljina prostorne dijagonale kocke ako je brid $a=5$?", "tip_zadatka": "visestruki_izbor", "slika_zadana": "da", "slika_url": "SLIKA_03", "ponudjeni_odgovori": ["5", "5\\sqrt{2}", "5\\sqrt{3}", "25"], "konacan_odgovor": "C", "status_provjere": ""}
(oznake točaka "A B C D E F G H" ispod slike NISU tekst zadatka)

Primjer 2 - set. Ulaz: "Za zadatke 6. i 7. koristi tablicu. [tablica] 6. Koliko je učenika ukupno? 7. Koji je razred najbrojniji? A) 5.a B) 5.b C) 5.c". Izlaz:
{"privremeni_broj": "6-7", "uloga": "skupina", "tekst_zadatka_latex": "Koristi tablicu. \\begin{tabular}{|c|c|} ... \\end{tabular}"},
{"privremeni_broj": "6", "uloga": "stavka", "roditelj_privremeni_broj": "6-7", "oznaka_stavke": "6", "tekst_zadatka_latex": "Koliko je učenika ukupno?", "tip_zadatka": "kratki_odgovor"},
{"privremeni_broj": "7", "uloga": "stavka", "roditelj_privremeni_broj": "6-7", "oznaka_stavke": "7", "tekst_zadatka_latex": "Koji je razred najbrojniji?", "tip_zadatka": "visestruki_izbor", "ponudjeni_odgovori": ["5.a", "5.b", "5.c"]}

Primjer 3 - slika koje nema u ulazu (fotografija). Ulaz: "3. Na slici je graf funkcije $f$. Odredi $f(2)$." (bez oznake slike). Izlaz:
{"privremeni_broj": "3", "uloga": "samostalan", "tekst_zadatka_latex": "Na slici je graf funkcije $f$. Odredi $f(2)$.", "tip_zadatka": "kratki_odgovor", "slika_zadana": "da", "slika_url": "", "status_provjere": "SLIKA: zadatak ovisi o slici koje nema u ulazu, treba ručno dodati"}
"""

DEEPSEEK_NAPOMENA = """

TEHNIČKA NAPOMENA ZA OVO SUČELJE: odgovori JEDNIM JSON OBJEKTOM oblika {"zadaci": [ ... ]}, gdje je lista točno ona lista objekata
koju gore tražimo (isti nazivi polja). Bez ikakvog teksta izvan tog objekta."""


def sastavi_prompt(predmet: str = "matematika", pruzatelj: str = "claude") -> str:
    """Cijeli system prompt: postojeći za predmet + DODATAK_UVOZ (+ napomena o obliku odgovora za DeepSeek)."""
    from baza_zadataka_pipeline import sastavi_extraction_prompt
    p = sastavi_extraction_prompt(predmet) + DODATAK_UVOZ
    if pruzatelj == "deepseek":
        p += DEEPSEEK_NAPOMENA
    return p


def sastavi_korisnicku_poruku(sifrarnik, sifrarnik_potpoglavlja, ispit_md, rjesenja_md=None,
                              izvor_naziv="", vrsta_ulaza="", tokeni=None, dio=None):
    """Isti raspored kao u postojećem extract_zadaci_with_claude, plus kratka napomena o ulazu."""
    s = (f"ŠIFRARNIK (koristi isključivo ove kategorije/cjeline, doslovno):\n{sifrarnik}\n\n"
         f"ŠIFRARNIK POTPOGLAVLJA (za svaku cjelinu, koristi isključivo navedena potpoglavlja, doslovno):\n"
         f"{sifrarnik_potpoglavlja}\n\n")
    napomena = [f"Izvor: {izvor_naziv}" if izvor_naziv else "", f"Vrsta ulaza: {vrsta_ulaza}" if vrsta_ulaza else ""]
    if tokeni is not None:
        napomena.append("Dostupne oznake slika u ulazu: " + (", ".join(tokeni) if tokeni else "nema nijedne (nema slika u ulazu)"))
    if dio and dio[1] > 1:
        napomena.append(f"[[DIO {dio[0]}/{dio[1]}]] - ovo je dio većeg dokumenta, obradi samo zadatke koji u ovom dijelu počinju.")
    napomena = [n for n in napomena if n]
    if napomena:
        s += "=== NAPOMENA O ULAZU ===\n" + "\n".join(napomena) + "\n\n"
    s += f"=== TEKST ISPITA (Mathpix Markdown) ===\n{ispit_md}\n"
    if rjesenja_md:
        s += f"\n=== TEKST RJEŠENJA/BODOVANJA (Mathpix Markdown) ===\n{rjesenja_md}\n"
    return s


# ---------------------------------------------------------------------------------------------------------------
# 3. NAZIVI DATOTEKA -> IZVORI (grupiranje)
# ---------------------------------------------------------------------------------------------------------------

SLIKA_EKS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_RJ_RE = re.compile(r"(?i)(?:^|[\s_\-.()])(rj|rješ|rjes|rješenj\w*|rjesenj\w*|ključ|kljuc|solutions?|answers?|key)(\d*)(?=$|[\s_\-.()])")
_RJ_MAPA_RE = re.compile(r"(?i)^(rj|rješenja|rjesenja|rješenje|rjesenje|ključ|kljuc|solutions?|key|answers?)$")
_STRANICA_RE = re.compile(r"(?i)[\s_\-]*(?:str(?:anica|ana)?|page|p|slika|img|scan)[\s_\-.]*\(?\d{1,4}\)?$")
_IMPL_STRANICA_RE = re.compile(r"(?:[\s_\-]+\d{1,4}|\s*\(\d{1,3}\))$")
ULOGE = ["zadaci", "rješenja", "preskoči"]


def prirodni_kljuc(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]


def _stem(naziv: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{2,5}$", "", naziv or "")


def vrsta_datoteke(f: dict) -> str:
    """'pdf' | 'slika' | '' (nije podržano). Gleda ekstenziju, a ako nje nema, MIME tip."""
    naziv = (f.get("name") or "").lower()
    mime = (f.get("mimeType") or "").lower()
    ext = "." + naziv.rsplit(".", 1)[-1] if "." in naziv else ""
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext in SLIKA_EKS or mime.startswith("image/"):
        return "slika"
    return ""


def mathpix_ime(f: dict) -> str:
    """Naziv s ekstenzijom koji Mathpix helper (pipeline.je_slika) prepoznaje."""
    naziv = f.get("name") or "datoteka"
    v = vrsta_datoteke(f)
    if v == "pdf" and not naziv.lower().endswith(".pdf"):
        return naziv + ".pdf"
    if v == "slika" and "." + naziv.lower().rsplit(".", 1)[-1] not in SLIKA_EKS:
        mime = (f.get("mimeType") or "image/png").split("/")[-1].replace("jpeg", "jpg")
        return f"{naziv}.{mime}"
    return naziv


def izvuci_folder_id(tekst: str) -> str:
    """Drive poveznica ili sirovi ID -> ID foldera ('' ako se ne prepoznaje)."""
    t = (tekst or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", t) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", t)
    if m:
        return m.group(1)
    return t if re.fullmatch(r"[A-Za-z0-9_-]{10,}", t) else ""


def _ocisti_stem_za_grupu(stem: str) -> str:
    s = _RJ_RE.sub(" ", stem)
    s = _STRANICA_RE.sub("", s)
    return re.sub(r"[\s_\-.]+$", "", re.sub(r"\s{2,}", " ", s)).strip()


def predlozi_grupiranje(datoteke: list[dict], nacin: str = "auto") -> list[dict]:
    """datoteke: [{id, name, mimeType, putanja: [mape...]}]. Vraća redove tablice za uređivanje:
    [{id, naziv, putanja, vrsta, uloga, grupa}] u prirodnom redoslijedu.
    nacin: 'auto' (po nazivu unutar mape), 'po_podmapi' (jedna mapa = jedan izvor), 'svaka_datoteka', 'sve_jedan'."""
    redovi = []
    for f in datoteke:
        v = vrsta_datoteke(f)
        put = list(f.get("putanja") or [])
        stem = _stem(f.get("name", ""))
        je_rj = bool(_RJ_RE.search(stem))
        # mapa s rješenjima ("rjesenja/") -> datoteke su rješenja, a izvor se određuje po mapi iznad
        eff_put = list(put)
        if eff_put and _RJ_MAPA_RE.match(eff_put[-1].strip()):
            je_rj = True
            eff_put = eff_put[:-1]
        elif eff_put and _RJ_RE.search(eff_put[-1]) and not _STRANICA_RE.search(eff_put[-1]):
            pass  # mapa s nazivom poput "ispit rj" tretira se kao običan izvor
        redovi.append({"f": f, "v": v, "stem": stem, "put": eff_put, "rj": je_rj, "orig_put": put})

    # implicitni sufiks stranice ("list_3_001") skidamo samo ako ISTI prefiks ima još barem jedna datoteka u istoj mapi
    prefiksi = {}
    for r in redovi:
        ocist = _ocisti_stem_za_grupu(r["stem"])
        r["ocist"] = ocist
        impl = _IMPL_STRANICA_RE.sub("", ocist).strip(" _-.")
        r["impl"] = impl
        prefiksi.setdefault((tuple(r["put"]), impl.lower()), set()).add(r["f"]["id"])

    izlaz = []
    for r in redovi:
        f = r["f"]
        if r["v"] == "":
            grupa, uloga = "", "preskoči"
        else:
            uloga = "rješenja" if r["rj"] else "zadaci"
            if nacin == "svaka_datoteka":
                grupa = _ocisti_stem_za_grupu(r["stem"]) or r["stem"]
                uloga = "zadaci"
            elif nacin == "sve_jedan":
                grupa = "izvor"
            elif nacin == "po_podmapi":
                grupa = r["put"][-1] if r["put"] else (r["ocist"] or r["stem"])
            else:  # auto
                osnova = r["impl"] if len(prefiksi.get((tuple(r["put"]), r["impl"].lower()), ())) >= 2 else r["ocist"]
                grupa = osnova or r["stem"]
        izlaz.append({"id": f["id"], "naziv": f.get("name", ""), "putanja": "/".join(r["orig_put"]),
                      "vrsta": r["v"] or "—", "uloga": uloga, "grupa": grupa, "_kljuc": (r["orig_put"], f.get("name", ""))})
    izlaz.sort(key=lambda x: (prirodni_kljuc(x["putanja"]), prirodni_kljuc(x["naziv"])))
    for x in izlaz:
        x.pop("_kljuc", None)
    return izlaz


def sastavi_grupe(redovi: list[dict], datoteke_po_id: dict) -> dict:
    """redovi (nakon Cakijevih izmjena) -> {grupa: {"zadaci": [datoteka...], "rjesenja": [...]}} (u redoslijedu redaka)."""
    grupe = {}
    for r in redovi:
        g = (r.get("grupa") or "").strip()
        if not g or r.get("uloga") not in ("zadaci", "rješenja") or r["id"] not in datoteke_po_id:
            continue
        d = grupe.setdefault(g, {"zadaci": [], "rjesenja": []})
        d["zadaci" if r["uloga"] == "zadaci" else "rjesenja"].append(datoteke_po_id[r["id"]])
    return grupe


def sanitiziraj_izvor_naziv(naziv: str) -> str:
    s = unicodedata.normalize("NFC", naziv or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^\w\-.]", "", s)
    return re.sub(r"_+", "_", s).strip("_.")[:60] or "izvor"


def predlozi_godinu(naziv: str) -> str:
    m = re.search(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)", naziv or "")
    return m.group(1) if m else ""


def otisak_datoteka(datoteke: list[dict]) -> str:
    """Otisak skupa datoteka (id + md5/vrijeme izmjene): promijeni li se datoteka, otisak se promijeni."""
    dijelovi = sorted(f"{f.get('id')}:{f.get('md5Checksum') or f.get('modifiedTime') or ''}" for f in datoteke)
    return hashlib.sha1("|".join(dijelovi).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------------------------------------------
# 4. OCR TEKST: čišćenje, slike -> oznake, rezanje na dijelove
# ---------------------------------------------------------------------------------------------------------------

_SLIKA_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
_SLIKA_HTML_RE = re.compile(r"<img[^>]+src=[\"'](https?://[^\"']+)[\"'][^>]*>", re.I)
_ZW_RE = re.compile("[\u200b\u200c\u200d\ufeff]")


def ocisti_ocr(md: str) -> str:
    """Bezopasno čišćenje OCR teksta PRIJE slanja AI-ju (ne dira sadržaj): znakovi nulte širine, NBSP, prijelomi redaka,
    višestruki prazni redovi. Delimitere formula NE dira (to radi normaliziraj_matematiku nad odgovorom AI-ja)."""
    t = (md or "").replace("\r\n", "\n").replace("\r", "\n")
    t = _ZW_RE.sub("", t).replace("\u00a0", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def izdvoji_url_slika(md: str) -> list[str]:
    """Jedinstveni URL-ovi slika iz Mathpix Markdowna, redoslijedom pojavljivanja."""
    urlovi = []
    for m in sorted(list(_SLIKA_MD_RE.finditer(md)) + list(_SLIKA_HTML_RE.finditer(md)), key=lambda x: x.start()):
        if m.group(1) not in urlovi:
            urlovi.append(m.group(1))
    return urlovi


def zamijeni_url_slika(md: str, mapa_url_oznaka: dict) -> str:
    """URL -> '![](oznaka)'. URL kojeg nema u mapi (nije preuzet) postaje ![](SLIKA_NEDOSTUPNA)."""
    def md_zamjena(m):
        return f"![]({mapa_url_oznaka.get(m.group(1), 'SLIKA_NEDOSTUPNA')})"
    t = _SLIKA_MD_RE.sub(md_zamjena, md)
    return _SLIKA_HTML_RE.sub(md_zamjena, t)


def sastavi_ulaz(dijelovi: list[dict], pocetni_broj: int = 1, oznaka: str = "DATOTEKA"):
    """dijelovi: [{naziv, md, slike: [{oznaka_lok, drive_id, naziv}]}] (md ima ![](@S1) oznake iz cachea).
    Vraća (md_ukupno, mapa_slika, sljedeci_broj): globalne oznake SLIKA_NN, markeri [[DATOTEKA k/n: naziv]]."""
    mapa, dijelovi_md, br = {}, [], pocetni_broj
    n = len(dijelovi)
    for k, d in enumerate(dijelovi, 1):
        md = ocisti_ocr(d.get("md", ""))
        lok = {}
        for s in d.get("slike") or []:
            glob = f"SLIKA_{br:02d}"
            br += 1
            lok[s["oznaka_lok"]] = glob
            mapa[glob] = {"drive_id": s.get("drive_id", ""), "naziv": s.get("naziv", ""), "datoteka": d.get("naziv", "")}
        md = re.sub(r"!\[[^\]]*\]\(@(S\d+)\)", lambda m: f"![]({lok.get(m.group(1), 'SLIKA_NEDOSTUPNA')})", md)
        dijelovi_md.append(f"[[{oznaka} {k}/{n}: {d.get('naziv', '')}]]\n{md}")
    return "\n\n---\n\n".join(dijelovi_md), mapa, br


_GRANICA_ZADATKA_RE = re.compile(
    r"(?m)^[ \t]*(?:#{1,4}[ \t]*)?(?:\*\*)?[ \t]*(?:Zadatak[ \t]+|Zad\.[ \t]*)?(\d{1,3})[ \t]*(?:\.|\*\*\.?)[ \t]+\S|"
    r"^[ \t]*(?:#{1,4}[ \t]*)?(?:\*\*)?[ \t]*Zadatak[ \t]+(\d{1,3})\b")
_PRAZNI_RED_RE = re.compile(r"\n\s*\n")


def _okoliš_ok(md: str, pozicija: int) -> bool:
    """Ne reži unutar tablice/okoline: broj \\begin == broj \\end ispred pozicije."""
    pred = md[:pozicija]
    return len(re.findall(r"\\begin\{", pred)) == len(re.findall(r"\\end\{", pred))


def podijeli_md(md: str, max_znakova: int) -> list[str]:
    """Reže dugačak ulaz na dijelove <= max_znakova, PREFERIRAJUĆI početak zadatka ('12. ...' ili 'Zadatak 12') kao granicu,
    inače prazni red, nikad unutar \\begin..\\end okoline. Kratak ulaz vraća netaknut."""
    md = md or ""
    if len(md) <= max_znakova:
        return [md]
    primarne = [m.start() for m in _GRANICA_ZADATKA_RE.finditer(md)]
    sekundarne = [m.end() for m in _PRAZNI_RED_RE.finditer(md)]
    dijelovi, start = [], 0
    while len(md) - start > max_znakova:
        gornja, donja = start + max_znakova, start + int(max_znakova * 0.5)
        rez = None
        for skup in (primarne, sekundarne):
            kand = [p for p in skup if donja < p <= gornja and _okoliš_ok(md, p)]
            if kand:
                rez = max(kand)
                break
        if rez is None:
            nl = md.rfind("\n", donja, gornja)
            rez = nl + 1 if nl > start else gornja
        dijelovi.append(md[start:rez])
        start = rez
    if md[start:].strip():
        dijelovi.append(md[start:])
    return dijelovi


def numerirani_zadaci_u_ulazu(md: str) -> list[int]:
    """Brojevi zadataka koji se u OCR-u vide kao 'N.' / 'Zadatak N' na početku retka (grubo, za usporedbu s AI-jem)."""
    brojevi = []
    for m in _GRANICA_ZADATKA_RE.finditer(md or ""):
        b = int(m.group(1) or m.group(2))
        if b not in brojevi:
            brojevi.append(b)
    return brojevi


# ---------------------------------------------------------------------------------------------------------------
# 5. ODGOVOR AI-ja -> lista zadataka
# ---------------------------------------------------------------------------------------------------------------

def parsiraj_odgovor(raw: str, log=None):
    """-> (zadaci: list[dict], potpuno: bool). Podnosi ValueError ako nema ničega upotrebljivog.
    Podržava: golu JSON listu (Claude), {"zadaci": [...]} (DeepSeek), odrezani odgovor, tekst prije JSON-a, ```json ograde,
    niz odvojenih objekata. Koristi _spasi_djelomican_json_popis iz postojećeg pipelinea."""
    from baza_zadataka_pipeline import _spasi_djelomican_json_popis
    t = _ZW_RE.sub("", (raw or "")).strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    if not t:
        raise ValueError("prazan odgovor")
    m = re.match(r'^\{\s*"[A-Za-z_]+"\s*:\s*\[', t)
    if m:  # omotnica {"zadaci": [ ... ]} -> gola lista (radi i kad je odgovor odrezan)
        t = "[" + t[m.end():]
        t = re.sub(r"\]\s*\}\s*$", "]", t)
    elif not t.startswith(("[", "{")):
        m2 = re.search(r"\[\s*\{", t)
        if not m2:
            raise ValueError(f"model nije vratio JSON ('{t[:100]}')")
        t = t[m2.start():]
    zadaci, potpuno = _spasi_djelomican_json_popis(t, log=log)
    if len(zadaci) == 1 and "tekst_zadatka_latex" not in zadaci[0]:  # omotnica s drugim ključem
        for v in zadaci[0].values():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                zadaci = v
                break
    return [z for z in zadaci if isinstance(z, dict)], potpuno


def ukloni_sudare_brojeva(zadaci: list[dict], zauzeti: set | None = None) -> list[dict]:
    """privremeni_broj mora biti JEDINSTVEN (po njemu se stavke vežu uz skupinu i imenuju slike). Ako se ponovi
    (npr. dva dijela dokumenta oba počinju od 1), ponavljanju se dodaje sufiks _2, _3... a stavke koje slijede
    prate NAJNOVIJU skupinu s tim brojem. Ulaz se ne mijenja (radi se na kopijama)."""
    zauzeti = set(zauzeti or ())
    izlaz, trenutna = [], {}
    for z in zadaci:
        z = dict(z)
        pb = str(z.get("privremeni_broj", "") or "").strip()
        uloga = str(z.get("uloga", "") or "").strip().lower()
        rod = str(z.get("roditelj_privremeni_broj", "") or "").strip()
        if uloga == "stavka" and rod:
            z["roditelj_privremeni_broj"] = trenutna.get(rod, rod)
            # stavka mora imati jedinstven vlastiti broj (uobičajeno "8.1"); sudar rješavamo kao i za ostale
        novi = pb
        if pb in zauzeti or not pb:
            k = 2
            osnova = pb or "bez-broja"
            novi = f"{osnova}_{k}" if pb else f"{osnova}-{len(zauzeti) + 1}"
            while novi in zauzeti:
                k += 1
                novi = f"{osnova}_{k}"
        if uloga != "stavka" or True:
            trenutna[pb] = novi
        zauzeti.add(novi)
        z["privremeni_broj"] = novi
        izlaz.append(z)
    return izlaz


# ---------------------------------------------------------------------------------------------------------------
# 6. PROGRAMSKA OBRADA ODGOVORA (bez AI-ja)
# ---------------------------------------------------------------------------------------------------------------

TIPOVI = ("visestruki_izbor", "kratki_odgovor", "prosireni_odgovor")
ULOGE_Z = ("samostalan", "skupina", "stavka")
TEKST_POLJA = ["tekst_zadatka_latex", "rjesenje", "uputa", "konacan_odgovor"]
STRING_POLJA = ["privremeni_broj", "uloga", "roditelj_privremeni_broj", "oznaka_stavke", "tekst_zadatka_latex", "kategorija",
                "cjelina", "potpoglavlje", "kljucne_rijeci", "tezina", "vizualni_potencijal", "rjesenje", "tip_rjesenja_izvor",
                "max_bodovi", "status_provjere", "tip_zadatka", "slika_zadana", "slika_url", "slika_rjesenje_url",
                "konacan_odgovor", "uputa"]

_UNICODE_MAT = {
    "≤": r"\leq ", "≥": r"\geq ", "≠": r"\neq ", "≈": r"\approx ", "×": r"\times ", "÷": r"\div ", "·": r"\cdot ", "⋅": r"\cdot ",
    "²": "^2", "³": "^3", "½": r"\frac{1}{2}", "¼": r"\frac{1}{4}", "¾": r"\frac{3}{4}", "∞": r"\infty ", "π": r"\pi ",
    "∈": r"\in ", "∉": r"\notin ", "∪": r"\cup ", "∩": r"\cap ", "⊂": r"\subset ", "⊆": r"\subseteq ", "→": r"\to ",
    "⇒": r"\Rightarrow ", "⇔": r"\Leftrightarrow ", "±": r"\pm ", "∓": r"\mp ", "°": r"^\circ ", "−": "-", "–": "-", "∠": r"\angle ",
    "△": r"\triangle ", "⊥": r"\perp ", "∥": r"\parallel ", "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ", "δ": r"\delta ",
    "Δ": r"\Delta ", "ε": r"\varepsilon ", "θ": r"\theta ", "λ": r"\lambda ", "μ": r"\mu ", "ρ": r"\rho ", "σ": r"\sigma ",
    "τ": r"\tau ", "φ": r"\varphi ", "ω": r"\omega ", "Ω": r"\Omega ", "Σ": r"\Sigma ", "Φ": r"\Phi ", "∑": r"\sum ", "∫": r"\int ",
    "∂": r"\partial ", "∇": r"\nabla ", "…": r"\ldots ",
}
_CIRIL_LATINICA = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "а": "a", "с": "c", "е": "e", "Д": "D"})
_KOR_LATINICA = {"А": "A", "В": "B", "С": "C", "Е": "E"}
_NEJASNO_RE = re.compile(r"\[NEJASNO[^\]]*\]")
_MARKER_RE = re.compile(r"\[\[(?:DATOTEKA|DIO)[^\]]*\]\]\s*")


def razlozi_na_segmente(s: str):
    """Razlaže tekst na [("t", obični), ("m", matematika)...] prepoznajući $..$, $$..$$, \\(..\\), \\[..\\]. Escapeani znakovi
    (\\$, \\\\) ostaju netaknuti. Vraća (segmenti, ok); ok=False ako neka matematika nije zatvorena."""
    seg, buf, i, n = [], [], 0, len(s)
    stanje, zatvarac = "t", None

    def isprazni(tip):
        if buf:
            seg.append((tip, "".join(buf)))
            buf.clear()

    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            if stanje == "t" and s[i + 1] in "([":
                isprazni("t")
                stanje, zatvarac = "m", "\\)" if s[i + 1] == "(" else "\\]"
                i += 2
                continue
            if stanje == "m" and zatvarac in ("\\)", "\\]") and s.startswith(zatvarac, i):
                isprazni("m")
                stanje, zatvarac = "t", None
                i += 2
                continue
            buf.append(s[i:i + 2])
            i += 2
            continue
        if c == "$":
            if stanje == "t":
                isprazni("t")
                if s.startswith("$$", i):
                    stanje, zatvarac = "m", "$$"
                    i += 2
                else:
                    stanje, zatvarac = "m", "$"
                    i += 1
                continue
            if zatvarac == "$$" and s.startswith("$$", i):
                isprazni("m")
                stanje, zatvarac = "t", None
                i += 2
                continue
            if zatvarac == "$":
                isprazni("m")
                stanje, zatvarac = "t", None
                i += 1
                continue
        buf.append(c)
        i += 1
    if stanje != "t":
        return [("t", s)], False
    isprazni("t")
    return seg, True


def _uravnotezeno(mat: str):
    """Greške uparenosti unutar jedne matematike: {}, \\left/\\right, \\begin/\\end."""
    p = []
    t = re.sub(r"\\[{}]", "", mat)
    t = re.sub(r"\\\\", "", t)
    if t.count("{") != t.count("}"):
        p.append("vitičaste zagrade { } nisu uparene")
    if len(re.findall(r"\\left\b", mat)) != len(re.findall(r"\\right\b", mat)):
        p.append(r"\left i \right nisu upareni")
    stog = []
    for m in re.finditer(r"\\(begin|end)\{([^}]*)\}", mat):
        if m.group(1) == "begin":
            stog.append(m.group(2))
        elif stog and stog[-1] == m.group(2):
            stog.pop()
        else:
            p.append(r"\begin i \end nisu upareni")
            break
    if stog:
        p.append(r"\begin bez \end")
    return p


def _popravi_unicode_u_matematici(mat: str):
    ostalo = []
    mat = re.sub(r"√\s*(\d+(?:[.,]\d+)?|[A-Za-z]\w*)", lambda m: r"\sqrt{" + m.group(1) + "}", mat)
    for znak, zamjena in _UNICODE_MAT.items():
        if znak in mat:
            mat = mat.replace(znak, zamjena)
    mat = re.sub(r"\^\\circ \^\\circ ", r"^\\circ ", mat)
    for ch in mat:
        if ord(ch) > 127 and not ch.isalpha():
            ostalo.append(ch)
        elif ch in "√":
            ostalo.append(ch)
    return mat, sorted(set(ostalo))


_DEC_ZAREZ_RE = re.compile(r"(?:(?<=^)|(?<=[\s=+\-*/<>^]))(\d+),(\d+)(?![\d]|,\d)")


def normaliziraj_matematiku(tekst: str):
    """Pretvara sve delimitere u $...$, popravlja Unicode u matematici, bezopasno escapea % & # u običnom tekstu i
    pretvara crte za upis (___) u $\\ldots$. Vraća (novi_tekst, upozorenja[]). Ako $ nisu upareni, tekst se vraća
    NETAKNUT uz upozorenje (ne pogađamo)."""
    upoz = []
    s = tekst or ""
    if not s:
        return s, upoz
    seg, ok = razlozi_na_segmente(s)
    if not ok:
        return s, ["LATEX: neuparen $ (matematika nije zatvorena) - provjeri tekst"]
    izlaz = []
    for tip, sadrzaj in seg:
        if tip == "m":
            mat = sadrzaj.strip()
            if mat and sadrzaj != mat and "$$" not in sadrzaj[:2] and (sadrzaj[0].isspace() or sadrzaj[-1].isspace()) and not sadrzaj.startswith("\\"):
                upoz.append("LATEX: razmak uz granicu $...$ - možda je $ znak za dolar, provjeri")
            if not mat:
                upoz.append("LATEX: prazna matematika $$ izbačena")
                continue
            mat, ostali = _popravi_unicode_u_matematici(mat)
            if ostali:
                upoz.append("LATEX: nepoznati znak(ovi) u matematici: " + " ".join(ostali))
            mat = DEC_ZAREZ(mat)
            for p in _uravnotezeno(mat):
                upoz.append("LATEX: " + p)
            izlaz.append("$" + re.sub(r"\s{2,}", " ", mat).strip() + "$")
        else:
            t = sadrzaj
            t = re.sub(r"(\d)\s*°", lambda m: f"{m.group(1)}$^\\circ$" if False else f"${m.group(1)}^\\circ$", t)
            t = re.sub(r"(?<!\\)%", r"\\%", t)
            t = re.sub(r"(?<!\\)&", r"\\&", t)
            t = re.sub(r"(?<!\\)#", r"\\#", t)
            t = re.sub(r"_{2,}", r"$\\ldots$", t)
            izlaz.append(t)
    rez = "".join(izlaz)
    # matematika izvan $: \frac, \sqrt, a^2, x_1 u običnom tekstu
    izvan = "".join(t for tip, t in seg if tip == "t")
    if re.search(r"\\(?:frac|sqrt|cdot|leq|geq|angle|triangle|overline)\b|[A-Za-z0-9\)]\s*\^\s*[\{\d]|[A-Za-z]\s*_\s*[\{\d]", izvan):
        upoz.append("LATEX: izgleda da ima matematike izvan $...$ - provjeri")
    ostali = sorted({ch for ch in izvan if ch in "≤≥≠×÷√²³½∞π∈∪∩→±"})
    if ostali:
        upoz.append("LATEX: Unicode znak izvan matematike: " + " ".join(ostali))
    return rez, upoz


def DEC_ZAREZ(mat: str) -> str:
    """Decimalni zarez u matematici: '2,5' -> '2{,}5' samo kad je nedvosmisleno (nakon razmaka, =, +, - ...)."""
    return _DEC_ZAREZ_RE.sub(lambda m: f"{m.group(1)}{{,}}{m.group(2)}", mat)


def _dodaj_status(z: dict, poruka: str):
    poruka = (poruka or "").strip()
    if not poruka:
        return
    cur = str(z.get("status_provjere", "") or "").strip()
    if poruka in cur:
        return
    z["status_provjere"] = f"{cur}; {poruka}" if cur else poruka


def _kao_tekst(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def _normaliziraj_opcije(opcije, z):
    """ponudjeni_odgovori -> lista stringova bez oznaka A)/a)/(A) i bez $ ako je cijela opcija jedna formula."""
    if isinstance(opcije, str):
        t = opcije.strip()
        try:
            opcije = json.loads(t) if t.startswith("[") else [o for o in t.split("||")]
        except Exception:  # noqa: BLE001
            opcije = t.split("||")
    if not isinstance(opcije, list):
        opcije = []
    izlaz = []
    for o in opcije:
        o = _kao_tekst(o)
        o = _ZW_RE.sub("", o).strip()
        o = re.sub(r"^\(?\s*([A-Ea-eАВСЕ])\s*[\).]\s+", "", o) if re.match(r"^\(?\s*[A-Ea-eАВСЕ]\s*[\).]\s+", o) else o
        o = re.sub(r"^\(([A-Ea-e])\)\s*", "", o)
        seg, ok = razlozi_na_segmente(o) if o else ([], True)
        if ok and o:
            o2, upoz = normaliziraj_matematiku(o)
            for u in upoz:
                _dodaj_status(z, "OPCIJE: " + u)
            seg2, _ = razlozi_na_segmente(o2)
            if len(seg2) == 1 and seg2[0][0] == "m":  # cijela opcija je jedna formula -> bez $ (konvencija baze)
                o2 = seg2[0][1]
            o = o2
        izlaz.append(o)
    return izlaz


def _slovo_odgovora(vrijednost: str, opcije: list):
    """konacan_odgovor višestrukog izbora -> (slovo|None, napomena)."""
    v = (vrijednost or "").strip().translate(_CIRIL_LATINICA)
    if not v:
        return "", ""
    m = re.fullmatch(r"\(?\s*([A-Ea-e])\s*\)?\.?", v) or re.search(r"(?:odgovor|rješenje|rjesenje|točno|tocno)\s*[:\-]?\s*\(?([A-Ea-e])\)?\b", v, re.I)
    if m:
        return m.group(1).upper(), ""
    norm = lambda x: re.sub(r"[\s$]", "", x or "").lower()  # noqa: E731
    za = [i for i, o in enumerate(opcije) if norm(o) == norm(v) and norm(v)]
    if len(za) == 1:
        return "ABCDEFGH"[za[0]], f"KLJUC: ključ je dao vrijednost '{v}', pretvorena u slovo {'ABCDEFGH'[za[0]]} - provjeri"
    return None, f"KLJUC: konacan_odgovor '{v}' nije slovo ni vrijednost jedne opcije"


def _tokeni(vrijednost) -> list:
    if isinstance(vrijednost, list):
        vrijednost = "|".join(str(x) for x in vrijednost)
    t = str(vrijednost or "")
    nadjeni = re.findall(r"SLIKA_[A-Z0-9]+", t.upper())
    izlaz = []
    for x in nadjeni:
        if x not in izlaz:
            izlaz.append(x)
    return izlaz


def _normaliziraj_tip(tip: str) -> str:
    t = re.sub(r"[\s\-]+", "_", (tip or "").strip().lower()).replace("š", "s").replace("č", "c").replace("ć", "c").replace("ž", "z")
    mapa = {"visestruki_izbor": "visestruki_izbor", "visestruki": "visestruki_izbor", "multiple_choice": "visestruki_izbor", "mc": "visestruki_izbor",
            "kratki_odgovor": "kratki_odgovor", "kratki": "kratki_odgovor", "prosireni_odgovor": "prosireni_odgovor",
            "prosireni": "prosireni_odgovor", "produzeni_odgovor": "prosireni_odgovor", "produzeni": "prosireni_odgovor"}
    return mapa.get(t, "")


_TEZINA_MAPA = {"lako": "lako", "lagano": "lako", "laka": "lako", "jednostavno": "lako", "l": "lako", "srednje": "srednje", "srednja": "srednje",
                "s": "srednje", "tesko": "tesko", "teško": "tesko", "teska": "tesko", "tezak": "tesko", "težak": "tesko", "t": "tesko"}


def dovrsi_zadatak(z: dict, mapa_slika: dict | None = None, ima_slika_u_ulazu: bool = True, datoteke_naziv: str = "") -> dict:
    """Programska obrada JEDNOG objekta zadatka iz AI odgovora. Vraća NOVI rječnik. Sigurno popravlja ono što je jednoznačno
    (delimiteri, Unicode u matematici, oznake opcija, slovo ključa, nazivi tipa/težine, markeri datoteka...), a sve ostalo
    OZNAČI u status_provjere - ništa se ne pogađa."""
    mapa_slika = mapa_slika or {}
    z = dict(z)
    for p in STRING_POLJA:
        z[p] = _kao_tekst(z.get(p))
    for p in ("tekst_zadatka_latex", "rjesenje", "uputa", "konacan_odgovor", "status_provjere"):
        z[p] = _MARKER_RE.sub("", z[p]).strip()

    uloga = z["uloga"].lower()
    if uloga not in ULOGE_Z:
        if uloga:
            _dodaj_status(z, f"SKUPINA: nepoznata uloga '{uloga}', tretirano kao samostalan")
        uloga = "samostalan"
    z["uloga"] = uloga

    # --- tekst, rješenje, uputa: delimiteri, Unicode, uparenost
    for p in ("tekst_zadatka_latex", "rjesenje", "uputa"):
        z[p], upoz = normaliziraj_matematiku(z[p])
        for u in upoz:
            _dodaj_status(z, f"{p.replace('tekst_zadatka_latex', 'tekst')}: {u}" if p != "tekst_zadatka_latex" else u)

    # --- broj zadatka / bodovi / "Odgovor: ____" ostaci u tekstu
    t = z["tekst_zadatka_latex"]
    pb, oz = z["privremeni_broj"], z["oznaka_stavke"]
    if pb and uloga != "stavka":
        t = re.sub(rf"^\s*(?:Zadatak\s*)?{re.escape(pb)}\s*[.)]\s+", "", t)
    if uloga == "stavka" and oz:
        t = re.sub(rf"^\s*\(?{re.escape(oz)}\)?\s*[.)]\s+", "", t)
    m = re.search(r"\s*[\(\[]\s*(\d+(?:[.,]\d+)?)\s*(?:bod\w*|b\.?|points?)\s*[\)\]]\s*$", t, re.I)
    if m:
        if not z["max_bodovi"]:
            z["max_bodovi"] = m.group(1)
        t = t[:m.start()].rstrip()
    t = re.sub(r"\s*Odgovor\s*:\s*(?:_+|\.{3,}|…+)?\s*(?:\\ldots)?\s*$", "", t, flags=re.I).rstrip()
    z["tekst_zadatka_latex"] = t
    if re.search(r"(?im)^\s*(?:RJ|Rj\.?|Rješenje|Rjesenje)\s*[:.]", t):
        _dodaj_status(z, "RJESENJE: u tekstu zadatka je ostalo rješenje - provjeri")

    # --- max_bodovi: samo broj
    if z["max_bodovi"]:
        mb = re.search(r"\d+(?:[.,]\d+)?", z["max_bodovi"])
        z["max_bodovi"] = mb.group(0) if mb else ""

    # --- težina
    z["tezina"] = _TEZINA_MAPA.get(z["tezina"].strip().lower(), "")

    # --- ponuđeni odgovori + tip + ključ
    opcije = _normaliziraj_opcije(z.get("ponudjeni_odgovori"), z)
    tip = _normaliziraj_tip(z["tip_zadatka"])
    if uloga == "skupina":
        z["tip_zadatka"] = tip
        z["ponudjeni_odgovori"] = []
        if z["rjesenje"] or z["konacan_odgovor"]:
            _dodaj_status(z, "SKUPINA: skupina ima rješenje/odgovor (očekuje se samo uvod) - provjeri")
    else:
        if z["tip_zadatka"] and not tip:
            _dodaj_status(z, f"TIP: nepoznat tip '{z['tip_zadatka']}'")
        if not tip:
            tip = "visestruki_izbor" if len(opcije) >= 2 else ("prosireni_odgovor" if len(z["rjesenje"]) > 80 else "kratki_odgovor")
            _dodaj_status(z, f"TIP: tip nije bio zadan, pretpostavljeno {tip}")
        if len(opcije) >= 2 and tip != "visestruki_izbor":
            _dodaj_status(z, f"TIP: ima {len(opcije)} ponuđenih odgovora, a tip je {tip} - postavljen visestruki_izbor")
            tip = "visestruki_izbor"
        if tip == "visestruki_izbor":
            if len(opcije) < 2:
                _dodaj_status(z, f"OPCIJE: višestruki izbor ima samo {len(opcije)} opcija - provjeri")
            elif len(opcije) > 5:
                _dodaj_status(z, f"OPCIJE: {len(opcije)} opcija (očekuje se 4-5) - provjeri")
            elif len(opcije) < 3:
                _dodaj_status(z, "OPCIJE: samo 2 opcije - provjeri")
            nz = [re.sub(r"\s", "", o).lower() for o in opcije if o]
            if len(nz) != len(set(nz)):
                _dodaj_status(z, "OPCIJE: dvije opcije su identične (vjerojatno OCR greška)")
            slovo, nap = _slovo_odgovora(z["konacan_odgovor"], opcije)
            if slovo is None:
                _dodaj_status(z, nap)
                z["konacan_odgovor"] = ""
            else:
                if nap:
                    _dodaj_status(z, nap)
                if slovo and "ABCDEFGH".index(slovo) >= len(opcije) and opcije:
                    _dodaj_status(z, f"KLJUC: slovo {slovo} nema opciju (opcija je {len(opcije)})")
                z["konacan_odgovor"] = slovo
        else:
            ka = z["konacan_odgovor"]
            if ka and re.search(r"[\\^_]", ka) and "$" not in ka:
                ka = "$" + ka + "$"
            z["konacan_odgovor"] = ka
        z["tip_zadatka"] = tip
        z["ponudjeni_odgovori"] = opcije if tip == "visestruki_izbor" else []

    # --- slike
    tok = _tokeni(z["slika_url"])
    ispravni = [x for x in tok if x in mapa_slika]
    neispravni = [x for x in tok if x not in mapa_slika]
    if neispravni:
        _dodaj_status(z, "SLIKA: nepoznata oznaka slike " + ", ".join(neispravni) + " (uklonjena)")
    if re.search(r"(?i)https?://", z["slika_url"]) and not tok:
        _dodaj_status(z, "SLIKA: AI je upisao URL umjesto oznake slike (uklonjen)")
    z["slika_url"] = "|".join(ispravni)
    trj = _tokeni(z["slika_rjesenje_url"])
    z["slika_rjesenje_url"] = "|".join(x for x in trj if x in mapa_slika)
    if len(trj) != len([x for x in trj if x in mapa_slika]):
        _dodaj_status(z, "SLIKA: nepoznata oznaka slike u rješenju (uklonjena)")
    if ispravni and z["slika_zadana"].lower() != "da":
        z["slika_zadana"] = "da"
    z["slika_zadana"] = "da" if z["slika_zadana"].lower() == "da" else "ne"
    if z["slika_zadana"] == "da" and not ispravni:
        izvor = f" (izvor: {datoteke_naziv})" if datoteke_naziv else ""
        _dodaj_status(z, f"SLIKA: slika nije prenesena iz ulaza{izvor}, treba ručno dodati")
    if z["slika_zadana"] == "da":
        z["vizualni_potencijal"] = "ne"
    elif z["slika_zadana"] == "ne" and re.search(
            r"(?i)\b(na\s+slici|slici\s+je|prikazan\w*|prikazuje|skic[aeiu]|crtež\w*|graf\s+funkcije|graf\s+prikazuje)\b", z["tekst_zadatka_latex"]):
        _dodaj_status(z, "SLIKA: tekst upućuje na sliku/graf, a slika nije označena - provjeri")

    # --- ostale oznake
    if _NEJASNO_RE.search(" ".join([z["tekst_zadatka_latex"], z["rjesenje"], z["konacan_odgovor"]] + opcije)):
        _dodaj_status(z, "NEJASNO: u tekstu je ostalo [NEJASNO] mjesto - dopuni ručno")
    if not z["tekst_zadatka_latex"] and uloga != "skupina":
        _dodaj_status(z, "OCR: prazan tekst zadatka")
    z["tekst_zadatka_mathjax"] = z["tekst_zadatka_latex"].replace("\\\\", "<br>")
    return z


def _norm_tekst(t: str) -> str:
    return re.sub(r"[\s$]+", " ", (t or "").lower()).strip()


def dovrsi_skup(zadaci: list[dict], mapa_slika: dict, ocr_md: str = "", datoteke_naziv: str = "", ima_slika_u_ulazu: bool = True):
    """Obrada cijelog odgovora: svaki zadatak + provjere na razini skupa (praznine u numeraciji, duplikati teksta, AI je možda
    preskočio zadatke koje OCR vidi). Vraća (zadaci, izvjestaj)."""
    gotovi = [dovrsi_zadatak(z, mapa_slika, ima_slika_u_ulazu, datoteke_naziv) for z in zadaci]
    izvj = {"upozorenja_skupa": [], "broj": len(gotovi),
            "po_ulozi": {u: sum(1 for z in gotovi if z["uloga"] == u) for u in ULOGE_Z}}
    # praznine u numeraciji (samo čisti cijeli brojevi na najvišoj razini)
    gore = [z for z in gotovi if z["uloga"] != "stavka"]
    brojevi = [int(z["privremeni_broj"]) for z in gore if re.fullmatch(r"\d{1,3}", z["privremeni_broj"])]
    if brojevi:
        for prev, z in zip(gore, gore[1:]):
            if re.fullmatch(r"\d{1,3}", prev["privremeni_broj"]) and re.fullmatch(r"\d{1,3}", z["privremeni_broj"]):
                a, b = int(prev["privremeni_broj"]), int(z["privremeni_broj"])
                if b > a + 1:
                    _dodaj_status(z, f"NUMERACIJA: nedostaje zadatak {a + 1}" + (f"-{b - 1}" if b - 1 > a + 1 else "") + " ispred ovoga")
                    izvj["upozorenja_skupa"].append(f"Nema zadataka {a + 1}-{b - 1} između {a} i {b}")
    # duplikati teksta
    vidjeni = {}
    for z in gotovi:
        k = _norm_tekst(z["tekst_zadatka_latex"])
        if len(k) < 25 or z["uloga"] == "skupina":
            continue
        if k in vidjeni:
            _dodaj_status(z, f"NUMERACIJA: isti tekst kao zadatak {vidjeni[k]} (duplikat u istom izvoru?)")
            izvj["upozorenja_skupa"].append(f"Zadatak {z['privremeni_broj']} ima isti tekst kao {vidjeni[k]}")
        else:
            vidjeni[k] = z["privremeni_broj"]
    # AI možda preskočio zadatke koje OCR vidi
    if ocr_md:
        u_ulazu = numerirani_zadaci_u_ulazu(ocr_md)
        imaju = set()
        for z in gotovi:
            for m in re.findall(r"\d+", z["privremeni_broj"].split("_")[0]) if z["uloga"] != "stavka" else []:
                imaju.add(int(m))
            if z["uloga"] == "stavka" and re.fullmatch(r"\d+", z["oznaka_stavke"] or ""):
                imaju.add(int(z["oznaka_stavke"]))
        fale = [b for b in u_ulazu if b not in imaju]
        if fale and len(fale) <= max(3, len(u_ulazu) // 2):
            izvj["upozorenja_skupa"].append("Moguće preskočeni zadaci (u OCR-u se vide, u odgovoru ih nema): " + ", ".join(map(str, fale[:30])))
            izvj["moguce_preskoceni"] = fale
    return gotovi, izvj


# ---------------------------------------------------------------------------------------------------------------
# 7. STRUKTURIRANJE (dijelovi + ponavljanje + dijeljenje kod odrezanog odgovora)
# ---------------------------------------------------------------------------------------------------------------

def strukturiraj(pozovi, predmet, pruzatelj, sifrarnik, sifrarnik_pp, ispit_md, rjesenja_md=None, izvor_naziv="", vrsta_ulaza="",
                 tokeni=None, max_znakova=40000, max_izlaz=None, log=None, _dubina=2, _dio=None):
    """Šalje ulaz modelu (u dijelovima ako je dugačak) i vraća dict:
    {"zadaci": [...sirovi...], "nepotpuno": bool, "greske": [...], "tokeni_ulaz": n, "tokeni_izlaz": n, "dijelova": n}.
    pozovi(system, user, max_tokens) -> {"tekst", "tokeni_ulaz", "tokeni_izlaz", "odrezano"} (vidi napravi_pozivatelja)."""
    log = log or (lambda *_: None)
    system = sastavi_prompt(predmet, pruzatelj)
    dijelovi = podijeli_md(ispit_md, max_znakova)
    rez = {"zadaci": [], "nepotpuno": False, "greske": [], "tokeni_ulaz": 0, "tokeni_izlaz": 0, "dijelova": len(dijelovi)}
    zauzeti: set = set()
    for k, dio_md in enumerate(dijelovi, 1):
        oznaka = _dio or (k, len(dijelovi))
        log(f"🤖 Dio {oznaka[0]}/{oznaka[1]}: {len(dio_md)} znakova ulaza...")
        user = sastavi_korisnicku_poruku(sifrarnik, sifrarnik_pp, dio_md, rjesenja_md, izvor_naziv, vrsta_ulaza, tokeni, dio=oznaka)
        odg, zadaci, potpuno, pokusaj = None, None, True, 0
        while pokusaj < 3:
            pokusaj += 1
            try:
                odg = pozovi(system, user, max_izlaz)
            except Exception as e:  # noqa: BLE001 - mrežna greška: zabilježi i probaj ponovno
                rez["greske"].append(f"dio {oznaka[0]}/{oznaka[1]}: poziv modela nije uspio: {e}")
                log(f"⚠️ Poziv modela nije uspio ({e}), pokušaj {pokusaj}/3")
                time.sleep(3 * pokusaj)
                continue
            rez["tokeni_ulaz"] += int(odg.get("tokeni_ulaz") or 0)
            rez["tokeni_izlaz"] += int(odg.get("tokeni_izlaz") or 0)
            if odg.get("odrezano") and _dubina > 0 and len(dio_md) > 1500:
                log(f"✂️ Odgovor odrezan (max_tokens) - dijelim ovaj dio na manje ({len(dio_md)} znakova)")
                pod = strukturiraj(pozovi, predmet, pruzatelj, sifrarnik, sifrarnik_pp, dio_md, rjesenja_md, izvor_naziv, vrsta_ulaza,
                                   tokeni, max_znakova=max(1500, len(dio_md) // 2 + 200), max_izlaz=max_izlaz, log=log,
                                   _dubina=_dubina - 1, _dio=oznaka)
                for z in pod["zadaci"]:
                    pass
                novi = ukloni_sudare_brojeva(pod["zadaci"], zauzeti)
                zauzeti.update(z["privremeni_broj"] for z in novi)
                rez["zadaci"].extend(novi)
                rez["nepotpuno"] |= pod["nepotpuno"]
                rez["greske"].extend(pod["greske"])
                rez["tokeni_ulaz"] += pod["tokeni_ulaz"]
                rez["tokeni_izlaz"] += pod["tokeni_izlaz"]
                zadaci = None
                break
            try:
                zadaci, potpuno = parsiraj_odgovor(odg.get("tekst", ""), log=log)
            except Exception as e:  # noqa: BLE001
                rez["greske"].append(f"dio {oznaka[0]}/{oznaka[1]}: odgovor se ne može pročitati: {e}")
                log(f"⚠️ Odgovor se ne može pročitati ({e}), pokušaj {pokusaj}/3")
                zadaci = None
                continue
            if odg.get("odrezano") or not potpuno:
                rez["nepotpuno"] = True
                rez["greske"].append(f"dio {oznaka[0]}/{oznaka[1]}: odgovor je odrezan/nepotpun - zadnji zadatak vjerojatno nedostaje")
            break
        if zadaci:
            novi = ukloni_sudare_brojeva(zadaci, zauzeti)
            zauzeti.update(z["privremeni_broj"] for z in novi)
            rez["zadaci"].extend(novi)
        elif zadaci is not None:  # parsirano, ali prazno
            rez["greske"].append(f"dio {oznaka[0]}/{oznaka[1]}: model nije vratio nijedan zadatak")
    if not rez["zadaci"] and not rez["greske"]:
        rez["greske"].append("model nije vratio nijedan zadatak")
    return rez


# ---------------------------------------------------------------------------------------------------------------
# 8. USPOREDBA MODELA
# ---------------------------------------------------------------------------------------------------------------

USPOREDBA_POLJA = ["uloga", "tip_zadatka", "konacan_odgovor", "max_bodovi", "slika_zadana", "cjelina", "potpoglavlje", "tezina"]


def usporedi_rezultate(a: list[dict], b: list[dict]) -> list[dict]:
    """Po privremeni_broj: sličnost teksta + popis polja koja se razlikuju. Redovi: broj, u_a, u_b, slicnost, razlike."""
    ia = {z.get("privremeni_broj"): z for z in a}
    ib = {z.get("privremeni_broj"): z for z in b}
    redovi = []
    for br in list(ia) + [x for x in ib if x not in ia]:
        za, zb = ia.get(br), ib.get(br)
        if za and zb:
            sl = difflib.SequenceMatcher(None, _norm_tekst(za.get("tekst_zadatka_latex")), _norm_tekst(zb.get("tekst_zadatka_latex"))).ratio()
            razl = [p for p in USPOREDBA_POLJA if str(za.get(p, "") or "").strip().lower() != str(zb.get(p, "") or "").strip().lower()]
            if len(za.get("ponudjeni_odgovori") or []) != len(zb.get("ponudjeni_odgovori") or []):
                razl.append("broj_opcija")
            if _norm_tekst(za.get("rjesenje")) != _norm_tekst(zb.get("rjesenje")):
                razl.append("rjesenje")
        else:
            sl, razl = 0.0, []
        redovi.append({"broj": br, "u_a": bool(za), "u_b": bool(zb), "slicnost": round(sl, 3), "razlike": razl})
    return redovi


# ---------------------------------------------------------------------------------------------------------------
# 9. EVIDENCIJA U SHEETU (tab Uvoz_izvori) - kvačice
# ---------------------------------------------------------------------------------------------------------------

IZVORI_TAB = "Uvoz_izvori"
IZVORI_HEADERS = ["grupa", "model", "izvor_naziv", "status", "otisak", "vrijeme", "broj_jedinica", "broj_upozorenja", "tokeni_ulaz",
                  "tokeni_izlaz", "izlaz_file_id", "dodano", "nadopunjeno", "datoteke", "poruka"]
STANJA = {"uneseno": "✅", "uneseno_promijenjeno": "♻️", "ai_gotovo": "🟡", "greska": "❌", "novo": "⬜"}


def stanje_izvora(grupa: str, otisak: str, redovi: list[dict]) -> str:
    moji = [r for r in redovi if r.get("grupa") == grupa]
    uneseni = [r for r in moji if r.get("status") == "uneseno"]
    if uneseni:
        return "uneseno" if any(r.get("otisak") == otisak for r in uneseni) else "uneseno_promijenjeno"
    if any(r.get("status") == "ai_gotovo" and r.get("otisak") == otisak for r in moji):
        return "ai_gotovo"
    if any(r.get("status") == "greska" and r.get("otisak") == otisak for r in moji):
        return "greska"
    return "novo"


def sada() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def ucitaj_evidenciju(ws) -> list[dict]:
    vrijednosti = ws.get_all_values()
    if not vrijednosti:
        return []
    zagl = vrijednosti[0]
    izlaz = []
    for i, red in enumerate(vrijednosti[1:], start=2):
        d = {h: (red[j] if j < len(red) else "") for j, h in enumerate(zagl)}
        d["_redak"] = i
        izlaz.append(d)
    return izlaz


def _slovo(idx0: int) -> str:
    idx, s = idx0 + 1, ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def zapisi_evidenciju(ws, vrijednosti: dict):
    """Ažurira redak s istim (grupa, model) ili dodaje novi. Jedan poziv (batch_update) za izmjenu, append_row za novi."""
    redovi = ucitaj_evidenciju(ws)
    vrijednosti = {**vrijednosti, "vrijeme": vrijednosti.get("vrijeme") or sada()}
    postojeci = next((r for r in redovi if r.get("grupa") == vrijednosti["grupa"] and r.get("model") == vrijednosti["model"]), None)
    if postojeci:
        novi = {h: vrijednosti.get(h, postojeci.get(h, "")) for h in IZVORI_HEADERS}
        n = postojeci["_redak"]
        ws.batch_update([{"range": f"A{n}:{_slovo(len(IZVORI_HEADERS) - 1)}{n}", "values": [[novi[h] for h in IZVORI_HEADERS]]}])
    else:
        ws.append_row([vrijednosti.get(h, "") for h in IZVORI_HEADERS])


# ---------------------------------------------------------------------------------------------------------------
# 10. DRIVE (cache, popis, kopiranje slika) - tanki omotač oko googleapiclienta
# ---------------------------------------------------------------------------------------------------------------

class DriveIO:
    """Drive operacije s ponavljanjem i klijentom PO DRETVI (httplib2 nije thread-safe - isti razlog kao u 7_ai_kontrola).
    napravi_servis: funkcija bez argumenata koja vraća svjež googleapiclient Drive servis."""

    def __init__(self, napravi_servis):
        import threading
        self._napravi = napravi_servis
        self._lokalno = threading.local()

    def servis(self):
        s = getattr(self._lokalno, "s", None)
        if s is None:
            s = self._napravi()
            self._lokalno.s = s
        return s

    def _ponovi(self, fn):
        zadnja = None
        for pokusaj in range(3):
            try:
                return fn(self.servis())
            except Exception as e:  # noqa: BLE001
                zadnja = e
                self._lokalno.s = None
                time.sleep(1.5 * (pokusaj + 1))
        raise zadnja

    def popis(self, folder_id, rekurzivno=True, najvise_dubina=3, najvise_datoteka=1500):
        """Sve datoteke u folderu (i podmapama), s putanjom. Preskače _uvoz_cache i _mathpix_md."""
        izlaz, red = [], [(folder_id, [])]
        while red and len(izlaz) < najvise_datoteka:
            fid, put = red.pop(0)
            token = None
            while True:
                def poziv(d, fid=fid, token=token):
                    return d.files().list(
                        q=f"'{fid}' in parents and trashed = false",
                        fields="nextPageToken, files(id,name,mimeType,md5Checksum,modifiedTime,size)",
                        pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
                res = self._ponovi(poziv)
                for f in res.get("files", []):
                    if f["mimeType"] == "application/vnd.google-apps.folder":
                        if rekurzivno and len(put) < najvise_dubina and f["name"] not in (CACHE_FOLDER_NAZIV, "_mathpix_md"):
                            red.append((f["id"], put + [f["name"]]))
                    else:
                        f["putanja"] = list(put)
                        izlaz.append(f)
                token = res.get("nextPageToken")
                if not token:
                    break
        return izlaz

    def nadji_ili_napravi_podfolder(self, parent_id, naziv):
        def traži(d):
            return d.files().list(q=(f"'{parent_id}' in parents and name = '{naziv}' and "
                                     "mimeType = 'application/vnd.google-apps.folder' and trashed = false"),
                                  fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        nadjeno = self._ponovi(traži).get("files", [])
        if nadjeno:
            return nadjeno[0]["id"]
        def napravi(d):
            return d.files().create(body={"name": naziv, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
                                    fields="id", supportsAllDrives=True).execute()
        return self._ponovi(napravi)["id"]

    def indeks(self, folder_id):
        """{naziv: file_id} svega u folderu (cache)."""
        izlaz, token = {}, None
        while True:
            def poziv(d, token=token):
                return d.files().list(q=f"'{folder_id}' in parents and trashed = false", fields="nextPageToken, files(id,name)",
                                      pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            res = self._ponovi(poziv)
            for f in res.get("files", []):
                izlaz[f["name"]] = f["id"]
            token = res.get("nextPageToken")
            if not token:
                return izlaz

    def preuzmi(self, file_id) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        def poziv(d):
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, d.files().get_media(fileId=file_id, supportsAllDrives=True))
            gotovo = False
            while not gotovo:
                _, gotovo = dl.next_chunk()
            return buf.getvalue()
        return self._ponovi(poziv)

    def spremi_bytes(self, folder_id, naziv, sadrzaj: bytes, mime="application/octet-stream", postojeci_id=None):
        from googleapiclient.http import MediaIoBaseUpload

        def poziv(d):
            media = MediaIoBaseUpload(io.BytesIO(sadrzaj), mimetype=mime, resumable=False)
            if postojeci_id:
                return d.files().update(fileId=postojeci_id, media_body=media, fields="id", supportsAllDrives=True).execute()
            return d.files().create(body={"name": naziv, "parents": [folder_id]}, media_body=media, fields="id",
                                    supportsAllDrives=True).execute()
        return self._ponovi(poziv)["id"]

    def spremi_json(self, folder_id, naziv, objekt, postojeci_id=None):
        return self.spremi_bytes(folder_id, naziv, json.dumps(objekt, ensure_ascii=False).encode("utf-8"),
                                 "application/json", postojeci_id)

    def procitaj_json(self, file_id):
        return json.loads(self.preuzmi(file_id).decode("utf-8"))

    def kopiraj(self, file_id, naziv, parent_id):
        def poziv(d):
            return d.files().copy(fileId=file_id, body={"name": naziv, "parents": [parent_id]}, fields="id",
                                  supportsAllDrives=True).execute()
        return self._ponovi(poziv)["id"]

    def postoji_naziv(self, folder_id, naziv) -> bool:
        def poziv(d):
            return d.files().list(q=f"'{folder_id}' in parents and name = '{naziv}' and trashed = false", fields="files(id)",
                                  supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        return bool(self._ponovi(poziv).get("files"))


# ---------------------------------------------------------------------------------------------------------------
# 11. OCR S CACHEOM (Mathpix SAMO JEDNOM po datoteci; slike se preuzimaju odmah)
# ---------------------------------------------------------------------------------------------------------------

def cache_naziv(f: dict) -> str:
    return f"ocr_{f['id']}.json"


def ocr_datoteka_s_cacheom(dio: DriveIO, cache_id: str, indeks: dict, f: dict, mathpix_id: str, mathpix_key: str,
                           log=None, ocr_fn=None, pdf_fn=None, preuzmi_url=None, cekaj_pdf_s=1500):
    """Vraća dict {md, slike:[{oznaka_lok, drive_id, naziv}], iz_cachea: bool, upozorenja:[...]}.
    Cache se poništava ako se promijenio md5 datoteke. PDF koji Mathpix još obrađuje pamti pdf_id pa se pri sljedećem
    pokretanju NASTAVLJA čekanje, a ne plaća ponovno. ocr_fn/pdf_fn/preuzmi_url se zamjenjuju u testovima."""
    log = log or (lambda *_: None)
    import baza_zadataka_pipeline as bp
    naziv_cachea = cache_naziv(f)
    cache_fid = indeks.get(naziv_cachea)
    md5 = f.get("md5Checksum") or f.get("modifiedTime") or ""
    zapis = None
    if cache_fid:
        try:
            zapis = dio.procitaj_json(cache_fid)
        except Exception:  # noqa: BLE001
            zapis = None
    if zapis and zapis.get("md5") == md5 and zapis.get("status") == "gotovo":
        log(f"♻️ {f['name']}: OCR već postoji (bez Mathpixa)")
        return {"md": zapis["md"], "slike": zapis.get("slike", []), "iz_cachea": True, "upozorenja": zapis.get("upozorenja", [])}

    sadrzaj = dio.preuzmi(f["id"])
    ime = mathpix_ime(f)
    if vrsta_datoteke(f) == "pdf":
        pdf_id = zapis.get("pdf_id") if (zapis and zapis.get("md5") == md5 and zapis.get("status") == "u_tijeku") else None
        if not pdf_id:
            log(f"📄 {f['name']}: šaljem PDF na Mathpix...")
            pdf_id = (pdf_fn or bp.mathpix_process_pdf)(sadrzaj, ime, mathpix_id, mathpix_key)
            cache_fid = dio.spremi_json(cache_id, naziv_cachea, {"status": "u_tijeku", "pdf_id": pdf_id, "md5": md5, "naziv": f["name"]}, cache_fid)
            indeks[naziv_cachea] = cache_fid
        else:
            log(f"⏳ {f['name']}: nastavljam čekati Mathpix (pdf_id {pdf_id[:8]}...)")
        md = bp.mathpix_wait_and_get(pdf_id, mathpix_id, mathpix_key, poll_seconds=4, timeout_seconds=cekaj_pdf_s, log=log)
    else:
        log(f"🖼️ {f['name']}: šaljem sliku na Mathpix...")
        md = (ocr_fn or bp.mathpix_process_image)(sadrzaj, ime, mathpix_id, mathpix_key)

    # slike: preuzmi ODMAH (poveznice isteknu), spremi u cache, u tekstu ih zamijeni lokalnom oznakom
    upozorenja, slike, mapa = [], [], {}
    urlovi = izdvoji_url_slika(md)
    for k, url in enumerate(urlovi, 1):
        try:
            bajtovi = (preuzmi_url or _preuzmi_url_slike)(url, mathpix_id, mathpix_key)
            naziv_slike = f"img_{f['id']}_{k:02d}.png"
            sid = dio.spremi_bytes(cache_id, naziv_slike, bajtovi, "image/png", indeks.get(naziv_slike))
            indeks[naziv_slike] = sid
            slike.append({"oznaka_lok": f"S{k}", "drive_id": sid, "naziv": naziv_slike})
            mapa[url] = f"@S{k}"
        except Exception as e:  # noqa: BLE001
            upozorenja.append(f"slika {k} nije preuzeta: {e}")
            log(f"⚠️ {f['name']}: slika {k} nije preuzeta ({e})")
    md2 = zamijeni_url_slika(md, mapa)
    cache_fid = dio.spremi_json(cache_id, naziv_cachea, {"status": "gotovo", "md5": md5, "naziv": f["name"], "md": md2, "slike": slike,
                                                         "upozorenja": upozorenja, "vrijeme": sada()}, cache_fid)
    indeks[naziv_cachea] = cache_fid
    log(f"✅ {f['name']}: OCR gotov ({len(md2)} znakova, {len(slike)} slika)")
    return {"md": md2, "slike": slike, "iz_cachea": False, "upozorenja": upozorenja}


def _preuzmi_url_slike(url, mathpix_id, mathpix_key) -> bytes:
    import requests
    zadnja = None
    for pokusaj in range(3):
        try:
            r = requests.get(url, headers={"app_id": mathpix_id, "app_key": mathpix_key}, timeout=40)
            r.raise_for_status()
            if len(r.content) < 100:
                raise ValueError("preuzeta datoteka je prekratka")
            return r.content
        except Exception as e:  # noqa: BLE001
            zadnja = e
            time.sleep(2 * (pokusaj + 1))
    raise zadnja


# ---------------------------------------------------------------------------------------------------------------
# 12. UPIS: kopiranje slika iz cachea u 02_SLIKE + pretvorba oznaka u slika_putanja
# ---------------------------------------------------------------------------------------------------------------

def pripremi_za_upis(zadaci: list[dict], mapa_slika: dict, izvor_naziv: str, dio: DriveIO, slike_folder_id: str, log=None) -> list[dict]:
    """Oznake SLIKA_NN -> kopija datoteke u 02_SLIKE (naziv kao u postojećem uvozu: <izvor>_zad<broj>[_n].png; za rješenje _rj).
    Ako naziv već postoji u folderu, dodaje se _v2, _v3... (nikad se ne prepisuje tuđa slika). Vraća NOVE rječnike."""
    log = log or (lambda *_: None)
    izlaz = []
    for z in zadaci:
        z = dict(z)
        for polje_url, polje_put, sufiks in (("slika_url", "slika_putanja", ""), ("slika_rjesenje_url", "slika_rjesenje_putanja", "_rj")):
            tok = [t for t in _tokeni(z.get(polje_url, "")) if t in mapa_slika]
            spremljene = []
            osnova = f"{izvor_naziv}_zad{z.get('privremeni_broj', '0')}{sufiks}".replace(" ", "_")
            for n, t in enumerate(tok, 1):
                naziv = f"{osnova}.png" if len(tok) == 1 else f"{osnova}_{n}.png"
                konacni, v = naziv, 1
                while dio.postoji_naziv(slike_folder_id, konacni):
                    v += 1
                    konacni = naziv.replace(".png", f"_v{v}.png")
                try:
                    dio.kopiraj(mapa_slika[t]["drive_id"], konacni, slike_folder_id)
                    spremljene.append(konacni)
                    log(f"🖼️ {t} -> {konacni}")
                except Exception as e:  # noqa: BLE001
                    _dodaj_status(z, f"SLIKA: kopiranje {t} nije uspjelo ({e})")
                    log(f"⚠️ Slika {t} nije kopirana: {e}")
            z[polje_put] = "|".join(spremljene)
        izlaz.append(z)
    return izlaz
