# Social Media Search Dashboard (MVP basis)

Python-project voor het lokaal doorzoeken van content van eigen Instagram Business- en Facebook Page-accounts.

Deze fase bevat:

- projectsetup
- configuratie
- SQLite schema en init-script
- basis dataclasses/models
- skeleton voor dashboard en sync-entrypoint
- robuuste Meta API-client (paginering, retry/backoff, foutafhandeling, logging)

Er is nog **geen volledige data-sync naar SQLite** geïmplementeerd in deze fase.

## Scope v1 (doel)

- Instagram posts/captions/hashtags
- Instagram comments
- Facebook Page posts
- Facebook comments
- Geen stories
- Geen replies (nested comments) in MVP
- Zoeken alleen in lokale SQLite database

## Architectuur (huidige basis)

- `app.py`: Streamlit dashboard entrypoint
- `sync.py`: sync CLI entrypoint (placeholder)
- `config.py`: env-configuratie
- `models.py`: basis dataclasses
- `meta/client.py`: Graph API client skeleton
- `meta/endpoints.py`: endpoint- en fieldset-definities
- `db/schema.sql`: SQLite schema + FTS5
- `db/database.py`: DB helper functies
- `scripts/init_db.py`: database initialisatie
- `scripts/check_meta_client.py`: handmatige API-client smoke check met `.env`
- `scripts/meta_api_inspector.py`: uitgebreide API-validatie en JSON-export

## Vereisten

- Python 3.11+
- Windows/macOS/Linux

## Installatie

1. Maak een virtual environment:

   ```bash
   python -m venv .venv
   ```

2. Activeer de omgeving:

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Installeer dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Maak `.env` op basis van voorbeeld:

   ```bash
   copy .env.example .env
   ```

   (op macOS/Linux: `cp .env.example .env`)

5. Vul de Meta-gegevens in `.env` in.

## Facebook Login for Business (aanbevolen flow)

Voor productie heb je doorgaans nodig:

- `pages_show_list`
- `pages_read_engagement`
- `instagram_basic`
- `instagram_manage_comments`

Daarnaast:

- gekoppelde Facebook Page en Instagram Business-account
- juiste Page-taken voor de gebruiker
- App Review/Business Verification (buiten testmodus)

## Database initialiseren

Voer uit:

```bash
python scripts/init_db.py
```

Dit maakt standaard de database aan op `data/social_search.db`.

## Dashboard starten

```bash
streamlit run app.py
```

## Meta setup flow (zonder SQLite sync)

1. Maak `.env` aan:

```powershell
copy .env.example .env
```

2. Vul minimaal in:
- `META_APP_ID`
- `META_APP_SECRET`
- `META_USER_ACCESS_TOKEN` (short-lived uit Graph API Explorer)
- `META_PAGE_ID`
- `META_INSTAGRAM_BUSINESS_ACCOUNT_ID`

3. Vernieuw tokens structureel (aanbevolen):

```powershell
python scripts/refresh_all_tokens.py
```

Dit script:
- zet de short-lived `META_USER_ACCESS_TOKEN` om naar een long-lived user token
- haalt een nieuw Page Access Token op via `GET /{META_PAGE_ID}?fields=access_token`
- werkt `.env` bij (`META_USER_ACCESS_TOKEN`, `META_PAGE_ACCESS_TOKEN`, optioneel IG account id)
- print alleen gemaskeerde tokens

4. Alternatief: losse stappen

```powershell
python scripts/get_long_lived_token.py --update-env
python scripts/get_page_access_token.py --update-env
```

5. Valideer API-data:

```powershell
python scripts/meta_api_inspector.py --limit 5 --export-json inspector-output.json
```

### Token verlopen (Graph API error code 190)

Gebruik geen nieuwe short-lived Graph Explorer tokens als permanente oplossing.

