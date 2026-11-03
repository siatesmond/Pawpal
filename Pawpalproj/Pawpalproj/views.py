from django.shortcuts import redirect, render
from user.views import home_for


def index(request):
    # logged in -> send them to their own home page
    user_type = request.session.get("user_type")
    if user_type:
        return redirect(home_for(user_type))

    # guest -> normal landing page (G1)
    return render(request, "index.html")
