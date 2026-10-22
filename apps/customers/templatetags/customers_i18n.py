"""Small helpers so the customer pages can show translated units and labels."""
from django import template
from django.template.defaultfilters import floatformat
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

register = template.Library()

# Stock confidence tags. The English words are used as internal keys elsewhere,
# so they stay English in the code and are translated only when shown.
CONFIDENCE_LABELS = {
    "Verified": gettext_lazy("Verified"),
    "Calculated": gettext_lazy("Calculated"),
    "Estimated": gettext_lazy("Estimated"),
    "Overdue": gettext_lazy("Overdue for check"),
}


@register.filter
def tn(value, arg="1g"):
    """A tonnage with its unit, for example '12.5 t' (the unit is translated)."""
    return format_html("{} {}", floatformat(value, arg), _("t"))


@register.filter
def confidence_label(value):
    return CONFIDENCE_LABELS.get(value, value)


@register.filter
def tonnes_t(value):
    """A tonnage exactly as stored, followed by the translated unit, for example '12.500 t'."""
    return format_html("{} {}", value, _("t"))
