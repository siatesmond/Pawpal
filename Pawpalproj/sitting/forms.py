from decimal import Decimal

from django import forms
from django.core.validators import FileExtensionValidator, RegexValidator

from user.forms import MOBILE_INPUT, PASSWORD_HELP, check_password_strength
from user.models import MOBILE_VALIDATOR, User, check_email_domain

from review.models import Review

from .models import PetSitter, SittingRequest, SittingUpdate
from .onemap import look_up_postal_code

# Forms in this file:
# SitterRegistrationForm  (pet sitter sign-up, also used to edit the application)
# SitterProfileForm       (Profile page: bio, area, experience, rate, ID document)
# SitterAccountForm       (Profile page: name, email, mobile)
# SittingUpdateForm       (My jobs: post a note or photo during a job)
# OwnerRatingForm         (My jobs: the sitter rates the pet owner after a job)
# SitterReviewForm        (a pet owner reviews the sitter after a job)


# Pet experience options shown as chips on sign-up and profile
PET_EXPERIENCE_CHOICES = [
    ("Dogs", "Dogs"),
    ("Cats", "Cats"),
    ("Small pets", "Small pets"),
    ("Senior pets", "Senior pets"),
    ("Medication", "Medication"),
    ("Puppies & kittens", "Puppies & kittens"),
]



def ticked_experience(sitter):
    # the chips to tick for what the sitter saved, e.g. "dogs, cats" -> ["Dogs", "Cats"]
    saved = []
    for item in sitter.pet_experience.split(","):
        saved.append(item.strip().lower())
    ticked = []
    for value, label in PET_EXPERIENCE_CHOICES:
        if value.lower() in saved:
            ticked.append(value)
    return ticked


