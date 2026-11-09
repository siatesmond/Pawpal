from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from user.models import OTP
from user.views import send_otp_code

from .forms import SitterRegistrationForm
from .models import PetSitter


class SitterSignupView(View):
    template_name = "sitting/signup.html"

    def get(self, request):
        sitter = self._current_sitter(request)
        return render(
            request,
            self.template_name,
            {"form": SitterRegistrationForm(sitter=sitter), "edit_mode": bool(sitter)},
        )

    def post(self, request):
        sitter = self._current_sitter(request)
        form = SitterRegistrationForm(request.POST, request.FILES, sitter=sitter)
        if form.is_valid():
            sitter = form.save()
            if request.session.get("user_type") == "sitter":
                return redirect("sitting:application_status")
            send_otp_code(sitter, OTP.Purpose.REGISTER)
            request.session["otp_user_id"] = sitter.pk
            request.session["otp_purpose"] = OTP.Purpose.REGISTER
            return redirect("user:verify_otp")
        return render(
            request,
            self.template_name,
            {"form": form, "edit_mode": bool(sitter)},
        )

    @staticmethod
    def _current_sitter(request):
        if request.session.get("user_type") != "sitter":
            return None
        return PetSitter.objects.filter(pk=request.session.get("user_id")).first()


class SitterApplicationStatusView(View):
    template_name = "sitting/application_status.html"

    def get(self, request):
        if request.session.get("user_type") != "sitter":
            return redirect("user:login")
        sitter = get_object_or_404(PetSitter, pk=request.session["user_id"])
        return render(request, self.template_name, {"sitter": sitter})
