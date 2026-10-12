from datetime import date

from django import forms

from apps.core.validators import mobile_validator
from apps.farms.models import Farmer, FarmPlot, PlotSeason
from apps.geography.models import Village
from apps.reference.models import Crop, Season

# Rough box around India: catches swapped or mistyped coordinates.
LAT_RANGE = (6.0, 38.0)
LON_RANGE = (68.0, 98.0)


class FarmerForm(forms.Form):
    name = forms.CharField(max_length=200)
    mobile = forms.CharField(max_length=16, validators=[mobile_validator])
    village = forms.ModelChoiceField(queryset=Village.objects.none())
    preferred_language = forms.ChoiceField(
        choices=[("", "Not stated")] + Farmer.Language.choices, required=False
    )
    consent = forms.BooleanField(
        required=True,
        label="The farmer has been told how their information will be used and agrees.",
        error_messages={"required": "Consent is needed before a farmer can be registered."},
    )

    def __init__(self, *args, villages=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["village"].queryset = villages if villages is not None else Village.objects.all()
        self.fields["mobile"].widget.attrs.update({"inputmode": "tel", "autocomplete": "off"})

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_mobile(self):
        return self.cleaned_data["mobile"].replace(" ", "")


class PlotForm(forms.Form):
    latitude = forms.DecimalField(max_digits=9, decimal_places=6)
    longitude = forms.DecimalField(max_digits=9, decimal_places=6)
    area_acres = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=0.01, label="Area (acres)"
    )
    ownership = forms.ChoiceField(choices=[("", "Not stated")] + FarmPlot.Ownership.choices, required=False)
    irrigation = forms.ChoiceField(choices=[("", "Not stated")] + FarmPlot.Irrigation.choices, required=False)

    def clean_latitude(self):
        value = self.cleaned_data["latitude"]
        if not LAT_RANGE[0] <= value <= LAT_RANGE[1]:
            raise forms.ValidationError("Latitude should be between 6 and 38 for India.")
        return value

    def clean_longitude(self):
        value = self.cleaned_data["longitude"]
        if not LON_RANGE[0] <= value <= LON_RANGE[1]:
            raise forms.ValidationError("Longitude should be between 68 and 98 for India.")
        return value


class SeasonForm(forms.Form):
    season = forms.ModelChoiceField(queryset=Season.objects.none())
    year = forms.IntegerField(min_value=2000, max_value=2100, initial=date.today().year)
    crop = forms.ModelChoiceField(queryset=Crop.objects.none())
    variety = forms.CharField(max_length=100, required=False)
    sowing_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_harvest_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["season"].queryset = Season.objects.filter(status="active")
        self.fields["crop"].queryset = Crop.objects.filter(status="active")

    def clean(self):
        data = super().clean()
        sowing, harvest = data.get("sowing_date"), data.get("expected_harvest_date")
        if sowing and harvest and harvest < sowing:
            self.add_error("expected_harvest_date", "The harvest date cannot be before the sowing date.")
        return data
