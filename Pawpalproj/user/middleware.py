from django.contrib import messages
from django.shortcuts import redirect

from .models import User
from .views import home_for

# User type -> the pages only that type can open.
# Any page not listed here (e.g. /, /user/login/, /loadData/) is open to everyone.
PROTECTED_PATHS = {
    # Customer pages
    "customer": [
        "/user/home/",
        "/user/profile/",
        "/user/pets/",
        "/user/bookings/",
        "/user/orders/",
        "/user/points/",
        "/user/cart/",
        "/service/book/",
        "/sitting/find/",
        "/sitting/sitters/",
        "/sitting/requests/",
    ],
    # Staff pages (the business owner can open them too)
    "staff": [
        "/inventory/staff/",
        "/inventory/stock/",
    ],
    # Business owner (admin) pages
    "owner": [
        "/admin-panel/",
        "/core/admin-panel/",
    ],
    # Pet sitter pages
    "sitter": [
        "/sitting/jobs/",
        "/sitting/my-jobs/",
        "/sitting/earnings/",
        "/sitting/profile/",
        "/sitting/application/",
    ],
}


def security_middleware(get_response):

    def middleware(request):

        # 1. Find which user type this page is for
        page_for = None
        for user_type, paths in PROTECTED_PATHS.items():
            for path in paths:
                if request.path.startswith(path):
                    page_for = user_type

        if page_for is not None:

            # 2. Not logged in (or the account was deactivated): go to the login page
            if not User.objects.filter(pk=request.session.get("user_id"), is_active=True).exists():
                if "user_id" in request.session:
                    request.session.flush()
                return redirect("/user/login/")

            # 3. Logged in as another user type: show an error and go back to their home page
            user_type = request.session.get("user_type")
            owner_on_staff_page = user_type == "owner" and page_for == "staff"
            if user_type != page_for and not owner_on_staff_page:
                messages.error(request, "That page isn't available for your account.")
                return redirect(home_for(user_type))

        # 4. Allowed: let the view run
        response = get_response(request)

        return response

    return middleware