1. Genereer een nieuwe **User Token** in [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Zet die tijdelijk in `META_USER_ACCESS_TOKEN` in `.env`
3. Run:

```powershell
python scripts/refresh_all_tokens.py
python sync.py --all
```

Het dashboard toont bij error code 190:
`Meta token verlopen. Genereer nieuwe User Token en run scripts/refresh_all_tokens.py.`

Setup-scripts maskeren secrets in console-output (alleen eerste/laatste 4 tekens).

## Meta client smoke test (zonder DB-sync)

Voer uit:

```bash
python scripts/check_meta_client.py
```

Optioneel met request debug logging:

```bash
python scripts/check_meta_client.py --verbose
```

Dit controleert technisch:

- ophalen van Pages
- ophalen van gekoppeld Instagram Business Account ID
- ophalen van Instagram media + comments
- ophalen van Facebook Page posts + comments

## Meta API Inspector (validatiefase, zonder SQLite)

Voer uit:

```bash
python scripts/meta_api_inspector.py
```

Nuttige opties:

```bash
python scripts/meta_api_inspector.py --limit 5 --export-json inspector-output.json
python scripts/meta_api_inspector.py --show-raw
python scripts/meta_api_inspector.py --verbose
```

Inspector-functionaliteit:

- test de Meta API verbinding
- toont beschikbare Facebook Pages
- toont gekoppelde Instagram Business Account
- haalt laatste posts en comments op (IG + FB)
- normaliseert output per post/comment
- toont beschikbare en ontbrekende velden
- schrijft optioneel volledige debug JSON weg

Belangrijk: Inspector schrijft niets naar SQLite.

## Social vergelijking (Business Discovery)

De pagina **Social vergelijking** vergelijkt `@theartofliving.online` (eigen account + discovery-host) met concurrenten via Instagram Business Discovery. Concurrenten, posts en metingen worden in SQLite bewaard. Het scherm leest alleen uit de database; API-calls gebeuren uitsluitend bij een expliciete ophaalrun.

Discovery-paginagrootte via `DISCOVERY_MEDIA_PAGE_SIZE` (standaard **25**). Grotere waarden worden niet aangenomen goedkoper of officieel ondersteund te zijn. Per HTTP-call worden duur, paginagrootte, aantal posts en veilige usage-headers gelogd. Bij onderbreking (o.a. rate limit) blijven opgehaalde pagina’s bewaard; de periode wordt als onvolledig gemarkeerd en hervat vanaf de cursor met deduplicatie op post-ID.

Handmatig of via externe cron verversen:

```powershell
python scripts/refresh_comparison.py
python scripts/refresh_comparison.py --force
python scripts/refresh_comparison.py --resume-hoog
python scripts/refresh_comparison.py --skip-own --only hoog.design
```

Na een Meta-fout `#4` (aanvraaglimiet) stopt discovery meteen, zonder retry-lussen; bestaande posts/metingen blijven staan. Met `Retry-After` wordt die wachttijd gerespecteerd (`--force` omzeilt die niet). Zonder `Retry-After`: status “Resetmoment onbekend” — informatief, blokkeert toekomstige aanvragen niet permanent. Gecontroleerd hervatten: knop **Hervat met hoog.design** of `--resume-hoog` (één aanvraag, geen retries, geen gelijktijdige runs; niet automatisch).

### Deployment & database

| Omgeving | Wat draait | Database |
| --- | --- | --- |
| **Lokaal (huidige werkcopy)** | Streamlit via `app.py` / venv | `DATABASE_PATH=data/social_search.db` (SQLite op schijf) |
| **Render (repo-config)** | Web: `python run_web.py` + cron wake (`render.yaml`) | Ephemeral SQLite via `DATABASE_PATH=data/social_search.db`; scheduler in het webproces (zelfde DB) |

Runtime-DB en back-ups staan in `.gitignore` (`data/*.db`, `data/backups/`). Alleen `seed_social_search.db` / media-seed gaan mee in Git.

Historische vergelijkingsmetingen (offline, zonder Meta-API) samenvoegen — **live-first**: eerst de live/target-DB veiligstellen, daarna V2-bron erin mergen (nooit live overschrijven met een lokaal mergebestand):

```powershell
python scripts/merge_comparison_history.py `
  --source path\to\v2_social_search.db `
  --target path\to\live_social_search.db `
  --backup-dir data\backups
```

Het script maakt eerst back-ups, behoudt bestaande target-metingen, en voegt alleen ontbrekende **rechtstreeks opgeslagen** metingen toe op basis van `(platform, external_id, measured_at)`. Logtijden gelden niet als meettijd.

Dagelijkse jobs draaien **in het webproces** (zelfde SQLite): 07:30 growth, 13:30 social vergelijking, 20:30 volledige refresh (Europe/Amsterdam). De Render cron `dashboard-wake` houdt de web service wakker; zet `DASHBOARD_URL` naar de live URL. Stel **geen** aparte worker in met een eigen DB-kopie.

### Dagelijkse run (lokaal gepland — nog niet bewezen)

Windows Taakplanner-taak **`META-Dashboard-Daily-Comparison`** is ingesteld (dagelijks 06:15 lokale tijd). Preflight van paden/DB is getest; een echte geslaagde Meta-run van deze taak is nog niet vastgelegd — noem dagelijks ophalen pas werkend na status `completed` / `completed_with_errors`.

**Configuratie:**

1. Trigger: dagelijks 06:15 (lokale Windows-tijd / Europe/Amsterdam).
2. Actie → `powershell.exe` met wrapper `scripts\run_daily_comparison.ps1`
   - Programma (venv): `.venv\Scripts\python.exe`
   - CLI: `scripts\refresh_comparison.py --source daily`
   - Starten in: projectroot `AutomationDashboardMETA`
   - `DATABASE_PATH` = absoluut pad naar `data\social_search.db` (zelfde bestand als Streamlit)
3. Geen overlap: Task Scheduler `MultipleInstances=IgnoreNew` + CLI `find_active_fetch_run`.
4. Logs: `logs\daily_comparison_*.log` (status per account via CLI).
5. Preflight zonder Meta: `python scripts/refresh_comparison.py --preflight` of `.\scripts\run_daily_comparison.ps1 -Preflight`.

Als de app later op **Render** draait: Cron Job, schedule `15 4 * * *` (UTC = 06:15 Europe/Amsterdam in winter) of `15 5 * * *` in zomertijd, **zelfde** disk mount + `DATABASE_PATH` als de web service, startcommando:

```bash
cd /app && python scripts/refresh_comparison.py --source daily
```

## Unit tests (zonder echte API-calls)

De tests gebruiken HTTP mocking, dus er worden geen echte Meta API-calls gedaan:

```bash
pytest -q
```

## Maaike-dashboard (React + FastAPI)

Dit is de ontwikkelbasis voor Maaike. De Streamlit-ingang `app_maaike.py` blijft beschikbaar als terugval en gebruikt dezelfde SQLite-database `data/maaike_redrock.db`. De TAOL-app (`app.py`, `data/social_search.db`) blijft een apart programma.

Start twee processen vanuit de projectmap. Meta- of AI-sleutels zijn niet nodig om het scherm te openen.

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn maaike_web.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Frontend, in een tweede venster:

```powershell
cd frontend
npm install
npm run dev
```

Open daarna http://127.0.0.1:5173

Adressen staan in de omgeving, met deze standaardwaarden:

- `MAAIKE_FRONTEND_URL=http://127.0.0.1:5173`
- `MAAIKE_BACKEND_URL=http://127.0.0.1:8000`
- `MAAIKE_CORS_ORIGINS=http://127.0.0.1:5173`
- `MAAIKE_WEB_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/meta/callback`

De frontend leest `VITE_API_URL` (zie `frontend/.env.example`). Gebruik overal `127.0.0.1`, niet afwisselend met `localhost`, zodat de sessiecookie meegaat.

De Streamlit-terugval start met `streamlit run app_maaike.py`. Die gebruikt een ander callback-adres: `http://127.0.0.1:8502/`.

## Huidige status

- Dashboard: zoeken, performance per maand, social vergelijking.
- Vergelijkingsdata komt uit Meta Business Discovery + lokale metingen.
- MVP blijft local-first voor zoeken in SQLite.
