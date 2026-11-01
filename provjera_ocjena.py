"""CAKI — provjera_ocjena.py  (1.11.2026.)

🧑‍🏫 **Provjera i ispravak ocjena** — JEDNO mjesto, tri posla:

1. **⏳ Čeka odluku** — zadaci sa statusom `ceka` (nema ključa / postupak) ili `sumnja`
   (odgovor je sličan ključu, ali se nije mogao automatski odlučiti).
2. **✏️ Ispravak po zadatku** — Caki može otvoriti **BILO KOJI** predani rezultat i promijeniti
   odluku po zadatku: točno / djelomično (pola boda) / netočno.
3. **🧮 Preračun starih rezultata** — testovi predani prije 1.11.2026. nose krive bodove jer se
   uspoređivao zapis, a ne vrijednost (`\\mathrm{8.8605}` prema `8.8605`). Prvo se pokaže **što bi
   se promijenilo**, pa tek uz potvrdu upis ide u `Rezultati_testova`.

ZAŠTO MODUL (Cakijeva uputa 1.11.2026.): *„Spojiti provjeru rješenja s testovi karticom da sve
bude na jednom mjestu."* Isti kod sada zove **kartica 📝 Testovi** (tab 🧑‍🏫 Provjera) i, kao
prečac, zasebna stranica `pages/18_provjera_rjesenja.py`. Da se ne raziđu, sučelje je samo ovdje.

MATEMATIKA U PRIKAZU (Cakijev nalaz 1.11.2026.): učenikov odgovor se prikazuje kao **formula**, ne
kao izvorni LaTeX (`\\mathrm{\\frac{\\left(3-a\\right)}{3a}}`). Uz to stoji i izvorni zapis, jer se
samo tako može provjeriti je li formula dobro prepisana. `\\degree` se zamjenjuje s `^{\\circ}`
(KaTeX u Streamlitu ne poznaje `\\degree`), inače bi formula pukla na prikazu.

Logika (bez Streamlita) je u `testovi_admin.py` i testirana je odvojeno:
`potrebna_provjera`, `zadaci_za_provjeru`, `primijeni_provjeru`, `preracunaj_rezultat`,
`polja_preracuna`, `upisi_u_redak`.
"""
from __future__ import annotations

import re

import testovi_admin as ta

# ============================================================
# Prikaz odgovora — formula, ne izvorni kod
# ============================================================

_RX_LATEX = re.compile(r"\\[a-zA-Z]+")


def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def je_latex(tekst) -> bool:
    """Izgleda li zapis kao matematika (LaTeX), a ne kao obična rečenica."""
    t = _tekst(tekst)
    if not t:
        return False
    if t.count("$") >= 2:
        return True
    if _RX_LATEX.search(t):                     # \frac, \mathrm, \left, \cdot, \pi …
        return True
    return bool(re.search(r"[\^_]\s*\{", t))    # x^{2}, a_{1}


def _za_prikaz_latex(tex: str) -> str:
    """LaTeX prilagođen KaTeXu u Streamlitu (ne mijenja se ništa u bazi ni u ocjeni)."""
    t = tex
    t = t.replace("\\degree", "^{\\circ}")
    t = re.sub(r"\^\s*\{\s*\\circ\s*\}", r"^{\\circ}", t)      # zamjena mora biti RAW (\\c)
    t = re.sub(r"\^\s*\{\s*\\prime\s*\}", "'", t)
    t = t.replace("\\prime", "'")
    return t


def prikaz_odgovora(tekst, prazno: str = "_nije odgovoreno_") -> str:
    """Markdown za `st.markdown`: matematika u `$…$` (vidi se formula), tekst ostaje tekst."""
    t = _tekst(tekst)
    if not t:
        return prazno
    if t.count("$") >= 2:
        return t                                # baza ključeve zapisuje kao `$…$`
    if je_latex(t):
        return "$" + _za_prikaz_latex(t) + "$"
    return t


def izvorni_zapis(tekst) -> str:
    """Izvorni zapis za provjeru (samo kad je formula — inače prazno)."""
    t = _tekst(tekst)
    return f"`{t}`" if je_latex(t) else ""


def normalizovano(tekst, najvise: int = 90) -> str:
    """Kako sustav vidi odgovor nakon normalizacije — za redak „usporedba" kod sumnje."""
    try:
        import provjera_odgovora as _po          # noqa: PLC0415

        n = _po.normalizuj(tekst)
    except Exception:                                   # noqa: BLE001
        n = _tekst(tekst)
    return n if len(n) <= najvise else n[:najvise] + "…"


# ============================================================
# Pomoćno
# ============================================================

def _zadaci_rezultata(testovi, rezultat: dict) -> list:
    test = ta.nadji_test(testovi, str(rezultat.get("test_id", ""))) or {}
    return ta.zadaci_iz_testa(test) if test else []


def _oznaka(r: dict) -> str:
    """„Ana (AA1111) · Test 1 · 2026-11-01 12:05 · 10/25 b"."""
    ime = str(r.get("ime_djeteta") or r.get("ucenik_id") or "?").strip()
    return (f"{ime} · {str(r.get('naziv_testa') or '').strip()} · "
            f"{str(r.get('vrijeme_predaje') or '')[:16]} · "
            f"{str(r.get('bodovi') or '0')}/{str(r.get('bodovi_max') or '0')} b")


