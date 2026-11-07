from django import forms
from django.core.validators import RegexValidator

from core.models import Outlet
from user.models import Address

from .models import Payment


class CheckoutForm(forms.Form):
    delivery_method = forms.ChoiceField(
        choices=(
            ("delivery", "Delivery"),
            ("pickup", "Pick-up"),
        ),
        label="Order method",
        widget=forms.RadioSelect,
        initial="delivery",
    )
    delivery_address = forms.ModelChoiceField(
        queryset=Address.objects.none(),
        required=False,
        empty_label="Select a delivery address",
        label="Delivery address",
    )
    use_new_address = forms.BooleanField(
        required=False,
        label="Use a new address",
    )
    new_address_label = forms.CharField(
        required=False,
        max_length=50,
        label="Address label",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Home"}),
    )
    new_address_line1 = forms.CharField(
        required=False,
        label="Address line 1",
    )
    new_address_line2 = forms.CharField(
        required=False,
        label="Address line 2",
    )
    new_address_postal_code = forms.CharField(
        required=False,
        max_length=6,
        label="Postal code",
    )
    save_address = forms.BooleanField(
        required=False,
        label="Save this address to my profile",
    )
    new_address_is_default = forms.BooleanField(
        required=False,
        label="Set as my default address",
    )
    pickup_outlet = forms.ModelChoiceField(
        queryset=Outlet.objects.filter(is_active=True),
        required=False,
        empty_label="Select an outlet",
        label="Pick-up outlet",
    )
    payment_method = forms.ChoiceField(
        choices=Payment.Method.choices,
        label="Payment method",
    )
    card_number = forms.CharField(
        label="Card number",
        max_length=19,
        validators=[
            RegexValidator(
                regex=r"^\d{13,19}$",
                message="Enter a card number with 13 to 19 digits.",
            )
        ],
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "cc-number"}
        ),
    )
    expiry = forms.CharField(
        label="Expiry",
        max_length=5,
        validators=[
            RegexValidator(
                regex=r"^(0[1-9]|1[0-2])\/\d{2}$",
                message="Use MM/YY format.",
            )
        ],
        widget=forms.TextInput(
            attrs={"placeholder": "MM/YY", "autocomplete": "cc-exp"}
        ),
    )
    cvv = forms.CharField(
        label="CVV",
        max_length=4,
        validators=[
            RegexValidator(
                regex=r"^\d{3,4}$",
                message="Enter a 3 or 4 digit CVV.",
            )
        ],
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "cc-csc"}
        ),
    )

    def __init__(self, customer, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Queryset of customer addresses
        addresses = customer.addresses.all()
        self.fields["delivery_address"].queryset = addresses

        # Change empty_label and disable field if no addresses exist
        if not addresses.exists():
            self.fields["delivery_address"].empty_label = "No saved delivery address"
            self.fields["delivery_address"].widget.attrs["disabled"] = "disabled"

        if not self.is_bound:
            self.initial["delivery_address"] = (
                addresses.filter(is_default=True).first()
            )

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get("delivery_method")

        if method == "delivery":
            if cleaned_data.get("use_new_address"):
                if not cleaned_data.get("new_address_label"):
                    self.add_error("new_address_label", "Enter a label for this address.")
                if not cleaned_data.get("new_address_line1"):
                    self.add_error("new_address_line1", "Enter your address.")
                if not cleaned_data.get("new_address_postal_code"):
                    self.add_error(
                        "new_address_postal_code", "Enter your postal code."
                    )
            else:
                # Validate delivery_address only if the user has saved addresses to choose from
                if not cleaned_data.get("delivery_address"):
                    self.add_error("delivery_address", "Select a delivery address or use a new address.")
        elif method == "pickup" and not cleaned_data.get("pickup_outlet"):
            self.add_error("pickup_outlet", "Select a pick-up outlet.")

        return cleaned_data