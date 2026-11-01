from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from service.models import Booking

from .forms import LoginForm, RegisterForm
from .models import Customer


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


class LoginView(View):
    form_class = LoginForm
    template_name = "user/login.html"

    def get(self, request, *args, **kwargs):
        # already logged in -> go straight to the right page
        if "user_id" in request.session:
            return redirect(home_for(request.session.get("user_type")))
        return render(request, self.template_name, {"form": self.form_class()})

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)

        if form.is_valid():
            user = form.cleaned_data["user"]

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
            form.save()
            return redirect("/user/login/")
        return render(request, self.template_name, {"form": form})


class LogoutView(View):
    def get(self, request, *args, **kwargs):
        request.session.flush()  # clears all session data (Lecture 7, slide 38)
        return redirect("/user/login/")


class CustomerHomeView(View):
    """C1 – customer home. The middleware has already checked the login."""

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
