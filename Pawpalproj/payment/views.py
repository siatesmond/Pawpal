from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from inventory.models import CartItem, Order, OrderItem, Product
from user.models import Address, Customer
from .models import Payment, PointsTransaction

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
                    #Calculate subtotal and total
                    subtotal_cents = sum(item.product.price_cents * item.quantity for item in cart_items)

                    use_points = form.cleaned_data.get("use_points")
                    points_to_redeem = form.cleaned_data.get("points_to_redeem") or 0   

                    current_balance = customer.points_transactions.aggregate(total=Sum("points"))["total"] or 0
                    if use_points:
                        # Ensure points to redeem never exceeds actual available balance
                        points_to_redeem = min(points_to_redeem, current_balance)
                    else:
                        points_to_redeem = 0

                    points_discount_cents = 0
                    if use_points and points_to_redeem > 0:
                        raw_discount_cents = points_to_redeem * 1
                        points_discount_cents = min(raw_discount_cents, subtotal_cents)

                    total_cents = subtotal_cents - points_discount_cents
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
                        total_cents=total_cents,
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

                    # Create Payment Record
                    payment = Payment.objects.create(
                        customer=customer,
                        order=order,
                        amount_cents=order.total_cents,
                        method=form.cleaned_data["payment_method"],
                        card_number=card_num,
                        status=Payment.Status.COMPLETED,
                    )

                    # 7. Record REDEEMED Points Transaction (Must be negative per check constraint)
                    if points_discount_cents > 0 and points_to_redeem > 0:
                        PointsTransaction.objects.create(
                            customer=customer,
                            points=-points_to_redeem,
                            transaction_type=PointsTransaction.Type.REDEEMED,
                            payment=payment,
                            reason=f"Redeemed on Order #{order.pk}",
                        )

                    # 8. Record EARNED Points Transaction (10 points per $1 spent on cash total)
                    points_earned = (total_cents // 100) * 10
                    if points_earned > 0:
                        PointsTransaction.objects.create(
                            customer=customer,
                            points=points_earned,
                            transaction_type=PointsTransaction.Type.EARNED,
                            payment=payment,
                            reason=f"Earned from Order #{order.pk}",
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
        "points_discount_dollars": 0,
        "points_earned": (subtotal_cents // 100) * 10,
        "total_dollars": subtotal_cents / 100,
    }
    return render(request, "payment/checkout.html", checkout_context)


def checkout_success(request):
    return render(request, "payment/checkout_success.html")
