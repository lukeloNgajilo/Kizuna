



# Create your models here.

from django.db import models

# Create your models here.
# models.py
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Max
from mirai.utils.generator import generate_transaction_ref
from django.contrib.auth.models import AbstractUser




class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True)

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    def _apply_ordering(self, qs):
        """Apply model ordering if defined in Meta."""
        if hasattr(self.model._meta, 'ordering') and self.model._meta.ordering:
            return qs.order_by(*self.model._meta.ordering)
        return qs

    def get_queryset(self):
        qs = SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)
        return self._apply_ordering(qs)

    def all_with_deleted(self):
        qs = SoftDeleteQuerySet(self.model, using=self._db)
        return self._apply_ordering(qs)

    def only_deleted(self):
        qs = SoftDeleteQuerySet(self.model, using=self._db).deleted()
        return self._apply_ordering(qs)
    
class BaseTrackingModel(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_updated"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    # Managers
    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager()

    class Meta:
        abstract = True
        ordering = ['-created_at']  # newest first

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.save()

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using, keep_parents)










def generate_webhook_secret():
    return "whsec_" + secrets.token_urlsafe(32)





import hashlib
import secrets

from django.db import models
from django.utils import timezone


class APIKey(BaseTrackingModel):
    class Environment(models.TextChoices):
        LIVE = "live"
        TEST = "test"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)                  # "Production server", "Staging"
    prefix = models.CharField(max_length=12, unique=True, db_index=True)
    hashed_key = models.CharField(max_length=64)
    environment = models.CharField(max_length=4, choices=Environment.choices, default=Environment.TEST)
    scopes = models.JSONField(default=list)                  # ["payments:create", "payments:read"]
    allowed_ips = models.JSONField(default=list, blank=True) # empty = any IP
    merchant = models.ForeignKey(
        "Merchant",                      # string, because Merchant is defined below
        on_delete=models.PROTECT,        # can't delete a merchant that still has keys
        related_name="api_keys",
        null=True, blank=True,           # nullable so existing keys don't break the migration
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()

    @classmethod
    def generate(cls, name, environment="test", scopes=None, expires_at=None):
        """Create a key. Returns (api_key, full_key). Show full_key to the customer once."""
        prefix = secrets.token_hex(4)                        # 8 chars, public
        secret = secrets.token_urlsafe(32)                   # 256 bits, private
        full_key = f"sk_{environment}_{prefix}_{secret}"
        api_key = cls.objects.create(
            name=name,
            prefix=prefix,
            hashed_key=cls.hash_secret(secret),
            environment=environment,
            scopes=scopes or [],
            expires_at=expires_at,
        )
        return api_key, full_key

    @property
    def is_active(self):
        if self.revoked_at:
            return False
        return not (self.expires_at and self.expires_at <= timezone.now())

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])    


