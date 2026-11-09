import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from inventory.models import CartItem, Product
from payment.services import points_earned
from service.models import Booking

from .forms import (
    ForgotPasswordEmailForm,
    AddressForm,
    LoginForm,
    OTPForm,
    PasswordChangeForm,
    PetForm,
    ProfileForm,
    RegisterForm,
    ResetPasswordForm,
)
from .models import OTP, Customer, Pet, User


# USER TYPE AND OTP HELPERS

def get_user_type(user):
    """Which child table this user has a row in (multi-table inheritance)."""
    if hasattr(user, "customer"):
        return "customer"
    if hasattr(user, "staff"):
        return "staff"
    if hasattr(user, "businessowner"):
        return "owner"
    if hasattr(user, "petsitter"):
        return "sitter"
    return None


def send_otp_code(user, purpose):
    # Generate a random 6-digit code for the user.
    code = f"{secrets.randbelow(1_000_000):06d}"

    # Delete the user's previous code so only the newest code can be used.
    OTP.objects.filter(user=user, purpose=purpose).delete()

    # Save the hashed code in the database. The real code is never stored.
    OTP.objects.create(
        user=user,
        code_hash=make_password(code),
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=OTP.VALID_MINUTES),
    )

    # Send the real code to the user's email address.
    send_mail(
        "Your Pawpal verification code",
        f"Your Pawpal verification code is {code}. "
        f"It expires in {OTP.VALID_MINUTES} minutes.",
        None,
        [user.email],
        fail_silently=False,
    )


# LOGIN, REGISTRATION AND OTP VERIFICATION

class LoginView(View):
    form_class = LoginForm
    template_name = "user/login.html"

    def get(self, request, *args, **kwargs):
        # already logged in -> go straight to the right page
        if "user_id" in request.session:
            return redirect(home_for(request.session.get("user_type")))
        if request.GET.get("guest_notice") == "1":
            messages.info(request, "Please log in to view more details.")
        return render(request, self.template_name, {"form": self.form_class()})

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)

        if form.is_valid():
            user = form.cleaned_data["user"]

            if not user.is_verified:
                send_otp_code(user, OTP.Purpose.REGISTER)
                request.session["otp_user_id"] = user.pk
                request.session["otp_purpose"] = OTP.Purpose.REGISTER
                return redirect("user:verify_otp")

            # store the login in the session (request.session is like a dict)
            request.session["user_id"] = user.pk
            request.session["user_type"] = get_user_type(user)
            request.session["username"] = user.first_name or user.username

            if not form.cleaned_data["remember"]:
                request.session.set_expiry(0)  # ends when the browser is closed
            # otherwise it lasts SESSION_COOKIE_AGE (settings.py)

            return redirect(home_for(request.session["user_type"]))

        return render(request, self.template_name, {"form": form})


class RegisterView(View):
    form_class = RegisterForm
    template_name = "user/register.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"form": self.form_class()})

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            user = form.save()
            send_otp_code(user, OTP.Purpose.REGISTER)
            request.session["otp_user_id"] = user.pk
            request.session["otp_purpose"] = OTP.Purpose.REGISTER
            return redirect("user:verify_otp")
        return render(request, self.template_name, {"form": form})


