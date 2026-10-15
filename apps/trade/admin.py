from datetime import date

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html, format_html_join

from apps.core.admin import NoDeleteAdminMixin
from apps.ledger import chain
from apps.ledger.chain import entries_for

from .models import BuyerPayment, Dispatch, DispatchEvent, DispatchStage, FeeSchedule, LeaseCharge, Sale
from .services import (
    announce_dispatch,
    announce_lease,
    announce_sale,
    lease_terms,
    mark_buyer_paid,
    mark_mitra_settled,
    record_event,
    sale_numbers,
    suggested_farmer_payment,
    validate_event,
    validate_new_dispatch,
)


@admin.register(FeeSchedule)
class FeeScheduleAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("region", "fee_model", "flat_rupees_per_tonne", "percentage", "lease_rupees_per_month", "effective_from", "effective_to", "status")
    list_filter = ("fee_model", "region", "status")


# ---- dispatch ---------------------------------------------------------------------------------


class DispatchAdminForm(forms.ModelForm):
    class Meta:
        model = Dispatch
        fields = ["grid", "product", "factory", "requirement", "quantity_tonnes", "vehicle_ref", "note"]

    def clean(self):
        data = super().clean()
        if self.instance._state.adding and all(data.get(k) for k in ("grid", "product", "factory", "quantity_tonnes")):
            validate_new_dispatch(
                grid=data["grid"], product=data["product"], factory=data["factory"],
                quantity_tonnes=data["quantity_tonnes"], requirement=data.get("requirement"),
            )
        return data


class EventFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        new = [f for f in self.forms if f.has_changed() and f.instance._state.adding and not f.cleaned_data.get("DELETE")]
        if len(new) > 1:
            raise ValidationError("Add one step at a time.")
        for form in new:
            data = form.cleaned_data
            validate_event(self.instance, data["event_type"], data.get("quantity_tonnes"))


class DispatchEventInline(admin.TabularInline):
    """Staff add the next step here. Past steps are read-only: the history is never rewritten."""

    model = DispatchEvent
    formset = EventFormSet
    extra = 0
    fields = ("event_type", "quantity_tonnes", "occurred_at", "vehicle_ref", "note", "ledger_seq")
    readonly_fields = ("ledger_seq",)
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Dispatch)
class DispatchAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = DispatchAdminForm
    list_display = ("code", "grid", "hub", "product", "factory", "quantity_tonnes", "current_quantity_tonnes", "stage", "status")
    list_filter = ("stage", "status", "grid", "factory")
    search_fields = ("code", "factory__name", "vehicle_ref")
    readonly_fields = ("code", "hub", "stage", "current_quantity_tonnes", "loss", "journey")
    inlines = [DispatchEventInline]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["grid", "product", "factory", "requirement", "quantity_tonnes", "vehicle_ref", "note"]
        return ["code", "grid", "hub", "product", "factory", "requirement", "quantity_tonnes", "current_quantity_tonnes", "loss", "stage", "vehicle_ref", "note", "journey"]

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("code", "grid", "hub", "product", "factory", "requirement", "quantity_tonnes", "current_quantity_tonnes", "loss", "stage", "journey")

    def get_inlines(self, request, obj):
        return [DispatchEventInline] if obj is not None and not obj.is_closed else []

    @admin.display(description="Lost on the way (t)")
    def loss(self, obj):
        return obj.loss_tonnes

    @admin.display(description="Ledger trail")
    def journey(self, obj):
        rows = entries_for(obj)
        if not rows:
            return "-"
        return format_html_join("", "<div>#{} {} · {}</div>", ((e.seq, e.created_at.strftime("%d %b %Y %H:%M"), e.entry_type) for e in rows))

    def save_model(self, request, obj, form, change):
        if not change:
            obj.hub = obj.grid.hub
            super().save_model(request, obj, form, change)
            announce_dispatch(obj)
        else:
            super().save_model(request, obj, form, change)
            if "paid_on" in form.changed_data and obj.paid_on:
                chain.append("lease.paid", obj, {"grid": obj.grid.code, "period_start": obj.period_start, "amount": obj.amount, "paid_on": obj.paid_on})

    def save_formset(self, request, form, formset, change):
        if formset.model is not DispatchEvent:
            return super().save_formset(request, form, formset, change)
        for event_form in formset.forms:
            if event_form.has_changed() and event_form.instance._state.adding:
                data = event_form.cleaned_data
                record_event(
                    form.instance, data["event_type"], quantity_tonnes=data.get("quantity_tonnes"),
                    occurred_at=data.get("occurred_at"), vehicle_ref=data.get("vehicle_ref", ""), note=data.get("note", ""),
                )


