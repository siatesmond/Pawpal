# Product recommender (Decision Tree)
#
# Same idea as the Decision Tree in the course notebook:
#   X = the pet's details (pet type, age, weight, life stage, health needs, allergy)
#   y = the product the owner bought for that pet
#
# Training: python manage.py make_training_data  -> user/ml/pet_purchases.csv
#           python manage.py train_recommender   -> user/ml/recommender.joblib
# This file turns a real pet into the same columns, asks the tree for each
# product's chance, then shows the top 3 that pass the safety rules.

from pathlib import Path

import joblib
import pandas as pd
from django.conf import settings
from django.utils import timezone

from inventory.models import CartItem, Order, OrderItem, Product

ML_FOLDER = Path(settings.BASE_DIR) / "user" / "ml"
DATA_PATH = ML_FOLDER / "pet_purchases.csv"
MODEL_PATH = ML_FOLDER / "recommender.joblib"
REPORT_PATH = ML_FOLDER / "report.txt"


# Pet health needs and the words in the pet's notes that point to them

# same tags staff can tick on a product
NEEDS = []
for value, label in Product.CARE_TAG_CHOICES:
    NEEDS.append(value)

NEED_WORDS = {
    "skin": ["skin", "itch", "rash", "dermatitis"],
    "joint": ["joint", "hip", "dysplasia", "arthritis", "stiff"],
    "dental": ["dental", "teeth", "tooth", "gum", "plaque"],
    "digestion": ["stomach", "digest", "diarrh", "vomit", "tummy"],
    "eye": ["eye", "tear"],
    "hairball": ["hairball"],
    "heart": ["heart", "cardiac"],
    "weight": ["overweight", "obese", "weight loss"],
    "calming": ["anxious", "anxiety", "nervous", "skittish", "stress"],
}

# words used in the reason line, e.g. "Because Mochi has sensitive skin"
NEED_REASONS = {
    "skin": "Because {name} has sensitive skin",
    "joint": "Supports {name}'s joints",
    "dental": "Helps with {name}'s dental care",
    "digestion": "Gentle on {name}'s stomach",
    "eye": "For {name}'s eye care",
    "hairball": "Helps {name} with hairballs",
    "heart": "Supports {name}'s heart health",
    "weight": "Helps {name} keep a healthy weight",
    "calming": "Helps {name} stay calm",
}

# food allergies we look for (in the allergies box and the notes)
ALLERGY_WORDS = ["chicken", "beef", "fish", "lamb", "turkey", "pork", "dairy", "egg", "grain"]

# used up and bought again; toys and accessories are bought once
CONSUMABLE_CATEGORIES = ["Food", "Treats", "Grooming", "Health"]

# used when a pet has no birthday or weight saved
DEFAULT_AGE = 4
DEFAULT_WEIGHT = {"DOG": 12, "CAT": 4.5}


# Small helpers

def split_tags(text):
    # "chicken, rice" -> {"chicken", "rice"}
    tags = set()
    for tag in text.lower().split(","):
        if tag.strip():
            tags.add(tag.strip())
    return tags


def pet_type_name(pet_type):
    if pet_type == "DOG":
        return "dog"
    return "cat"


def life_stage_for(pet_type, age_years):
    # puppy/kitten under 1; dogs are seniors from 7, cats from 10 (dogs age faster)
    if age_years < 1:
        return "YOUNG"
    senior_age = 7
    if pet_type == "CAT":
        senior_age = 10
    if age_years >= senior_age:
        return "SENIOR"
    return "ADULT"


def find_allergens(pet):
    # the allergies box, plus any sentence in the notes that mentions an allergy
    lines = [pet.allergies.lower()]
    notes = (pet.medical_notes + ". " + pet.conditions).lower()
    for sentence in notes.split("."):
        if "allerg" in sentence:
            lines.append(sentence)

    allergens = set()
    for line in lines:
        for word in ALLERGY_WORDS:
            if word in line:
                allergens.add(word)
    return allergens


# Turn database objects into plain dicts (the training data uses the same dicts)

def pet_profile(pet):
    text = " ".join(
        [pet.medical_notes, pet.allergies, pet.conditions, pet.medication, pet.behaviour_notes]
    ).lower()

    needs = set()
    for need in NEEDS:
        for word in NEED_WORDS[need]:
            if word in text:
                needs.add(need)

    age_years = DEFAULT_AGE
    if pet.date_of_birth:
        age_years = (timezone.localdate() - pet.date_of_birth).days / 365.25

    weight_kg = DEFAULT_WEIGHT[pet.pet_type]
    if pet.weight_kg:
        weight_kg = float(pet.weight_kg)

    life_stage = life_stage_for(pet.pet_type, age_years)
    if "senior" in text:
        life_stage = "SENIOR"

    return {
        "name": pet.name,
        "pet_type": pet.pet_type,
        "age_years": age_years,
        "weight_kg": weight_kg,
        "life_stage": life_stage,
        "needs": needs,
        "allergens": find_allergens(pet),
    }


def product_info(product):
    return {
        "id": product.pk,
        "name": product.name,
        "pet_type": product.pet_type,
        "category": product.category.name,
        "care_tags": split_tags(product.care_tags),
        "ingredients": product.ingredients.lower(),
        "life_stage": product.life_stage,
    }


