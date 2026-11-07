from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from inventory.models import CartItem, Order, OrderItem, Product
from user.models import Address, Customer

from .forms import CheckoutForm


def checkout(request):
    if (
        "user_id" not in request.session
        or request.session.get("user_type") != "customer"
    ):
        messages.error(request, "You must be logged in as a customer to check out.")
        return redirect("user:login")

    customer = get_object_or_404(Customer, pk=request.session["user_id"])

    # Calculate current loyalty points balance for context
    points_balance = customer.points_transactions.aggregate(total=Sum("points"))["total"] or 0

    if request.method == "POST":
        form = CheckoutForm(customer, request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Fetch cart items with locks only when processing POST
                cart_items = list(
                    CartItem.objects.select_for_update()
                    .select_related("product")
                    .filter(customer=customer)
                )

                if not cart_items:
                    messages.error(request, "Your cart is empty.")
                    return redirect("user:customer_cart")

                # Validate stock levels
                for item in cart_items:
                    if item.quantity > item.product.stock_quantity:
                        form.add_error(
                            None,
                            f"Stock for {item.product.name} is insufficient, please reduce the quantity.",
                        )
                        break  # Break to re-render form with errors
                else:
                    # No stock errors, proceed with order and payment creation
                    subtotal_cents = sum(item.product.price_cents * item.quantity for item in cart_items)
                    method = form.cleaned_data["delivery_method"]

                    delivery_address = None
                    delivery_line1 = ""
                    delivery_line2 = ""
                    delivery_postal_code = ""

                    if method == "delivery":
                        if form.cleaned_data.get("use_new_address"):
                            delivery_line1 = form.cleaned_data["new_address_line1"]
                            delivery_line2 = form.cleaned_data.get("new_address_line2", "")
                            delivery_postal_code = form.cleaned_data["new_address_postal_code"]

                            # Save the new address to user profile if checked
                            if form.cleaned_data.get("save_address"):
                                if form.cleaned_data.get("new_address_is_default"):
                                    customer.addresses.update(is_default=False)

                                delivery_address = Address.objects.create(
                                    customer=customer,
                                    label=form.cleaned_data["new_address_label"],
                                    line1=delivery_line1,
                                    line2=delivery_line2,
                                    postal_code=delivery_postal_code,
                                    is_default=form.cleaned_data.get("new_address_is_default", False),
                                )
                        else:
                            # Use selected saved address as delivery address in order table
                            delivery_address = form.cleaned_data.get("delivery_address")
                            if delivery_address:
                                delivery_line1 = delivery_address.line1
                                delivery_line2 = delivery_address.line2 or ""
                                delivery_postal_code = delivery_address.postal_code

                    # Create Order
                    order = Order.objects.create(
                        customer=customer,
                        delivery_address=delivery_address if method == "delivery" else None,
                        delivery_line1=delivery_line1,
                        delivery_line2=delivery_line2,
                        delivery_postal_code=delivery_postal_code,
                        pickup_outlet=form.cleaned_data.get("pickup_outlet") if method == "pickup" else None,
                        subtotal_cents=subtotal_cents,
                        total_cents=subtotal_cents,
                    )

                    # Create Order Items and decrease Stock
                    for item in cart_items:
                        product = item.product
                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            quantity=item.quantity,
                            unit_price_cents=product.price_cents,
                        )
                        product.stock_quantity -= item.quantity
                        product.save(update_fields=["stock_quantity"])

                    # Extract card details 
                    card_num = form.cleaned_data.get("card_number", "")
                    card_last4 = card_num[-4:] if card_num else ""

                    # Create Payment Record
                    payment = Payment.objects.create(
                        customer=customer,
                        order=order,
                        amount_cents=order.total_cents,
                        method=form.cleaned_data["payment_method"],
                        card_last4=card_last4,
                        status=Payment.Status.SUCCESS,
                    )

                    # Clear Cart
                    CartItem.objects.filter(customer=customer).delete()
                    return redirect("payment:checkout_success")
    else:
        form = CheckoutForm(customer)

    # Context for GET or failed POST validation
    cart_items = list(CartItem.objects.select_related("product").filter(customer=customer))
    subtotal_cents = sum(item.product.price_cents * item.quantity for item in cart_items)

    checkout_context = {
        "form": form,
        "cart_items": cart_items,
        "subtotal_dollars": subtotal_cents / 100,
        "points_balance": points_balance,
        "total_dollars": subtotal_cents / 100,
    }
    return render(request, "payment/checkout.html", checkout_context)


def checkout_success(request):
    return render(request, "payment/checkout_success.html")