class SitterRegistrationForm(forms.Form):
    full_name = forms.CharField(max_length=61)
    mobile = forms.CharField(max_length=8, widget=MOBILE_INPUT, help_text="8 digits, e.g. 91234567")
    email = forms.EmailField(validators=[check_email_domain])
    # Only the postal code is asked; the map position and area name come from OneMap
    postal_code = forms.CharField(
        max_length=6,
        label="Home postal code",
        help_text="Used to match you with nearby pet owners. Owners only see your area, not your postal code.",
        validators=[RegexValidator(r"^\d{6}$", "Enter a 6-digit Singapore postal code.")],
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "e.g. 529536"}),
    )
    password = forms.CharField(widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    experience_years = forms.IntegerField(min_value=0, max_value=80)
    daily_rate = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=8, decimal_places=2
    )
    pet_experience = forms.MultipleChoiceField(
        choices=PET_EXPERIENCE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    bio = forms.CharField(widget=forms.Textarea, max_length=2000)
    id_document = forms.FileField(
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "pdf"])
        ]
    )
    terms = forms.BooleanField(
        label="I agree to Pawpal's sitter terms and 10% service fee"
    )

    def __init__(self, *args, sitter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sitter = sitter

        # clearer labels and example text, the same style as the customer sign-up
        self.fields["full_name"].label = "Full name"
        self.fields["experience_years"].label = "Years of experience"
        self.fields["daily_rate"].label = "Daily rate (SGD)"
        self.fields["daily_rate"].help_text = "What you charge per day. You keep 90% after Pawpal's 10% fee."
        self.fields["pet_experience"].label = "Pets you can care for"
        self.fields["bio"].label = "About you"
        self.fields["bio"].help_text = "Tell pet owners about your experience and how you care for pets."
        self.fields["id_document"].label = "ID document"
        self.fields["id_document"].help_text = "NRIC or passport, as a PDF or photo (JPG, PNG), max 5 MB."
        placeholders = {
            "full_name": "e.g. Grace Koh",
            "mobile": "e.g. 91234567",
            "email": "name@example.com",
            "password": "Create a password",
            "confirm_password": "Type it again",
            "experience_years": "e.g. 3",
            "daily_rate": "e.g. 50.00",
            "bio": "e.g. I grew up with dogs and have looked after senior pets for 3 years...",
        }
        for name, text in placeholders.items():
            self.fields[name].widget.attrs["placeholder"] = text
        if sitter:
            for name in ("password", "confirm_password", "id_document", "terms"):
                self.fields[name].required = False
            self.initial.update(
                {
                    "full_name": f"{sitter.first_name} {sitter.last_name}".strip(),
                    "mobile": sitter.mobile,
                    "email": sitter.email,
                    "postal_code": sitter.postal_code,
                    "experience_years": sitter.experience_years,
                    "daily_rate": sitter.daily_rate_cents / 100,
                    "pet_experience": ticked_experience(sitter),
                    "bio": sitter.bio,
                    "terms": True,
                }
            )
            if sitter.id_document:
                self.initial["id_document"] = sitter.id_document

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        users = User.objects.filter(email__iexact=email)
        if self.sitter:
            users = users.exclude(pk=self.sitter.pk)
        if users.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        check_password_strength(password)
        return password

    def clean_mobile(self):
        # same rule as every other form: exactly 8 digits
        mobile = self.cleaned_data["mobile"].strip()
        MOBILE_VALIDATOR(mobile)
        return mobile

    def clean_postal_code(self):
        postal_code = self.cleaned_data["postal_code"]
        place = look_up_postal_code(postal_code)
        if place == {}:
            raise forms.ValidationError("We couldn't find this postal code. Please check it.")
        self.place = place  # None if OneMap could not be reached; we still save the postal code
        return postal_code

    def clean_id_document(self):
        document = self.cleaned_data.get("id_document")
        if document and document.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The ID document must be 5 MB or smaller.")
        return document

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        if password and password != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self):
        full_name = " ".join(self.cleaned_data["full_name"].split())
        first_name, *last_name = full_name.split(" ")

        if self.sitter:
            sitter = self.sitter
            sitter.email = self.cleaned_data["email"]
            sitter.first_name = first_name
            sitter.last_name = " ".join(last_name)
            sitter.mobile = self.cleaned_data["mobile"]
            if self.cleaned_data.get("password"):
                sitter.set_password(self.cleaned_data["password"])
        else:
            username = self.cleaned_data["email"].split("@", 1)[0]
            base_username = username
            suffix = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{suffix}"
                suffix += 1
            sitter = PetSitter(
                username=username,
                email=self.cleaned_data["email"],
                first_name=first_name,
                last_name=" ".join(last_name),
                mobile=self.cleaned_data["mobile"],
            )
            sitter.set_password(self.cleaned_data["password"])

        sitter.postal_code = self.cleaned_data["postal_code"]
        if self.place:
            sitter.latitude = self.place["latitude"]
            sitter.longitude = self.place["longitude"]
            sitter.service_area = self.place["area"]
        elif not sitter.service_area:
            sitter.service_area = "Singapore"  # OneMap was down; the next save fills in the real area
        sitter.experience_years = self.cleaned_data["experience_years"]
        sitter.daily_rate_cents = int(self.cleaned_data["daily_rate"] * 100)
        sitter.pet_experience = ", ".join(self.cleaned_data["pet_experience"])
        sitter.bio = self.cleaned_data["bio"]
        if self.cleaned_data.get("id_document"):
            sitter.id_document = self.cleaned_data["id_document"]
        sitter.application_status = PetSitter.Status.PENDING
        sitter.rejection_reason = ""
        sitter.save()
        return sitter


class SitterProfileForm(forms.Form):
    # What pet owners see. Only the postal code is typed; the map position
    # and area name come from OneMap.
    bio = forms.CharField(widget=forms.Textarea, max_length=2000, required=False)
    postal_code = forms.CharField(
        max_length=6,
        label="Home postal code",
        validators=[RegexValidator(r"^\d{6}$", "Enter a 6-digit Singapore postal code.")],
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "e.g. 529536"}),
    )
    experience_years = forms.IntegerField(label="Years of experience", min_value=0, max_value=80)
    pet_experience = forms.MultipleChoiceField(
        label="Pet experience",
        choices=PET_EXPERIENCE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    daily_rate = forms.DecimalField(
        label="Daily rate (SGD)", min_value=Decimal("0.01"), max_digits=8, decimal_places=2
    )
    id_document = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "pdf"])],
        widget=forms.FileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png", "hidden": True}),
    )

    def __init__(self, *args, sitter, **kwargs):
        super().__init__(*args, **kwargs)
        self.sitter = sitter
        self.place = None
        # fill the boxes with what is saved now
        self.initial = {
            "bio": sitter.bio,
            "postal_code": sitter.postal_code,
            "experience_years": sitter.experience_years,
            "pet_experience": ticked_experience(sitter),
            "daily_rate": sitter.daily_rate_cents / 100,
        }

    def clean_postal_code(self):
        postal_code = self.cleaned_data["postal_code"]
        # only ask OneMap when the postal code changed (or was never found)
        if postal_code != self.sitter.postal_code or self.sitter.latitude is None:
            place = look_up_postal_code(postal_code)
            if place == {}:
                raise forms.ValidationError("We couldn't find this postal code. Please check it.")
            if place is None:
                # keep the old postal code, so it never points to a different place than the saved map position
                raise forms.ValidationError("We couldn't check your postal code right now. Please try again.")
            self.place = place
        return postal_code

    def clean_id_document(self):
        document = self.cleaned_data.get("id_document")
        if document and document.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The ID document must be 5 MB or smaller.")
        return document

    def save(self):
        sitter = self.sitter
        sitter.bio = self.cleaned_data["bio"]
        sitter.postal_code = self.cleaned_data["postal_code"]
        if self.place:
            sitter.latitude = self.place["latitude"]
            sitter.longitude = self.place["longitude"]
            sitter.service_area = self.place["area"]
        sitter.experience_years = self.cleaned_data["experience_years"]
        sitter.daily_rate_cents = int(self.cleaned_data["daily_rate"] * 100)
        sitter.pet_experience = ", ".join(self.cleaned_data["pet_experience"])
        if self.cleaned_data["id_document"]:
            sitter.id_document = self.cleaned_data["id_document"]
        sitter.save()


