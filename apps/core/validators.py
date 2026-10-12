from django.core.validators import RegexValidator

mobile_validator = RegexValidator(
    regex=r"^\+?\d{10,15}$",
    message="Enter a mobile number with 10 to 15 digits, optionally starting with +.",
)