class VerifyOTPView(View):
    template_name = "user/verify_otp.html"

    def get(self, request, *args, **kwargs):
        # Find the user who is currently waiting to verify an OTP.
        user_id = request.session.get("otp_user_id")
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            return redirect("user:login")
        return render(
            request,
            self.template_name,
            {
                "form": OTPForm(),
                "email": user.email,
                "purpose": request.session.get("otp_purpose"),
            },
        )

    def post(self, request, *args, **kwargs):
        # Read the user and OTP purpose saved during registration or password reset.
        user_id = request.session.get("otp_user_id")
        purpose = request.session.get("otp_purpose")
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None or purpose not in (
            OTP.Purpose.REGISTER,
            OTP.Purpose.PASSWORD_RESET,
        ):
            return redirect("user:login")

        # Check the code submitted by the user.
        form = OTPForm(request.POST)
        otp = OTP.objects.filter(
            user=user,
            purpose=purpose,
        ).order_by("-created_at").first()

        # Reject the code if it does not exist or is older than 5 minutes.
        if otp is None or otp.is_expired():
            form.add_error("code", "This code has expired. Request a new one.")

        # Stop accepting codes after too many incorrect attempts.
        elif otp.attempts >= OTP.MAX_ATTEMPTS:
            form.add_error("code", "Too many incorrect attempts. Request a new code.")

        # Only check the code when the form contains valid 6-digit input.
        elif form.is_valid():
            # Count this submission as one attempt before checking the code.
            otp.attempts += 1
            otp.save(update_fields=["attempts"])

            if check_password(form.cleaned_data["code"], otp.code_hash):
                # Delete the code after successful use so it cannot be reused.
                otp.delete()
                request.session.pop("otp_user_id", None)
                request.session.pop("otp_purpose", None)

                if purpose == OTP.Purpose.REGISTER:
                    # Mark a newly registered account as verified and log it in.
                    user.is_verified = True
                    user.save(update_fields=["is_verified"])
                    request.session["user_id"] = user.pk
                    request.session["user_type"] = get_user_type(user)
                    request.session["username"] = user.first_name or user.username
                    return redirect(home_for(request.session["user_type"]))

                # A password-reset OTP leads to the change-password page.
                request.session["password_reset_user_id"] = user.pk
                request.session["password_reset_step"] = "password"
                request.session["password_reset_verified"] = True
                return redirect("user:forgot_password")

            # Keep the form on the page and show an error for a wrong code.
            form.add_error("code", "That code is incorrect.")

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "email": user.email,
                "purpose": purpose,
            },
        )


class ResendOTPView(View):
    def post(self, request, *args, **kwargs):
        # Find the user and the type of OTP that needs to be sent again.
        user_id = request.session.get("otp_user_id")
        purpose = request.session.get("otp_purpose")
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None or purpose not in (
            OTP.Purpose.REGISTER,
            OTP.Purpose.PASSWORD_RESET,
        ):
            return redirect("user:login")

        # Get the newest OTP to check when the last code was sent.
        otp = OTP.objects.filter(
            user=user,
            purpose=purpose,
        ).order_by("-created_at").first()

        # Prevent repeated resend requests within 30 seconds.
        if otp and timezone.now() - otp.created_at < timedelta(seconds=30):
            return render(
                request,
                "user/verify_otp.html",
                {
                    "form": OTPForm(),
                    "email": user.email,
                    "purpose": purpose,
                    "status_message": "Please wait 30 seconds before requesting another code.",
                },
            )

        # The cooldown has ended, so create and send a new code.
        send_otp_code(user, purpose)
        return redirect("user:verify_otp")


# FORGOT PASSWORD