class Merchant(BaseTrackingModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15, blank=True)

    # Optional link to a Tanaka user who manages this merchant

    # Where you forward payment events when a request doesn't include its own webhook
    default_webhook = models.URLField(max_length=500, blank=True)
    # Used to sign forwarded events so the merchant can verify they came from you
    webhook_secret = models.CharField(max_length=64, default=generate_webhook_secret, editable=False)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class InTransaction(BaseTrackingModel):

    class Status(models.TextChoices):
        INITIATING = "initiating", "Initiating"
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REVERSED = "reversed", "Reversed"

    class Gateway(models.TextChoices):
        TEMBO = "tembo", "Tembo"
        SNIPPE = "snippe", "Snippe"

    class Environment(models.TextChoices):
        LIVE = "live", "Live"
        TEST = "test", "Test"

    class Type(models.TextChoices):
        COLLECTION = "collection", "Collection"
        DISBURSEMENT = "disbursement", "Disbursement"
        REVERSAL = "reversal", "Reversal"   

    CREDIT_TYPES = {"collection", "reversal"}
    DEBIT_TYPES = {"disbursement"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Ownership: nullable until the Merchant model exists
    merchant = models.ForeignKey(
        "mirai.Merchant", on_delete=models.PROTECT,
        related_name="transactions", null=True, blank=True,
    )
    api_key = models.ForeignKey(
        "APIKey", on_delete=models.PROTECT,
        related_name="transactions", null=True, blank=True,
    )
    environment = models.CharField(
        max_length=4, choices=Environment.choices, default=Environment.TEST,
    )

    # References
    transaction_ref = models.CharField(max_length=100, unique=True, editable=False)  # yours
    merchant_reference = models.CharField(max_length=100, blank=True)                # theirs

    type = models.CharField(
        max_length=20, choices=Type.choices, default=Type.COLLECTION, db_index=True,
    )

    related_transaction = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals",
    )


    # Customer
    msisdn = models.CharField(max_length=15)
    network = models.CharField(max_length=20, blank=True, default="")
    channel = models.CharField(max_length=30)          # provider's code; Snippe's may be longer
    narration = models.TextField()

    # Money
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    provider_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fees = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Status
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.INITIATING, db_index=True,
    )
    failure_reason = models.CharField(max_length=50, blank=True, default="")

    # Provider
    gateway = models.CharField(max_length=20, choices=Gateway.choices, null=True, blank=True)
    provider_status = models.CharField(max_length=50, blank=True, default="")  # raw: PENDING_ACK, 200...
    provider_response = models.JSONField(null=True, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)       # provider's ID
    external_reference = models.CharField(max_length=255, null=True, blank=True)

    balance_after = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    # Callback to merchant
    webhook = models.URLField(max_length=500, blank=True, default="")

    transaction_date = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "merchant_reference"],
                condition=~models.Q(merchant_reference=""),
                name="unique_merchant_reference_per_merchant",
            ),
            models.UniqueConstraint(
                fields=["gateway", "transaction_id"],
                condition=models.Q(transaction_id__isnull=False),
                name="unique_provider_txn_per_gateway",
            ),
        ]
        indexes = [
            models.Index(fields=["merchant", "-transaction_date"]),
            models.Index(fields=["status", "transaction_date"]),   # reconciliation sweep
        ]

    def __str__(self):
        return f"{self.status} {self.amount} {self.msisdn}"

    def save(self, *args, **kwargs):
        if not self.transaction_ref:
            self.transaction_ref = generate_transaction_ref()
        super().save(*args, **kwargs)


    @property
    def direction(self):
        if self.type in self.CREDIT_TYPES:
            return "credit"
        if self.type in self.DEBIT_TYPES:
            return "debit"
        return "credit" if self.amount >= 0 else "debit"     # adjustment: sign of amount

    @property
    def balance_effect(self):
        """Signed change to the merchant balance."""
        fee = self.platform_fee or 0
        if self.type == self.Type.COLLECTION:
            return self.amount - fee                  # customer pays 10,000, fee 150 → +9,850
        if self.type == self.Type.DISBURSEMENT:
            return -(self.amount + fee)               # pay out 10,000, fee 150 → −10,150
        if self.type == self.Type.REVERSAL:
            return self.amount                        # full refund, fee included
        return self.amount      


from django.db import models
from django.utils import timezone


class IdempotencyRecord(BaseTrackingModel):

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    api_key = models.ForeignKey(
        "APIKey",
        on_delete=models.PROTECT,
        related_name="idempotency_records",
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    transaction = models.ForeignKey(            # ← add this
        "InTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idempotency_records",
    )

    idempotency_key = models.CharField(
        max_length=255,
    )

    request_hash = models.CharField(
        max_length=64,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )

    response_status = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    response_body = models.JSONField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    expires_at = models.DateTimeField(
        db_index=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["api_key", "idempotency_key"],
                name="unique_idempotency_key_per_api_key",
            ),
        ]

        indexes = [
            models.Index(
                fields=["status", "created_at"],
            ),
        ]

    def __str__(self):
        return (
            f"{self.api_key.prefix}: "
            f"{self.idempotency_key}"
        )            


