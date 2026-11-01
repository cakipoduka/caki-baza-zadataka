"""CAKI — pages/18_provjera_rjesenja.py  (25.10.2026., prošireno 1.11.2026.)

🧑‍🏫 **Provjera i ispravak ocjena** — tri posla na jednom mjestu:

1. **⏳ Čeka odluku** — zadaci sa statusom `ceka` (nema ključa / postupak) ili `sumnja` (odgovor je
   sličan ključu, ali se nije mogao automatski odlučiti). Tek ovdje rezultat prelazi u `ocjenjeno`.
2. **✏️ Ispravak po zadatku** — Caki može otvoriti **BILO KOJI** predani rezultat (ne samo onaj koji
   čeka) i promijeniti odluku po zadatku: točno / djelomično (pola boda) / netočno. Bodovi se
   preračunaju i upišu odmah.
3. **🧮 Preračun starih rezultata** — testovi predani prije 1.11.2026. nose krive bodove jer se
   uspoređivao zapis, a ne vrijednost (`\\mathrm{8.8605}` prema `8.8605`). Odgovori su sačuvani u
   `odgovori_json`, a zadaci zamrznuti u testu — pa se sve može pošteno preračunati. Prvo se pokaže
   **što bi se promijenilo** (ništa se ne piše), pa tek uz izričitu potvrdu upis ide u
   `Rezultati_testova`.

Logika je u `testovi_admin.py` (`potrebna_provjera`, `zadaci_za_provjeru`, `primijeni_provjeru`,
`preracunaj_rezultat`, `polja_preracuna`) i testirana je bez Streamlita. Ovdje je SAMO sučelje;
upisuje se isključivo u `Rezultati_testova` (`detalji_json`, `bodovi`, `bodovi_max`, `postotak`,
`provjera`, `provjerio`, `provjereno`). `odgovori_json` se NIKAD ne mijenja.

SECRETS: GOOGLE_SERVICE_ACCOUNT_JSON, APP_PASSWORD, CRM_SHEET_ID.
"""
import streamlit as st

import predmet_config
import testovi_admin as ta
from baza_zadataka_pipeline import get_gspread_client
from secrets_json import ucitaj as _ucitaj_json

st.set_page_config(page_title="CAKI — Provjera rješenja", page_icon="🧑‍🏫", layout="wide")


def provjeri_lozinku() -> bool:
    def na_unos():
        st.session_state["autoriziran_provjera"] = (
            st.session_state.get("lozinka_provjera") == st.secrets.get("APP_PASSWORD"))

    if st.session_state.get("autoriziran_provjera"):
        return True
    st.title("🧑‍🏫 CAKI — Provjera rješenja")
    st.text_input("Lozinka", type="password", key="lozinka_provjera", on_change=na_unos)
    if st.session_state.get("autoriziran_provjera") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()

predmet = predmet_config.odaberi_predmet(st)
postavke = predmet_config.postavke(predmet)
st.title("🧑‍🏫 Provjera i ispravak ocjena")
st.caption(f"Predmet: **{postavke['naziv']}** · tri posla: odluka o zadatku koji čeka, ručni ispravak "
           f"bilo kojeg rezultata, i preračun testova predanih prije popravka ocjenjivanja.")

if "CRM_SHEET_ID" not in st.secrets:
    st.error("U Streamlit Secrets nedostaje **CRM_SHEET_ID**.")
    st.stop()


