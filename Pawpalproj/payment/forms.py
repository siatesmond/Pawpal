from django import forms
from django.core.validators import RegexValidator
from django.db.models import Sum

from core.models import Outlet
from user.models import Address

from payment.models import Payment
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
    
    # Points Redemption Fields
    use_points = forms.BooleanField(
        required=False,
        label="Redeem loyalty points for discount",
    )
    points_to_redeem = forms.IntegerField(
        required=False,
        min_value=0,
        label="Points to redeem",
        widget=forms.NumberInput(attrs={"placeholder": "0", "min": "0"}),
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

    def __init__(self, customer, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        
        # Calculate current net points balance
        self.max_points = (
            customer.points_transactions.aggregate(total=Sum("points"))["total"] or 0
        )
        
        # Dynamically update label to show available points balance
        self.fields["use_points"].label = f"Redeem loyalty points for discount (Available: {self.max_points} pts)"
        
        # Disable loyalty point fields if user has no points, otherwise set HTML5 constraints
        if self.max_points <= 0:
            self.fields["use_points"].disabled = True
            self.fields["use_points"].help_text = "You have 0 loyalty points available."
            self.fields["points_to_redeem"].disabled = True
            self.fields["points_to_redeem"].widget.attrs["placeholder"] = "0 points available"
        else:
            self.fields["points_to_redeem"].max_value = self.max_points
            self.fields["points_to_redeem"].widget.attrs.update({
                "max": str(self.max_points),
                "min": "0",
                "placeholder": f"Max {self.max_points}",
            })

        # Queryset of customer addresses
        addresses = customer.addresses.all()
        self.fields["delivery_address"].queryset = addresses

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

        # Points Redemption Validation
        use_points = cleaned_data.get("use_points")
        points_to_redeem = cleaned_data.get("points_to_redeem") or 0

        if use_points:
            if self.max_points <= 0:
                self.add_error("use_points", "You do not have any points available to redeem.")
            elif points_to_redeem <= 0:
                self.add_error("points_to_redeem", "Enter a valid number of points to redeem.")
            elif points_to_redeem > self.max_points:
                self.add_error(
                    "points_to_redeem",
                    f"You only have {self.max_points} points available."
                )

        return cleaned_data