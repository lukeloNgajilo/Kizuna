from django.db import connection, transaction
from django.utils import timezone
from django.utils.timezone import localdate




def generate_transaction_ref():
    """
    Generate a unique reference:
    KZ + YYYYMMDD + 5-digit sequence.

    PostgreSQL atomically increments the daily counter,
    preventing duplicate sequence numbers under concurrency.
    """

    reference_date = localdate(timezone.now())

    with transaction.atomic():
        from mirai.models import DailyTransactionCounter
        table = connection.ops.quote_name(
            DailyTransactionCounter._meta.db_table
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {table} (reference_date, last_number)
                VALUES (%s, 1)
                ON CONFLICT (reference_date)
                DO UPDATE SET
                    last_number = {table}.last_number + 1
                RETURNING last_number
                """,
                [reference_date],
            )

            sequence_number = cursor.fetchone()[0]

    date_part = reference_date.strftime("%Y%m%d")

    return f"KZ{date_part}{sequence_number:05d}"