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
from decimal import Decimal, ROUND_HALF_UP
from .models import APIKey, Merchant, generate_webhook_secret,InTransaction,IdempotencyRecord, FeePlan
from django.core.exceptions import ValidationError
from django.db.models import Q

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
TXN_TYPE_COLORS = {
    InTransaction.Type.COLLECTION: "#15803d",
    InTransaction.Type.DISBURSEMENT: "#b91c1c",
    InTransaction.Type.REVERSAL: "#2563eb",

}


@admin.register(InTransaction)
class InTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_ref", "type_badge", "direction_badge", "merchant", "msisdn", "network",
        "amount_display", "fee_display", "effect_display", "balance_after_display",
        "status_badge", "environment", "transaction_date",
    )
    list_filter = (
        "type", "status", "environment", "gateway", "network",
        "merchant", "failure_reason", "transaction_date",
    )
    search_fields = (
        "transaction_ref", "merchant_reference", "transaction_id",
        "external_reference", "msisdn", "merchant__name",
    )
    list_select_related = ("merchant", "api_key", "related_transaction")
    date_hierarchy = "transaction_date"
    ordering = ("-transaction_date",)
    list_per_page = 50
    show_full_result_count = False
    actions = ["export_csv"]

    fieldsets = (
        ("Summary", {"fields": (
            "id", "transaction_ref", "merchant_reference",
            "type_badge", "direction_badge", "status_badge", "failure_reason",
            "transaction_date", "completed_at",
        )}),
        ("Money", {"fields": (
            "amount", "currency", "platform_fee", "provider_fee", "margin_display",
            "net_amount", "effect_display", "balance_after",
        )}),
        ("Merchant", {"fields": ("merchant", "api_key_link", "environment")}),
        ("Customer", {"fields": ("msisdn", "network", "channel", "narration")}),
        ("Related", {"fields": ("related_link", "reversals_list")}),
        ("Provider", {"fields": (
            "gateway", "provider_status", "transaction_id",
            "external_reference", "provider_response_pretty",
        )}),
        ("Merchant webhook", {"fields": ("webhook",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        model_fields = [f.name for f in self.model._meta.fields]
        return model_fields + [
            "type_badge", "direction_badge", "status_badge", "effect_display",
            "margin_display", "api_key_link", "related_link", "reversals_list",
            "provider_response_pretty",
        ]

    # Financial records: view only
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ── Display helpers ──

    @staticmethod
    def _tzs(value):
        return "—" if value is None else f"{value:,.0f}"

    @admin.display(description="Type", ordering="type")
    def type_badge(self, obj):
        color = TXN_TYPE_COLORS.get(obj.type, "#6b7280")
        return format_html('<b style="color:{}">{}</b>', color, obj.get_type_display())

    @admin.display(description="Dir")
    def direction_badge(self, obj):
        if obj.direction == "credit":
            return format_html('<b style="color:#15803d">▲ CR</b>')
        return format_html('<b style="color:#b91c1c">▼ DR</b>')

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        color = TXN_STATUS_COLORS.get(obj.status, "#6b7280")
        return format_html('<b style="color:{}">{}</b>', color, obj.get_status_display())

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return f"{obj.currency} {obj.amount:,.0f}"

    @admin.display(description="Fee", ordering="platform_fee")
    def fee_display(self, obj):
        return self._tzs(obj.platform_fee)

    @admin.display(description="Balance effect")
    def effect_display(self, obj):
        # Only completed collections and reversals, or started disbursements, moved the balance
        if obj.balance_after is None:
            return "—"
        effect = obj.balance_effect
        color = "#15803d" if effect >= 0 else "#b91c1c"
        return format_html('<b style="color:{}">{}</b>', color, f"{effect:+,.0f}")

    @admin.display(description="Balance after", ordering="balance_after")
    def balance_after_display(self, obj):
        if obj.balance_after is None:
            return "—"
        return format_html("<b>{}</b>", f"{obj.balance_after:,.0f}")

    @admin.display(description="Margin (fee − provider fee)")
    def margin_display(self, obj):
        if obj.platform_fee is None or obj.provider_fee is None:
            return "—"
        margin = obj.platform_fee - obj.provider_fee
        color = "#15803d" if margin >= 0 else "#b91c1c"
        return format_html('<b style="color:{}">{}</b>', color, f"{margin:,.0f}")

    @admin.display(description="API key")
    def api_key_link(self, obj):
        if not obj.api_key:
            return "—"
        url = reverse(
            f"admin:{obj.api_key._meta.app_label}_{obj.api_key._meta.model_name}_change",
            args=[obj.api_key.pk],
        )
        return format_html('<a href="{}">{} ({})</a>', url, obj.api_key.name, obj.api_key.prefix)

    def _txn_url(self, txn):
        return reverse(f"admin:{txn._meta.app_label}_intransaction_change", args=[txn.pk])

    @admin.display(description="Reverses")
    def related_link(self, obj):
        if not obj.related_transaction:
            return "—"
        rel = obj.related_transaction
        return format_html('<a href="{}">{}</a>', self._txn_url(rel), rel.transaction_ref)

    @admin.display(description="Reversed by")
    def reversals_list(self, obj):
        items = list(obj.reversals.all())
        if not items:
            return "—"
        return format_html(", ".join(
            f'<a href="{self._txn_url(r)}">{r.transaction_ref}</a>' for r in items
        ))

    @admin.display(description="Provider response")
    def provider_response_pretty(self, obj):
        return pretty_json(obj.provider_response)

    @admin.action(description="Export selected to CSV")
    def export_csv(self, request, queryset):
        fields = [
            "id", "transaction_ref", "merchant_reference", "type", "merchant__name",
            "environment", "msisdn", "network", "channel", "gateway",
            "amount", "currency", "platform_fee", "provider_fee", "net_amount", "balance_after",
            "status", "failure_reason", "provider_status",
            "transaction_id", "external_reference", "related_transaction__transaction_ref",
            "transaction_date", "completed_at", "narration",
        ]
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="transactions-{stamp}.csv"'
        writer = csv.writer(response)
        writer.writerow(fields + ["direction", "balance_effect"])
        for txn in queryset.select_related("merchant", "related_transaction").iterator():
            row = []
            for f in fields:
                value = txn
                for part in f.split("__"):
                    value = getattr(value, part, None) if value is not None else None
                row.append(value)
            effect = txn.balance_effect if txn.balance_after is not None else ""
            writer.writerow(row + [txn.direction, effect])
        return response



def _fee_for(plan, amount: Decimal) -> Decimal:
    """Same calculation as services/fees.py, for display only."""
    fee = amount * plan.percent / Decimal("100") + plan.fixed
    fee = max(fee, plan.minimum)
    if plan.maximum is not None:
        fee = min(fee, plan.maximum)
    return fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class FeePlanForm(forms.ModelForm):
    class Meta:
        model = FeePlan
        fields = "__all__"
        help_texts = {
            "merchant": "Leave blank for the default plan that applies to all merchants.",
            "network": "vodacom, tigo, airtel, halotel, or blank for all networks.",
            "max_amount": "Leave blank for no upper limit.",
            "percent": "1.50 means 1.5%.",
            "fixed": "Flat TZS added to the percentage.",
        }

    def clean(self):
        data = super().clean()
        lo = data.get("min_amount") or Decimal("0")
        hi = data.get("max_amount")

        if hi is not None and hi < lo:
            raise ValidationError({"max_amount": "Max amount must be greater than min amount."})

        if data.get("maximum") is not None and data["maximum"] < (data.get("minimum") or 0):
            raise ValidationError({"maximum": "Maximum fee must be greater than minimum fee."})

        if not data.get("is_active"):
            return data

        # Find active plans for the same merchant, type and network whose band overlaps this one
        others = FeePlan.objects.filter(
            merchant=data.get("merchant"),
            transaction_type=data.get("transaction_type"),
            network=data.get("network") or "",
            is_active=True,
        )
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)

        # Overlap: other.min <= this.max  AND  this.min <= other.max (blank max = no limit)
        if hi is not None:
            others = others.filter(min_amount__lte=hi)
        others = others.filter(Q(max_amount__isnull=True) | Q(max_amount__gte=lo))

        clash = others.first()
        if clash:
            raise ValidationError(f"This band overlaps an existing active plan: {clash}")
        return data


@admin.register(FeePlan)
class FeePlanAdmin(admin.ModelAdmin):
    form = FeePlanForm

    list_display = (
        "who", "transaction_type", "network_display", "band",
        "percent", "fixed", "minimum", "maximum", "example_fee", "is_active",
    )
    list_filter = ("transaction_type", "is_active", "network", "merchant")
    search_fields = ("merchant__name",)
    list_select_related = ("merchant",)
    list_editable = ("is_active",)
    ordering = ("merchant", "transaction_type", "network", "min_amount")
    actions = ["activate", "deactivate"]

    fieldsets = (
        ("Applies to", {"fields": ("merchant", "transaction_type", "network")}),
        ("Amount band", {"fields": ("min_amount", "max_amount")}),
        ("Fee", {"fields": ("percent", "fixed", "minimum", "maximum")}),
        ("Status", {"fields": ("is_active", "examples")}),
    )
    readonly_fields = ("examples",)

    # Keep history: switch plans off instead of deleting them
    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Merchant", ordering="merchant__name")
    def who(self, obj):
        return obj.merchant or "Default (all merchants)"

    @admin.display(description="Network", ordering="network")
    def network_display(self, obj):
        return obj.network or "All"

    @admin.display(description="Band (TZS)", ordering="min_amount")
    def band(self, obj):
        top = f"{obj.max_amount:,.0f}" if obj.max_amount is not None else "∞"
        return f"{obj.min_amount:,.0f} – {top}"

    @admin.display(description="Example")
    def example_fee(self, obj):
        # Fee at the bottom of the band (or 10,000 for open bands starting at 0)
        amount = obj.min_amount if obj.min_amount > 0 else Decimal("10000")
        if obj.max_amount is not None and amount > obj.max_amount:
            amount = obj.max_amount
        return f"{amount:,.0f} → fee {_fee_for(obj, amount):,.0f}"

    @admin.display(description="Example fees")
    def examples(self, obj):
        if not obj or not obj.pk:
            return "Save to see examples."
        lo = obj.min_amount
        hi = obj.max_amount if obj.max_amount is not None else lo + Decimal("100000")
        samples = sorted({lo, (lo + hi) / 2, hi})
        rows = [f"{a:,.0f} → fee {_fee_for(obj, a):,.0f}" for a in samples if a > 0]
        return "\n".join(rows) or "—"

    @admin.action(description="Activate selected plans")
    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f"Activated {count} plan(s). Check that no active bands overlap.",
            messages.WARNING,
        )

    @admin.action(description="Deactivate selected plans")
    def deactivate(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {count} plan(s).", messages.SUCCESS)    