from django import forms
from django.utils.translation import gettext_lazy as _

from apps.customers.models import CountMethod


class HeatForm(forms.Form):
    temperature_c = forms.DecimalField(
        max_digits=5, decimal_places=1, min_value=-20, max_value=200, label=_("Temperature (°C)"),
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.1"}),
    )
    spot = forms.CharField(max_length=80, required=False, label=_("Where in the stack"), help_text=_("For example north face, 1 m deep"))
    depth_cm = forms.IntegerField(min_value=0, max_value=500, required=False, label=_("Probe depth (cm)"))


class InspectionForm(forms.Form):
    looks_wet = forms.BooleanField(required=False, label=_("The stack looks wet"))
    mould = forms.BooleanField(required=False, label=_("Mould is visible"))
    steam_or_smell = forms.BooleanField(required=False, label=_("Steam, or a burnt or musty smell"))
    cover_in_place = forms.BooleanField(required=False, initial=True, label=_("Cover is in place and secure"))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("Notes"))


class _BatchForm(forms.Form):
    def __init__(self, *args, batches, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["batch"] = forms.ModelChoiceField(queryset=batches, label=_("Batch"), empty_label=None)
        self.order_fields(["batch"])


class CountForm(_BatchForm):
    tonnes = forms.DecimalField(
        max_digits=10, decimal_places=3, min_value=0, label=_("Counted (tonnes)"),
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.001"}),
    )
    method = forms.ChoiceField(choices=CountMethod.choices, label=_("How it was counted"))


class MoistureForm(_BatchForm):
    percent = forms.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, label=_("Moisture (%)"),
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.1"}),
    )
    method = forms.CharField(max_length=60, initial="handheld meter", label=_("Method"))


class SizeForm(forms.Form):
    length_m = forms.DecimalField(max_digits=5, decimal_places=1, min_value=0.1, required=False, label=_("Length (m)"))
    width_m = forms.DecimalField(max_digits=5, decimal_places=1, min_value=0.1, required=False, label=_("Width (m)"))
    height_m = forms.DecimalField(max_digits=4, decimal_places=1, min_value=0.1, required=False, label=_("Height (m)"))
    cover_type = forms.CharField(max_length=100, required=False, label=_("Cover"), help_text=_("For example tarp, shed, none"))
