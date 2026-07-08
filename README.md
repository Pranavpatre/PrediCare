# PrediCare — AI District-Health Operating System

PrediCare is a live, predictive command center for India's primary health system.
It turns fragmented, backward-looking health data into **foresight and
coordination** — predicting medicine/test/bed shortages *before* they hit
patients and helping district officers act on them.

Built on real data from **52,339 health facilities** across India.

## Live apps

| App | URL | For | Login |
|-----|-----|-----|-------|
| **Admin dashboard** | https://predicare-dashboard.web.app | District / State / National officers | `9876543210` |
| **Field-worker PWA** | https://predicare-field-app.web.app | PHC/CHC field workers (offline-first) | `9876500001` |

Auth is **phone + OTP**. Dev OTP: **`000000`**. You see data for your scope: a
national admin sees all-India; a district/state officer sees their own
district/state (and can tap the 📍 badge to switch to their GPS location).

## What it does

**Admin dashboard**
- Live national → state → district → facility health map, every facility scored.
- Alerts feed (stockouts, zero-attendance, anomalies) + at-risk facility list.
- **Planning tab** — pre-emptive actionables ~2 weeks ahead: which facilities will
  run short of medicines/tests, how much to order and by when (downloadable
  supplier CSV + on-demand email), plus a **doctor-redistribution plan** (move
  surplus doctors to nearby short-staffed facilities) and bed/doctor capacity gaps.
- **AI assistant** (Gemini) — plain-language Q&A on facilities, medicines,
  doctors, tests, beds, alerts and plans, in 10 Indian languages, grounded only
  on live district data.
- State/UT bed infrastructure (real data.gov.in).

**Field-worker PWA** (offline-first)
- Daily entry: patient count, footfall tally, per-doctor attendance, bed matrix
  with a per-bed expected free-up date.
- Stock tab: medicine availability + diagnostic test availability.
- Patient referrals (create / retrieve by code or phone+OTP).
- Queues offline and syncs automatically when back online.

## Forecast & scoring modelling

- **District-customized demand model** — per-facility required stock derived from
  its own footfall: `worst-case (P95) daily footfall × per-patient usage × supplier
  lead time × safety factor`, giving dynamic reorder levels (replacing a flat
  global constant). Runs weekly.
- **Seasonal + weather-aware planning** — demand is scaled by a disease-season
  calendar (monsoon → ORS/antimalarial/fever, winter → respiratory, summer →
  heat), the district's own historical footfall seasonality, and a live weather
  blend (OpenWeather), so seasonal spikes are anticipated.
- **District-relative health scoring** — facilities are graded against their
  district peers (terciles) with absolute guardrails, plus a critical-alert
  override.

## Architecture

- **Backend** — Python 3.11, FastAPI, async SQLAlchemy, Pydantic. PostgreSQL 16 +
  PostGIS (geospatial, KNN nearest-facility), materialized views for fast reads.
  Celery + Redis for scheduled jobs (health scoring, weekly demand model, anomaly
  scan, daily planning digest).
- **AI** — Google Gemini 2.5 Flash (grounded assistant, thinking disabled for
  low latency) + speech-to-text / TTS.
- **Frontend** — React 18 + TypeScript + Vite, TailwindCSS, TanStack Query,
  Zustand, React Router, react-i18next (10 languages), Leaflet. Field app is a
  PWA (vite-plugin-pwa + Dexie/IndexedDB).
- **Infra** — Google Cloud Run (API + Celery worker/beat), Cloud SQL, Firebase
  Hosting, Artifact Registry, Secret Manager, GitHub Actions CI/CD.

## Repository layout

```
backend/api/            FastAPI app (routers, models, tasks, services)
backend/ml-models/      health-score scorer + Gemini assistant
frontend/dashboard/     Admin dashboard (React/Vite)
frontend/field-app/     Field-worker PWA (React/Vite)
data/schemas/           Numbered SQL schema files (source of truth, applied in order)
```

## Local development

```bash
# Backend + Postgres + Redis
docker compose up -d

# Dashboard
cd frontend/dashboard && npm install && npm run dev

# Field app
cd frontend/field-app && npm install && npm run dev
```

The database schema is built from `data/schemas/*.sql` (numbered, applied in
order) — this is the source of truth. CI applies them and runs the backend test
suite (pytest), lint (ruff), and frontend builds on every push.

## Deploy

- **Frontends** auto-deploy to Firebase Hosting on push to `main` touching
  `frontend/**`.
- **Backend** is built with Cloud Build and deployed to Cloud Run
  (`predicare-api`, plus `predicare-celery-worker` / `predicare-celery-beat`).
