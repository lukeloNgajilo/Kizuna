# payments/gateways/base.py
from dataclasses import dataclass, field


@dataclass
class GatewayResult:
    status: str
    provider_status: str
    provider_txn_id: str | None = None
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)