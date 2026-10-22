# mirai/gateways/tembo.py
import logging
import uuid
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

from mirai.models import InTransaction
from mirai.networks import TIGO, AIRTEL, HALOTEL
from .base import GatewayResult

logger = logging.getLogger(__name__)
S = InTransaction.Status


# Statuses Tembo returns when you START a collection
TEMBO_STATUS_MAP = {
    "PENDING_ACK":          (S.PENDING, ""),
    "INSUFFICIENT_FUNDS":   (S.FAILED, "insufficient_funds"),
    "INSUFFICIENT_BALANCE": (S.FAILED, "insufficient_funds"),
    "PAYMENT_REJECTED":     (S.FAILED, "rejected"),
    "THIRDPARTY_FAILED":    (S.FAILED, "provider_error"),
    "GENERIC_ERROR":        (S.FAILED, "provider_error"),
}

# NEW: final statuses Tembo reports in the callback / status check
TEMBO_FINAL_MAP = {
    "PAYMENT_ACCEPTED":     (S.COMPLETED, ""),
    "PAYMENT_REJECTED":     (S.FAILED, "rejected"),
    "INSUFFICIENT_FUNDS":   (S.FAILED, "insufficient_funds"),
    "INSUFFICIENT_BALANCE": (S.FAILED, "insufficient_funds"),
    "THIRDPARTY_FAILED":    (S.FAILED, "provider_error"),
    "GENERIC_ERROR":        (S.FAILED, "provider_error"),
}


class TemboClient:
    name = "tembo"
    min_amount = Decimal("1000")
    channels = {
        TIGO: "TZ-TIGO-C2B",
        AIRTEL: "TZ-AIRTEL-C2B",
        HALOTEL: "TZ-HALOTEL-C2B",
    }

    def supports(self, network: str, amount: Decimal) -> bool:
        return network in self.channels and amount >= self.min_amount

    # NEW: shared headers for every Tembo call
    def _headers(self, request_id=None):
        return {
            "x-account-id": settings.TEMBO_ACCOUNT_ID,
            "x-secret-key": settings.TEMBO_SECRET_KEY,
            "x-request-id": request_id or str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    def collect(self, txn: InTransaction) -> GatewayResult:
        payload = {
            "msisdn": txn.msisdn,
            "channel": self.channels[txn.network],
            "amount": int(txn.amount),          # confirm the type Tembo expects
            "narration": txn.narration,
            "transactionRef": str(txn.id),
            "transactionDate": timezone.localtime(txn.transaction_date).strftime("%Y-%m-%d %H:%M:%S"),
            "callbackUrl": settings.TEMBO_CALLBACK_URL,
        }

        try:
            resp = requests.post(
                settings.TEMBO_COLLECTION_URL,
                json=payload,
                headers=self._headers(request_id=str(txn.id)),   # stable per transaction
                timeout=(5, 20),
            )
        except requests.ConnectTimeout:
            # Never reached Tembo → safe to fail
            return GatewayResult(S.FAILED, "CONNECT_TIMEOUT", failure_reason="provider_unreachable")
        except requests.RequestException as exc:
            # May have reached Tembo → outcome unknown, reconcile later
            logger.warning("Tembo no response for %s: %s", txn.id, exc)
            return GatewayResult(S.PENDING, "NO_RESPONSE")

        try:
            data = resp.json()
        except ValueError:
            logger.error("Tembo non-JSON (%s) for %s", resp.status_code, txn.id)
            data = {"body": resp.text[:1000]}

        code = data.get("statusCode", "")

        if code in TEMBO_STATUS_MAP:
            status, reason = TEMBO_STATUS_MAP[code]
            return GatewayResult(status, code, data.get("transactionId"), reason, data)

        # Unknown or missing statusCode: decide by HTTP status
        if 400 <= resp.status_code < 500:
            # Tembo rejected the request without processing it (bad auth, bad payload)
            logger.error("Tembo %s rejected %s: %s", resp.status_code, txn.id, data)
            return GatewayResult(S.FAILED, code or f"HTTP_{resp.status_code}",
                                 failure_reason="provider_error", raw=data)

        # 5xx or an unrecognised code on 2xx: outcome unknown, reconcile later
        logger.error("Unclear Tembo response %s %r for %s", resp.status_code, code, txn.id)
        return GatewayResult(S.PENDING, code or f"HTTP_{resp.status_code}", raw=data)

    # NEW: ask Tembo for the real status (used by the callback and reconciliation)
    def check_status(self, txn: InTransaction) -> dict | None:
        payload = {                                  # ← confirm field names with Tembo's docs
            "transactionRef": str(txn.id),
            "transactionId": txn.transaction_id,
        }
        try:
            resp = requests.post(
                settings.TEMBO_COLLECTION_STATUS_URL,
                json=payload,
                headers=self._headers(),
                timeout=(5, 15),
            )
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Tembo status check failed for %s: %s", txn.id, exc)
            return None