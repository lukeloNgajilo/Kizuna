# mirai/services/fees.py
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Q

from mirai.models import FeePlan

# What each provider charges YOU, as a percent. Fill in from your contracts.
PROVIDER_RATES = getattr(settings, "PROVIDER_FEE_PERCENT", {
    "tembo": Decimal("0.00"),
    "snippe": Decimal("0.00"),
})


def _tzs(value) -> Decimal:
    """TZS has no cents in mobile money: round to whole shillings."""
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def find_fee_plan(merchant, network):
    """Most specific plan wins: merchant+network > merchant > default+network > default."""
    plans = FeePlan.objects.filter(
        Q(merchant=merchant) | Q(merchant__isnull=True),
        Q(network=network) | Q(network=""),
        is_active=True,
    )

    def rank(p):
        return (p.merchant_id is not None, p.network != "")

    return max(plans, key=rank, default=None)


def platform_fee_for(merchant, network, amount: Decimal) -> Decimal:
    plan = find_fee_plan(merchant, network)
    if not plan:
        return Decimal("0")
    fee = amount * plan.percent / Decimal("100") + plan.fixed
    fee = max(fee, plan.minimum)
    if plan.maximum is not None:
        fee = min(fee, plan.maximum)
    return _tzs(min(fee, amount))          # never charge more than the payment


def provider_fee_for(gateway, amount: Decimal, reported=None) -> Decimal:
    if reported not in (None, ""):
        return _tzs(reported)              # trust the provider's own figure when given
    rate = PROVIDER_RATES.get(gateway, Decimal("0"))
    return _tzs(amount * rate / Decimal("100"))


def apply_fees(txn, provider_reported_fee=None):
    """Call once, when txn moves to COMPLETED. Sets the fields; the caller saves."""
    txn.provider_fee = provider_fee_for(txn.gateway, txn.amount, provider_reported_fee)
    txn.platform_fee = platform_fee_for(txn.merchant, txn.network, txn.amount)
    txn.net_amount = txn.amount - txn.platform_fee