# Pet -> one row of numbers for the tree
# Same as predict_classifier.ipynb: start with every column the tree was trained on,
# fill in the ones this pet has, and leave the rest as 0.

def pet_row(pet):
    row = {
        "age_years": pet["age_years"],
        "weight_kg": pet["weight_kg"],
        "pet_type_" + pet["pet_type"]: 1,
        "life_stage_" + pet["life_stage"]: 1,
    }
    for need in pet["needs"]:
        row["need_" + need] = 1
    for allergen in pet["allergens"]:
        row["allergy_" + allergen] = 1
    return row


def pet_features(pet, columns):
    row = pet_row(pet)
    values = {}
    for column in columns:
        values[column] = row.get(column, 0)
    return pd.DataFrame([values], columns=columns)


# Safety and business rules, checked after the model

def is_allowed(pet, product, bought_ids):
    if product["pet_type"] != pet["pet_type"]:
        return False

    # never suggest food that contains something the pet is allergic to
    for allergen in pet["allergens"]:
        if allergen in product["ingredients"]:
            return False

    # a toy or stroller is only bought once
    if product["id"] in bought_ids and product["category"] not in CONSUMABLE_CATEGORIES:
        return False
    return True


# One-line reason: the pet detail on the tree's path that matches the product

def make_reason(pet, product, path_columns):
    name = pet["name"]
    matched_needs = pet["needs"] & product["care_tags"]

    # 1. a health need the tree looked at, and the product is made for it
    for column in path_columns:
        if column.startswith("need_") and column[5:] in matched_needs:
            return NEED_REASONS[column[5:]].format(name=name)

    # 2. any health need the product is made for
    for need in NEEDS:
        if need in matched_needs:
            return NEED_REASONS[need].format(name=name)

    # 3. made for the pet's age
    if product["life_stage"] == pet["life_stage"]:
        if pet["life_stage"] == "SENIOR":
            return "Because " + name + " is a senior " + pet_type_name(pet["pet_type"])
        if pet["life_stage"] == "ADULT":
            return "Made for adult " + pet_type_name(pet["pet_type"]) + "s like " + name
        if pet["pet_type"] == "DOG":
            return "Made for puppies like " + name
        return "Made for kittens like " + name

    return "Popular with " + pet_type_name(pet["pet_type"]) + " owners like you"


def path_columns_for(model, columns, features):
    # the pet details the tree checked on its way to the answer (only the ones the pet has)
    used = []
    nodes = model.decision_path(features).indices
    for node in nodes:
        column_number = model.tree_.feature[node]
        if column_number >= 0:
            column = columns[column_number]
            if features.iloc[0][column] > 0 and column not in used:
                used.append(column)
    return used


def highest_chance_first(candidate):
    # sort order: biggest chance first; same chance -> smaller product id first
    chance, product_id, product, info = candidate
    return (-chance, product_id)


# Load the saved model once and keep it in memory

saved_model = None


def load_model():
    global saved_model
    if saved_model is None and MODEL_PATH.exists():
        saved_model = joblib.load(MODEL_PATH)
    return saved_model


def recommend_for_customer(customer, per_pet=3):
    # returns [{"pet": pet, "items": [{"pet", "product", "reason", "score"}, ...]}, ...]
    saved = load_model()
    if saved is None:
        return []  # model not trained yet: python manage.py train_recommender
    model = saved["model"]
    columns = saved["columns"]

    # products the customer bought before (for the "bought once" rule)
    bought_ids = set(
        OrderItem.objects.filter(order__customer=customer)
        .exclude(order__status=Order.Status.CANCELLED)
        .values_list("product_id", flat=True)
    )
    in_cart = set(CartItem.objects.filter(customer=customer).values_list("product_id", flat=True))

    # only products that are on sale and in stock
    products = (
        Product.objects.filter(is_active=True, stock_quantity__gt=0)
        .exclude(pk__in=in_cart)
        .select_related("category")
    )

    results = []
    shown = set()  # do not show the same product for two pets
    # recommendations are for dogs and cats only
    for pet in customer.pets.filter(pet_type__in=["DOG", "CAT"]):
        profile = pet_profile(pet)
        features = pet_features(profile, columns)

        # the tree's chance for every product, e.g. {"Royal Canin Kitten Dry Food 2kg": 0.31, ...}
        chances = {}
        product_chances = model.predict_proba(features)[0]
        for i in range(len(model.classes_)):
            chances[model.classes_[i]] = product_chances[i]
        path_columns = path_columns_for(model, columns, features)

        candidates = []
        for product in products:
            info = product_info(product)
            chance = chances.get(product.name, 0)
            if chance > 0 and product.pk not in shown and is_allowed(profile, info, bought_ids):
                candidates.append((chance, product.pk, product, info))
        candidates.sort(key=highest_chance_first)

        items = []
        for chance, pk, product, info in candidates[:per_pet]:
            shown.add(product.pk)
            items.append(
                {
                    "pet": pet,
                    "product": product,
                    "reason": make_reason(profile, info, path_columns),
                    "score": round(chance * 100),
                }
            )
        if items:
            results.append({"pet": pet, "items": items})

    return results
