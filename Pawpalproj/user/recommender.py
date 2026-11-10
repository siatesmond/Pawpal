# Product recommender (logistic regression)
#
# The same feature builder is used when training (management command
# train_recommender) and when showing recommendations on the customer home page,
# so the model always sees the features in the same order.

import math
from pathlib import Path

import joblib
import numpy as np
from django.conf import settings
from django.utils import timezone

from inventory.models import CartItem, Order, OrderItem, Product

MODEL_PATH = Path(settings.BASE_DIR) / "user" / "ml" / "recommender.joblib"
REPORT_PATH = Path(settings.BASE_DIR) / "user" / "ml" / "report.txt"


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

# ingredients we look for when a pet has a food allergy
ALLERGY_WORDS = ["chicken", "beef", "fish", "lamb", "turkey", "pork", "dairy", "egg", "grain"]

CATEGORIES = ["Food", "Treats", "Toys", "Accessories", "Grooming", "Health"]

# used up and bought again; toys and accessories are bought once
CONSUMABLE_CATEGORIES = ["Food", "Treats", "Grooming", "Health"]

RESTOCK_DAYS = 21  # a consumable bought this long ago is probably running out
RECENT_DAYS = 14  # bought this recently, probably still has plenty

FEATURE_NAMES = (
    ["need_" + need for need in NEEDS]
    + ["care_tag_not_needed", "life_stage_match", "life_stage_mismatch"]
    + ["category_" + category.lower() for category in CATEGORIES]
    + [
        "bought_before",
        "due_for_restock",
        "bought_recently",
        "already_owns_item",
        "likes_category",
        "likes_brand",
        "popularity",
        "price_gap",
    ]
)


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


def life_stage_of(pet):
    text = (pet.medical_notes + " " + pet.conditions).lower()
    if "senior" in text:
        return "SENIOR"
    if not pet.date_of_birth:
        return "ADULT"

    age = (timezone.localdate() - pet.date_of_birth).days / 365.25
    if age < 1:
        return "YOUNG"

    # dogs age faster than cats
    senior_age = 7
    if pet.pet_type == "CAT":
        senior_age = 10
    if age >= senior_age:
        return "SENIOR"
    return "ADULT"


def find_allergens(pet):
    # the allergies field, plus any sentence in the notes that mentions an allergy
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


# Turn database objects into plain dicts (training uses the same dicts)

def pet_profile(pet):
    text = " ".join(
        [pet.medical_notes, pet.allergies, pet.conditions, pet.medication, pet.behaviour_notes]
    ).lower()

    needs = set()
    for need in NEEDS:
        for word in NEED_WORDS[need]:
            if word in text:
                needs.add(need)

    return {
        "name": pet.name,
        "pet_type": pet.pet_type,
        "needs": needs,
        "allergens": find_allergens(pet),
        "life_stage": life_stage_of(pet),
    }


def product_info(product, popularity):
    return {
        "id": product.pk,
        "pet_type": product.pet_type,
        "category": product.category.name,
        "brand": product.brand.name,
        "care_tags": split_tags(product.care_tags),
        "ingredients": product.ingredients.lower(),
        "life_stage": product.life_stage,
        "price_cents": product.price_cents,
        "popularity": popularity.get(product.pk, 0.0),
    }


def product_popularity():
    # number of times each product was ordered, scaled so the best seller is 1.0
    counts = {}
    items = OrderItem.objects.exclude(order__status=Order.Status.CANCELLED)
    for item in items:
        counts[item.product_id] = counts.get(item.product_id, 0) + item.quantity

    if not counts:
        return {}
    highest = max(counts.values())
    popularity = {}
    for product_id, count in counts.items():
        popularity[product_id] = count / highest
    return popularity


def purchase_history(customer):
    days_since = {}  # product id -> days since the last time it was bought
    category_counts = {}
    brands = set()
    prices = []

    items = (
        OrderItem.objects.filter(order__customer=customer)
        .exclude(order__status=Order.Status.CANCELLED)
        .select_related("order", "product__category", "product__brand")
    )
    for item in items:
        days = (timezone.now() - item.order.created_at).days
        if item.product_id not in days_since or days < days_since[item.product_id]:
            days_since[item.product_id] = days

        category = item.product.category.name
        category_counts[category] = category_counts.get(category, 0) + 1
        brands.add(item.product.brand.name)
        prices.append(item.unit_price_cents)

    return make_history(days_since, category_counts, brands, prices)


def make_history(days_since, category_counts, brands, prices):
    average_price = None
    if prices:
        average_price = sum(prices) / len(prices)
    return {
        "days_since": days_since,
        "category_counts": category_counts,
        "total_items": sum(category_counts.values()),
        "brands": brands,
        "average_price": average_price,
    }


# Features for one (pet, product) pair

