import hashlib
import hmac
import json
import logging
import time

import requests
from celery import shared_task

from mirai.models import InTransaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=6)
def forward_webhook(self, txn_id):
    txn = InTransaction.objects.select_related("merchant").get(pk=txn_id)
    merchant = txn.merchant
    url = txn.webhook or (merchant.default_webhook if merchant else "")
    if not url or not merchant:
        return "no webhook"

    body = {
        "event": f"payment.{txn.status}",
        "id": str(txn.id),
        "transaction_ref": txn.transaction_ref,
        "merchant_reference": txn.merchant_reference,
        "status": txn.status,
        "amount": str(txn.amount),
        "platform_fee": str(txn.platform_fee) if txn.platform_fee is not None else None,
        "net_amount": str(txn.net_amount) if txn.net_amount is not None else None,
        "currency": txn.currency,
        "msisdn": txn.msisdn,
        "network": txn.network,
        "failure_reason": txn.failure_reason or None,
        "completed_at": txn.completed_at.isoformat() if txn.completed_at else None,
    }
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    ts = str(int(time.time()))
    signature = hmac.new(
        merchant.webhook_secret.encode(), f"{ts}.{raw}".encode(), hashlib.sha256,
    ).hexdigest()

    try:
        resp = requests.post(
            url, data=raw, timeout=10,
            headers={
                "Content-Type": "application/json",
                "X-Kizuna-Timestamp": ts,
                "X-Kizuna-Signature": f"sha256={signature}",
            },
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"merchant returned {resp.status_code}")
    except Exception as exc:
        # retry after 1, 2, 4, 8, 16, 32 minutes
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

    return "delivered"