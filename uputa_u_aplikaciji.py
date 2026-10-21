"""
CAKI — uputa_u_aplikaciji.py  (21.10.2026.)
KRATKE UPUTE UNUTAR BAZE ZADATAKA — Caki i profesori ne izlaze iz aplikacije da bi pročitali kako
nešto radi.

Cakijev zahtjev: upute ne smiju biti zasebna stranica ni drugi prozor. Zato je uputa **sklopivi
blok (expander) na vrhu stranice** koju upravo gledaš. Zasebna stranica 📖 Upute je **ugašena**
(21.10.2026.) — ovi blokovi je u cijelosti zamjenjuju.

Kako se koristi: na početku stranice `_uputa.prikazi(st, "test_builder")`.
Modul ne uvozi ništa osim Streamlita — ne dira Sheet, Drive ni bazu.
"""
import streamlit as st

UPUTE = {
    "test_builder": {
        "naslov": "Kako sastaviti test (🧪 Test Builder)",
        "koraci": [
            "**Lijevo** filtriraj bazu (cjelina, potpoglavlje, težina, izvor) i klikni **➕** da dodaš "
            "zadatak u odabir. Možeš i **➕ Dodaj ručni** zadatak.",
            "**Desno** slažeš redoslijed (strelicama ili brojem pozicije) i po zadatku upisuješ "
            "**Bodovi** i **🧠 Bloom razinu**.",
            "**🧠 Bloom razina** nije težina: 1 Zapamti · 2 Razumije · 3 Primijeni · 4 Analiziraj · "
            "5 Vrednuj. Označi je ovdje — samo za zadatke koji uđu u test. Bez nje analiza po razinama "
            "taj zadatak preskače.",
            "Unesi naslov, tip dokumenta i (za online test) trajanje i rok, pa **generiraj PDF** ili "
            "**📝 Objavi kao online test**.",
            "**📁 Predlošci** čuvaju cijeli odabir — za seriju sličnih testova.",
        ],
        "pazi": [
            "Skupina zadataka (uvod + stavke a/b/c) **ne može** u online test — portal rješava "
            "pojedinačan zadatak. U PDF ide normalno.",
            "Zadatak bez `konacan_odgovor` ne može u online test (nema po čemu ocijeniti).",
            "Test je **zamrznuta kopija**: poslije objave mijenjanje zadatka u bazi ne mijenja test.",
        ],
        "dalje": "Poslije objave: 📝 Testovi (rezultati, zadavanje grupi, provjere).",
    },

    "testovi": {
        "naslov": "Kako radi 📝 Testovi — rezultati i upravljanje",
        "koraci": [
            "**📋 Testovi** — popis objavljenih; otvori test za pregled s točnim odgovorima, "
            "**⏸️ Deaktiviraj** (učenik ga više ne vidi, rezultati ostaju), **📄 Kloniraj** ili 🗑️ obriši.",
            "**📊 Rezultati** — tko je predao, uspjeh po zadatku, po cjelinama, matrica učenik × zadatak, "
            "matrica razreda, usporedba dvaju testova.",
            "**👤 Po učeniku** — povijest, slabe cjeline, promašeni zadaci, **🧠 profil po Bloom "
            "razinama**, gotov sažetak za roditelja (kopiraj u WhatsApp/mail).",
            "**👥 Zadaj grupi** — isti test cijeloj grupi Upisa ili kanti Mature (jedan redak po učeniku, "
            "zajednička oznaka `serija`).",
            "**🩺 Provjere** — tabovi, stupci, dupli ID-evi, test bez roka, započeli-bez-predaje.",
        ],
        "pazi": [
            "**Rješenja učenik vidi tek po isteku roka** — dok rok traje, učenik vidi samo bodove.",
            "Brisanje testa briše **i njegove rezultate** — nema vraćanja.",
            "Rezultate piše **samo portal**; ova stranica ih nikad ne mijenja.",
        ],
        "dalje": "Ako nešto ne štima, prvo 🩺 Provjere — pokriju većinu grešaka prije nego ih vidi učenik.",
    },

    "pretpregled": {
        "naslov": "Kako radi 👁️ Pretpregled testa",
        "koraci": [
            "Odaberi **bilo koji objavljeni test** — i onaj koji je već istekao ili je ugašen.",
            "Riješi ga kao učenik i klikni **Ocijeni** — bodovi se pokažu na ekranu.",
            "**Ništa se ne upisuje** ni u `Rezultati_testova` ni u bilo koji drugi tab.",
        ],
        "pazi": [
            "Ovo služi **tebi** za provjeru prije/nakon objave; učenik i dalje rješava u Moj CAKI.",
            "Kratki odgovor je ovdje običan tekst (bez MathLive) — dovoljno za provjeru bodovanja.",
        ],
    },

    "uvoz": {
        "naslov": "Kako radi 📥 Uvoz iz foldera / dokumenta",
        "koraci": [
            "Stavi ispit i rješenja u jednu mapu (PDF) — alat čita tekst i šalje ga modelu.",
            "Model vraća **strukturirane zadatke** (tekst, tip, odgovor, cjelina, težina).",
            "Pregledaj prije upisa: **ništa se ne upisuje samo** dok ne potvrdiš.",
            "Zadatke bez konačnog odgovora označi ručno — bez njih ne mogu u online test.",
        ],
        "pazi": [
            "Skupine zadataka (uvod + stavke) traže poseban prolaz — alat ih sam prepoznaje.",
            "Ako je odgovor u PDF-u kao slika, tekst se ne pročita — provjeri `konacan_odgovor`.",
        ],
    },

    "spremnost": {
        "naslov": "Kako čitati 🎯 Spremnost baze",
        "koraci": [
            "Za svaku cjelinu piše koliko je zadataka **spremno za test** (nije skupina i ima konačan "
            "odgovor).",
            "To je odgovor na „mogu li iz ove cjeline složiti test”, a ne „koliko zadataka imam”.",
            "Kvačica učitava tab `Zadaci` (20.000 redaka) — uključi je samo kad ti treba.",
        ],
        "pazi": ["Brojanje ne mijenja bazu — samo čita."],
    },

    "raspodjela": {
        "naslov": "Kako radi 🧩 Raspodjela po cjelinama",
        "koraci": [
            "Alat uzme zadatke iz baze i **predloži** kojoj cjelini iz šifrarnika pripadaju — za slučaj "
            "kad je baza uvezena u manje cjelina nego što ih šifrarnik ima (fizika: 21 od 55).",
            "Odaberi što razvrstavati (sve / samo neke cjeline / samo bez cjeline) i model, pa **▶ Razvrsti**.",
            "Pregledaj tablicu: što se mijenja, koliko je model siguran i zašto. Nesigurne možeš preskočiti.",
            "**💾 Upiši** ide tek uz tvoju potvrdu. Upisuje se samo `cjelina`; stara vrijednost se pamti u "
            "`cjelina_prije`, pa se promjena može vratiti.",
            "Na kraju piše koje cjeline **ostaju prazne** — za njih treba novih zadataka, razvrstavanje to "
            "ne može riješiti.",
        ],
        "pazi": [
            "Model ne izmišlja cjeline: ako predloži ime kojeg nema u šifrarniku, prijedlog se **odbija**.",
            "Nesigurno („niska”) znači da model nagađa — takve provjeri ručno ili preskoči.",
            "Razvrstavanje troši tokene modela; 1.800 zadataka je ~70 poziva.",
        ],
        "dalje": "Poslije upisa: 📝 Testovi → 🎯 Spremnost baze → 🧩 Pokrivenost po cjelinama.",
    },
}


def prikazi(st, kljuc: str) -> None:
    """Sklopivi blok s uputom za stranicu koju upravo gledaš. Nepoznat ključ = ništa."""
    u = UPUTE.get(str(kljuc or ""))
    if not u:
        return
    with st.expander(f"ℹ️ {u['naslov']}", expanded=False):
        for i, korak in enumerate(u.get("koraci", []), start=1):
            st.markdown(f"**{i}.** {korak}")
        if u.get("pazi"):
            st.markdown("**⚠️ Pazi:**")
            for p in u["pazi"]:
                st.markdown(f"- {p}")
        if u.get("dalje"):
            st.caption(f"➡️ {u['dalje']}")