def build_features(pet, product, history):
    features = []

    # pet need x product care tag, e.g. pet has joint problems and product is for joints
    matched_needs = pet["needs"] & product["care_tags"]
    for need in NEEDS:
        features.append(1 if need in matched_needs else 0)

    # product is for a health need the pet does not have
    features.append(1 if product["care_tags"] and not matched_needs else 0)

    # pet life stage x product life stage (puppy food for a senior dog is a mismatch)
    if product["life_stage"] == "ALL":
        features.append(0)
        features.append(0)
    elif product["life_stage"] == pet["life_stage"]:
        features.append(1)
        features.append(0)
    else:
        features.append(0)
        features.append(1)

    for category in CATEGORIES:
        features.append(1 if product["category"] == category else 0)

    # repurchase timing
    consumable = product["category"] in CONSUMABLE_CATEGORIES
    days = history["days_since"].get(product["id"])
    bought_before = days is not None
    features.append(1 if bought_before else 0)
    features.append(1 if bought_before and consumable and days >= RESTOCK_DAYS else 0)
    features.append(1 if bought_before and days < RECENT_DAYS else 0)
    features.append(1 if bought_before and not consumable else 0)

    # what this customer usually buys
    if history["total_items"]:
        share = history["category_counts"].get(product["category"], 0) / history["total_items"]
    else:
        share = 0
    features.append(share)
    features.append(1 if product["brand"] in history["brands"] else 0)

    features.append(product["popularity"])

    # price fit: 0 when the price is close to what the customer normally pays
    if history["average_price"]:
        gap = abs(math.log(product["price_cents"] / history["average_price"]))
        features.append(min(gap, 3))
    else:
        features.append(0)

    return features


# Safety and business rules, checked after the model

def is_allowed(pet, product, history):
    if product["pet_type"] != pet["pet_type"]:
        return False

    # never suggest food that contains something the pet is allergic to
    for allergen in pet["allergens"]:
        if allergen in product["ingredients"]:
            return False

    # a toy or stroller is only bought once
    bought_before = product["id"] in history["days_since"]
    if bought_before and product["category"] not in CONSUMABLE_CATEGORIES:
        return False
    return True


# One-line reason taken from the feature that pushed the score up the most

def make_reason(pet, product, history, features, model):
    scaler = model.named_steps["scale"]
    classifier = model.named_steps["model"]
    scaled = (np.array(features) - scaler.mean_) / scaler.scale_
    weights = classifier.coef_[0]

    best_name = None
    best_value = 0
    for i, name in enumerate(FEATURE_NAMES):
        value = weights[i] * scaled[i]
        if features[i] > 0 and weights[i] > 0 and value > best_value:
            best_name = name
            best_value = value

    name = pet["name"]
    if best_name is None:
        return "A good match for " + name
    if best_name.startswith("need_"):
        return NEED_REASONS[best_name[5:]].format(name=name)
    if best_name == "life_stage_match":
        if pet["life_stage"] == "SENIOR":
            return "Because " + name + " is a senior " + pet_type_name(pet["pet_type"])
        if pet["life_stage"] == "ADULT":
            return "Made for adult " + pet_type_name(pet["pet_type"]) + "s like " + name
        if pet["pet_type"] == "DOG":
            return "Made for puppies like " + name
        return "Made for kittens like " + name
    if best_name == "due_for_restock":
        days = history["days_since"][product["id"]]
        return f"Time to restock, you last bought this {days} days ago"
    if best_name == "likes_category":
        return "You often buy " + product["category"].lower() + " at Pawpal"
    if best_name == "likes_brand":
        return "You have bought " + product["brand"] + " before"
    if best_name == "popularity":
        return "Popular with other " + pet_type_name(pet["pet_type"]) + " owners"
    return "A good match for " + name


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

    history = purchase_history(customer)
    popularity = product_popularity()
    in_cart = set(CartItem.objects.filter(customer=customer).values_list("product_id", flat=True))

    # only products that are on sale and in stock
    products = (
        Product.objects.filter(is_active=True, stock_quantity__gt=0)
        .exclude(pk__in=in_cart)
        .select_related("category", "brand")
    )

    results = []
    shown = set()  # do not show the same product for two pets
    # recommendations are for dogs and cats only
    for pet in customer.pets.filter(pet_type__in=["DOG", "CAT"]):
        profile = pet_profile(pet)

        candidates = []
        for product in products:
            info = product_info(product, popularity)
            if product.pk in shown or not is_allowed(profile, info, history):
                continue
            features = build_features(profile, info, history)
            candidates.append((product, info, features))

        if not candidates:
            continue

        rows = np.array([features for product, info, features in candidates])
        scores = model.predict_proba(rows)[:, 1]

        ranked = sorted(zip(scores, range(len(candidates))), reverse=True)
        items = []
        for score, i in ranked[:per_pet]:
            product, info, features = candidates[i]
            shown.add(product.pk)
            items.append(
                {
                    "pet": pet,
                    "product": product,
                    "reason": make_reason(profile, info, history, features, model),
                    "score": round(score * 100),
                }
            )
        results.append({"pet": pet, "items": items})

    return results
