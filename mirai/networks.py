# payments/networks.py
import re

VODACOM, TIGO, AIRTEL, HALOTEL = "vodacom", "tigo", "airtel", "halotel"

PREFIX_TO_NETWORK = {
    "74": VODACOM, "75": VODACOM, "76": VODACOM,
    "65": TIGO, "67": TIGO, "71": TIGO, "77": TIGO,
    "68": AIRTEL, "69": AIRTEL, "78": AIRTEL,
    "61": HALOTEL, "62": HALOTEL,
}

def normalize_msisdn(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    elif len(digits) == 9:
        digits = "255" + digits
    return digits if re.fullmatch(r"255[67]\d{8}", digits) else None

def detect_network(msisdn: str) -> str | None:
    return PREFIX_TO_NETWORK.get(msisdn[3:5])