# ---- sales ------------------------------------------------------------------------------------


class SaleAdminForm(forms.ModelForm):
    farmer_payment = forms.DecimalField(
        required=False, max_digits=14, decimal_places=2, min_value=0,
        help_text="Leave empty to use the Grid's average pickup price x the delivered weight (marked as an estimate).",
    )

    class Meta:
        model = Sale
        fields = ["dispatch", "sale_value", "farmer_payment"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "dispatch" in self.fields:
            self.fields["dispatch"].queryset = Dispatch.objects.filter(stage=DispatchStage.DELIVERED, sale__isnull=True)

    def clean(self):
        data = super().clean()
        if self.instance._state.adding and data.get("dispatch") and data.get("sale_value") is not None:
            self.numbers = sale_numbers(data["dispatch"], sale_value=data["sale_value"], farmer_payment=data.get("farmer_payment"))
        return data


@admin.register(Sale)
class SaleAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = SaleAdminForm
    list_display = ("code", "dispatch", "quantity_tonnes", "sale_value", "farmer_payment", "platform_fee", "mitra_margin", "fee_model", "buyer_payment", "mitra_settled_on")
    list_filter = ("buyer_payment", "fee_model", "region")
    search_fields = ("code", "dispatch__code", "dispatch__factory__name")
    actions = ["buyer_paid", "mitra_settled"]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["dispatch", "sale_value", "farmer_payment"]
        return ["code", "dispatch", "region", "quantity_tonnes", "sale_value", "farmer_payment", "farmer_payment_estimated", "platform_fee", "mitra_margin", "fee_model", "fee_parameters", "buyer_payment", "buyer_paid_on", "payment_reference", "mitra_settled_on", "journey"]

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else tuple(f for f in self.get_fields(request, obj)) 

    @admin.display(description="Ledger trail")
    def journey(self, obj):
        rows = entries_for(obj)
        return format_html_join("", "<div>#{} {} · {}</div>", ((e.seq, e.created_at.strftime("%d %b %Y %H:%M"), e.entry_type) for e in rows)) if rows else "-"

    def get_form(self, request, obj=None, **kwargs):
        # On an existing sale nothing is editable, so use a plain form over no fields.
        if obj is not None:
            kwargs["form"] = forms.ModelForm
            kwargs["fields"] = []
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            return
        for name, value in form.numbers.items():
            setattr(obj, name, value)
        super().save_model(request, obj, form, change)
        announce_sale(obj)

    @admin.action(description="Record that the buyer's payment was received today")
    def buyer_paid(self, request, queryset):
        for sale in queryset:
            try:
                mark_buyer_paid(sale, received_on=date.today())
            except ValidationError as error:
                self.message_user(request, f"{sale.code}: {' '.join(error.messages)}", messages.ERROR)

    @admin.action(description="Record that the Mitra was paid their margin today")
    def mitra_settled(self, request, queryset):
        for sale in queryset:
            try:
                mark_mitra_settled(sale, settled_on=date.today())
            except ValidationError as error:
                self.message_user(request, f"{sale.code}: {' '.join(error.messages)}", messages.ERROR)


# ---- lease ------------------------------------------------------------------------------------


class LeaseChargeAdminForm(forms.ModelForm):
    amount = forms.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=0, help_text="Leave empty to use the schedule's monthly amount.")

    class Meta:
        model = LeaseCharge
        fields = ["grid", "period_start", "amount", "paid_on"]

    def clean(self):
        data = super().clean()
        if self.instance._state.adding and data.get("grid") and data.get("period_start"):
            self.terms = lease_terms(data["grid"], data["period_start"], data.get("amount"))
        return data


@admin.register(LeaseCharge)
class LeaseChargeAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = LeaseChargeAdminForm
    list_display = ("grid", "period_start", "amount", "paid_on", "status")
    list_filter = ("grid", "status")

    def get_readonly_fields(self, request, obj=None):
        return ("grid", "period_start", "amount") if obj is not None else ()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.period_start, obj.amount, schedule = form.terms
            super().save_model(request, obj, form, change)
            announce_lease(obj, schedule)
        else:
            super().save_model(request, obj, form, change)
            if "paid_on" in form.changed_data and obj.paid_on:
                chain.append("lease.paid", obj, {"grid": obj.grid.code, "period_start": obj.period_start, "amount": obj.amount, "paid_on": obj.paid_on})