class SitterAccountForm(forms.ModelForm):
    # Name, email and mobile on the sitter's Profile page
    class Meta:
        model = PetSitter
        fields = ["first_name", "last_name", "email", "mobile"]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email",
            "mobile": "Mobile number (8 digits)",
        }
        widgets = {"mobile": MOBILE_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True

    def clean_email(self):
        # saved in lowercase; no other account may use it
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email


class SittingUpdateForm(forms.ModelForm):
    # A note and/or photo the sitter posts while a job is in progress
    request_id = forms.ChoiceField(label="Job")

    class Meta:
        model = SittingUpdate
        fields = ["note", "photo"]
        labels = {"note": "Message", "photo": "Photo (optional)"}
        widgets = {
            "note": forms.Textarea(attrs={"placeholder": "How is the pet doing? e.g. walk, meals, mood..."}),
            "photo": forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp"}),
        }
        help_texts = {"photo": "JPG, PNG or WEBP, max 5 MB. It appears in the timeline after you post."}

    def __init__(self, *args, jobs, **kwargs):
        super().__init__(*args, **kwargs)
        # one option per job in progress, e.g. "Mochi · Amy · 10 Nov–14 Nov"
        choices = []
        for job in jobs:
            pet_names = []
            for pet in job.pets.all():
                pet_names.append(pet.name)
            label = f"{' + '.join(pet_names)} · {job.owner.first_name} · {job.start_date:%d %b}–{job.end_date:%d %b}"
            choices.append((job.pk, label))
        self.fields["request_id"].choices = choices

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Photo must be 5 MB or smaller.")
        return photo

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("note", "").strip() and not cleaned_data.get("photo"):
            raise forms.ValidationError("Add a message or photo before posting an update.")
        return cleaned_data


class OwnerRatingForm(forms.ModelForm):
    # The sitter rates the pet owner 1-5 stars after a completed job.
    # Stars are listed 5 to 1, so the CSS can colour the stars to the left.
    owner_rating = forms.TypedChoiceField(
        choices=[(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")],
        coerce=int,
        widget=forms.RadioSelect,
        error_messages={"required": "Choose a rating from 1 to 5 stars."},
    )

    class Meta:
        model = SittingRequest
        fields = ["owner_rating", "owner_feedback"]
        widgets = {
            "owner_feedback": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Optional: clear care notes? on time? easy to reach?"}
            ),
        }


class SitterReviewForm(forms.ModelForm):
    # 1-5 star rating, optional comment and optional photo
    RATING_CHOICES = [(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")]

    rating = forms.TypedChoiceField(
        choices=RATING_CHOICES,
        coerce=int,
        widget=forms.RadioSelect,  # shown as clickable stars in the template
        error_messages={"required": "Choose a rating from 1 to 5 stars."},
    )

    class Meta:
        model = Review
        fields = ["rating", "comment", "photo"]
        labels = {"comment": "Comment (optional)", "photo": "Photo (optional)"}
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3, "placeholder": "How was the sitter? e.g. sent daily photos, followed the feeding plan..."}),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        # only check new uploads (an old photo kept when editing is already saved)
        if photo and hasattr(photo, "size") and getattr(photo, "content_type", None) and photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The photo must be 5 MB or smaller.")
        return photo
