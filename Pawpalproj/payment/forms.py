from datetime import date

from django import forms
from django.core.validators import MaxValueValidator, RegexValidator

from core.models import Outlet
from user.models import Address

from payment.models import Payment
from payment.services import get_points_balance, points_limit_message

# Points redemption and card fields are shared between the shop and service-booking checkouts
# both checkout forms inherit this
class PaymentDetailsForm(forms.Form):
    
    # Points Redemption Field
    points_to_redeem = forms.IntegerField(
        required=False,
        min_value=0,
        label="Points to redeem",
        widget=forms.NumberInput(attrs={"placeholder": "0"}),
    )

    # Payment Fields
    payment_method = forms.ChoiceField(
        choices=Payment.Method.choices,
        label="Payment method",
    )
    card_number = forms.CharField(
        label="Card number",
        max_length=16,
        validators=[
            RegexValidator(
                regex=r"^\d{16}$",
                message="Enter a valid card number.",
            )
        ],
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", 
                   "autocomplete": "cc-number",
                   "placeholder": "1234 5678 9012 3456"}
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

    def __init__(self, customer, *args, points_balance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer

        # Use the balance passed in by the view to avoid a duplicate query
        if points_balance is None:
            points_balance = get_points_balance(customer)
        self.max_points = points_balance
        
        self.fields["points_to_redeem"].label = (
            f"Points to redeem (Available: {self.max_points} pts)"
        )

        # Disable the points field if the user has no points, otherwise set constraints
        if self.max_points <= 0:
            self.fields["points_to_redeem"].disabled = True
            self.fields["points_to_redeem"].widget.attrs["placeholder"] = "0 points available"
        else:
            points_field = self.fields["points_to_redeem"]
            points_field.validators.append(
                MaxValueValidator(  # blocks exceeding the balance
                    self.max_points,
                    message=points_limit_message(self.max_points),
                )
            )
            points_field.widget.attrs.update({
                "max": str(self.max_points),
                "placeholder": f"Max {self.max_points}",
            })

    # Validate that the card has not expired
    def clean_expiry(self):
        expiry = self.cleaned_data["expiry"]
        month, year = expiry.split("/")
        today = date.today()
        if (2000 + int(year), int(month)) < (today.year, today.month):
            raise forms.ValidationError("This card has expired.")
        return expiry

# Inherits PaymentDetailsForm and adds delivery / pick-up fields for the shop products checkout
class CheckoutForm(PaymentDetailsForm):

    # Show delivery fields before the inherited points + card fields
    field_order = [
        "delivery_method", "delivery_address", "use_new_address",
        "new_address_label", "new_address_line1", "new_address_line2",
        "new_address_postal_code", "save_address", "new_address_is_default",
        "pickup_outlet",
    ]

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

    # Populate the delivery address queryset and pre-select the default address
    def __init__(self, customer, *args, **kwargs):
        super().__init__(customer, *args, **kwargs)

        # Queryset of customer addresses
        addresses = customer.addresses.all()
        self.fields["delivery_address"].queryset = addresses

        if not addresses.exists():
            self.fields["delivery_address"].empty_label = "No saved delivery address"
            self.fields["delivery_address"].widget.attrs["disabled"] = "disabled"

        # Pre-select the default address, unless an initial value was passed in
        if not self.is_bound and "delivery_address" not in self.initial:
            self.initial["delivery_address"] = (
                addresses.filter(is_default=True).first()
            )

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get("delivery_method")

        # Delivery / Pickup validation
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
                if not cleaned_data.get("delivery_address"):
                    self.add_error("delivery_address", "Select a delivery address or use a new address.")
        elif method == "pickup" and not cleaned_data.get("pickup_outlet"):
            self.add_error("pickup_outlet", "Select a pick-up outlet.")

        return cleaned_data