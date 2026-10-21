from decimal import ROUND_DOWN, Decimal

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html_join

from apps.core.admin import NoDeleteAdminMixin
from apps.ledger.chain import entries_for

from . import contracts, services
from .models import (
    Batch,
    Contract,
    ContractLine,
    CustomerMember,
    MonthlyPlan,
    PurchaseOrder,
    InventoryTransaction,
    PlantProfile,
    Pile,
    QualityObservation,
    Reservation,
    StockCount,
    Stockyard,
)


def adopt(obj, row):
    """Make the unsaved admin object stand for the row a service just created."""
    obj.__dict__.update(row.__dict__)
    obj._state = row._state


class AddOnlyMixin(NoDeleteAdminMixin):
    """Stock records are added, never edited: a correction is a new record."""

    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)


@admin.register(CustomerMember)
class CustomerMemberAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("user", "buyer", "job_role", "status")
    list_filter = ("job_role", "status")
    search_fields = ("user__username", "buyer__company_name")


@admin.register(PlantProfile)
class PlantProfileAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("factory", "daily_consumption_tonnes", "status")


class PileInline(admin.TabularInline):
    model = Pile
    extra = 0
    fields = ("label", "form", "exposure", "cover_type", "status")


@admin.register(Stockyard)
class StockyardAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "owner_type", "owner_name", "capacity_tonnes", "region", "status")
    list_filter = ("owner_type", "region", "status")
    search_fields = ("code", "name", "owner_name")
    readonly_fields = ("code",)
    inlines = [PileInline]


@admin.register(Pile)
class PileAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("yard", "label", "form", "exposure", "cover_type", "status")
    list_filter = ("exposure", "form", "yard")
    search_fields = ("label", "yard__name")


@admin.register(Batch)
class BatchAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "customer", "pile", "form", "intake_tonnes", "received_on", "book", "status")
    list_filter = ("form", "customer", "status")
    search_fields = ("code", "customer__company_name", "source_note")
    date_hierarchy = "received_on"

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        # Quantities change only through stock transactions.
        return ("code", "customer", "biomass_type", "form", "intake_tonnes", "intake_moisture_percent", "received_on", "book", "journey")

    @admin.display(description="Book stock (t)")
    def book(self, obj):
        return services.book_tonnes(obj) if obj.pk else "-"

    @admin.display(description="Ledger trail")
    def journey(self, obj):
        rows = entries_for(obj)
        return format_html_join("", "<div>#{} {} · {}</div>", ((e.seq, e.created_at.strftime("%d %b %Y %H:%M"), e.entry_type) for e in rows)) if rows else "-"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            services.receive_batch(obj)


class TransactionForm(forms.ModelForm):
    tonnes = forms.DecimalField(
        required=False, max_digits=10, decimal_places=3,
        help_text="Type a positive weight. Only an adjustment may be negative. Not needed for a move between piles.",
    )

    class Meta:
        model = InventoryTransaction
        fields = ["batch", "kind", "tonnes", "loss_cause", "to_pile", "occurred_at", "note"]

    def clean(self):
        data = super().clean()
        if data.get("batch") and data.get("kind"):
            data["change"] = services.validate_transaction(
                data["batch"], data["kind"], data.get("tonnes"), data.get("loss_cause", ""), data.get("to_pile")
            )
        return data


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(AddOnlyMixin, admin.ModelAdmin):
    form = TransactionForm
    list_display = ("batch", "kind", "tonnes_change", "loss_cause", "occurred_at", "ledger_seq")
    list_filter = ("kind", "loss_cause")
    search_fields = ("batch__code",)

    def save_model(self, request, obj, form, change):
        d = form.cleaned_data
        row = services.record_transaction(
            d["batch"], d["kind"], d.get("tonnes"), loss_cause=d.get("loss_cause", ""), to_pile=d.get("to_pile"),
            occurred_at=d.get("occurred_at"), note=d.get("note", ""),
        )
        adopt(obj, row)


class CountForm(forms.ModelForm):
    class Meta:
        model = StockCount
        fields = ["batch", "counted_tonnes", "method", "counted_on", "counted_by"]


@admin.register(StockCount)
class StockCountAdmin(AddOnlyMixin, admin.ModelAdmin):
    form = CountForm
    list_display = ("batch", "counted_tonnes", "method", "counted_on", "counted_by", "ledger_seq")
    list_filter = ("method",)
    search_fields = ("batch__code",)

    def save_model(self, request, obj, form, change):
        d = form.cleaned_data
        adopt(obj, services.record_count(d["batch"], d["counted_tonnes"], d["method"], counted_on=d["counted_on"], counted_by=d["counted_by"]))


