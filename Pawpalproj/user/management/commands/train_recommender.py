# Trains the product recommender.
#   python manage.py train_recommender
#
# Pawpal only has a few real orders, so we make synthetic customers and pets,
# give each one a purchase history, and simulate what they buy next.
# The model then learns which (pet, product) pairs lead to a purchase.

import math
from datetime import datetime

import joblib
import numpy as np
from django.core.management.base import BaseCommand, CommandError
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, GroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from inventory.models import Product
from user import recommender

SEED = 42  # same random numbers every run, so results can be repeated


# Synthetic data

def make_fake_pet(rng):
    pet_type = rng.choice(["DOG", "CAT"])
    life_stage = rng.choice(["YOUNG", "ADULT", "SENIOR"], p=[0.2, 0.55, 0.25])

    needs = set()
    for need in recommender.NEEDS:
        chance = 0.12
        if life_stage == "SENIOR" and need in ["joint", "heart", "dental"]:
            chance = 0.4  # older pets have more joint, heart and teeth problems
        if need == "hairball" and pet_type != "CAT":
            chance = 0
        if rng.random() < chance:
            needs.add(need)

    allergens = set()
    if rng.random() < 0.2:
        allergens.add(rng.choice(["chicken", "beef", "fish", "lamb"]))

    return {
        "name": "Pet",
        "pet_type": pet_type,
        "needs": needs,
        "allergens": allergens,
        "life_stage": life_stage,
    }


def chance_to_buy(pet, product, history, appeal):
    # The hidden "real world" rule the model has to discover.
    # The model never sees this function, only the purchases it produces.
    score = -3.2 + appeal[product["id"]]
    matched = pet["needs"] & product["care_tags"]
    score += 2.0 * len(matched)
    if product["care_tags"] and not matched:
        score -= 0.6
    if product["life_stage"] == pet["life_stage"]:
        score += 1.0
    elif product["life_stage"] != "ALL":
        score -= 2.0
    if product["category"] == "Food":
        score += 0.6
    if product["category"] == "Accessories":
        score -= 0.6

    days = history["days_since"].get(product["id"])
    consumable = product["category"] in recommender.CONSUMABLE_CATEGORIES
    if days is not None:
        if not consumable:
            score -= 3.0
        elif days >= recommender.RESTOCK_DAYS:
            score += 1.8
        elif days < recommender.RECENT_DAYS:
            score -= 1.0

    if history["total_items"]:
        score += 1.5 * history["category_counts"].get(product["category"], 0) / history["total_items"]
    if product["brand"] in history["brands"]:
        score += 0.5
    if history["average_price"]:
        score -= 0.4 * abs(math.log(product["price_cents"] / history["average_price"]))

    for allergen in pet["allergens"]:
        if allergen in product["ingredients"]:
            return 0.0  # owners never buy food their pet is allergic to
    return 1 / (1 + math.exp(-score))


def make_dataset(products, customers, rng):
    # some products are simply liked more (taste, packaging, word of mouth)
    appeal = {}
    for product in products:
        appeal[product["id"]] = rng.normal(0, 0.7)

    # 1. past purchases for every fake customer
    people = []
    order_counts = {}
    for customer_id in range(customers):
        pet = make_fake_pet(rng)
        empty = recommender.make_history({}, {}, set(), [])
        days_since = {}
        category_counts = {}
        brands = set()
        prices = []

        matching = [p for p in products if p["pet_type"] == pet["pet_type"]]
        for i in range(rng.integers(0, 7)):
            weights = np.array([chance_to_buy(pet, p, empty, appeal) for p in matching])
            if weights.sum() == 0:
                break
            product = matching[rng.choice(len(matching), p=weights / weights.sum())]
            days = int(rng.integers(1, 120))
            if product["id"] not in days_since or days < days_since[product["id"]]:
                days_since[product["id"]] = days
            category_counts[product["category"]] = category_counts.get(product["category"], 0) + 1
            brands.add(product["brand"])
            prices.append(product["price_cents"])
            order_counts[product["id"]] = order_counts.get(product["id"], 0) + 1

        history = recommender.make_history(days_since, category_counts, brands, prices)
        people.append((customer_id, pet, history))

    # 2. popularity from those purchases, best seller = 1.0
    highest = max(order_counts.values())
    for product in products:
        product["popularity"] = order_counts.get(product["id"], 0) / highest

    # 3. one row per (customer, product): did they buy it in the next month?
    rows = []
    labels = []
    groups = []
    allowed = []
    popularity = []
    for customer_id, pet, history in people:
        for product in products:
            if product["pet_type"] != pet["pet_type"]:
                continue
            bought = rng.random() < chance_to_buy(pet, product, history, appeal)
            rows.append(recommender.build_features(pet, product, history))
            labels.append(1 if bought else 0)
            groups.append(customer_id)
            allowed.append(recommender.is_allowed(pet, product, history))
            popularity.append(product["popularity"])

    return (
        np.array(rows),
        np.array(labels),
        np.array(groups),
        np.array(allowed),
        np.array(popularity),
    )