class ForgotPasswordView(View):
    template_name = "user/forgot_password.html"

    def get(self, request, *args, **kwargs):
        # Decide which page to show: enter email or set a new password.
        step = request.session.get("password_reset_step", "email")
        if step not in {"email", "password"}:
            step = "email"
        if step == "password" and not request.session.get("password_reset_verified"):
            step = "email"
        if step == "email":
            form = ForgotPasswordEmailForm()
        else:
            form = ResetPasswordForm()
        return render(
            request,
            self.template_name,
            {"step": step, "form": form},
        )

    def post(self, request, *args, **kwargs):
        # Read the current step saved in the user's session.
        step = request.session.get("password_reset_step", "email")

        if step == "email":
            # Check the email entered by the user.
            form = ForgotPasswordEmailForm(request.POST)
            if form.is_valid():
                # Find an active account with the submitted email.
                user = User.objects.filter(
                    email__iexact=form.cleaned_data["email"],
                    is_active=True,
                ).first()
                if user is None:
                    form.add_error(
                        "email", "We couldn't find an active account with that email."
                    )
                else:
                    # Send the user to the shared OTP verification page.
                    send_otp_code(user, OTP.Purpose.PASSWORD_RESET)
                    request.session["otp_user_id"] = user.pk
                    request.session["otp_purpose"] = OTP.Purpose.PASSWORD_RESET
                    return redirect("user:verify_otp")
            return render(request, self.template_name, {"step": "email", "form": form})

        user_id = request.session.get("password_reset_user_id")
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            # Clear incomplete reset details if the user no longer exists.
            request.session.pop("password_reset_user_id", None)
            request.session.pop("password_reset_step", None)
            request.session.pop("password_reset_verified", None)
            return redirect("user:forgot_password")

        if step == "password":
            # Only allow this page after the shared OTP page verified the code.
            if not request.session.get("password_reset_verified"):
                return redirect("user:forgot_password")

            # Check the new password and confirmation entered by the user.
            form = ResetPasswordForm(request.POST)
            if form.is_valid():
                # Hash the new password before saving it in the database.
                user.password = make_password(form.cleaned_data["password"])
                user.save(update_fields=["password"])

                # Delete any remaining reset code after the password changes.
                OTP.objects.filter(
                    user=user,
                    purpose=OTP.Purpose.PASSWORD_RESET,
                ).delete()

                # Clear the reset session so the flow cannot be reused.
                request.session.pop("password_reset_user_id", None)
                request.session.pop("password_reset_step", None)
                request.session.pop("password_reset_verified", None)
                messages.success(
                    request, "Your password has been changed. You can now log in."
                )
                return redirect("user:login")
            return render(
                request, self.template_name, {"step": "password", "form": form}
            )

        request.session.pop("password_reset_user_id", None)
        request.session.pop("password_reset_step", None)
        request.session.pop("password_reset_verified", None)
        return redirect("user:forgot_password")


# LOGOUT AND CUSTOMER HOME

class LogoutView(View):
    def get(self, request, *args, **kwargs):
        # clears all session data
        request.session.flush()
        return redirect("/user/login/")

class CustomerHomeView(View):
    """customer home. The middleware has already checked the login."""

    template_name = "user/home.html"

    def get(self, request, *args, **kwargs):
        customer = Customer.objects.get(pk=request.session["user_id"])

        upcoming = (
            Booking.objects.filter(_current_bookings(), customer=customer)
            .select_related("pet", "slot__service", "slot__outlet")
            .order_by("slot__start_time")
        )

        context = {
            "customer": customer,
            "pets": customer.pets.all(),
            "upcoming_bookings": upcoming,
        }
        return render(request, self.template_name, context)


# CUSTOMER PROFILE

# used in BookingListView to filter bookings into current/upcoming vs past
# used in CustomerHomeView to filter upcoming bookings for the dashboard
def _current_bookings():
    return Q(status__in=Booking.IN_CARE_STATUSES) | Q(
        status__in=Booking.BOOKED_STATUSES, slot__start_time__gte=timezone.now()
    )

class CustomerProfileView(View):
    template_name = "user/profile.html"

    def get(self, request, *args, **kwargs):
        # Load the customer who is logged in from the session.
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "form": ProfileForm(instance=customer),
                "password_form": PasswordChangeForm(),
            },
        )

    def post(self, request, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])

        if request.POST.get("action") == "change_password":
            password_form = PasswordChangeForm(request.POST)
            if password_form.is_valid() and check_password(
                password_form.cleaned_data["current_password"],
                customer.password,
            ):
                customer.password = make_password(
                    password_form.cleaned_data["new_password"]
                )
                customer.save(update_fields=["password"])
                messages.success(request, "Your password has been updated.")
                return redirect("user:profile")
            if password_form.is_valid():
                password_form.add_error(
                    "current_password", "Your current password is incorrect."
                )
            return render(
                request,
                self.template_name,
                {
                    "customer": customer,
                    "form": ProfileForm(instance=customer),
                    "password_form": password_form,
                },
            )

        # Bind the submitted values to the logged-in customer's existing record.
        form = ProfileForm(request.POST, instance=customer)

        if form.is_valid():
            # Save the updated profile details.
            form.save()
            request.session["username"] = customer.first_name or customer.username
            messages.success(request, "Your profile has been updated.")
            return redirect("user:profile")

        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "form": form,
                "password_form": PasswordChangeForm(),
            },
        )


