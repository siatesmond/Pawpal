# Makes the training data for the product recommender and saves it as a CSV.
#   python manage.py make_training_data
#   -> user/ml/pet_purchases.csv (one row per purchase)
#
# Pawpal only has a few real orders, so we make up realistic ones:
# real Singapore breeds with their normal weight, ages from puppy to senior,
# the health problems each breed is known for, and food allergies.
# Each pet's owner then buys a product, following simple shopping habits.

import csv
import math

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Product
from user import recommender

SEED = 42  # same random numbers every run, so the CSV can be made again

# breed: (pet type, how common, lightest and heaviest adult weight in kg, health problems it is known for)
BREEDS = {
    "Singapore Special (mixed)": ("DOG", 10, 12, 22, []),
    "Golden Retriever": ("DOG", 7, 25, 34, ["joint", "skin"]),
    "Labrador Retriever": ("DOG", 6, 25, 36, ["joint", "weight"]),
    "Poodle (Toy)": ("DOG", 8, 2, 4, ["dental", "eye"]),
    "Shih Tzu": ("DOG", 8, 4, 7, ["eye", "skin", "dental"]),
    "Maltese": ("DOG", 6, 2, 4, ["eye", "dental", "digestion"]),
    "Pomeranian": ("DOG", 6, 1.5, 3.5, ["dental", "calming"]),
    "Shiba Inu": ("DOG", 5, 8, 11, ["skin", "calming"]),
    "Corgi": ("DOG", 5, 10, 14, ["joint", "weight"]),
    "French Bulldog": ("DOG", 5, 8, 13, ["skin", "digestion"]),
    "Miniature Schnauzer": ("DOG", 4, 5, 9, ["digestion", "skin"]),
    "Beagle": ("DOG", 4, 9, 14, ["weight", "heart"]),
    "Dachshund": ("DOG", 4, 7, 12, ["joint", "weight"]),
    "Chihuahua": ("DOG", 3, 1.5, 3, ["dental", "heart", "calming"]),
    "Siberian Husky": ("DOG", 2, 18, 27, ["skin"]),
    "Domestic Short Hair": ("CAT", 14, 3.5, 5.5, ["hairball"]),
    "British Shorthair": ("CAT", 6, 4, 7, ["weight", "heart"]),
    "Persian": ("CAT", 5, 3.5, 5.5, ["eye", "hairball"]),
    "Ragdoll": ("CAT", 5, 4.5, 8, ["hairball", "heart"]),
    "Scottish Fold": ("CAT", 4, 3, 5.5, ["joint"]),
    "Maine Coon": ("CAT", 3, 5, 9, ["joint", "heart", "hairball"]),
    "Siamese": ("CAT", 3, 3, 5, ["dental", "calming"]),
    "Bengal": ("CAT", 3, 4, 6.5, ["digestion", "calming"]),
    "Sphynx": ("CAT", 1, 3, 5, ["skin", "dental"]),
}

PET_NAMES = [
    "Mochi", "Milo", "Luna", "Coco", "Bella", "Max", "Kopi", "Tofu", "Oreo", "Lucky",
    "Snowy", "Cookie", "Bobo", "Mimi", "Charlie", "Lucy", "Rocky", "Peanut", "Kaya",
    "Muffin", "Nala", "Simba", "Teddy", "Ginger", "Biscuit", "Pepper", "Momo", "Bao",
]

# most common food allergies first
ALLERGIES = ["chicken", "beef", "fish", "lamb", "dairy", "grain"]
ALLERGY_CHANCE = [0.40, 0.25, 0.12, 0.08, 0.08, 0.07]


