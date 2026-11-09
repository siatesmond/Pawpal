from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from inventory.models import CartItem, Order, OrderItem
from user.models import Address, Customer

from .forms import CheckoutForm
from .services import (
    bind_checkout_form,
    calculate_points_discount,
    checkout_totals,
    get_points_balance,
    record_payment,
)

# Checkout for the products shopping cart
def checkout(request):
    if (
        "user_id" not in request.session
        or request.session.get("user_type") != "customer"
    ):
        messages.error(request, "You must be logged in as a customer to check out.")
        return redirect("user:login")

    customer = get_object_or_404(Customer, pk=request.session["user_id"])
    points_balance = get_points_balance(customer)
    form, preview_points = bind_checkout_form(request, CheckoutForm, customer, points_balance)

    # Place order button clicked
    placing_order = request.POST.get("action") == "place_order"
    if placing_order and form.is_valid():
        with transaction.atomic(): # all or nothing
            # Lock the cart rows while the order is created
            cart_items = list(
                CartItem.objects.select_for_update()
                .select_related("product")
                .filter(customer=customer)
            )
            if not cart_items:
                messages.error(request, "Your cart is empty.")
                return redirect("user:customer_cart")

            # Stock check: if any product's quantity exceeds its stock, show an error
            short = next((i for i in cart_items if i.quantity > i.product.stock_quantity), None)
            if short:
                form.add_error(
                    None,
                    f"Stock for {short.product.name} is insufficient, please reduce the quantity.",
                )
            else:
                # All checks passed, create the order and record the payment
                order = _create_order(customer, form, cart_items)
                record_payment(
                    customer, form,
                    amount_cents=order.total_cents,
                    points_redeemed=order.points_discount_cents,
                    label=f"Order #{order.pk}",
                    order=order,
                )
                CartItem.objects.filter(customer=customer).delete()
                request.session["checkout_order_id"] = order.pk
                return redirect("payment:checkout_success")

    # Display the checkout page:
    # If the user clicked "Apply points", preview_points is set to the requested amount (capped at balance) and the summary shows the discount, but nothing is saved yet.
    # Place order clicked but failed validation
    # Place order pressed by short of stock
    cart_items = list(CartItem.objects.select_related("product").filter(customer=customer))
    subtotal_cents = sum(item.product.price_cents * item.quantity for item in cart_items)

    discount_cents = calculate_points_discount(subtotal_cents, preview_points, points_balance)

    return render(request, "payment/checkout.html", {
        "form": form,
        "cart_items": cart_items,
        "points_balance": points_balance,
        **checkout_totals(subtotal_cents, discount_cents),
    })

# Create and save an order from the cart items and the checkout form
def _create_order(customer, form, cart_items):
    data = form.cleaned_data
    subtotal_cents = sum(item.product.price_cents * item.quantity for item in cart_items)

    # Re-check the balance inside the transaction so points can't be spent twice
    discount_cents = calculate_points_discount(subtotal_cents, data.get("points_to_redeem") or 0, get_points_balance(customer))

    method = data["delivery_method"]
    delivery_address = None
    line1 = line2 = postal_code = ""
    if method == "delivery":
        if data.get("use_new_address"):
            line1 = data["new_address_line1"]
            line2 = data.get("new_address_line2", "")
            postal_code = data["new_address_postal_code"]

            # Save the new address to the profile if chosen, 
            # and set it as default if selected
            if data.get("save_address"):
                if data.get("new_address_is_default"):
                    customer.addresses.update(is_default=False)
                delivery_address = Address.objects.create(
                    customer=customer,
                    label=data["new_address_label"],
                    line1=line1,
                    line2=line2,
                    postal_code=postal_code,
                    is_default=data.get("new_address_is_default", False),
                )
        else:
            delivery_address = data.get("delivery_address")
            if delivery_address:
                line1 = delivery_address.line1
                line2 = delivery_address.line2 or ""
                postal_code = delivery_address.postal_code

    order = Order.objects.create(
        customer=customer,
        delivery_address=delivery_address,
        delivery_line1=line1,
        delivery_line2=line2,
        delivery_postal_code=postal_code,
        pickup_outlet=data.get("pickup_outlet") if method == "pickup" else None,
        subtotal_cents=subtotal_cents,
        points_discount_cents=discount_cents,
        total_cents=subtotal_cents - discount_cents,
    )

    for item in cart_items:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            unit_price_cents=item.product.price_cents,
        )
        item.product.stock_quantity -= item.quantity
        item.product.save(update_fields=["stock_quantity"]) # Update stock quantity after order is placed
    return order


def checkout_success(request):
    if (
        "user_id" not in request.session
        or request.session.get("user_type") != "customer"
    ):
        messages.error(request, "You must be logged in as a customer to view this page.")
        return redirect("user:login")

    customer = get_object_or_404(Customer, pk=request.session["user_id"])
    order_id = request.session.get("checkout_order_id")
    if order_id is None:
        messages.error(request, "No recent order was found.")
        return redirect("index")

    order = get_object_or_404(Order, pk=order_id, customer=customer)
    request.session.pop("checkout_order_id", None)

    return render(
        request,
        "payment/checkout_success.html",
        {
            "order": order,
            "total_dollars": order.total_cents / 100,
            "points_discount_dollars": order.points_discount_cents / 100,
        },
    )
