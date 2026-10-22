import hmac
import logging
import uuid

from django.conf import settings
from django.db import transaction as db
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from mirai.gateways.tembo import TEMBO_FINAL_MAP, TemboClient
from mirai.models import InTransaction
from mirai.service.transaction import FINAL_STATES, mark_completed, mark_failed
from mirai.tasks import forward_webhook

logger = logging.getLogger(__name__)
S = InTransaction.Status


def _find_transaction(payload):
    ref = payload.get("transactionRef")
    if ref:
        try:
            return InTransaction.objects.filter(pk=uuid.UUID(str(ref)), gateway="tembo").first()
        except ValueError:
            pass
    provider_id = payload.get("transactionId")
    if provider_id:
        return InTransaction.objects.filter(transaction_id=provider_id, gateway="tembo").first()
    return None


class TemboCallback(APIView):
    authentication_classes = []        # Tembo has no API key; the URL token protects this
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request, token):
        # 1. Reject anything without our secret token (404 so the endpoint isn't advertised)
        if not hmac.compare_digest(token, settings.TEMBO_CALLBACK_TOKEN):
            return Response(status=404)

        payload = request.data if isinstance(request.data, dict) else {}
        logger.info("Tembo callback: %s", payload)

        # 2. Find our transaction
        txn = _find_transaction(payload)
        if not txn:
            logger.warning("Tembo callback for unknown transaction: %s", payload)
            return Response({"received": True})      # 200, so Tembo doesn't retry forever

        if txn.status in FINAL_STATES:
            return Response({"received": True})      # duplicate callback

        # 3. Work out the real status
        if settings.TEMBO_VERIFY_CALLBACKS:
            confirmed = TemboClient().check_status(txn) or {}
            code = confirmed.get("statusCode", "")
            evidence = {"callback": payload, "status_check": confirmed}
        else:
            code = payload.get("statusCode", "")
            evidence = {"callback": payload}

        if code not in TEMBO_FINAL_MAP:
            # Still pending, or unknown/unverified: leave it for the reconciliation job
            logger.info("Tembo %s not final yet (%r)", txn.id, code)
            return Response({"received": True})

        # 4. Apply it
        new_status, reason = TEMBO_FINAL_MAP[code]
        if new_status == S.COMPLETED:
            txn = mark_completed(txn.id, evidence, provider_fee=None)   # ← pass Tembo's fee field if it sends one
        else:
            txn = mark_failed(txn.id, evidence, reason=reason)

        # 5. Notify the merchant once the database change is committed
        db.on_commit(lambda: forward_webhook.delay(str(txn.id)))

        return Response({"received": True})