# CUSTOMER ADDRESSES

class AddAddressView(View):
    template_name = "user/add_address.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"form": AddressForm()})

    def post(self, request, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        form = AddressForm(request.POST)

        if form.is_valid():
            address = form.save(commit=False)
            address.customer = customer

            # Only one address can be the default address for this customer.
            if address.is_default:
                customer.addresses.update(is_default=False)

            address.save()
            messages.success(request, "Your address has been added.")
            return redirect("user:profile")

        return render(request, self.template_name, {"form": form})


# CUSTOMER PET PROFILES

# Customer bookings
class BookingListView(View):

    template_name = "user/bookings.html"

    def get(self, request, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])

        bookings = (
            Booking.objects.filter(customer=customer)
            .select_related("pet", "slot__service", "slot__outlet")
        )
        current_bookings = _current_bookings()
        upcoming_bookings = list(bookings.filter(current_bookings).order_by("slot__start_time"))

        # Completed and Cancelled statuses
        past_bookings = list(bookings.exclude(current_bookings).order_by("-slot__start_time"))

        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "upcoming_bookings": upcoming_bookings,
                "past_bookings": past_bookings  ,
                "active_account_page": "bookings",
            },
        )

class BookingDetailView(View):

    template_name = "user/booking_detail.html"

    def get(self, request, booking_id, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])

        booking = get_object_or_404(
            Booking.objects.select_related("pet", "slot__service", "slot__outlet"),
            pk=booking_id,
            customer=customer,
        )
        # Get the most recent payment for this booking
        payment = booking.payments.order_by("-created_at").first()

        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "booking": booking,
                "payment": payment,
                "price_dollars": booking.price_cents / 100,
                "discount_dollars": booking.points_discount_cents / 100,
                "total_dollars": booking.total_cents / 100,
                "points_earned": points_earned(booking.total_cents),
                "active_account_page": "bookings",
            },
        )

class PetListView(View):
    template_name = "user/pets.html"

    def get(self, request, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "pets": customer.pets.all().order_by("name"),
                "active_account_page": "pets",
            },
        )


class AddPetView(View):
    template_name = "user/pet_form.html"

    def get(self, request, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "form": PetForm(),
                "active_account_page": "pets",
            },
        )

    def post(self, request, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        form = PetForm(request.POST, request.FILES)
        if form.is_valid():
            pet = form.save(commit=False)
            pet.owner_id = customer
            pet.save()
            messages.success(request, "Your pet has been added.")
            return redirect("user:pets")
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "form": form,
                "active_account_page": "pets",
            },
        )


class EditPetView(View):
    template_name = "user/pets.html"

    def get_pet(self, request, pet_id):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        pet = get_object_or_404(Pet, pk=pet_id, owner_id=customer)
        return customer, pet

    def get(self, request, pet_id, *args, **kwargs):
        customer, pet = self.get_pet(request, pet_id)
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "pets": customer.pets.all().order_by("name"),
                "form": PetForm(instance=pet),
                "editing_pet": pet,
                "active_account_page": "pets",
            },
        )

    def post(self, request, pet_id, *args, **kwargs):
        customer, pet = self.get_pet(request, pet_id)
        form = PetForm(request.POST, request.FILES, instance=pet)
        if form.is_valid():
            form.save()
            messages.success(request, "Your pet profile has been updated.")
            return redirect("user:pets")
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "pets": customer.pets.all().order_by("name"),
                "form": form,
                "editing_pet": pet,
                "active_account_page": "pets",
            },
        )


