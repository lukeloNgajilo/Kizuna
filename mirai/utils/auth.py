# mirai/utils/auth.py
import hmac
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from mirai.models import APIKey


class APIKeyPrincipal:
    """Stands in for request.user on API-key requests."""
    is_authenticated = True
    is_anonymous = False

    def __init__(self, api_key):
        self.api_key = api_key
        self.merchant = api_key.merchant

    @property
    def pk(self):
        # UserRateThrottle reads request.user.pk
        return f"apikey:{self.api_key.id}"

    def __str__(self):
        return f"apikey:{self.api_key.prefix}"


class APIKeyAuthentication(BaseAuthentication):
    """
    Reads the payment key from either header:
      X-Payment-Key: sk_test_...
      Authorization: Bearer sk_test_...
    """

    def _get_raw_key(self, request):
        key = request.META.get("HTTP_X_PAYMENT_KEY", "").strip()
        if key:
            return key
        auth = request.META.get("HTTP_AUTHORIZATION", "").strip()
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return ""

    def authenticate(self, request):
        raw = self._get_raw_key(request)

        if not raw:
            raise AuthenticationFailed("No payment key sent. Use header X-Payment-Key: sk_test_...")
        if not raw.startswith("sk_"):
            raise AuthenticationFailed("That is not a payment key (got a login token?). Use the sk_test_... key.")

        try:
            _, env, prefix, secret = raw.split("_", 3)
        except ValueError:
            raise AuthenticationFailed("Malformed payment key.")

        try:
            key = APIKey.objects.select_related("merchant").get(prefix=prefix)
        except APIKey.DoesNotExist:
            raise AuthenticationFailed("Payment key not found. Copy the whole key again.")

        if not hmac.compare_digest(APIKey.hash_secret(secret), key.hashed_key):
            raise AuthenticationFailed("Payment key is wrong.")
        if key.environment != env:
            raise AuthenticationFailed("Key environment mismatch.")
        if not key.is_active:
            raise AuthenticationFailed("Payment key revoked or expired.")

        if not key.merchant:
            raise AuthenticationFailed("This key is not linked to a merchant.")
        if not key.merchant.is_active:
            raise AuthenticationFailed("Merchant account is disabled.")

        if key.allowed_ips and request.META.get("REMOTE_ADDR") not in key.allowed_ips:
            raise AuthenticationFailed("Your IP is not allowed for this key.")

        # Record usage at most every 5 minutes
        if not key.last_used_at or key.last_used_at < timezone.now() - timedelta(minutes=5):
            APIKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())

        return APIKeyPrincipal(key), key

    def authenticate_header(self, request):
        return "Bearer"


class HasScope(BasePermission):
    message = "This API key lacks the required scope."

    def has_permission(self, request, view):
        if not isinstance(request.auth, APIKey):
            return False
        required = getattr(view, "required_scopes", None)
        if required is None:
            return False                      # fail closed if a view forgets
        return set(required).issubset(request.auth.scopes or [])