SOURCE_CHOICES = [
        ("WELCOME", "WELCOME"),
        ('NEW_LEASE', 'NEW_LEASE'),
        ('SYSTEM', 'SYSTEM'),
        ('OTP', 'OTP'),
    ]





from django.db import models


class DailyTransactionCounter(models.Model):
    reference_date = models.DateField(unique=True)
    last_number = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "mirai_daily_transaction_counter"
        verbose_name = "Daily Transaction Counter"
        verbose_name_plural = "Daily Transaction Counters"

    def __str__(self):
        return f"{self.reference_date}: {self.last_number}"


class SMS_gateway(BaseTrackingModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=15)
    message = models.TextField()
    source = models.CharField(max_length=100, null=True, blank=True,choices=SOURCE_CHOICES)
   # batch = models.ForeignKey(
   #     'SMSBatch', 
    #    on_delete=models.SET_NULL, 
    #    null=True, 
    #    blank=True, 
    #    related_name='logs'
    #)
    is_final = models.BooleanField(default=False) # True if DELIVERED or PERMANENT_FAILURE
    retry_count = models.IntegerField(default=0)
    message_type = models.CharField(max_length=60, null=True, blank=True)  
    vendor_message_id = models.CharField(null=True,max_length=255)
    status = models.CharField(null=True,max_length=50)
    raw_response = models.JSONField(null=True, blank=True)  # To store the full JSON response
    created_at = models.DateTimeField(auto_now_add=True) 

   # content_type = models.ForeignKey(
    #    ContentType,
    #    on_delete=models.SET_NULL,
    #    null=True,
    #    blank=True,
    #)
    object_id = models.UUIDField(null=True, blank=True)
    #content_object = GenericForeignKey("content_type", "object_id")

    #recipient_content_type = models.ForeignKey(
    #ContentType,
    #on_delete=models.SET_NULL,
    #null=True,
    #blank=True,
    #related_name="sms_recipient_logs",
#)
    recipient_object_id = models.UUIDField(null=True, blank=True)
 #   recipient = GenericForeignKey("recipient_content_type", "recipient_object_id")



    recipient_type = models.CharField(
        max_length=20,
        choices=[
            ("LANDLORD", "Landlord"),
            ("TENANT", "Tenant"),
            ("MANAGER", "Manager"),
            ("OTHER", "Other"),
        ],
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["phone_number", "status"]),
        ]
        ordering = ['-created_at']



class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=15, unique=True)
    middle_name =models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    email=models.CharField(max_length=100, blank=True, null=True)
    gender = models.CharField(max_length=10, choices = [
    ('Male', 'Male'),
    ('Female', 'Female'),
], blank=True, null=True)
    #role = models.ForeignKey(Role, on_delete=models.SET_NULL,blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    #payment_details = models.TextField(blank=True, null=True)
    date_joined = models.DateTimeField(auto_now=True) 
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    
    welcome_sms_sent = models.BooleanField(default=False,null=True,blank=True)
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users'
    )        


class FeePlan(BaseTrackingModel):
    """
    Platform fee. Most specific match wins.
    Blank merchant = default for everyone. Blank network = all networks.
    """
    merchant = models.ForeignKey(
        "Merchant", on_delete=models.CASCADE, null=True, blank=True, related_name="fee_plans",
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=[("collection", "Collection"), ("disbursement", "Disbursement")],
        default="collection",
    )
    network = models.CharField(max_length=20, blank=True, default="")

    # Band: this plan applies when min_amount <= amount <= max_amount
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # blank = no upper limit

    percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # 1.50 = 1.5%
    fixed = models.DecimalField(max_digits=12, decimal_places=2, default=0)    # flat TZS
    minimum = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maximum = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["transaction_type", "network", "min_amount"]

    def __str__(self):
        who = self.merchant or "Default"
        top = self.max_amount if self.max_amount is not None else "∞"
        return f"{who} {self.transaction_type} {self.network or 'all'} [{self.min_amount}–{top}]"