class QualityForm(forms.ModelForm):
    class Meta:
        model = QualityObservation
        fields = ["batch", "basis", "observed_at", "moisture_percent", "ash_percent", "gcv", "method", "tested_by"]


@admin.register(QualityObservation)
class QualityObservationAdmin(AddOnlyMixin, admin.ModelAdmin):
    form = QualityForm
    list_display = ("batch", "basis", "observed_at", "moisture_percent", "ash_percent", "gcv", "tested_by")
    list_filter = ("basis",)
    search_fields = ("batch__code",)

    def save_model(self, request, obj, form, change):
        d = form.cleaned_data
        adopt(obj, services.record_quality(
            d["batch"], moisture_percent=d.get("moisture_percent"), ash_percent=d.get("ash_percent"), gcv=d.get("gcv"),
            basis=d["basis"], observed_at=d.get("observed_at"), method=d.get("method", ""), tested_by=d.get("tested_by", ""),
        ))


class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ["batch", "factory", "tonnes", "note"]

    def clean(self):
        data = super().clean()
        if self.instance._state.adding and data.get("batch") and data.get("factory") and data.get("tonnes"):
            batch, factory = data["batch"], data["factory"]
            if factory.buyer_id != batch.customer_id:
                raise forms.ValidationError("A batch can only be reserved for its own customer's plant.")
            free = services.book_tonnes(batch) - services.reserved_tonnes(batch)
            if data["tonnes"] > free:
                raise forms.ValidationError(f"Only {free} t of this batch is not already reserved.")
        return data


@admin.register(Reservation)
class ReservationAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = ReservationForm
    list_display = ("batch", "factory", "tonnes", "note", "status")
    list_filter = ("status", "factory")

    def get_fields(self, request, obj=None):
        return ["batch", "factory", "tonnes", "note"] if obj is None else ["batch", "factory", "tonnes", "note", "status"]

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else ("batch", "factory", "tonnes", "note")

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            kwargs["form"] = forms.ModelForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        d = form.cleaned_data
        adopt(obj, services.reserve(d["batch"], d["factory"], d["tonnes"], d.get("note", "")))


# ---- contracts and purchase orders ------------------------------------------------------------


class ContractLineInline(admin.TabularInline):
    model = ContractLine
    extra = 1
    fields = ("product", "contracted_tonnes", "price_per_tonne", "max_moisture_percent", "min_gcv", "status")


@admin.register(Contract)
class ContractAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "customer", "reference", "start_date", "end_date", "risk_bearer", "status")
    list_filter = ("customer", "risk_bearer", "status")
    search_fields = ("code", "reference", "customer__company_name")
    readonly_fields = ("code",)
    filter_horizontal = ("allocated_yards",)
    inlines = [ContractLineInline]


class MonthlyPlanInline(admin.TabularInline):
    model = MonthlyPlan
    extra = 0
    fields = ("month", "planned_tonnes", "status")


@admin.register(ContractLine)
class ContractLineAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("contract", "product", "contracted_tonnes", "price_per_tonne", "status")
    list_filter = ("contract__customer", "status")
    search_fields = ("contract__code", "product__name")
    inlines = [MonthlyPlanInline]
    actions = ["spread_evenly"]

    @admin.action(description="Spread the contracted tonnes evenly over the contract's months")
    def spread_evenly(self, request, queryset):
        for line in queryset:
            if line.plan.exists():
                self.message_user(request, f"{line}: already has a monthly plan, so it was left alone.", messages.WARNING)
                continue
            months = contracts.months_between(line.contract.start_date, line.contract.end_date)
            each = (line.contracted_tonnes / len(months)).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
            for i, month in enumerate(months):
                last = i == len(months) - 1
                MonthlyPlan.objects.create(
                    line=line, month=month, planned_tonnes=line.contracted_tonnes - each * (len(months) - 1) if last else each
                )
            self.message_user(request, f"{line}: planned {len(months)} months.")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "customer_po_number", "line", "factory", "tonnes", "deliver_from", "deliver_by", "state", "delivered")
    list_filter = ("state", "factory__buyer", "status")
    search_fields = ("code", "customer_po_number", "factory__name")
    readonly_fields = ("code",)

    @admin.display(description="Delivered (t)")
    def delivered(self, obj):
        return contracts.order_progress(obj).delivered
