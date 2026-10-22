# mirai/services/transactions.py
from django.db import transaction as db
from django.utils import timezone

from mirai.models import InTransaction
from mirai.service.balance import apply_to_balance
from mirai.service.fee import apply_fees

S = InTransaction.Status
T = InTransaction.Type
FINAL_STATES = {S.COMPLETED, S.FAILED, S.REVERSED}


def mark_completed(txn_id, provider_payload: dict, provider_fee=None):
    with db.atomic():
        txn = InTransaction.objects.select_for_update().get(pk=txn_id)
        if txn.status in FINAL_STATES:
            return txn

        txn.status = S.COMPLETED
        txn.completed_at = timezone.now()
        txn.provider_response = provider_payload

        if txn.type == T.COLLECTION:
            apply_fees(txn, provider_reported_fee=provider_fee)
            apply_to_balance(txn)                     # credit now
        # disbursement: already debited when it started; nothing to do

        txn.save(update_fields=[
            "status", "completed_at", "provider_response",
            "platform_fee", "net_amount", "balance_after", "updated_at",
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

        if txn.type == T.DISBURSEMENT:
            refund_disbursement(txn)                  # give the money back
    return txn


def start_disbursement(*, merchant, api_key, environment, msisdn, network, amount, narration, merchant_reference):
    """Create a disbursement and debit the balance immediately. Raises InsufficientBalance."""
    with db.atomic():
        txn = InTransaction(
            type=T.DISBURSEMENT,
            merchant=merchant, api_key=api_key, environment=environment,
            msisdn=msisdn, network=network, amount=amount,
            narration=narration, merchant_reference=merchant_reference,
            status=S.INITIATING,
        )
        apply_fees(txn)
        apply_to_balance(txn, require_funds=True)     # debit now, or refuse
        txn.save()
    return txn                                         # then call the gateway's payout API


def refund_disbursement(original):
    """Credit back a failed disbursement as its own row. Call inside atomic()."""
    if original.reversals.exists():                   # never refund twice
        return
    reversal = InTransaction(
        type=T.REVERSAL,
        related_transaction=original,
        merchant=original.merchant, api_key=original.api_key,
        environment=original.environment,
        msisdn=original.msisdn, network=original.network,
        amount=original.amount + (original.platform_fee or 0),
        narration=f"Reversal of {original.transaction_ref}",
        status=S.COMPLETED,
        completed_at=timezone.now(),
    )
    apply_to_balance(reversal)
    reversal.save()