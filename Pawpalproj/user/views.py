from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.views import View
from service.models import Booking

from .forms import LoginForm, RegisterForm
from .models import Customer
from inventory.models import CartItem, Product


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


# CART
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
        customer_id=request.session["user_id"], #ensures only customer can edit own cart
    )

    # Check stock availability before saving the incremented quantity
    if item.quantity >= item.product.stock_quantity:
        messages.error(
            request,
            f"You've reached the maximum available stock for this item",
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
        customer_id=request.session["user_id"], #ensures only customer can edit own cart
    )

    # Check stock availability before saving the decremented quantity
    if item.quantity > 1:
        item.quantity -= 1
        item.save(update_fields=["quantity"])
    else:
        item.delete()

    return redirect("user:customer_cart")
