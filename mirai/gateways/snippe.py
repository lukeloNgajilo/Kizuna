# payments/gateways/snippe.py
from decimal import Decimal
from mirai.networks import VODACOM, TIGO, AIRTEL, HALOTEL

class SnippeClient:
    name = "snippe"
    min_amount = Decimal("100")          # ← confirm Snippe's real minimum
    channels = {                          # ← replace with Snippe's actual channel codes
        VODACOM: "...",
        TIGO: "...",
        AIRTEL: "...",
        HALOTEL: "...",
    }

    def supports(self, network, amount) -> bool:
        return network in self.channels and amount >= self.min_amount

    def collect(self, txn):
        ...