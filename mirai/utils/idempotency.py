import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction as db
from django.utils import timezone
from rest_framework.response import Response

from mirai.models import IdempotencyRecord

STALE_AFTER = timedelta(minutes=2)


def _request_hash(request) -> str:
    body = json.dumps(request.data, sort_keys=True, default=str)
    return hashlib.sha256(f"{request.method}|{request.path}|{body}".encode()).hexdigest()


def acquire(api_key, key: str, request):
    """Returns (record, None) to proceed, or (None, Response) to return immediately."""
    req_hash = _request_hash(request)
    manager = IdempotencyRecord._base_manager      # sees every row, no filtering

    for _ in range(2):
        try:
            with db.atomic():
                record = manager.create(
                    api_key=api_key,
                    idempotency_key=key,
                    request_hash=req_hash,
                    expires_at=timezone.now() + timedelta(hours=24),
                )
            return record, None
        except IntegrityError:
            existing = manager.filter(api_key=api_key, idempotency_key=key).first()
            if existing is None:
                continue                            # deleted in between: retry once

        # Expired, or stuck in processing: reclaim it
        stale = (
            existing.status == IdempotencyRecord.Status.PROCESSING
            and existing.created_at < timezone.now() - STALE_AFTER
        )
        if existing.expires_at <= timezone.now() or stale:
            manager.filter(pk=existing.pk).delete()
            continue

        if existing.request_hash != req_hash:
            return None, Response(
                {"detail": "Idempotency-Key reused with a different request."}, status=422
            )
        if existing.status == IdempotencyRecord.Status.COMPLETED:
            return None, Response(existing.response_body, status=existing.response_status)
        return None, Response(
            {"detail": "A request with this Idempotency-Key is in progress."}, status=409
        )

    return None, Response({"detail": "Could not acquire Idempotency-Key. Retry."}, status=409)


def complete(record, status_code: int, body: dict, txn=None):
    record.status = IdempotencyRecord.Status.COMPLETED
    record.response_status = status_code
    record.response_body = body
    record.transaction = txn
    record.save(update_fields=["status", "response_status", "response_body", "transaction", "updated_at"])


def release(record):
    """Free the key after an unexpected crash so the client can retry. Always a hard delete."""
    IdempotencyRecord._base_manager.filter(pk=record.pk).delete()