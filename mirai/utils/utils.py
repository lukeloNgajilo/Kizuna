# payments/utils.py
import re

from rest_framework_simplejwt.exceptions import AuthenticationFailed

NETWORK_CHANNELS = {
    "61": "TZ-HALOTEL-C2B", "62": "TZ-HALOTEL-C2B",
    "65": "TZ-TIGO-C2B", "67": "TZ-TIGO-C2B", "71": "TZ-TIGO-C2B", "77": "TZ-TIGO-C2B",
    "68": "TZ-AIRTEL-C2B", "69": "TZ-AIRTEL-C2B", "78": "TZ-AIRTEL-C2B",
}

def normalize_msisdn(raw: str) -> str | None:
    """Accepts +255712..., 255712..., 0712..., 712... → 255712345678"""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    elif len(digits) == 9:
        digits = "255" + digits
    return digits if re.fullmatch(r"255[67]\d{8}", digits) else None

def detect_channel(msisdn: str) -> str | None:
    return NETWORK_CHANNELS.get(msisdn[3:5])


