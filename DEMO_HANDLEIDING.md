# Demonstratiehandleiding — Bruine Beer

**Datum navigatie-update:** 3 november 2026  
**Open:** https://127.0.0.1:5173/  
**Appnaam in de UI:** Bruine Beer

---

## Nieuw klikpad (sidebar)

1. **Bruine Beer** (appnaam)
2. **Client** — kiezer + compacte **+** (klant toevoegen) + badge **Active** + **⚙** (client settings)
3. **Synchronisation** — compacte Meta-status (`Connected` / `Reconnect required` / `Not connected`) + sync-knop  
   → horizontale lijn
4. Hoofdmenu (Engels), vaste volgorde:
   - Targets & Strategy
   - Performance
   - Reports & Analysis
   - Search
   - Competitors
   - Settings

**Active ≠ Connected.** Active = geselecteerde klant. Connected = geldige Meta-koppeling.

### Client settings (⚙ of oude `?page=clients`)
- Naam wijzigen
- Meta verbinden / account kiezen / bevestigen
- **Disconnect Meta** (bevestiging; alleen deze klant; posts/strategie/legenda/rapporten blijven)

### Reports & Analysis — tabs
Reports · Logs · Export & Import · Images · AI Trial  

Images = voormalige Beeldtest → **Not available yet**.

### Settings — tabs
AI Connections · Legend (per klant; klantnaam zichtbaar)

### Targets & Strategy
Tab **Specialist**: bovenaan strategy & targets; daaronder **Specialist Findings & Conclusions**.

### URL-aliases (blijven werken)
`clients` → client settings · `logs` / `reports` / `data` / `image_test` / `ai_trial` → Reports & Analysis · `legend` / `ai` → Settings · `zoeken` / `posts` → Search

---

## Wat je betrouwbaar kunt tonen (inhoud)

Zie eerdere checks: Red Rock Meta **Connected**, posts sync, concurrent crawl, editorial behoud.  
Demo-regel: kijk op **Red Rock**; schrijf/ontkoppel-tests op **QA Controle** — **verbreek Red Rock niet** voor een disconnect-demo.

## Wat je niet als werkend mag presenteren

Images/Beeldtest, echte Claude end-to-end, paid report execute, multi-concurrent refresh.

## ~5 minuten demo

1. Open https://127.0.0.1:5173/ → kies **Red Rock** (Active-badge).  
2. Toon compacte Meta-status onder Synchronisation.  
3. ⚙ Client settings → Connected (niet disconnecten op Red Rock).  
4. Targets & Strategy → Specialist.  
5. Performance → één maand.  
6. Reports & Analysis → Reports / Logs / AI Trial (mock).  
7. Search → kort filteren.  
8. Competitors → zes namen.  
9. Settings → AI Connections + Legend.

## UI-taal

Interface-chrome (navigatie, tabs, filters, statussen, fouten, lege staten, periodekeuzes, ratingformule-labels) is **Engels**.  
Bewust Nederlands blijven: klantinhoud, Excel-importteksten/kolomkoppen in bestanden, Maaike-analyseprompts, AI-sentinelwaarden zoals `Geen passend bestaand format` / `Niet vast te stellen`, en historische crawl-details die al in de database stonden.

## Resterende punten

1. Images nog niet gebouwd.  
2. Disconnect alleen op testklant demonstreren.  
3. Oude bookmarks met Nederlandse menunamen: aliases vangen de `page=`-waarden op.  
4. Oude opgeslagen activity/crawl-detailregels kunnen nog NL bevatten tot een nieuwe sync.
