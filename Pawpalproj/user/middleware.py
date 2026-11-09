from django.shortcuts import redirect

from .models import User

# URL prefix -> which user types may open it
PROTECTED_PATHS = {
    "/user/home/": ["customer"],
    "/user/profile/": ["customer"],
    "/user/profile/address/": ["customer"],
    "/user/pets/": ["customer"],
    "/user/cart/": ["customer"],
    "/inventory/staff/": ["staff", "owner"],
    "/inventory/stock/": ["staff", "owner"],
    "/service/book/": ["customer"],
    # US-021: only the business owner can open the owner dashboard and accounts
    "/admin-panel/": ["owner"],
    "/core/admin-panel/": ["owner"],  # same pages through the old /core/ prefix
    "/sitting/jobs/": ["sitter"],
    "/sitting/my-jobs/": ["sitter"],
    "/sitting/earnings/": ["sitter"],
    "/sitting/profile/": ["sitter"],
    "/sitting/application/": ["sitter"],
}


def login_required_middleware(get_response):
    # One-time configuration and initialisation.

    def middleware(request):
        # Code executed for each request BEFORE the view is called.
        for prefix, allowed_types in PROTECTED_PATHS.items():
            if request.path.startswith(prefix):
                if "user_id" not in request.session:
                    return redirect("/user/login/")  # not logged in
                user = User.objects.filter(
                    pk=request.session.get("user_id"),
                    is_active=True,
                ).first()
                actual_type = get_user_type(user) if user else None
                if actual_type not in allowed_types:
                    request.session.flush()
                    return redirect("/user/login/")
                if request.session.get("user_type") != actual_type:
                    request.session["user_type"] = actual_type
                break

        response = get_response(request)

        # Code executed for each request/response AFTER the view is called.
        return response

    return middleware


def get_user_type(user):
    """Return the role represented by the user's multi-table child row."""
    if user is None:
        return None
    if hasattr(user, "customer"):
        return "customer"
    if hasattr(user, "staff"):
        return "staff"
    if hasattr(user, "businessowner"):
        return "owner"
    if hasattr(user, "petsitter"):
        return "sitter"
    return None
