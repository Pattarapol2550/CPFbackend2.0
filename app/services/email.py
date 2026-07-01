"""
app/services/email.py — Alarm email notifications via Resend.
"""

import logging
import time
from typing import Optional

import resend

from app.config import ALARM_EMAIL_FROM, ALARM_EMAIL_TO, RESEND_API_KEY

logger = logging.getLogger(__name__)

resend.api_key = RESEND_API_KEY

# throttle: compressor_id → unix timestamp of last sent email
# ป้องกันส่ง email ซ้ำถี่เกินไป (cooldown 10 นาที/compressor)
_last_sent: dict[str, float] = {}
COOLDOWN_SECONDS = 600


def _should_send(compressor_id: str) -> bool:
    last = _last_sent.get(compressor_id, 0)
    return (time.time() - last) >= COOLDOWN_SECONDS


def _mark_sent(compressor_id: str) -> None:
    _last_sent[compressor_id] = time.time()


def _build_html(compressor_id: str, alarms: list[dict], timestamp: Optional[str]) -> str:
    alarm_rows = ""
    for a in alarms:
        color = "#f85149" if a.get("severity") == "Critical" else "#e3b341"
        recs  = "".join(f"<li>{r}</li>" for r in a.get("recommendation", []))
        alarm_rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #30363d;">
            <span style="color:{color};font-weight:700;">{a.get('severity','')}</span>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #30363d;color:#e6edf3;">
            {a.get('title','')}
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #30363d;color:#8b949e;font-size:13px;">
            {a.get('message','')}<br/>
            {'<ul style="margin:6px 0 0 16px;padding:0;color:#8b949e;">' + recs + '</ul>' if recs else ''}
          </td>
        </tr>"""

    return f"""
    <div style="font-family:'Segoe UI',sans-serif;background:#0d1117;padding:32px;border-radius:12px;max-width:640px;margin:0 auto;">
      <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden;">
        <div style="background:#f85149;padding:16px 20px;">
          <h2 style="margin:0;color:#fff;font-size:18px;">🔴 CRITICAL ALARM — {compressor_id}</h2>
          <p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:13px;">{timestamp or ''}</p>
        </div>
        <div style="padding:20px;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:1px solid #30363d;">
                <th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase;">Severity</th>
                <th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase;">Alarm</th>
                <th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase;">Detail</th>
              </tr>
            </thead>
            <tbody>{alarm_rows}</tbody>
          </table>
        </div>
        <div style="padding:12px 20px;border-top:1px solid #30363d;font-size:11px;color:#8b949e;">
          CPF Refrigeration SCADA · อีเมลนี้ส่งอัตโนมัติเมื่อเกิด Critical alarm
        </div>
      </div>
    </div>"""


async def send_alarm_email(
    compressor_id: str,
    alarms: list[dict],
    admin_emails: list[str],
    timestamp: Optional[str] = None,
) -> None:
    """ส่ง alarm email — มี cooldown 10 นาทีต่อ compressor
    ถ้าตั้ง ALARM_EMAIL_TO ไว้ใน env จะใช้นั้นเลย ไม่งั้นใช้ admin emails จาก DB
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY ไม่ได้ตั้งค่า — ข้าม email notification")
        return

    to_emails = ALARM_EMAIL_TO if ALARM_EMAIL_TO else admin_emails

    if not to_emails:
        logger.warning("ไม่มี email ปลายทาง — ข้าม email notification")
        return

    critical = [a for a in alarms if a.get("severity") == "Critical"]
    if not critical:
        return

    if not _should_send(compressor_id):
        logger.debug("alarm email cooldown active for %s", compressor_id)
        return

    try:
        resend.Emails.send({
            "from":    ALARM_EMAIL_FROM,
            "to":      to_emails,
            "subject": f"🔴 CRITICAL ALARM — {compressor_id}",
            "html":    _build_html(compressor_id, critical, timestamp),
        })
        _mark_sent(compressor_id)
        logger.info("alarm email sent for %s to %s", compressor_id, to_emails)
    except Exception as e:
        logger.error("ส่ง alarm email ไม่สำเร็จ: %s", e)
