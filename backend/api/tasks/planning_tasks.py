"""
Daily planning digest — run by Celery beat.

For every active district officer with an email, builds their district's
pre-emptive refill list (same seasonal model as the /planning API) and emails it
with a supplier-ready CSV attachment, so they can forward requirements to medicine
POCs ~2 weeks ahead. WhatsApp delivery is a deferred stub.

Email is sent via SMTP read from the environment (SMTP_HOST/PORT/USER/PASSWORD/
FROM — set these in Secret Manager). When SMTP isn't configured the task still
runs and logs what it *would* have sent, so it deploys safely without secrets.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import structlog

from celery_app import celery_app
from services.planning_core import build_refill_items, refills_to_csv
from services import seasonality

log = structlog.get_logger(__name__)

HORIZON_DAYS = 14

_REFILL_SQL = """
    SELECT f.id AS fid, f.name, f.code, f.address, d.name AS district,
           ST_Y(f.location) AS lat, ST_X(f.location) AS lng,
           m.name AS item, m.category AS cat, m.unit,
           GREATEST(m.lead_time_days, 1) AS lead,
           fmr.expected_daily_demand AS edd, fmr.required_stock AS req,
           COALESCE(SUM(sb.quantity) FILTER (
               WHERE sb.expiry_date > CURRENT_DATE), 0) AS stock
    FROM facility_medicine_requirements fmr
    JOIN facilities f ON f.id = fmr.facility_id
    JOIN districts d ON d.id = f.district_id
    JOIN medicines m ON m.id = fmr.medicine_id AND m.is_active = TRUE
    LEFT JOIN stock_batches sb ON sb.facility_id = f.id AND sb.medicine_id = m.id
    WHERE f.district_id = %(did)s AND fmr.expected_daily_demand > 0
    GROUP BY f.id, f.name, f.code, f.address, d.name, f.location,
             m.name, m.category, m.unit, m.lead_time_days,
             fmr.expected_daily_demand, fmr.required_stock
    HAVING COALESCE(SUM(sb.quantity) FILTER (
               WHERE sb.expiry_date > CURRENT_DATE), 0) < fmr.required_stock * 2
"""

_HIST_SQL = """
    SELECT AVG((ds.opd_count + ds.ipd_count))
               FILTER (WHERE EXTRACT(MONTH FROM ds.time) = %(m)s) AS m_avg,
           AVG((ds.opd_count + ds.ipd_count)) AS all_avg
    FROM daily_snapshots ds
    JOIN facilities f ON f.id = ds.facility_id
    WHERE ds.time >= NOW() - INTERVAL '2 years' AND f.district_id = %(did)s
"""


def _sync_db_url() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _send_email(to_addr: str, subject: str, body: str, csv_text: str, fname: str) -> bool:
    """Send one digest email via SMTP. Returns False (and logs) when SMTP isn't
    configured or the send fails — never raises into the task loop."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        log.info("planning_digest_email_skipped_no_smtp", to=to_addr, subject=subject)
        return False
    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER", "noreply@predicare")
        msg["To"] = to_addr
        msg.set_content(body)
        msg.add_attachment(
            csv_text.encode("utf-8"), maintype="text", subtype="csv", filename=fname
        )
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=20) as s:
            if os.environ.get("SMTP_STARTTLS", "true").lower() != "false":
                s.starttls()
            user = os.environ.get("SMTP_USER")
            if user:
                s.login(user, os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        log.info("planning_digest_email_sent", to=to_addr)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("planning_digest_email_failed", to=to_addr, error=str(exc))
        return False


@celery_app.task(
    name="tasks.planning_tasks.run_daily_planning_digest",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def run_daily_planning_digest(self) -> dict:
    """Email each district officer their district's pre-emptive refill list."""
    import psycopg2
    import psycopg2.extras

    horizon = int(os.environ.get("PLANNING_HORIZON_DAYS", str(HORIZON_DAYS)))
    today = datetime.now(timezone.utc).date()
    target_month = (today + timedelta(days=horizon)).month

    try:
        conn = psycopg2.connect(_sync_db_url())
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # District officers with an email + a home district are the recipients.
        cur.execute(
            """
            SELECT DISTINCT district_id, email
            FROM users
            WHERE is_active = TRUE AND role = 'DISTRICT_OFFICER'
              AND email IS NOT NULL AND district_id IS NOT NULL
            """
        )
        recipients = cur.fetchall()

        sent = 0
        for rec in recipients:
            did = rec["district_id"]
            email = rec["email"]
            try:
                cur.execute(_HIST_SQL, {"m": target_month, "did": did})
                h = cur.fetchone()
                hist = (
                    round(float(h["m_avg"]) / float(h["all_avg"]), 3)
                    if h and h["all_avg"] and float(h["all_avg"]) > 0 and h["m_avg"] is not None
                    else 1.0
                )

                cur.execute(_REFILL_SQL, {"did": did})
                rows = cur.fetchall()

                weather = {"rain": 1.0, "heat": 1.0}
                for r in rows:
                    if r["lat"] is not None and r["lng"] is not None:
                        weather = seasonality.fetch_weather_factor(float(r["lat"]), float(r["lng"]))
                        break

                items = build_refill_items(rows, target_month, hist, weather, today, horizon)
                if not items:
                    log.info("planning_digest_no_items", district=did, to=email)
                    continue

                high = sum(1 for i in items if i["urgency"] == "HIGH")
                body = (
                    f"PrediCare pre-emptive planning digest — {today.isoformat()}\n\n"
                    f"{len(items)} facility-medicine refills needed in the next "
                    f"{horizon} days ({high} urgent). The attached CSV lists each "
                    f"facility, address, item, order quantity and deliver-by date — "
                    f"forward it to your supply POCs.\n\n"
                    f"Top items:\n"
                    + "\n".join(
                        f"  • {i['facility']} — {i['item']}: order {i['order_qty']} {i['unit']} "
                        f"by {i['deliver_by']} ({i['urgency']})"
                        for i in items[:10]
                    )
                )
                fname = f"planning_refills_{today.isoformat()}.csv"
                if _send_email(email, f"PrediCare planning — {len(items)} refills due", body,
                               refills_to_csv(items), fname):
                    sent += 1
                # WhatsApp delivery: deferred until WhatsApp Business creds are set.
            except Exception as rec_err:  # noqa: BLE001
                log.error("planning_digest_recipient_failed", district=did, error=str(rec_err))
                continue

        cur.close()
        conn.close()
        log.info("planning_digest_complete", recipients=len(recipients), sent=sent)
        return {"recipients": len(recipients), "sent": sent}
    except Exception as exc:
        log.error("planning_digest_failed", error=str(exc))
        raise self.retry(exc=exc)
