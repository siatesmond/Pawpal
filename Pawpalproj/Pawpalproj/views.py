from django.shortcuts import redirect, render
from inventory.models import Product
from service.models import Service
from user.views import home_for


# photo for each service card on the landing page (in static/image/)
SERVICE_PHOTOS = {
    "Basic Bath & Brush": "image/service_bath.webp",
    "Full Grooming Package": "image/service_full_grooming.webp",
    "Daycare (Full Day)": "image/service_daycare.png",
    "Overnight Boarding": "image/service_boarding.webp",
}


def index(request):
    # logged in -> send them to their own home page
    user_type = request.session.get("user_type")
    if user_type:
        return redirect(home_for(user_type))

    # Guests see the public landing page with active services and products.
    services = list(Service.objects.filter(is_active=True).order_by("id")[:4])
    for service in services:
        service.photo = SERVICE_PHOTOS.get(service.name, "")
        service.price_from = service.price_cents // 100  # 4500 cents -> 45
        if service.duration_minutes is None:
            service.length = "Overnight"
        elif service.duration_minutes >= 120:
            service.length = f"{service.duration_minutes // 60} hours"
        else:
            service.length = f"{service.duration_minutes} min"

    return render(
        request,
        "index.html",
        {
            "services": services,
            "products": Product.objects.filter(is_active=True)
            .select_related("brand")
            .order_by("id")[:4],
        },
    )