def _redak_rezultata(ws, rezultat_id: str) -> int:
    """Broj retka u `Rezultati_testova` (0 ako ga nema)."""
    try:
        return [str(v).strip() for v in ws.col_values(1)].index(str(rezultat_id).strip()) + 1
    except Exception:                                   # noqa: BLE001
        return 0


def _ws_rezultati(sheet):
    return sheet.worksheet(ta.REZ_TAB)


# ============================================================
# 1) ⏳ Čeka odluku
# ============================================================

def _tab_ceka(st, sheet, testovi, rezultati) -> None:
    na_cekanju = [r for r in rezultati
                  if ta.potrebna_provjera(r) or str(r.get("provjera", "")).strip() == "ceka"]
    st.markdown(f"**Rezultata koji čekaju provjeru: {len(na_cekanju)}** "
                f"(od ukupno {len(rezultati)} predaja)")

    if not na_cekanju:
        st.success("Nema što provjeravati — svi rezultati su zaključeni.")
        return

    oznake = [f"{r.get('ime_djeteta') or r.get('ucenik_id')} · {r.get('naziv_testa')} · "
              f"{str(r.get('vrijeme_predaje', ''))[:16]} · {r.get('bodovi')}/{r.get('bodovi_max')} b"
              for r in na_cekanju]
    odabrano = st.selectbox("Rezultat za provjeru", range(len(na_cekanju)),
                            format_func=lambda i: oznake[i], key="pv_ceka_odabir")
    rezultat = na_cekanju[int(odabrano)]
    test = ta.nadji_test(testovi, str(rezultat.get("test_id", ""))) or {}
    zadaci = ta.zadaci_iz_testa(test) if test else []

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
            c1.markdown(f"> {prikaz_odgovora(d.get('odgovor'))}")
            if izvorni_zapis(d.get("odgovor")):
                c1.caption(f"zapis: {izvorni_zapis(d.get('odgovor'))}")
            c2.markdown("**Očekivano rješenje:**")
            c2.markdown(f"> {prikaz_odgovora(d.get('ocekivano'), prazno='_nema ključa_')}")
            if izvorni_zapis(d.get("ocekivano")):
                c2.caption(f"zapis: {izvorni_zapis(d.get('ocekivano'))}")
            st.caption(f"Bodovi zadatka: {d.get('max')} · status: {_status}")

            _izvor, _zasto = str(d.get("izvor", "")).strip(), str(d.get("zasto", "")).strip()
            if _izvor == "ai":
                st.info(f"🤖 AI (samo prijedlog, ključ je bio jedini izvor istine): {_zasto or '—'}")
            elif _status == "sumnja":
                st.warning(f"⚠️ Nije odlučeno automatski: {_zasto or 'sličan zapis, nije sigurno'}")
                st.caption("Usporedba nakon normalizacije: "
                           f"`{normalizovano(d.get('odgovor'))}` prema "
                           f"`{normalizovano(d.get('ocekivano'))}`"
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
            return
        ws = _ws_rezultati(sheet)
        redak = _redak_rezultata(ws, str(rezultat.get("rezultat_id", "")))
        if not redak:
            st.error("Ne mogu naći redak rezultata u tabu `Rezultati_testova`.")
            return
        polja = ta.primijeni_provjeru(ws, redak, rezultat, odluke, provjerio="Caki")
        st.cache_data.clear()
        st.success(f"✅ Spremljeno: {polja['bodovi']} b ({polja['postotak']} %), "
                   f"status provjere: **{polja['provjera']}**.")
        st.rerun()


# ============================================================
# 2) ✏️ Ispravak po zadatku — BILO KOJI rezultat
# ============================================================

def _tab_ispravak(st, sheet, testovi, rezultati) -> None:
    st.markdown("**Ručni ispravak ocjene** — otvori bilo koji predani test i promijeni odluku po zadatku.")
    st.caption("Radi i za testove ocijenjene prije 1.11.2026., i za djelomične bodove (npr. pola boda "
               "za ispravan postupak). `odgovori_json` se ne dira — mijenja se samo ocjena.")

    if not rezultati:
        st.info("Još nema predanih testova.")
        return

    poredak = sorted(rezultati, key=lambda r: str(r.get("vrijeme_predaje") or ""), reverse=True)
    izbor = st.selectbox("Rezultat koji ispravljaš", list(range(len(poredak))),
                         format_func=lambda i: _oznaka(poredak[i]), key="pv_isp_odabir")
    rez = poredak[int(izbor)]
    zadaci_i = _zadaci_rezultata(testovi, rez)
    detalji_i = ta.detalji_iz_retka(rez)
    if not detalji_i:
        st.warning("Ovaj rezultat nema `detalji_json` — nema što ispravljati po zadatku.")
        return

    st.markdown(f"Trenutno: **{rez.get('bodovi')}/{rez.get('bodovi_max')}** b "
                f"({rez.get('postotak')} %) · provjera: `{rez.get('provjera') or '—'}`")
    odluke_i = {}
    for i, d in enumerate(detalji_i):
        z = zadaci_i[i] if i < len(zadaci_i) else {}
        _st = str(d.get("status", "")).strip()
        _ikona = {"tocno": "✅", "netocno": "❌", "ceka": "⏳", "sumnja": "⚠️",
                  "prazno": "⬜"}.get(_st, "·")
        with st.expander(f"{i + 1}. {_ikona} {z.get('tekst', '')[:70] or '_(tekst nedostupan)_'}",
                         expanded=False):
            st.markdown(z.get("tekst", ""))
            c1, c2 = st.columns(2)
            c1.markdown("**Učenikov odgovor:**")
            c1.markdown(f"> {prikaz_odgovora(d.get('odgovor'))}")
            if izvorni_zapis(d.get("odgovor")):
                c1.caption(f"zapis: {izvorni_zapis(d.get('odgovor'))}")
            c2.markdown("**Ključ:**")
            c2.markdown(f"> {prikaz_odgovora(d.get('ocekivano'), prazno='_nema ključa_')}")
            if izvorni_zapis(d.get("ocekivano")):
                c2.caption(f"zapis: {izvorni_zapis(d.get('ocekivano'))}")
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
            return
        ws = _ws_rezultati(sheet)
        redak = _redak_rezultata(ws, str(rez.get("rezultat_id", "")))
        if not redak:
            st.error("Ne mogu naći redak rezultata u tabu `Rezultati_testova`.")
            return
        polja = ta.primijeni_provjeru(ws, redak, rez, odluke_i, provjerio="Caki")
        st.cache_data.clear()
        st.success(f"✅ Spremljeno: **{polja['bodovi']}/{polja['bodovi_max']}** b "
                   f"({polja['postotak']} %).")
        st.rerun()


# ============================================================
# 3) 🧮 Preračun starih rezultata
# ============================================================

def _tab_preracun(st, sheet, testovi, rezultati) -> None:
    st.markdown("**Preračun već predanih testova** — ocjena se ponovno računa današnjom logikom.")
    st.caption("Odgovori učenika su sačuvani (`odgovori_json`), a zadaci zamrznuti u testu — zato se "
               "ocjena može pošteno preračunati. Prvo vidiš **što bi se promijenilo**; upis ide tek "
               "nakon potvrde, i to samo u `Rezultati_testova`.")

    if not rezultati:
        st.info("Još nema predanih testova.")
        return

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

    plan = []
    for r in ciljni:
        rez_p = ta.preracunaj_rezultat(r, _zadaci_rezultata(testovi, r))
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
                    st.markdown(f"- #{d['zadatak']}: {prikaz_odgovora(d['odgovor'])} prema "
                                f"{prikaz_odgovora(d['ocekivano'])} · {d['staro']} → **{d['novo']}** "
                                f"({d['prije']} → {d['poslije']} b)"
                                + (f" · izvor: {d['izvor']}" if d["izvor"] else ""))

        st.divider()
        potvrda = st.checkbox(
            f"Potvrđujem upis u `Rezultati_testova` — mijenja se {len(za_upis)} rezultata "
            f"(od {len(plan)}).", key="pv_pre_potvrda")
        if st.button("💾 Upiši preračun", type="primary", disabled=not potvrda, key="pv_pre_upisi"):
            ws = _ws_rezultati(sheet)
            upisano, greske = 0, []
            for p in za_upis:
                r = p["rezultat"]
                redak = _redak_rezultata(ws, str(r.get("rezultat_id", "")))
                if not redak:
                    greske.append(f"{_oznaka(r)} — redak nije nađen")
                    continue
                polja = ta.polja_preracuna(r, _zadaci_rezultata(testovi, r),
                                           provjerio="preračun 1.11.2026.")
                if not polja:
                    greske.append(f"{_oznaka(r)} — nema što upisati")
                    continue
                try:
                    ta.upisi_u_redak(ws, redak, polja)
                    upisano += 1
                except Exception as e:                 # noqa: BLE001
                    greske.append(f"{_oznaka(r)} — {type(e).__name__}")
            st.cache_data.clear()
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


# ============================================================
# Ulazna točka (zove kartica 📝 Testovi i stranica 18)
# ============================================================

def prikazi(st, sheet, testovi, rezultati) -> None:
    """Tri taba provjere. `sheet` = CRM Sheet; piše se SAMO u `Rezultati_testova`."""
    testovi = list(testovi or [])
    rezultati = list(rezultati or [])
    tab_ceka, tab_ispravak, tab_preracun = st.tabs(
        ["⏳ Čeka odluku", "✏️ Ispravak po zadatku", "🧮 Preračun starih rezultata"])
    with tab_ceka:
        _tab_ceka(st, sheet, testovi, rezultati)
    with tab_ispravak:
        _tab_ispravak(st, sheet, testovi, rezultati)
    with tab_preracun:
        _tab_preracun(st, sheet, testovi, rezultati)


__all__ = ["prikazi", "prikaz_odgovora", "izvorni_zapis", "normalizovano", "je_latex"]