def make_pet(rng):
    breeds = list(BREEDS)
    how_common = []
    for breed in breeds:
        how_common.append(BREEDS[breed][1])
    how_common = np.array(how_common, dtype=float)
    breed = breeds[rng.choice(len(breeds), p=how_common / how_common.sum())]
    pet_type, common, lightest, heaviest, breed_problems = BREEDS[breed]

    # most pets are young adults; a few are babies or very old
    if pet_type == "DOG":
        age = min(rng.gamma(2.2, 2.2), 16)
    else:
        age = min(rng.gamma(2.4, 2.6), 19)
    age = max(round(age, 1), 0.2)
    life_stage = recommender.life_stage_for(pet_type, age)

    # weight: babies are lighter, and about 1 in 6 adults is overweight
    weight = rng.uniform(lightest, heaviest)
    if age < 1:
        weight *= 0.3 + 0.7 * age
    overweight = age >= 1 and rng.random() < 0.17
    if overweight:
        weight *= rng.uniform(1.15, 1.35)
    weight = round(weight, 1)

    needs = set()
    for problem in breed_problems:
        if rng.random() < 0.45:
            needs.add(problem)
    if overweight:
        needs.add("weight")
    if life_stage == "SENIOR":
        for problem in ["joint", "dental", "heart"]:
            if rng.random() < 0.35:
                needs.add(problem)
    for problem in ["skin", "digestion", "calming"]:
        if rng.random() < 0.06:  # can happen to any pet
            needs.add(problem)
    if pet_type == "DOG":
        needs.discard("hairball")

    allergens = set()
    if rng.random() < 0.18:
        allergens.add(ALLERGIES[rng.choice(len(ALLERGIES), p=ALLERGY_CHANCE)])

    return {
        "name": PET_NAMES[rng.integers(len(PET_NAMES))],
        "pet_type": pet_type,
        "breed": breed,
        "age_years": age,
        "weight_kg": weight,
        "life_stage": life_stage,
        "needs": needs,
        "allergens": allergens,
    }


def want_score(pet, product, appeal):
    # How much this owner wants the product. A bigger score = picked more often.
    score = appeal[product["name"]]
    matched = pet["needs"] & product["care_tags"]
    score += 2.0 * len(matched)  # made for the pet's health problem
    if product["care_tags"] and not matched:
        score -= 0.6  # made for a problem the pet does not have
    if product["life_stage"] == pet["life_stage"]:
        score += 1.0  # made for the pet's age
    elif product["life_stage"] != "ALL":
        score -= 2.0  # puppy food for a senior dog
    if product["category"] == "Food":
        score += 0.6  # everyone needs food
    if product["category"] == "Accessories":
        score -= 0.6  # bigger, less frequent buys
    return score


def pick_product(pet, products, appeal, rng):
    # owners never buy food their pet is allergic to
    choices = []
    weights = []
    for product in products:
        if recommender.is_allowed(pet, product, set()):
            choices.append(product)
            weights.append(math.exp(want_score(pet, product, appeal)))
    weights = np.array(weights)
    return choices[rng.choice(len(choices), p=weights / weights.sum())]


class Command(BaseCommand):
    help = "Make realistic mock pets and purchases for training, saved as a CSV"

    def add_arguments(self, parser):
        parser.add_argument("--rows", type=int, default=10000)

    def handle(self, *args, **options):
        rng = np.random.default_rng(SEED)

        products = []
        for product in Product.objects.filter(pet_type__in=["DOG", "CAT"]).select_related("category"):
            products.append(recommender.product_info(product))
        if not products:
            raise CommandError("No products found. Load the seed data first (/loadData/).")

        # some products are simply liked more (taste, packaging, word of mouth)
        appeal = {}
        for product in products:
            appeal[product["name"]] = rng.normal(0, 0.7)

        recommender.ML_FOLDER.mkdir(parents=True, exist_ok=True)
        with open(recommender.DATA_PATH, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([
                "pet_id", "pet_name", "pet_type", "breed", "age_years", "weight_kg",
                "life_stage", "health_needs", "allergy", "product_bought",
            ])
            for pet_id in range(1, options["rows"] + 1):
                pet = make_pet(rng)
                product = pick_product(pet, products, appeal, rng)
                writer.writerow([
                    pet_id,
                    pet["name"],
                    pet["pet_type"],
                    pet["breed"],
                    pet["age_years"],
                    pet["weight_kg"],
                    pet["life_stage"],
                    ";".join(sorted(pet["needs"])),  # e.g. "joint;skin", empty when healthy
                    "".join(pet["allergens"]),
                    product["name"],
                ])

        self.stdout.write(self.style.SUCCESS(
            f"Saved {options['rows']} rows to {recommender.DATA_PATH}"
        ))