class DeletePetView(View):
    def post(self, request, pet_id, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        pet = get_object_or_404(Pet, pk=pet_id, owner_id=customer)
        pet.delete()
        messages.success(request, "Your pet has been deleted.")
        return redirect("user:pets")


# ADDRESS EDITING

class EditAddressView(View):
    template_name = "user/add_address.html"

    def get(self, request, address_id, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        address = get_object_or_404(
            customer.addresses,
            pk=address_id,
        )
        return render(
            request,
            self.template_name,
            {"form": AddressForm(instance=address), "edit_mode": True},
        )

    def post(self, request, address_id, *args, **kwargs):
        customer = get_object_or_404(Customer, pk=request.session["user_id"])
        address = get_object_or_404(
            customer.addresses,
            pk=address_id,
        )
        form = AddressForm(request.POST, instance=address)

        if form.is_valid():
            updated_address = form.save(commit=False)
            if updated_address.is_default:
                customer.addresses.exclude(pk=address.pk).update(is_default=False)
            updated_address.save()
            messages.success(request, "Your address has been updated.")
            return redirect("user:profile")

        return render(
            request,
            self.template_name,
            {"form": form, "edit_mode": True},
        )


# REDIRECT USERS TO THE CORRECT HOME PAGE

def home_for(user_type):
    """Where each type of user lands after logging in."""
    return {
        "customer": "/user/home/",
        "staff": "/admin-panel/",
        "owner": "/admin-panel/",
        "sitter": "/sitting/jobs/",
    }.get(user_type, "/")


# CART

def cart(request):
    customer = get_object_or_404(Customer, pk=request.session.get("user_id"))
    cart_items = CartItem.objects.select_related("product").filter(customer=customer)
    subtotal_cents = sum(item.line_total_cents for item in cart_items)

    return render(
        request,
        "user/cart.html",
        {
            "active_page": "cart",
            "cart_items": cart_items,
            "subtotal_cents": subtotal_cents,
            "subtotal_dollars": subtotal_cents / 100,
        },
    )


# Add a product to the customer's cart
def add_to_cart(request, product_id):
    # Check if the user is authenticated as customer
    if (
        "user_id" not in request.session
        or request.session.get("user_type") != "customer"
    ):
        messages.error(
            request, "You must be logged in as a customer to add items to the cart!"
        )
        return redirect("user:login")

    # Get customer id from session
    customer = get_object_or_404(Customer, pk=request.session.get("user_id"))

    # Get product if active
    product = get_object_or_404(Product, pk=product_id, is_active=True)

    # Check if item is already in cart
    item = CartItem.objects.filter(customer=customer, product=product).first()

    if item:
        # Existing item: Add 1 to current quantity (capped by stock)
        new_quantity = item.quantity + 1
        item.quantity = min(new_quantity, product.stock_quantity)
        item.save(update_fields=["quantity"])
    else:
        # New item: Create with a quantity of 1 (capped by stock)
        CartItem.objects.create(
            customer=customer,
            product=product,
            quantity=min(1, product.stock_quantity),
        )

    messages.success(request, f"Added {product.name} to your cart.")
    return redirect("user:customer_cart")


# Increase the quantity of a cart item by one
def increment_cart_item(request, item_id):
    if (
        "user_id" not in request.session
        or request.session.get("user_type") != "customer"
    ):
        messages.error(
            request, "You must be logged in as a customer to update your cart."
        )
        return redirect("user:login")

    item = get_object_or_404(
        CartItem.objects.select_related("product"),
        pk=item_id,
        customer_id=request.session[
            "user_id"
        ],  # ensures only customer can edit own cart
    )

    # Check stock availability before saving the incremented quantity
    if item.quantity >= item.product.stock_quantity:
        messages.error(
            request,
            "You've reached the maximum available stock for this item",
        )
    else:
        item.quantity += 1
        item.save(update_fields=["quantity"])

    return redirect("user:customer_cart")


# Decrease the quantity of a cart item by one
def decrement_cart_item(request, item_id):
    if (
        "user_id" not in request.session
        or request.session.get("user_type") != "customer"
    ):
        messages.error(
            request, "You must be logged in as a customer to update your cart."
        )
        return redirect("user:login")

    # Get the cart item user clicked on
    item = get_object_or_404(
        CartItem.objects.select_related("product"),
        pk=item_id,
        customer_id=request.session[
            "user_id"
        ],  # ensures only customer can edit own cart
    )

    # Check stock availability before saving the decremented quantity
    if item.quantity > 1:
        item.quantity -= 1
        item.save(update_fields=["quantity"])
    else:
        item.delete()

    return redirect("user:customer_cart")
