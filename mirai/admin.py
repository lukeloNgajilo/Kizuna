# admin.py
import secrets
import csv
import json
from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html
from django.urls import reverse

from .models import APIKey, Merchant, generate_webhook_secret,InTransaction,IdempotencyRecord, FeePlan


# ───────────────────────── Shared helpers ─────────────────────────

AVAILABLE_SCOPES = [
    ("payments:create", "payments:create (initiate collections)"),
    ("payments:read", "payments:read (check transaction status)"),
]


def _new_prefix():
    prefix = secrets.token_hex(4)
    while APIKey.objects.filter(prefix=prefix).exists():
        prefix = secrets.token_hex(4)
    return prefix


def _status(obj):
    if obj.revoked_at:
        return "Revoked", "#b91c1c"
    if obj.expires_at and obj.expires_at <= timezone.now():
        return "Expired", "#a16207"
    return "Active", "#15803d"


def _show_key_once(modeladmin, request, api_key, secret, extra=""):
    full_key = f"sk_{api_key.environment}_{api_key.prefix}_{secret}"
    modeladmin.message_user(
        request,
        format_html(
            "Key for <strong>{}</strong>. Copy it now, it will <strong>not</strong> be shown again:"
            "<br><code style='font-size:14px;user-select:all'>{}</code>{}",
            api_key.merchant or "—", full_key, extra,
        ),
        level=messages.WARNING,
    )


# ───────────────────────── API key forms ─────────────────────────