@st.cache_resource(show_spinner=False)
def _crm(sheet_id: str):
    # 1.11.2026.: parametar NE smije počinjati s `_` — Streamlit takve parametre preskače pri
    # izračunu ključa keša, pa bi se podaci dvaju različitih CRM Sheetova zamijenili.
    sa = _ucitaj_json(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
    return get_gspread_client(sa).open_by_key(sheet_id)


@st.cache_data(ttl=120, show_spinner=False)
def _podaci(sheet_id: str):
    sheet = _crm(sheet_id)
    return ta.load_testovi(sheet), ta.load_rezultati(sheet)


crm_id = str(st.secrets["CRM_SHEET_ID"]).strip()
testovi, rezultati = _podaci(crm_id)


def _zadaci_rezultata(rezultat: dict) -> list:
    test = ta.nadji_test(testovi, str(rezultat.get("test_id", ""))) or {}
    return ta.zadaci_iz_testa(test) if test else []


def _oznaka(r: dict) -> str:
    """„Ana (AA1111) · Test 1 · 2026-11-01 12:05 · 10/25 b" za padajući izbornik."""
    ime = str(r.get("ime_djeteta") or r.get("ucenik_id") or "?").strip()
    return (f"{ime} · {str(r.get('naziv_testa') or '').strip()} · "
            f"{str(r.get('vrijeme_predaje') or '')[:16]} · "
            f"{str(r.get('bodovi') or '0')}/{str(r.get('bodovi_max') or '0')} b")


def _redak_rezultata(ws, rezultat_id: str) -> int:
    """Broj retka u `Rezultati_testova` (0 ako ga nema)."""
    try:
        idovi = [str(v).strip() for v in ws.col_values(1)]
        return idovi.index(str(rezultat_id).strip()) + 1
    except Exception:                                      # noqa: BLE001
        return 0


tab_ceka, tab_ispravak, tab_preracun = st.tabs(
    ["⏳ Čeka odluku", "✏️ Ispravak po zadatku", "🧮 Preračun starih rezultata"])

# ============================================================
# 1) ⏳ Čeka odluku
# ============================================================
with tab_ceka:
    na_cekanju = [r for r in rezultati
                  if ta.potrebna_provjera(r) or str(r.get("provjera", "")).strip() == "ceka"]
    st.markdown(f"**Rezultata koji čekaju provjeru: {len(na_cekanju)}** "
                f"(od ukupno {len(rezultati)} predaja)")

    if not na_cekanju:
        st.success("Nema što provjeravati — svi rezultati su zaključeni.")
    else:
        oznake = [f"{r.get('ime_djeteta') or r.get('ucenik_id')} · {r.get('naziv_testa')} · "
                  f"{str(r.get('vrijeme_predaje', ''))[:16]} · {r.get('bodovi')}/{r.get('bodovi_max')} b"
                  for r in na_cekanju]
        odabrano = st.selectbox("Rezultat za provjeru", range(len(na_cekanju)),
                                format_func=lambda i: oznake[i], key="pv_ceka_odabir")
        rezultat = na_cekanju[int(odabrano)]
        test = ta.nadji_test(testovi, str(rezultat.get("test_id", ""))) or {}
        zadaci = ta.zadaci_iz_testa(test) if test else []
        detalji = ta.detalji_iz_retka(rezultat)

        if not test:
            st.warning("Test iz ovog rezultata više ne postoji u tabu `Testovi_zakazani` — "
                       "zadaci se ne mogu prikazati, ali provjera se može spremiti ako je test bio obrisan.")

        st.divider()
        odluke = {}
        for i, d in ta.zadaci_za_provjeru(rezultat):
            zadatak = zadaci[i] if i < len(zadaci) else {}
            _status = str(d.get("status", "")).strip()
            _znak = "⚠️ sumnja" if _status == "sumnja" else "⏳ čeka"
            with st.expander(f"#{i + 1} · {_znak} · {zadatak.get('tekst', '')[:60]}…", expanded=True):
                st.markdown(zadatak.get("tekst", "_(tekst zadatka nije dostupan)_"))
                c1, c2 = st.columns(2)
                c1.markdown("**Učenikov odgovor:**")
                c1.markdown(f"> {d.get('odgovor') or '_nije odgovoreno_'}")
                c2.markdown("**Očekivano rješenje:**")
                c2.markdown(f"> {d.get('ocekivano') or '_nema ključa_'}")
                st.caption(f"Bodovi zadatka: {d.get('max')} · status: {_status}")
                # 1.11.2026.: zašto je zadatak ovdje — AI je drugi glas, ne odluka (v. provjera_odgovora.py)
                _izvor, _zasto = str(d.get("izvor", "")).strip(), str(d.get("zasto", "")).strip()
                if _izvor == "ai":
                    st.info(f"🤖 AI (samo prijedlog, ključ je bio jedini izvor istine): {_zasto or '—'}")
                elif _status == "sumnja":
                    st.warning(f"⚠️ Nije odlučeno automatski: {_zasto or 'sličan zapis, nije sigurno'}"
                               + (f" · izvor: {_izvor}" if _izvor else ""))
                izbor = st.radio(
                    "Odluka", ["⏳ ostavi otvoreno", "✅ točno", "❌ netočno"],
                    key=f"odluka_{rezultat.get('rezultat_id')}_{i}", horizontal=True,
                )
                if izbor == "✅ točno":
                    odluke[i] = {"status": "tocno"}
                elif izbor == "❌ netočno":
                    odluke[i] = {"status": "netocno"}

        st.divider()
        if st.button("💾 Spremi provjeru", type="primary", key="pv_ceka_spremi"):
            if not odluke:
                st.warning("Nijedna odluka nije odabrana — ništa nije spremljeno.")
            else:
                ws = _crm(crm_id).worksheet(ta.REZ_TAB)
                redak = _redak_rezultata(ws, str(rezultat.get("rezultat_id", "")))
                if not redak:
                    st.error("Ne mogu naći redak rezultata u tabu `Rezultati_testova`.")
                else:
                    polja = ta.primijeni_provjeru(ws, redak, rezultat, odluke, provjerio="Caki")
                    _podaci.clear()
                    st.success(f"✅ Spremljeno: {polja['bodovi']} b ({polja['postotak']} %), "
                               f"status provjere: **{polja['provjera']}**.")
                    st.rerun()

# ============================================================
# 2) ✏️ Ispravak po zadatku — BILO KOJI rezultat
# ============================================================
with tab_ispravak:
    st.markdown("**Ručni ispravak ocjene** — otvori bilo koji predani test i promijeni odluku po zadatku.")
    st.caption("Radi i za testove koji su ocijenjeni prije 1.11.2026., i za djelomične bodove "
               "(npr. pola boda za ispravan postupak). `odgovori_json` se ne dira — mijenja se samo ocjena.")

    if not rezultati:
        st.info("Još nema predanih testova.")
    else:
        poredak = sorted(rezultati, key=lambda r: str(r.get("vrijeme_predaje") or ""), reverse=True)
        izbor = st.selectbox("Rezultat koji ispravljaš", list(range(len(poredak))),
                             format_func=lambda i: _oznaka(poredak[i]), key="pv_isp_odabir")
        rez = poredak[int(izbor)]
        zadaci_i = _zadaci_rezultata(rez)
        detalji_i = ta.detalji_iz_retka(rez)
        if not detalji_i:
            st.warning("Ovaj rezultat nema `detalji_json` — nema što ispravljati po zadatku.")
        else:
            st.markdown(f"Trenutno: **{rez.get('bodovi')}/{rez.get('bodovi_max')}** b "
                        f"({rez.get('postotak')} %) · provjera: `{rez.get('provjera') or '—'}`")
            odluke_i = {}
            for i, d in enumerate(detalji_i):
                z = zadaci_i[i] if i < len(zadaci_i) else {}
                _st = str(d.get("status", "")).strip()
                _ikona = {"tocno": "✅", "netocno": "❌", "ceka": "⏳", "sumnja": "⚠️",
                          "prazno": "⬜"}.get(_st, "·")
                with st.expander(
                        f"{i + 1}. {_ikona} {z.get('tekst', '')[:70] or '_(tekst nedostupan)_'}",
                        expanded=False):
                    st.markdown(z.get("tekst", ""))
                    c1, c2 = st.columns(2)
                    c1.markdown("**Učenikov odgovor:**")
                    c1.markdown(f"> {d.get('odgovor') or '_nije odgovoreno_'}")
                    c2.markdown("**Ključ:**")
                    c2.markdown(f"> {d.get('ocekivano') or '_nema ključa_'}")
                    st.caption(f"Sada: `{_st or '—'}` · {d.get('bodovi')} / {d.get('max')} b"
                               + (f" · {d.get('zasto')}" if d.get("zasto") else ""))

                    izbor_i = st.radio(
                        "Nova odluka",
                        ["— ostavi kako je —", "✅ točno", "🟡 djelomično", "❌ netočno"],
                        key=f"pvi_{rez.get('rezultat_id')}_{i}", horizontal=True,
                    )
                    if izbor_i == "✅ točno":
                        odluke_i[i] = {"status": "tocno"}
                    elif izbor_i == "❌ netočno":
                        odluke_i[i] = {"status": "netocno"}
                    elif izbor_i == "🟡 djelomično":
                        koliko = st.number_input(
                            "Bodovi (djelomično)", min_value=0.0,
                            max_value=float(d.get("max") or 1), step=0.5,
                            value=float(d.get("max") or 1) / 2,
                            key=f"pvb_{rez.get('rezultat_id')}_{i}")
                        odluke_i[i] = {"status": "netocno", "bodovi": float(koliko)}

            st.divider()
            if st.button("💾 Spremi ispravak", type="primary", key="pv_isp_spremi"):
                if not odluke_i:
                    st.warning("Nijedna odluka nije promijenjena — ništa nije spremljeno.")
                else:
                    ws = _crm(crm_id).worksheet(ta.REZ_TAB)
                    redak = _redak_rezultata(ws, str(rez.get("rezultat_id", "")))
                    if not redak:
                        st.error("Ne mogu naći redak rezultata u tabu `Rezultati_testova`.")
                    else:
                        polja = ta.primijeni_provjeru(ws, redak, rez, odluke_i, provjerio="Caki")
                        _podaci.clear()
                        st.success(f"✅ Spremljeno: **{polja['bodovi']}/{polja['bodovi_max']}** b "
                                   f"({polja['postotak']} %).")
                        st.rerun()

# ============================================================
# 3) 🧮 Preračun starih rezultata
# ============================================================
with tab_preracun:
    st.markdown("**Preračun već predanih testova** — ocjena se ponovno računa današnjom logikom.")
    st.caption("Odgovori učenika su sačuvani (`odgovori_json`), a zadaci zamrznuti u testu — zato se "
               "ocjena može pošteno preračunati. Prvo vidiš **što bi se promijenilo**; upis ide tek "
               "nakon potvrde, i to samo u `Rezultati_testova` (bodovi, postotak, detalji, provjera).")

    if not rezultati:
        st.info("Još nema predanih testova.")
    else:
        s_izborom = {"__svi__": f"Svi testovi ({len(rezultati)} predaja)"}
        po_testu = {}
        for r in rezultati:
            po_testu.setdefault(str(r.get("test_id") or ""), []).append(r)
        for tid, grupa in po_testu.items():
            naziv = str(grupa[0].get("naziv_testa") or tid).strip()
            s_izborom[tid] = f"{naziv} ({len(grupa)} predaja)"
        odabir_t = st.selectbox("Koji test preračunati", list(s_izborom),
                                format_func=s_izborom.get, key="pv_pre_test")

        ciljni = rezultati if odabir_t == "__svi__" else po_testu.get(str(odabir_t), [])

        # priprema (bez upisa) — jeftino je, pa se računa svaki rerun
        plan = []
        for r in ciljni:
            z = _zadaci_rezultata(r)
            rez_p = ta.preracunaj_rezultat(r, z)
            promjena = len(rez_p.get("promjene") or [])
            plan.append({"rezultat": r, "rez": rez_p, "promjena": promjena,
                         "mijenja": bool(rez_p.get("moze")) and promjena > 0})
        za_upis = [p for p in plan if p["mijenja"]]
        preskoceno = [p for p in plan if not p["rez"].get("moze")]

        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("Rezultata ukupno", len(plan))
        m2.metric("Mijenja se", len(za_upis))
        m3.metric("Preskočeno", len(preskoceno))

        if za_upis:
            import pandas as pd

            redci = [{
                "Učenik": str(p["rezultat"].get("ime_djeteta") or p["rezultat"].get("ucenik_id")),
                "Test": str(p["rezultat"].get("naziv_testa") or ""),
                "Predano": str(p["rezultat"].get("vrijeme_predaje") or "")[:16],
                "Prije (b)": p["rez"]["stari_bodovi"],
                "Poslije (b)": p["rez"]["novi_bodovi"],
                "Prije (%)": int(p["rez"]["stari_postotak"]),
                "Poslije (%)": int(p["rez"]["novi_postotak"]),
                "Zadataka": p["promjena"],
            } for p in za_upis]
            redci.sort(key=lambda d: d["Poslije (%)"] - d["Prije (%)"], reverse=True)
            st.markdown("**Što bi se promijenilo** (najveći skok prvi)")
            st.dataframe(pd.DataFrame(redci), hide_index=True, width="stretch")

            stari_prosjek = round(sum(p["rez"]["stari_postotak"] for p in plan) / len(plan)) if plan else 0
            novi_prosjek = round(
                sum(p["rez"]["novi_postotak"] if p["rez"].get("moze") else p["rez"]["stari_postotak"]
                    for p in plan) / len(plan)) if plan else 0
            st.caption(f"Prosjek svih odabranih rezultata: **{stari_prosjek} % → {novi_prosjek} %**")

            with st.expander(f"🔍 Detalji po zadatku ({len(za_upis)} rezultata)"):
                for p in za_upis[:30]:
                    st.markdown(f"**{_oznaka(p['rezultat'])}** — "
                                f"{p['rez']['stari_bodovi']} → {p['rez']['novi_bodovi']} b")
                    for d in p["rez"]["promjene"]:
                        st.markdown(f"- #{d['zadatak']}: „{d['odgovor']}“ prema „{d['ocekivano']}“ · "
                                    f"{d['staro']} → **{d['novo']}** ({d['prije']} → {d['poslije']} b)"
                                    + (f" · izvor: {d['izvor']}" if d["izvor"] else ""))

            st.divider()
            potvrda = st.checkbox(
                f"Potvrđujem upis u `Rezultati_testova` — mijenja se {len(za_upis)} rezultata "
                f"(od {len(plan)}).", key="pv_pre_potvrda")
            if st.button("💾 Upiši preračun", type="primary", disabled=not potvrda, key="pv_pre_upisi"):
                ws = _crm(crm_id).worksheet(ta.REZ_TAB)
                upisano, greske = 0, []
                for p in za_upis:
                    r = p["rezultat"]
                    redak = _redak_rezultata(ws, str(r.get("rezultat_id", "")))
                    if not redak:
                        greske.append(f"{_oznaka(r)} — redak nije nađen")
                        continue
                    polja = ta.polja_preracuna(r, _zadaci_rezultata(r), provjerio="preračun 1.11.2026.")
                    if not polja:
                        greske.append(f"{_oznaka(r)} — nema što upisati")
                        continue
                    try:
                        ta.upisi_u_redak(ws, redak, polja)
                        upisano += 1
                    except Exception as e:                 # noqa: BLE001
                        greske.append(f"{_oznaka(r)} — {type(e).__name__}")
                _podaci.clear()
                st.success(f"✅ Preračunato i upisano: **{upisano}** rezultata.")
                if greske:
                    st.warning("Nije upisano: " + "; ".join(greske[:10]))
                st.rerun()
        else:
            st.success("Ništa se ne bi promijenilo — svi odabrani rezultati već nose ispravne bodove.")

        if preskoceno:
            with st.expander(f"⏭️ Preskočeno ({len(preskoceno)}) — zašto"):
                for p in preskoceno[:40]:
                    st.markdown(f"- {_oznaka(p['rezultat'])} — **{p['rez'].get('razlog') or '—'}**")
