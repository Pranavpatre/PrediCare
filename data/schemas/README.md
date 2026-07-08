# Database schema — source of truth

The PrediCare database schema is managed as **ordered, idempotent-ish SQL files
in this directory**, applied in numeric order. This is what the app is actually
deployed with (Cloud SQL / local) and what CI builds the test database from.

| File | Purpose |
|------|---------|
| `001_core.sql` | Core tables, enums, extensions (PostGIS, TimescaleDB-guarded), hypertables |
| `002_seed_demo.sql` | Demo seed data (Pune district) — **seed, not schema** |
| `003_state_infrastructure.sql` | State/UT bed-capacity reference tables |
| `004_staff_attendance.sql` | Geofenced attendance |
| `005_district_footfall.sql` | District footfall metrics |
| `006_beds_and_tests.sql` | Bed matrix + diagnostic test availability |
| `007_district_hmis_metrics.sql` | District HMIS metrics |
| `008_latest_score_matviews.sql` | `mv_facility_latest_score` / `mv_facility_latest_snapshot` read-path matviews |
| `009_referrals_and_abdm.sql` | Referral tables (patients/referrals/access-log/visit-notes) + ABDM columns |

## Applying

```bash
# structural schema (skip 002 seed)
for f in 001_core 003_state_infrastructure 004_staff_attendance \
         005_district_footfall 006_beds_and_tests \
         007_district_hmis_metrics 008_latest_score_matviews \
         009_referrals_and_abdm; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "data/schemas/$f.sql"
done
# demo seed (optional)
psql "$DATABASE_URL" -f data/schemas/002_seed_demo.sql
```

The matviews (`008`) are refreshed by the Celery task
`tasks.scoring_tasks.run_health_scores` (every 6h), which also self-heals them
via `CREATE MATERIALIZED VIEW IF NOT EXISTS`.

> **Note:** Alembic was removed — its `0001` migration had diverged from these
> SQL files and never ran cleanly. These SQL files are the single source of
> truth. Add a new numbered `NNN_*.sql` file for each schema change.