class APIKeyCreateForm(forms.ModelForm):
    scopes = forms.MultipleChoiceField(
        choices=AVAILABLE_SCOPES,
        widget=forms.CheckboxSelectMultiple,
        initial=["payments:create"],
    )

    class Meta:
        model = APIKey
        fields = ["merchant", "name", "environment", "scopes", "allowed_ips", "expires_at"]
        help_texts = {
            "allowed_ips": 'JSON list, e.g. ["41.59.10.20"]. Leave [] for any IP.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["merchant"].required = True
        self.fields["merchant"].queryset = Merchant.objects.filter(is_active=True)


class APIKeyChangeForm(forms.ModelForm):
    """Merchant, environment and key material can't change after creation."""
    scopes = forms.MultipleChoiceField(
        choices=AVAILABLE_SCOPES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = APIKey
        fields = ["name", "scopes", "allowed_ips", "expires_at"]


# ───────────────────────── API key admin ─────────────────────────

@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = (
        "name", "merchant", "masked_key", "environment", "status_badge",
        "scope_list", "last_used_at", "expires_at", "created_at",
    )
    list_filter = (
        "environment",
        "merchant",
        ("revoked_at", admin.EmptyFieldListFilter),
        ("expires_at", admin.EmptyFieldListFilter),
        "created_at",
    )
    search_fields = ("name", "prefix", "merchant__name")
    list_select_related = ("merchant",)
    ordering = ("-created_at",)
    actions = ["revoke_keys", "create_replacement_key"]

    change_readonly = (
        "merchant", "masked_key", "environment", "status_badge",
        "created_at", "last_used_at", "revoked_at",
    )

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = APIKeyCreateForm if obj is None else APIKeyChangeForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else self.change_readonly

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)

        secret = secrets.token_urlsafe(32)
        obj.prefix = _new_prefix()
        obj.hashed_key = APIKey.hash_secret(secret)
        super().save_model(request, obj, form, change)
        _show_key_once(self, request, obj, secret)

    # Revoke instead of delete
    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Revoke selected keys")
    def revoke_keys(self, request, queryset):
        count = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"Revoked {count} key(s).", messages.SUCCESS)

    @admin.action(description="Create replacement key (shows new key once)")
    def create_replacement_key(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one key.", messages.ERROR)
            return

        old = queryset.first()
        secret = secrets.token_urlsafe(32)
        new = APIKey.objects.create(
            merchant=old.merchant,
            name=f"{old.name} (replacement)",
            prefix=_new_prefix(),
            hashed_key=APIKey.hash_secret(secret),
            environment=old.environment,
            scopes=old.scopes,
            allowed_ips=old.allowed_ips,
            expires_at=old.expires_at,
        )
        _show_key_once(
            self, request, new, secret,
            extra=format_html(
                "<br>Old key <code>{}</code> is still active. Revoke it once the new one is in use.",
                old.prefix,
            ),
        )

    @admin.display(description="Key")
    def masked_key(self, obj):
        return f"sk_{obj.environment}_{obj.prefix}_••••••••"

    @admin.display(description="Status")
    def status_badge(self, obj):
        label, color = _status(obj)
        return format_html('<b style="color:{}">{}</b>', color, label)

    @admin.display(description="Scopes")
    def scope_list(self, obj):
        return ", ".join(obj.scopes) if obj.scopes else "—"


# ───────────────────────── Merchant admin ─────────────────────────

class APIKeyInline(admin.TabularInline):
    """Read-only list of the merchant's keys. Create keys from the API keys page."""
    model = APIKey
    fields = ("name", "masked_key", "environment", "status_badge", "last_used_at")
    readonly_fields = fields
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True

    @admin.display(description="Key")
    def masked_key(self, obj):
        return f"sk_{obj.environment}_{obj.prefix}_••••••••"

    @admin.display(description="Status")
    def status_badge(self, obj):
        label, color = _status(obj)
        return format_html('<b style="color:{}">{}</b>', color, label)


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "active_badge", "key_count", "transaction_count")
    list_filter = ("is_active",)
    search_fields = ("name", "email", "phone")
    ordering = ("name",)
    inlines = [APIKeyInline]
    actions = ["deactivate_merchants", "activate_merchants", "regenerate_webhook_secret"]

    fieldsets = (
        ("Merchant", {"fields": ("name", "email", "phone", "is_active")}),
        ("Webhooks", {"fields": ("default_webhook", "masked_webhook_secret")}),
    )
    readonly_fields = ("masked_webhook_secret",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _key_count=Count("api_keys", distinct=True),
            _txn_count=Count("transactions", distinct=True),
        )

    # Merchants with transactions can't be deleted (PROTECT); deactivate instead
    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Active", boolean=True, ordering="is_active")
    def active_badge(self, obj):
        return obj.is_active

    @admin.display(description="Keys", ordering="_key_count")
    def key_count(self, obj):
        return obj._key_count

    @admin.display(description="Transactions", ordering="_txn_count")
    def transaction_count(self, obj):
        return obj._txn_count

    @admin.display(description="Webhook secret")
    def masked_webhook_secret(self, obj):
        if not obj.webhook_secret:
            return "—"
        return f"{obj.webhook_secret[:10]}••••••••"

    @admin.action(description="Deactivate selected merchants")
    def deactivate_merchants(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {count} merchant(s).", messages.SUCCESS)

    @admin.action(description="Activate selected merchants")
    def activate_merchants(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"Activated {count} merchant(s).", messages.SUCCESS)

    @admin.action(description="Regenerate webhook secret (shows new secret once)")
    def regenerate_webhook_secret(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one merchant.", messages.ERROR)
            return
        merchant = queryset.first()
        merchant.webhook_secret = generate_webhook_secret()
        merchant.save(update_fields=["webhook_secret"])
        self.message_user(
            request,
            format_html(
                "New webhook secret for <strong>{}</strong>. Give it to the merchant now:"
                "<br><code style='font-size:14px;user-select:all'>{}</code>"
                "<br>Events signed with the old secret will no longer verify on their side.",
                merchant.name, merchant.webhook_secret,
            ),
            level=messages.WARNING,
        )





def pretty_json(value):
    if value in (None, "", [], {}):
        return "—"
    return format_html(
        '<pre style="white-space:pre-wrap;max-width:900px;margin:0;font-size:12px">{}</pre>',
        json.dumps(value, indent=2, ensure_ascii=False, default=str),
    )


TXN_STATUS_COLORS = {
    InTransaction.Status.INITIATING: "#6b7280",
    InTransaction.Status.PENDING: "#a16207",
    InTransaction.Status.COMPLETED: "#15803d",
    InTransaction.Status.FAILED: "#b91c1c",
    InTransaction.Status.REVERSED: "#7c3aed",
}

IDEM_STATUS_COLORS = {
    IdempotencyRecord.Status.PROCESSING: "#a16207",
    IdempotencyRecord.Status.COMPLETED: "#15803d",
    IdempotencyRecord.Status.FAILED: "#b91c1c",
}


# ───────────────────────── Transactions ─────────────────────────

@admin.register(InTransaction)
class InTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_ref", "merchant_reference", "merchant", "msisdn", "network",
        "amount_display", "gateway", "status_badge", "failure_reason",
        "environment", "transaction_date",
    )
    list_filter = (
        "status", "environment", "gateway", "network",
        "merchant", "failure_reason", "transaction_date",
    )
    search_fields = (
        "transaction_ref", "merchant_reference", "transaction_id",
        "external_reference", "msisdn", "merchant__name",
    )
    list_select_related = ("merchant", "api_key")
    date_hierarchy = "transaction_date"
    ordering = ("-transaction_date",)
    list_per_page = 50
    show_full_result_count = False
    actions = ["export_csv"]

    fieldsets = (
        ("Summary", {"fields": (
            "id", "transaction_ref", "merchant_reference",
            "status_badge", "failure_reason", "transaction_date",
        )}),
        ("Merchant", {"fields": ("merchant", "api_key_link", "environment")}),
        ("Customer", {"fields": ("msisdn", "network", "channel", "narration")}),
        ("Amounts", {"fields": ("amount", "currency", "fees", "net_amount")}),
        ("Provider", {"fields": (
            "gateway", "provider_status", "transaction_id",
            "external_reference", "provider_response_pretty",
        )}),
        ("Merchant webhook", {"fields": ("webhook",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        model_fields = [f.name for f in self.model._meta.fields]
        return model_fields + ["status_badge", "api_key_link", "provider_response_pretty"]

    # Financial records: view only
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        color = TXN_STATUS_COLORS.get(obj.status, "#6b7280")
        return format_html('<b style="color:{}">{}</b>', color, obj.get_status_display())

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return f"{obj.currency} {obj.amount:,.0f}"

    @admin.display(description="API key")
    def api_key_link(self, obj):
        if not obj.api_key:
            return "—"
        url = reverse(
            f"admin:{obj.api_key._meta.app_label}_{obj.api_key._meta.model_name}_change",
            args=[obj.api_key.pk],
        )
        return format_html('<a href="{}">{} ({})</a>', url, obj.api_key.name, obj.api_key.prefix)

    @admin.display(description="Provider response")
    def provider_response_pretty(self, obj):
        return pretty_json(obj.provider_response)

    @admin.action(description="Export selected to CSV")
    def export_csv(self, request, queryset):
        fields = [
            "id", "transaction_ref", "merchant_reference", "merchant__name",
            "environment", "msisdn", "network", "channel", "gateway",
            "amount", "currency", "fees", "net_amount",
            "status", "failure_reason", "provider_status",
            "transaction_id", "external_reference", "transaction_date", "narration",
        ]
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="transactions-{stamp}.csv"'
        writer = csv.writer(response)
        writer.writerow(fields)
        for row in queryset.values_list(*fields).iterator():
            writer.writerow(row)
        return response


# ───────────────────────── Idempotency records ─────────────────────────

@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "idempotency_key", "key_prefix", "merchant_name", "status_badge",
        "response_status", "transaction_link", "created_at", "is_expired",
    )
    list_filter = ("status", "response_status", "created_at")
    search_fields = (
        "idempotency_key", "api_key__prefix", "api_key__name",
        "api_key__merchant__name", "transaction__transaction_ref",
    )
    list_select_related = ("api_key", "api_key__merchant", "transaction")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ["clear_stuck_processing", "delete_expired"]

    fields = (
        "api_key", "idempotency_key", "status_badge", "request_hash",
        "transaction_link", "response_status", "response_body_pretty",
        "created_at", "updated_at", "expires_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="API key", ordering="api_key__prefix")
    def key_prefix(self, obj):
        return obj.api_key.prefix

    @admin.display(description="Merchant", ordering="api_key__merchant__name")
    def merchant_name(self, obj):
        return obj.api_key.merchant or "—"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        color = IDEM_STATUS_COLORS.get(obj.status, "#6b7280")
        return format_html('<b style="color:{}">{}</b>', color, obj.get_status_display())

    @admin.display(description="Transaction")
    def transaction_link(self, obj):
        if not obj.transaction_id:
            return "—"
        url = reverse(
            f"admin:{obj._meta.app_label}_intransaction_change",
            args=[obj.transaction_id],
        )
        return format_html('<a href="{}">{}</a>', url, obj.transaction.transaction_ref)

    @admin.display(description="Expired", boolean=True)
    def is_expired(self, obj):
        return obj.expires_at <= timezone.now()

    @admin.display(description="Response body")
    def response_body_pretty(self, obj):
        return pretty_json(obj.response_body)

    @admin.action(description="Clear stuck 'processing' records (older than 2 min)")
    def clear_stuck_processing(self, request, queryset):
        cutoff = timezone.now() - timezone.timedelta(minutes=2)
        count, _ = queryset.filter(
            status=IdempotencyRecord.Status.PROCESSING, created_at__lt=cutoff,
        ).delete()
        self.message_user(request, f"Cleared {count} stuck record(s).", messages.SUCCESS)

    @admin.action(description="Delete expired records")
    def delete_expired(self, request, queryset):
        count, _ = queryset.filter(expires_at__lte=timezone.now()).delete()
        self.message_user(request, f"Deleted {count} expired record(s).", messages.SUCCESS)        



@admin.register(FeePlan)
class FeePlanAdmin(admin.ModelAdmin):
    list_display = ("merchant", "network", "percent", "fixed", "minimum", "maximum", "is_active")
    list_filter = ("is_active", "network")        