"""
WhatsApp Cloud API client (Meta Graph API v19.0).

Environment variables required:
  WHATSAPP_TOKEN            — permanent or temporary access token
  WHATSAPP_PHONE_NUMBER_ID  — the phone-number object ID from Meta Business Suite
  WHATSAPP_API_VERSION      — default: v19.0

All public send_* methods are best-effort: they catch httpx errors and log them
rather than raising, so a WhatsApp delivery failure never blocks a Celery task.

API reference:
  https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

_DEFAULT_API_VERSION = "v19.0"

# Per-language message templates. All send_* methods look up their template by
# the caller's `language` (falling back to "en" for unsupported codes) instead
# of always sending English regardless of the language argument.
_STOCKOUT_WITH_PLAN = {
    "en": "🚨 {severity}: {facility_name} will run out of {medicine_name} in {days} day(s). Transfer {qty} units from {donor} available. Approve?",
    "hi": "🚨 {severity}: {facility_name} में {medicine_name} {days} दिन में खत्म हो जाएगी। {donor} से {qty} यूनिट स्थानांतरण उपलब्ध है। स्वीकृत करें?",
    "mr": "🚨 {severity}: {facility_name} मध्ये {medicine_name} {days} दिवसांत संपेल. {donor} कडून {qty} युनिट्स हस्तांतरण उपलब्ध. मंजूर करायचे का?",
    "gu": "🚨 {severity}: {facility_name} માં {medicine_name} {days} દિવસમાં ખતમ થશે. {donor} માંથી {qty} યુનિટ ટ્રાન્સફર ઉપલબ્ધ. મંજૂર કરવું છે?",
    "kn": "🚨 {severity}: {facility_name} ನಲ್ಲಿ {medicine_name} {days} ದಿನಗಳಲ್ಲಿ ಮುಗಿಯುತ್ತದೆ. {donor} ನಿಂದ {qty} ಯುನಿಟ್ ವರ್ಗಾವಣೆ ಲಭ್ಯವಿದೆ. ಅನುಮೋದಿಸುವುದೇ?",
    "ta": "🚨 {severity}: {facility_name} இல் {medicine_name} {days} நாட்களில் தீர்ந்துவிடும். {donor} இலிருந்து {qty} யூனிட் மாற்றம் கிடைக்கிறது. அங்கீகரிக்கவா?",
    "ml": "🚨 {severity}: {facility_name} ൽ {medicine_name} {days} ദിവസത്തിനുള്ളിൽ തീരും. {donor} ൽ നിന്ന് {qty} യൂണിറ്റ് ട്രാൻസ്ഫർ ലഭ്യമാണ്. അംഗീകരിക്കണോ?",
}

_STOCKOUT_NO_PLAN = {
    "en": "🚨 {severity}: {facility_name} — {medicine_name} runs out in {days} day(s). No surplus facility nearby. Escalate procurement.",
    "hi": "🚨 {severity}: {facility_name} — {medicine_name} {days} दिन में खत्म हो जाएगी। पास में कोई अतिरिक्त स्टॉक नहीं। खरीद प्रक्रिया तेज़ करें।",
    "mr": "🚨 {severity}: {facility_name} — {medicine_name} {days} दिवसांत संपेल. जवळपास अतिरिक्त साठा नाही. खरेदी प्रक्रिया वेगवान करा.",
    "gu": "🚨 {severity}: {facility_name} — {medicine_name} {days} દિવસમાં ખતમ થશે. નજીકમાં વધારાનો સ્ટોક નથી. ખરીદી પ્રક્રિયા ઝડપી કરો.",
    "kn": "🚨 {severity}: {facility_name} — {medicine_name} {days} ದಿನಗಳಲ್ಲಿ ಮುಗಿಯುತ್ತದೆ. ಹತ್ತಿರ ಹೆಚ್ಚುವರಿ ಸ್ಟಾಕ್ ಇಲ್ಲ. ಖರೀದಿ ಪ್ರಕ್ರಿಯೆ ತ್ವರಿತಗೊಳಿಸಿ.",
    "ta": "🚨 {severity}: {facility_name} — {medicine_name} {days} நாட்களில் தீர்ந்துவிடும். அருகில் உபரி இருப்பு இல்லை. கொள்முதலை விரைவுபடுத்தவும்.",
    "ml": "🚨 {severity}: {facility_name} — {medicine_name} {days} ദിവസത്തിനുള്ളിൽ തീരും. സമീപം അധിക സ്റ്റോക്ക് ഇല്ല. സംഭരണം വേഗത്തിലാക്കുക.",
}

_DISPATCH_INSTRUCTION = {
    "en": "📦 Action required: Please dispatch {qty} unit(s) of {medicine_name} to {destination}. Confirm dispatch by replying DISPATCHED.",
    "hi": "📦 कार्रवाई आवश्यक: कृपया {medicine_name} की {qty} इकाइयाँ {destination} भेजें। भेजने की पुष्टि के लिए DISPATCHED लिखें।",
    "mr": "📦 कारवाई आवश्यक: कृपया {medicine_name} च्या {qty} युनिट्स {destination} येथे पाठवा. पाठवल्याची पुष्टी करण्यासाठी DISPATCHED लिहा.",
    "gu": "📦 પગલાં જરૂરી: કૃપા કરીને {medicine_name} ના {qty} યુનિટ {destination} પર મોકલો. મોકલ્યાની પુષ્ટિ માટે DISPATCHED લખો.",
    "kn": "📦 ಕ್ರಮ ಅಗತ್ಯ: ದಯವಿಟ್ಟು {medicine_name} ನ {qty} ಯುನಿಟ್‌ಗಳನ್ನು {destination} ಗೆ ಕಳುಹಿಸಿ. ಕಳುಹಿಸಿದ್ದನ್ನು ಖಚಿತಪಡಿಸಲು DISPATCHED ಎಂದು ಉತ್ತರಿಸಿ.",
    "ta": "📦 நடவடிக்கை தேவை: {medicine_name} இன் {qty} யூனிட்களை {destination} க்கு அனுப்பவும். அனுப்பியதை உறுதிசெய்ய DISPATCHED என பதிலளிக்கவும்.",
    "ml": "📦 നടപടി ആവശ്യമാണ്: {medicine_name} ന്റെ {qty} യൂണിറ്റ് {destination} ലേക്ക് അയക്കുക. അയച്ചത് സ്ഥിരീകരിക്കാൻ DISPATCHED എന്ന് മറുപടി നൽകുക.",
}

_INCOMING_TRANSFER = {
    "en": "🚚 {qty} unit(s) of {medicine_name} dispatched from {source}. Expected within 24 hours. Reply RECEIVED once stock arrives.",
    "hi": "🚚 {source} से {medicine_name} की {qty} इकाइयाँ भेजी गईं। 24 घंटे में पहुँचने की उम्मीद है। स्टॉक मिलने पर RECEIVED लिखें।",
    "mr": "🚚 {source} कडून {medicine_name} च्या {qty} युनिट्स पाठवल्या. 24 तासांत पोहोचण्याची अपेक्षा आहे. साठा मिळाल्यावर RECEIVED लिहा.",
    "gu": "🚚 {source} માંથી {medicine_name} ના {qty} યુનિટ મોકલાયા. 24 કલાકમાં પહોંચવાની અપેક્ષા છે. સ્ટોક મળે ત્યારે RECEIVED લખો.",
    "kn": "🚚 {source} ನಿಂದ {medicine_name} ನ {qty} ಯುನಿಟ್‌ಗಳನ್ನು ಕಳುಹಿಸಲಾಗಿದೆ. 24 ಗಂಟೆಗಳಲ್ಲಿ ತಲುಪುವ ನಿರೀಕ್ಷೆ. ಸ್ಟಾಕ್ ಬಂದಾಗ RECEIVED ಎಂದು ಉತ್ತರಿಸಿ.",
    "ta": "🚚 {source} இலிருந்து {medicine_name} இன் {qty} யூனிட்கள் அனுப்பப்பட்டன. 24 மணி நேரத்தில் வர எதிர்பார்க்கப்படுகிறது. இருப்பு வந்ததும் RECEIVED எனப் பதிலளிக்கவும்.",
    "ml": "🚚 {source} ൽ നിന്ന് {medicine_name} ന്റെ {qty} യൂണിറ്റ് അയച്ചു. 24 മണിക്കൂറിനുള്ളിൽ എത്തുമെന്ന് പ്രതീക്ഷിക്കുന്നു. സ്റ്റോക്ക് എത്തിയാൽ RECEIVED എന്ന് മറുപടി നൽകുക.",
}

_MORNING_GREETING = {
    "en": "🌅 Good morning, {name}!", "hi": "🌅 सुप्रभात, {name}!", "mr": "🌅 सुप्रभात, {name}!",
    "gu": "🌅 સુપ્રભાત, {name}!", "kn": "🌅 ಶುಭೋದಯ, {name}!", "ta": "🌅 காலை வணக்கம், {name}!",
    "ml": "🌅 സുപ്രഭാതം, {name}!",
}
_MORNING_SUMMARY = {
    "en": "District Health Summary — today:", "hi": "जिला स्वास्थ्य सारांश — आज:", "mr": "जिल्हा आरोग्य सारांश — आज:",
    "gu": "જિલ્લા આરોગ્ય સારાંશ — આજે:", "kn": "ಜಿಲ್ಲಾ ಆರೋಗ್ಯ ಸಾರಾಂಶ — ಇಂದು:", "ta": "மாவட்ட சுகாதார சுருக்கம் — இன்று:",
    "ml": "ജില്ലാ ആരോഗ്യ സംഗ്രഹം — ഇന്ന്:",
}
_MORNING_OPEN_ALERTS = {
    "en": "Open alerts", "hi": "खुले अलर्ट", "mr": "उघडे अलर्ट", "gu": "ખુલ્લી ચેતવણીઓ",
    "kn": "ತೆರೆದ ಎಚ್ಚರಿಕೆಗಳು", "ta": "திறந்த எச்சரிக்கைகள்", "ml": "തുറന്ന അലേർട്ടുകൾ",
}
_MORNING_AVG_SCORE = {
    "en": "Avg district score", "hi": "औसत जिला स्कोर", "mr": "सरासरी जिल्हा गुण", "gu": "સરેરાશ જિલ્લા સ્કોર",
    "kn": "ಸರಾಸರಿ ಜಿಲ್ಲಾ ಸ್ಕೋರ್", "ta": "சராசரி மாவட்ட மதிப்பெண்", "ml": "ശരാശരി ജില്ലാ സ്കോർ",
}
_MORNING_ATTENTION = {
    "en": "Facilities needing attention:", "hi": "ध्यान देने योग्य केंद्र:", "mr": "लक्ष देण्याची गरज असलेली केंद्रे:",
    "gu": "ધ્યાન આપવાની જરૂર હોય તેવા કેન્દ્રો:", "kn": "ಗಮನ ಬೇಕಾದ ಕೇಂದ್ರಗಳು:", "ta": "கவனம் தேவைப்படும் மையங்கள்:",
    "ml": "ശ്രദ്ധ ആവശ്യമുള്ള കേന്ദ്രങ്ങൾ:",
}
_MORNING_HELP = {
    "en": "Reply HELP to see available commands.", "hi": "उपलब्ध कमांड देखने के लिए HELP लिखें।",
    "mr": "उपलब्ध कमांड पाहण्यासाठी HELP लिहा.", "gu": "ઉપલબ્ધ કમાન્ડ જોવા માટે HELP લખો.",
    "kn": "ಲಭ್ಯವಿರುವ ಆದೇಶಗಳನ್ನು ನೋಡಲು HELP ಎಂದು ಉತ್ತರಿಸಿ.", "ta": "கிடைக்கும் கட்டளைகளைப் பார்க்க HELP எனப் பதிலளிக்கவும்.",
    "ml": "ലഭ്യമായ കമാൻഡുകൾ കാണാൻ HELP എന്ന് മറുപടി നൽകുക.",
}


def _tpl(table: dict[str, str], language: str) -> str:
    return table.get(language, table["en"])


# ---------------------------------------------------------------------------
# Pure render_* helpers — build the same localized text the send_* methods
# transmit, so callers that also need to persist an in-app notification
# record (see routers/notifications.py) store the actual localized message
# rather than a separate hardcoded English placeholder.
# ---------------------------------------------------------------------------

def render_stockout_alert_with_plan(
    *, facility_name: str, medicine_name: str, days_until_stockout: int,
    severity: str, donor_facility_name: str, transfer_quantity: int, language: str = "en",
) -> str:
    return _tpl(_STOCKOUT_WITH_PLAN, language).format(
        severity=severity, facility_name=facility_name, medicine_name=medicine_name,
        days=days_until_stockout, qty=transfer_quantity, donor=donor_facility_name,
    )


def render_stockout_alert_no_plan(
    *, facility_name: str, medicine_name: str, days_until_stockout: int,
    severity: str, language: str = "en",
) -> str:
    return _tpl(_STOCKOUT_NO_PLAN, language).format(
        severity=severity, facility_name=facility_name, medicine_name=medicine_name,
        days=days_until_stockout,
    )


def render_dispatch_instruction(
    *, medicine_name: str, quantity: int, destination_name: str, language: str = "en",
) -> str:
    return _tpl(_DISPATCH_INSTRUCTION, language).format(
        qty=quantity, medicine_name=medicine_name, destination=destination_name,
    )


def render_incoming_transfer_notification(
    *, medicine_name: str, quantity: int, source_name: str, language: str = "en",
) -> str:
    return _tpl(_INCOMING_TRANSFER, language).format(
        qty=quantity, medicine_name=medicine_name, source=source_name,
    )


def render_morning_digest(
    *, officer_name: str, pending_alerts: int, avg_district_score: float,
    bottom_facilities: list[tuple[str, float, str]], language: str = "en",
) -> str:
    status_emoji = {"GREEN": "\U0001f7e2", "YELLOW": "\U0001f7e1", "RED": "\U0001f534"}
    lines: list[str] = [
        _tpl(_MORNING_GREETING, language).format(name=officer_name),
        _tpl(_MORNING_SUMMARY, language),
        f"  • {_tpl(_MORNING_OPEN_ALERTS, language)}: {pending_alerts}",
        f"  • {_tpl(_MORNING_AVG_SCORE, language)}: {avg_district_score:.1f}/100",
    ]
    if bottom_facilities:
        lines.append(f"\n{_tpl(_MORNING_ATTENTION, language)}")
        for fname, score, fstatus in bottom_facilities:
            emoji = status_emoji.get(fstatus, "⚪")
            lines.append(f"  {emoji} {fname}: {score:.1f}")
    lines.append(f"\n{_tpl(_MORNING_HELP, language)}")
    return "\n".join(lines)


class WhatsAppClient:
    """
    Thin wrapper around the Meta WhatsApp Cloud API /messages endpoint.

    Usage::

        client = WhatsAppClient()
        client.send_stockout_alert_with_plan(
            phone="+919876543210",
            facility_name="PHC Shirur",
            medicine_name="Paracetamol 500mg",
            days_until_stockout=2,
            severity="CRITICAL",
            donor_facility_name="CHC Daund",
            transfer_quantity=500,
            plan_id="abc-123",
            language="hi",
        )
    """

    def __init__(self) -> None:
        self._token: str = os.environ.get("WHATSAPP_TOKEN", "")
        self._phone_number_id: str = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self._api_version: str = os.environ.get(
            "WHATSAPP_API_VERSION", _DEFAULT_API_VERSION
        )

        if not self._token:
            log.warning("whatsapp_token_missing")
        if not self._phone_number_id:
            log.warning("whatsapp_phone_number_id_missing")

        self._base_url: str = (
            f"https://graph.facebook.com/{self._api_version}"
            f"/{self._phone_number_id}/messages"
        )
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # -------------------------------------------------------------------------
    # Public send methods
    # -------------------------------------------------------------------------

    def send_stockout_alert_with_plan(
        self,
        *,
        phone: str,
        facility_name: str,
        medicine_name: str,
        days_until_stockout: int,
        severity: str,
        donor_facility_name: str,
        transfer_quantity: int,
        plan_id: str,
        language: str = "en",
    ) -> None:
        """
        Send an interactive WhatsApp message with two quick-reply buttons:
          - ✅ Approve Transfer  (id: APPROVE_{plan_id})
          - ⏸ Defer for now     (id: DEFER_{plan_id}_later)

        Body text is in English. TODO: pipe through Gemini translation API for
        other BCP-47 language codes (hi, mr, ta, te, kn, bn, gu, or).

        Args:
            phone:                Recipient E.164 phone number, e.g. "+919876543210".
            facility_name:        Name of the facility running out of stock.
            medicine_name:        Name of the medicine at risk.
            days_until_stockout:  Days remaining before stockout.
            severity:             Alert severity label (CRITICAL | WARNING | INFO).
            donor_facility_name:  Facility that has surplus stock.
            transfer_quantity:    Units proposed for transfer.
            plan_id:              UUID of the redistribution plan.
            language:             BCP-47 language preference (default "en").
        """
        body_text = render_stockout_alert_with_plan(
            facility_name=facility_name, medicine_name=medicine_name,
            days_until_stockout=days_until_stockout, severity=severity,
            donor_facility_name=donor_facility_name, transfer_quantity=transfer_quantity,
            language=language,
        )

        # Button titles are capped at 20 chars by the WhatsApp API.
        buttons: list[dict[str, Any]] = [
            {
                "type": "reply",
                "reply": {
                    "id": f"APPROVE_{plan_id}",
                    "title": "✅ Approve Transfer",
                },
            },
            {
                "type": "reply",
                "reply": {
                    "id": f"DEFER_{plan_id}_later",
                    "title": "⏸ Defer for now",
                },
            },
        ]

        self._send_interactive(
            phone=phone,
            body_text=body_text,
            buttons=buttons,
        )

    def send_stockout_alert_no_plan(
        self,
        *,
        phone: str,
        facility_name: str,
        medicine_name: str,
        days_until_stockout: int,
        severity: str,
        language: str = "en",
    ) -> None:
        """
        Send a plain-text stockout alert when no redistribution plan exists.

        Args:
            phone:                Recipient E.164 phone number.
            facility_name:        Name of the at-risk facility.
            medicine_name:        Name of the medicine at risk.
            days_until_stockout:  Days remaining before stockout.
            severity:             Alert severity label.
            language:             BCP-47 language preference (default "en").
        """
        body = render_stockout_alert_no_plan(
            facility_name=facility_name, medicine_name=medicine_name,
            days_until_stockout=days_until_stockout, severity=severity, language=language,
        )
        self._send_text(phone=phone, body=body)

    def send_morning_digest(
        self,
        *,
        phone: str,
        officer_name: str,
        pending_alerts: int,
        avg_district_score: float,
        bottom_facilities: list[tuple[str, float, str]],
        language: str = "en",
    ) -> None:
        """
        Send a daily morning digest to a district officer.

        Args:
            phone:               Recipient E.164 phone number.
            officer_name:        Officer's display name (for greeting).
            pending_alerts:      Count of OPEN alerts in the district.
            avg_district_score:  Average health score across all facilities (0–100).
            bottom_facilities:   Up to 3 tuples of (facility_name, score, status).
            language:            BCP-47 language preference (default "en").
        """
        body = render_morning_digest(
            officer_name=officer_name, pending_alerts=pending_alerts,
            avg_district_score=avg_district_score, bottom_facilities=bottom_facilities,
            language=language,
        )
        self._send_text(phone=phone, body=body)

    def send_dispatch_instruction(
        self,
        *,
        phone: str,
        medicine_name: str,
        quantity: int,
        destination_name: str,
        language: str = "en",
    ) -> None:
        """
        Notify a donor facility worker to dispatch medicines.

        Args:
            phone:            Recipient E.164 phone number.
            medicine_name:    Medicine to dispatch.
            quantity:         Number of units to send.
            destination_name: Receiving facility name.
            language:         BCP-47 language preference (default "en").
        """
        body = render_dispatch_instruction(
            medicine_name=medicine_name, quantity=quantity,
            destination_name=destination_name, language=language,
        )
        self._send_text(phone=phone, body=body)

    def send_incoming_transfer_notification(
        self,
        *,
        phone: str,
        medicine_name: str,
        quantity: int,
        source_name: str,
        language: str = "en",
    ) -> None:
        """
        Notify a receiving facility worker that stock is on its way.

        Args:
            phone:         Recipient E.164 phone number.
            medicine_name: Medicine being transferred.
            quantity:      Number of units dispatched.
            source_name:   Sending facility name.
            language:      BCP-47 language preference (default "en").
        """
        body = render_incoming_transfer_notification(
            medicine_name=medicine_name, quantity=quantity,
            source_name=source_name, language=language,
        )
        self._send_text(phone=phone, body=body)

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _send_text(self, phone: str, body: str) -> None:
        """
        Send a plain-text WhatsApp message.

        Args:
            phone: E.164 phone number of the recipient.
            body:  Message content (max ~4096 chars).
        """
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _normalise_phone(phone),
            "type": "text",
            "text": {
                "preview_url": False,
                "body": body,
            },
        }
        self._post(payload)

    def _send_interactive(
        self,
        phone: str,
        body_text: str,
        buttons: list[dict[str, Any]],
    ) -> None:
        """
        Send an interactive WhatsApp message with quick-reply buttons.

        The Cloud API supports up to 3 buttons per message.

        Args:
            phone:      E.164 phone number of the recipient.
            body_text:  Body copy shown above the buttons (max ~1024 chars).
            buttons:    List of button objects in Cloud API format:
                        [{"type": "reply", "reply": {"id": "...", "title": "..."}}]
        """
        if len(buttons) > 3:
            log.warning(
                "whatsapp_too_many_buttons",
                count=len(buttons),
                phone=phone,
            )
            buttons = buttons[:3]

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _normalise_phone(phone),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": buttons},
            },
        }
        self._post(payload)

    def _post(self, payload: dict[str, Any]) -> None:
        """
        Execute an HTTP POST to the WhatsApp Cloud API messages endpoint.

        Errors are logged and swallowed — notifications are best-effort.
        The caller is responsible for retry logic via Celery task retries.
        """
        if not self._token or not self._phone_number_id:
            log.error(
                "whatsapp_config_incomplete",
                has_token=bool(self._token),
                has_phone_number_id=bool(self._phone_number_id),
            )
            return

        try:
            response = httpx.post(
                self._base_url,
                headers=self._headers,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            log.info(
                "whatsapp_message_sent",
                to=payload.get("to"),
                message_id=data.get("messages", [{}])[0].get("id"),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "whatsapp_http_status_error",
                status_code=exc.response.status_code,
                response_text=exc.response.text[:500],
                to=payload.get("to"),
            )
        except httpx.TimeoutException:
            log.error("whatsapp_timeout", to=payload.get("to"))
        except httpx.HTTPError as exc:
            log.error(
                "whatsapp_http_error",
                error=str(exc),
                to=payload.get("to"),
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _normalise_phone(phone: str) -> str:
    """
    Strip spaces and dashes; ensure the number starts with '+' for E.164.

    The WhatsApp Cloud API accepts E.164 without the leading '+' as well,
    but we keep it for consistency with the users table.
    """
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned
