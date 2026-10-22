from django.db import transaction as db
from django.utils import timezone

from mirai.models import InTransaction
from mirai.service.fee import apply_fees

S = InTransaction.Status
FINAL_STATES = {S.COMPLETED, S.FAILED, S.REVERSED}


def mark_completed(txn_id, provider_payload: dict, provider_fee=None):
    with db.atomic():
        txn = InTransaction.objects.select_for_update().get(pk=txn_id)

        if txn.status in FINAL_STATES:         # callbacks can arrive twice: do nothing
            return txn

        txn.status = S.COMPLETED
        txn.completed_at = timezone.now()
        txn.provider_response = provider_payload
        apply_fees(txn, provider_reported_fee=provider_fee)
        txn.save(update_fields=[
            "status", "completed_at", "provider_response",
            "provider_fee", "platform_fee", "net_amount", "updated_at",
        ])
    return txn


def mark_failed(txn_id, provider_payload: dict, reason: str = "provider_error"):
    with db.atomic():
        txn = InTransaction.objects.select_for_update().get(pk=txn_id)

        if txn.status in FINAL_STATES:
            return txn

        txn.status = S.FAILED
        txn.failure_reason = reason
        txn.provider_response = provider_payload
        txn.save(update_fields=["status", "failure_reason", "provider_response", "updated_at"])
    return txn