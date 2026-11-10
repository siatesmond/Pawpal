from django.shortcuts import redirect, render
from inventory.models import Product
from service.models import Service
from user.views import home_for


def index(request):
    # logged in -> send them to their own home page
    user_type = request.session.get("user_type")
    if user_type:
        return redirect(home_for(user_type))

    # Guests see the public landing page with active services and products.
    return render(
        request,
        "index.html",
        {
            "services": Service.objects.filter(is_active=True).order_by("id")[:4],
            "products": Product.objects.filter(is_active=True)
            .select_related("brand")
            .order_by("id")[:4],
        },
    )