# Precision@3: of the 3 products we would show, how many did the customer buy?

def precision_at_3(scores, labels, groups, allowed):
    results = []
    for customer_id in np.unique(groups):
        rows = np.where((groups == customer_id) & allowed)[0]
        if labels[rows].sum() == 0:
            continue  # bought nothing, cannot score this customer
        top = rows[np.argsort(-scores[rows])[:3]]
        results.append(labels[top].sum() / 3)
    return float(np.mean(results))


class Command(BaseCommand):
    help = "Train the logistic regression product recommender"

    def add_arguments(self, parser):
        parser.add_argument("--customers", type=int, default=3000)

    def handle(self, *args, **options):
        rng = np.random.default_rng(SEED)

        products = []
        # dogs and cats only
        dog_and_cat = Product.objects.filter(pet_type__in=["DOG", "CAT"])
        for product in dog_and_cat.select_related("category", "brand"):
            products.append(recommender.product_info(product, {}))
        if not products:
            raise CommandError("No products found. Load the seed data first (/core/loadData/).")

        X, y, groups, allowed, popularity = make_dataset(products, options["customers"], rng)

        # Train / test split by customer, so the test customers are never seen in training
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
        train, test = next(splitter.split(X, y, groups))

        # Scale the features, then tune C (regularisation) with 5-fold cross-validation
        pipeline = Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000)),
            ]
        )
        search = GridSearchCV(
            pipeline,
            {"model__C": [0.001, 0.01, 0.1, 1, 10]},
            scoring="roc_auc",
            cv=GroupKFold(n_splits=5),
        )
        search.fit(X[train], y[train], groups=groups[train])
        model = search.best_estimator_

        # Evaluate on the held-out test customers
        model_scores = model.predict_proba(X[test])[:, 1]
        model_auc = roc_auc_score(y[test], model_scores)
        baseline_auc = roc_auc_score(y[test], popularity[test])
        model_p3 = precision_at_3(model_scores, y[test], groups[test], allowed[test])
        baseline_p3 = precision_at_3(popularity[test], y[test], groups[test], allowed[test])

        # Report
        lines = []
        lines.append("Pawpal product recommender (logistic regression)")
        lines.append("Trained " + datetime.now().strftime("%d %b %Y %H:%M"))
        lines.append("")
        lines.append(f"Products in catalogue: {len(products)}")
        lines.append(f"Synthetic customers:   {options['customers']}")
        lines.append(f"(pet, product) rows:   {len(y)}  (train {len(train)}, test {len(test)})")
        lines.append(f"Rows that were bought: {y.mean() * 100:.1f}%")
        lines.append("")
        lines.append(f"Best C from 5-fold CV: {search.best_params_['model__C']}")
        lines.append(f"Cross-validation ROC-AUC: {search.best_score_:.3f}")
        lines.append("")
        lines.append("Test set results          Model   Popularity baseline")
        lines.append(f"ROC-AUC                   {model_auc:.3f}   {baseline_auc:.3f}")
        lines.append(f"Precision@3               {model_p3:.3f}   {baseline_p3:.3f}")
        lines.append("")
        lines.append("Coefficients (after scaling, so they can be compared)")
        lines.append("Positive = more likely to buy, negative = less likely")
        weights = model.named_steps["model"].coef_[0]
        order = np.argsort(-weights)
        for i in order:
            lines.append(f"  {recommender.FEATURE_NAMES[i]:<22} {weights[i]:+.3f}")
        report = "\n".join(lines)

        recommender.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": model, "feature_names": recommender.FEATURE_NAMES},
            recommender.MODEL_PATH,
        )
        recommender.REPORT_PATH.write_text(report + "\n")

        self.stdout.write(report)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Saved model to " + str(recommender.MODEL_PATH)))
