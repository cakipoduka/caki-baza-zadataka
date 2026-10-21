"""
CAKI — pages/11_upute_testovi.py  (21.10.2026.)

📖 Upute za sustav online testova — korak po korak, u samoj aplikaciji.
Namjerno BEZ pristupa podacima: ne čita Sheet, ne piše ništa. Samo tekst za Cakija
(da se ne traži po chatovima i uputama na disku).

Sadržaj prati stvarne kartice: Test Builder → 📝 Testovi → 👥 Zadaj grupi → rezultati →
👤 Po učeniku → održavanje → provjere.
"""
import streamlit as st

st.set_page_config(page_title="CAKI — Upute: testovi", page_icon="📖", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_upute"] = (
            st.session_state.get("lozinka_unos_upute") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_upute"):
        return True
    st.title("📖 CAKI — Upute za testove")
    st.text_input("Lozinka", type="password", key="lozinka_unos_upute", on_change=na_unos)
    if st.session_state.get("autoriziran_upute") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

st.title("📖 Upute — sustav online testova")
st.caption("Korak po korak za sve funkcije. Ovo je samo tekst — ništa se ovdje ne mijenja.")

t1, t2, t3, t4 = st.tabs(["⚡ Za 5 minuta", "📝 Objava i zadavanje", "🧑‍🎓 Učenik rješava", "🔧 Održavanje i provjere"])

# ---------------------------------------------------------------- 1
with t1:
    st.markdown("""
### Najkraći put od nule do rezultata

1. **🧪 Test Builder** → filtriraj zadatke (cjelina, težina, izvor) → klikni **➕** na zadatke
   koje želiš. Desno vidiš odabrane i možeš mijenjati redoslijed i bodove.
2. Na dnu stranice → **📝 Objavi kao online test** → upiši naziv, trajanje (min) i rok
   („otvoren od–do”) → **Objavi test**.
   *Rezultat:* jedan redak u `Testovi_zakazani`; učenik ga vidi u **Moj CAKI → 📝 Testovi**.
3. **📝 Testovi** (ova aplikacija, izbornik lijevo):
   - **📋 Testovi** — popis svih testova, uređivanje, pregled s točnim odgovorima;
   - **👥 Zadaj grupi** — isti test cijeloj grupi Upisa ili kanti Mature;
   - **📊 Rezultati** — tko je predao, uspjeh po zadatku i cjelini, matrica, CSV.
4. Kad učenici predaju → **📊 Rezultati** → odaberi test → vidiš brojeve i **koji zadatak je pao**.
5. Za razgovor s roditeljem → **👤 Po učeniku** → odaberi učenika → dolje je
   **📋 Sažetak za roditelja** (kopiraj u WhatsApp/mail).
""")
    st.info("Test se **ne šalje** učenicima automatski — vide ga kad otvore Moj CAKI, dok je "
            "aktivan i unutar roka. Ako ga ne treba više, ⏸️ **Deaktiviraj** (rezultati ostaju).")

# ---------------------------------------------------------------- 2
with t2:
    st.markdown("""
### A) Objava iz Test Buildera
- **Naziv** vidi učenik — stavi nešto prepoznatljivo („Matura A — vježba 3”).
- **Trajanje** je vrijeme rješavanja (5–240 min). Mjeri se od trenutka kad učenik **otvori**
  test i **ne staje** ako osvježi stranicu.
- **Otvoren od / do** su datumi kad je test vidljiv. Bez roka se nudi svaki dan dok ga ne
  isključiš (🩺 Provjere na to upozori).
- **Šifra učenika** (prazno = svi) — ciljani test vidi samo taj učenik, neovisno o programima.
- **Program** (prazno = svi) — koristi se samo za opću objavu.

### B) Zadavanje cijeloj grupi (👥 Zadaj grupi)
1. Odaberi **koji test** zadaješ (zadaci se kopiraju — izmjena izvornog ne dira ovo).
2. **Kome**: `Upisi grupa` (učenici s **potvrđenom** rezervacijom) ili `Matura kanta`
   (dan + termin + učionica iz Rasporeda Matura).
3. Vidiš popis učenika, upišeš naziv i rok → **📤 Objavi za N učenika**.
4. Svi dobiju **svoj** redak, a zajednička oznaka je **serija** — zato se u rezultatima
   gledaju kao cjelina.

| Što želiš | Gdje |
|---|---|
| promijeniti rok cijeloj grupi | otvori bilo koji redak serije → promijeni datum → 💾 Spremi (piše „za N učenika”) |
| ugasiti cijelu grupu | ⏸️ Deaktiviraj cijelu seriju |
| obrisati cijelu grupu | 🗑️ Obriši cijelu seriju (briše i rezultate) |
""")
    st.warning("Ako naknadno dodaš učenika u grupu, on **ne dobiva** već objavljenu seriju — "
               "zadaj mu test pojedinačno ili ponovi objavu za grupu.")

# ---------------------------------------------------------------- 3
with t3:
    st.markdown("""
### Što učenik vidi (Moj CAKI → 📝 Testovi)
- Popis dostupnih testova s brojem zadataka, trajanjem i rokom; gumb **▶️ Počni test**.
- Pitanja: višestruki izbor = gumbi A/B/C/D; kratki odgovor = matematičko polje
  (ako polje ne radi, običan tekstualni unos — učenik svejedno može odgovoriti).
- **Slika uz zadatak** se prikazuje ako je u aplikaciji postavljen `SLIKE_FOLDER_ID`.
- **Vrijeme**: piše do kada mora predati. Osvježavanje stranice **ne** vraća vrijeme na početak.
- **Predaja**: jedan klik. Ako klikne dvaput (ili otvori dva taba), drugi put ne upisuje novi
  rezultat — javi mu se „već predan”.

### Što učenik vidi nakon predaje
- Odmah: bodove i status („Predano” ili „Predano (vrijeme isteklo)”).
- Trajno: **📊 Rezultati** — tablica svih njegovih testova s postocima.

### Ako učenik kaže „ne vidim test”
1. Je li test **aktivan** i je li **danas unutar roka** (📋 Testovi).
2. Je li zadat **njemu** (šifra) ili **njegovoj grupi** — provjeri u 👥 Zadaj grupi.
3. Ako je zadan cijeloj grupi, je li njegova rezervacija **Potvrđeno** (CRM → Rezervacije).
""")

# ---------------------------------------------------------------- 4
with t4:
    st.markdown("""
### Održavanje testa (📋 Testovi)
| Gumb | Što radi |
|---|---|
| 💾 **Spremi izmjene** | naziv, trajanje, rokovi, aktivan — piše samo u taj test (ili cijelu seriju) |
| ⏸️ **Deaktiviraj** | učenik ga više ne vidi, **rezultati ostaju** — koristi ovo kad je test gotov |
| 📄 **Kloniraj** | novi test s istim zadacima (npr. ista vježba drugoj grupi) |
| 👁️ **Pregled** | kako test vidi učenik, s točnim odgovorima |
| 🗑️ **Obriši test** | **trajno**: nestaje iz Moj CAKI i iz rezultata (traži potvrdu) |

### Rezultati (📊 Rezultati)
- **Predaje** — najslabiji prvi, s trajanjem.
- **Uspjeh po zadatku** — koji zadatak razred nije znao (prvi redak = najgori).
- **📚 Uspjeh po cjelinama** — ista stvar, ali po cjelinama iz baze.
- **🧩 Matrica učenik × zadatak** — tko je što riješio (✓/✗), s CSV-om.
- **🧮 Matrica razreda** — svi učenici × posljednji testovi, s prosjekom.
- **🔀 Usporedba dvaju testova** — je li razred napredovao (samo oni koji su pisali oba).
- **🕓 Započeli, nisu predali** — otvorili su test i odustali; „Rješava (min)” pokazuje koliko su dugo unutra.
- **⬇️ CSV** — rezultati po zadacima i uspjeh po zadatku.

### Po učeniku (👤 Po učeniku)
Povijest svih njegovih testova, cjeline kroz sve testove (najslabija prva), popis zadataka koje
nije riješio točno (s njegovim upisom i točnim odgovorom) i **gotov tekst za roditelja**.

### Provjere
| Kartica | Što govori |
|---|---|
| 🩺 **Provjere** | 🧪 je li sve spojeno (tabovi/stupci/dupli ID-evi); aktivan test bez roka; test bez odgovora; test bez ijedne predaje; 🔒 je li se zadatak u bazi promijenio nakon objave |
| 🎯 **Spremnost baze** | koliko zadataka po cjelini ima konačan odgovor (može u test) |

### Ako nešto ne radi
| Simptom | Najčešći uzrok | Rješenje |
|---|---|---|
| Učenik ne vidi test | nije aktivan / izvan roka / nije njegov | 📋 Testovi → provjeri; 👥 Zadaj grupi |
| „Nema testova” u portalu | portal nije rebootan ili nema `CRM_SHEET_ID` | reboot + Secrets |
| Slika se ne vidi | nema `SLIKE_FOLDER_ID` ili račun ne vidi folder | Secrets + podijeli folder |
| Rezultat se ne pojavi | učenik nije kliknuo Predaj ili Google nije odgovorio | 📊 Rezultati → provjeri; pokušaj ponovno |
| Test se ne može objaviti | zadatak nema konačan odgovor ili je skupina | dopuni odgovor u bazi / objavi kao PDF |
""")
