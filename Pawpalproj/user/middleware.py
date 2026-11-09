from django.shortcuts import redirect

# URL prefix -> which user types may open it
PROTECTED_PATHS = {
    "/user/home/": ["customer"],
    "/user/profile/": ["customer"],
    "/user/profile/address/": ["customer"],
    "/user/pets/": ["customer"],
    "/user/bookings/": ["customer"],
    "/user/orders/": ["customer"],
    "/user/cart/": ["customer"],
    "/inventory/staff/": ["staff", "owner"],
    "/inventory/stock/": ["staff", "owner"],
    "/service/book/": ["customer"],
    "/admin-panel/": ["staff", "owner"],
    "/sitting/jobs/": ["sitter"],
}


def login_required_middleware(get_response):
    # One-time configuration and initialisation.

    def middleware(request):
        # Code executed for each request BEFORE the view is called.
        for prefix, allowed_types in PROTECTED_PATHS.items():
            if request.path.startswith(prefix):
                if "user_id" not in request.session:
                    return redirect("/user/login/")  # not logged in
                if request.session.get("user_type") not in allowed_types:
                    return redirect("/")  # logged in, wrong role
                break

        response = get_response(request)

        # Code executed for each request/response AFTER the view is called.
        return response

    return middleware
