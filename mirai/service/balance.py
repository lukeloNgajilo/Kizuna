# mirai/services/balance.py
from mirai.models import Merchant

FIELD = {"live": "balance_live", "test": "balance_test"}


class InsufficientBalance(Exception):
    pass


def apply_to_balance(txn, *, require_funds=False):
    """
    Apply txn.balance_effect to the merchant's balance and set txn.balance_after.
    MUST be called inside transaction.atomic(). The caller saves txn.
    """
    merchant = Merchant.objects.select_for_update().get(pk=txn.merchant_id)
    field = FIELD[txn.environment]
    current = getattr(merchant, field)
    new_balance = current + txn.balance_effect

    if require_funds and new_balance < 0:
        raise InsufficientBalance(f"Balance {current} is too low for {-txn.balance_effect}")

    setattr(merchant, field, new_balance)
    merchant.save(update_fields=[field])
    txn.balance_after = new_balance
    return new_balance