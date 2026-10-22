from django.conf import settings

from mirai.gateways.snippe import SnippeClient
from mirai.gateways.tembo import TemboClient

GATEWAYS = {
    "tembo": TemboClient(),
    "snippe": SnippeClient(),
}

# Order = preference: try Tembo first, fall back to Snippe
GATEWAY_PRIORITY = getattr(settings, "COLLECTION_GATEWAY_PRIORITY", ["tembo", "snippe"])


def pick_gateway(network, amount):
    for name in GATEWAY_PRIORITY:
        gw = GATEWAYS[name]
        if gw.supports(network, amount):
            return gw
    return None