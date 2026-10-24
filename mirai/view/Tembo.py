# mirai/views.py
from django.db import IntegrityError, transaction as db
from rest_framework.response import Response
from rest_framework.views import APIView

from mirai.models import InTransaction
from mirai.serializers.serializer import InitiateCollectionSerializer
from mirai.utils import idempotency
from mirai.utils.auth import APIKeyAuthentication, HasScope
from mirai.utils.response import custom_response, error_custom_response

S = InTransaction.Status

FAILURE_HTTP = {
    "insufficient_funds": 402,
    "rejected": 402,
    "provider_error": 502,
    "provider_unreachable": 502,
}


def _response_for(txn):
    body = {
        "id": str(txn.id),
        "transaction_ref": txn.transaction_ref,          # yours
        "merchant_reference": txn.merchant_reference,    # theirs
        "status": txn.status,
        "amount": str(txn.amount),
        "currency": txn.currency,
        "network": txn.network,
        "failure_reason": txn.failure_reason or None,
    }
    if txn.status in (S.PENDING, S.INITIATING):
        return body, 200
    if txn.status == S.COMPLETED:
        return body, 200
    return body, FAILURE_HTTP.get(txn.failure_reason, 402)


class InitiateCollection(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasScope]
    required_scopes = ["payments:create"]

    def post(self, request):
        key = request.headers.get("Idempotency-Key")
        if not key or len(key) > 255:
            return error_custom_response(description= "Idempotency-Key header is required.")

        ser = InitiateCollectionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        api_key = request.auth
        gateway = d["gateway"]          # picked by the router in the serializer

        record, early = idempotency.acquire(api_key, key, request)
        if early:
            return early

        try:
            try:
                with db.atomic():       # keeps an IntegrityError from breaking the outer transaction
                    txn = InTransaction.objects.create(
                        merchant=api_key.merchant,
                        api_key=api_key,
                        environment=api_key.environment,
                        gateway=gateway.name,
                        msisdn=d["phone_number"],
                        network=d["network"],
                        channel=gateway.channels[d["network"]],
                        amount=d["amount"],
                        narration=d["narration"],
                        merchant_reference=d["transaction_ref"],
                        webhook=d.get("webhook", ""),
                        status=S.INITIATING,
                    )
            except IntegrityError as exc:
                if "unique_merchant_reference_per_merchant" in str(exc):
                    body = {"detail": "transaction_ref already used for this merchant."}
                    idempotency.complete(record, 409, body)
                    return Response(body, status=409)
                raise          # any other constraint: let the real error show
            # Row is committed here. Don't wrap the provider call in atomic().
            result = gateway.collect(txn)
            txn.status = result.status
            txn.provider_status = result.provider_status
            txn.transaction_id = result.provider_txn_id
            txn.failure_reason = result.failure_reason
            txn.provider_response = result.raw
            txn.save(update_fields=[
                "status", "provider_status", "transaction_id",
                "failure_reason", "provider_response", "updated_at",
            ])

            body, code = _response_for(txn)
            idempotency.complete(record, code, body, txn)
            return Response(body, status=code)

        except Exception:
            # Unexpected crash: free the key so the client can retry
            record.delete()
            raise