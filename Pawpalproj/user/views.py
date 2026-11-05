import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from service.models import Booking

from .forms import LoginForm, OTPForm, RegisterForm
from .models import OTP, Customer, User


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


def send_otp_code(user):
    """Delete expired/old codes, save a new hashed code and email it to the user."""

    # remove all expired codes, and this user's old code
    OTP.objects.filter(expires_at__lt=timezone.now()).delete()
    OTP.objects.filter(user=user, purpose=OTP.Purpose.REGISTER).delete()

    code = f"{secrets.randbelow(1_000_000):06d}"  # e.g. "048213"

    OTP.objects.create(
        user=user,
        purpose=OTP.Purpose.REGISTER,
        code_hash=make_password(code),  # store the hash, not the real code
        expires_at=timezone.now() + timedelta(minutes=OTP.VALID_MINUTES),
    )

    send_mail(
        "Your Pawpal verification code",
        f"Hi {user.first_name or user.username},\n\n"
        f"Your Pawpal code is: {code}\n\n"
        f"It expires in {OTP.VALID_MINUTES} minutes.\n\n— The Pawpal team",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


class LoginView(View):

    form_class = LoginForm
    template_name = "user/login.html"

    def get(self, request, *args, **kwargs):

        # already logged in -> go straight to the right page
        if request.session.get("user_type"):

            return redirect(home_for(request.session["user_type"]))

        form = self.form_class()
        rendered_form = form.render("user/form_template.html")

        context = {
            "form": rendered_form,
            "status_type": None,
            "status_message": None,
        }

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):

        form = self.form_class(request.POST)
        status_type = None
        status_message = None

        if form.is_valid():

            user = form.cleaned_data["user"]

            # not verified yet -> email a new code and go to the verify page
            if not user.is_verified:

                send_otp_code(user)
                request.session["verify_user_id"] = user.pk

                return redirect("/user/verify/")

            # store the login in the session
            request.session["user_id"] = user.pk
            request.session["user_type"] = get_user_type(user)
            request.session["username"] = user.first_name or user.username

            if not form.cleaned_data["remember"]:

                request.session.set_expiry(0)  # ends when the browser is closed

            return redirect(home_for(request.session["user_type"]))

        else:

            status_type = "error"

            if form.non_field_errors():

                status_message = "Incorrect email or password."

            else:

                status_message = "Please enter a valid email and password."

        # keep the typed email and show field errors
        rendered_form = form.render("user/form_template.html")

        context = {
            "form": rendered_form,
            "status_type": status_type,
            "status_message": status_message,
        }

        return render(request, self.template_name, context)


class RegisterView(View):

    form_class = RegisterForm
    template_name = "user/register.html"

    def get(self, request, *args, **kwargs):

        form = self.form_class()
        rendered_form = form.render("user/form_template.html")

        context = {
            "form": rendered_form,
            "status_type": None,
            "status_message": None,
        }

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):

        form = self.form_class(request.POST)
        status_type = None
        status_message = None

        if form.is_valid():

            try:

                customer = form.save()  # is_verified is False by default

                # email the code and remember who is verifying
                send_otp_code(customer)
                request.session["verify_user_id"] = customer.pk

                return redirect("/user/verify/")

            except Exception as e:

                status_type = "error"
                status_message = f"Error creating account: {e!s}"

        else:

            status_type = "error"
            status_message = "Please correct the errors below."

        rendered_form = form.render("user/form_template.html")

        context = {
            "form": rendered_form,
            "status_type": status_type,
            "status_message": status_message,
        }

        return render(request, self.template_name, context)


class VerifyOTPView(View):

    form_class = OTPForm
    template_name = "user/verify_otp.html"

    def get_pending_user(self, request):
        """The user waiting to verify (saved in the session by register / login)."""
        user_id = request.session.get("verify_user_id")
        return User.objects.filter(pk=user_id).first() if user_id else None

    def get(self, request, *args, **kwargs):

        user = self.get_pending_user(request)

        if user is None:

            return redirect("/user/login/")

        form = self.form_class()
        rendered_form = form.render("user/form_template.html")

        message = request.session.pop("otp_message", None)  # read once, then remove

        context = {
            "form": rendered_form,
            "email": user.email,
            "status_type": "success" if message else None,
            "status_message": message,
        }

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):

        user = self.get_pending_user(request)

        if user is None:

            return redirect("/user/login/")

        form = self.form_class(request.POST)
        status_type = None
        status_message = None

        if form.is_valid():

            # remove all expired codes
            OTP.objects.filter(expires_at__lt=timezone.now()).delete()

            otp = OTP.objects.filter(user=user, purpose=OTP.Purpose.REGISTER).first()

            if otp is None:

                status_type = "error"
                status_message = "This code has expired. Please request a new one."

            elif otp.attempts >= OTP.MAX_ATTEMPTS:

                otp.delete()
                status_type = "error"
                status_message = "Too many wrong attempts. Please request a new code."

            elif check_password(form.cleaned_data["code"], otp.code_hash):

                otp.delete()  # used -> remove from db

                user.is_verified = True
                user.save(update_fields=["is_verified"])
                del request.session["verify_user_id"]

                # log them in straight away
                request.session["user_id"] = user.pk
                request.session["user_type"] = get_user_type(user)
                request.session["username"] = user.first_name or user.username

                return redirect(home_for(request.session["user_type"]))

            else:

                otp.attempts += 1
                otp.save(update_fields=["attempts"])
                status_type = "error"
                status_message = f"Incorrect code. {OTP.MAX_ATTEMPTS - otp.attempts} attempt(s) left."

            form = self.form_class()  # clear the box for the next try

        else:

            status_type = "error"
            status_message = "Please enter the 6-digit code from your email."

        rendered_form = form.render("user/form_template.html")

        context = {
            "form": rendered_form,
            "email": user.email,
            "status_type": status_type,
            "status_message": status_message,
        }

        return render(request, self.template_name, context)


class ResendOTPView(View):

    def post(self, request, *args, **kwargs):

        user_id = request.session.get("verify_user_id")
        user = User.objects.filter(pk=user_id).first() if user_id else None

        if user is None:

            return redirect("/user/login/")

        send_otp_code(user)  # old code is deleted, new one sent

        # show the message on the verify page after the redirect
        request.session["otp_message"] = "A new code has been sent to your email."

        return redirect("/user/verify/")


class LogoutView(View):
    def get(self, request, *args, **kwargs):
        request.session.flush()  # clears all session data (Lecture 7, slide 38)
        return redirect("/user/login/")


class CustomerHomeView(View):
    """customer home. The middleware has already checked the login."""

    template_name = "user/home.html"

    def get(self, request, *args, **kwargs):
        customer = Customer.objects.get(pk=request.session["user_id"])

        upcoming = (
            Booking.objects.filter(
                customer=customer, slot__start_time__gte=timezone.now()
            )
            .exclude(status="CANCELLED")
            .select_related("pet", "slot__service", "slot__outlet")
            .order_by("slot__start_time")
        )

        context = {
            "customer": customer,
            "pets": customer.pets.all(),
            "upcoming_bookings": upcoming,
        }
        return render(request, self.template_name, context)


def home_for(user_type):
    """Where each type of user lands after logging in."""
    return {
        "customer": "/user/home/",
        "staff": "/admin-panel/",
        "owner": "/admin-panel/",
        "sitter": "/sitting/jobs/",
    }.get(user_type, "/")
