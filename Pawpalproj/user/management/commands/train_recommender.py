# Trains the product recommender (Decision Tree), the same steps as the course notebook.
#   python manage.py make_training_data   (first, makes user/ml/pet_purchases.csv)
#   python manage.py train_recommender
#
#   X = the pet's details (pet type, age, weight, life stage, health needs, allergy)
#   y = the product the owner bought (product_bought)

from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from sklearn import metrics, tree
from sklearn.model_selection import GridSearchCV, train_test_split

from inventory.models import Product
from user import recommender

SEED = 42  # same random numbers every run, so results can be repeated


def read_data():
    df = pd.read_csv(recommender.DATA_PATH, keep_default_na=False)

    # turn the text columns into 0/1 columns (one-hot encoding), e.g. pet_type -> pet_type_DOG, pet_type_CAT
    X = pd.get_dummies(df[["age_years", "weight_kg", "pet_type", "life_stage"]], columns=["pet_type", "life_stage"])

    # "joint;skin" -> need_joint = 1, need_skin = 1
    needs = df["health_needs"].str.get_dummies(sep=";").add_prefix("need_")
    # "chicken" -> allergy_chicken = 1 (no allergy -> all 0)
    allergies = df["allergy"].str.get_dummies().add_prefix("allergy_")
    X = pd.concat([X, needs, allergies], axis=1).astype(float)

    y = df["product_bought"]
    return df, X, y


def csv_pet(row):
    # one CSV row -> the pet dict that is_allowed() needs
    allergens = set()
    if row["allergy"]:
        allergens.add(row["allergy"])
    return {"pet_type": row["pet_type"], "allergens": allergens}


def top_3_accuracy(model, df, X, y, products):
    # is the product the owner really bought in the 3 we would show?
    by_name = {}
    for product in products:
        by_name[product["name"]] = product

    chances = model.predict_proba(X)
    hits = 0
    for i in range(len(X)):
        row = df.iloc[i]
        pet = csv_pet(row)
        top = []
        for j in np.argsort(-chances[i]):
            name = model.classes_[j]
            if name in by_name and recommender.is_allowed(pet, by_name[name], set()):
                top.append(name)
            if len(top) == 3:
                break
        if y.iloc[i] in top:
            hits += 1
    return hits / len(X)


def best_sellers_top_3(df_train, df_test, products):
    # baseline without ML: always show the 3 best sellers for that pet type
    by_name = {}
    for product in products:
        by_name[product["name"]] = product

    hits = 0
    for i in range(len(df_test)):
        row = df_test.iloc[i]
        pet = csv_pet(row)
        sellers = df_train[df_train["pet_type"] == row["pet_type"]]["product_bought"].value_counts().index
        top = []
        for name in sellers:
            if name in by_name and recommender.is_allowed(pet, by_name[name], set()):
                top.append(name)
            if len(top) == 3:
                break
        if row["product_bought"] in top:
            hits += 1
    return hits / len(df_test)


class Command(BaseCommand):
    help = "Train the Decision Tree product recommender from user/ml/pet_purchases.csv"

    def handle(self, *args, **options):
        if not recommender.DATA_PATH.exists():
            raise CommandError("No training data yet. Run: python manage.py make_training_data")

        products = []
        for product in Product.objects.filter(pet_type__in=["DOG", "CAT"]).select_related("category"):
            products.append(recommender.product_info(product))

        df, X, y = read_data()

        # 70% to train, 30% to test, the same as the course notebook
        X_train, X_test, y_train, y_test, df_train, df_test = train_test_split(
            X, y, df, train_size=0.7, test_size=0.3, shuffle=True, stratify=y, random_state=SEED
        )

        # pick the best tree size with 5-fold cross-validation
        search = GridSearchCV(
            tree.DecisionTreeClassifier(criterion="gini", splitter="best", random_state=SEED),
            {"max_depth": [4, 6, 8, 10, 12], "min_samples_leaf": [5, 20, 50]},
            scoring="accuracy",
            cv=5,
        )
        search.fit(X_train, y_train)
        clf = search.best_estimator_

        # Check the model on the test pets it has never seen
        train_accuracy = metrics.accuracy_score(y_train, clf.predict(X_train))
        test_accuracy = metrics.accuracy_score(y_test, clf.predict(X_test))
        model_top_3 = top_3_accuracy(clf, df_test, X_test, y_test, products)
        baseline_top_3 = best_sellers_top_3(df_train, df_test, products)

        # Report
        lines = []
        lines.append("Pawpal product recommender (Decision Tree)")
        lines.append("Trained " + datetime.now().strftime("%d %b %Y %H:%M"))
        lines.append("")
        lines.append(f"Training data: {recommender.DATA_PATH.name}, {len(df)} rows")
        lines.append(f"Train / test:  {len(X_train)} / {len(X_test)}")
        lines.append(f"Columns (X):   {len(X.columns)}")
        lines.append(f"Products (y):  {len(clf.classes_)}")
        lines.append("")
        lines.append(f"Best tree from 5-fold CV: max_depth={clf.max_depth}, min_samples_leaf={clf.min_samples_leaf}")
        lines.append(f"Tree size: {clf.tree_.node_count} nodes, {clf.get_n_leaves()} leaves")
        lines.append("")
        lines.append(f"Training accuracy: {train_accuracy:.3f}")
        lines.append(f"Testing accuracy:  {test_accuracy:.3f}  (the 1 product the tree picks first)")
        lines.append("")
        lines.append("Top-3 accuracy on the test pets (the bought product is one of the 3 we show)")
        lines.append(f"  Decision Tree:           {model_top_3:.3f}")
        lines.append(f"  Best sellers (no ML):    {baseline_top_3:.3f}")
        lines.append("")
        lines.append("Feature importances (how much each pet detail helps the tree)")
        order = np.argsort(-clf.feature_importances_)
        for i in order:
            if clf.feature_importances_[i] > 0:
                lines.append(f"  {X.columns[i]:<22} {clf.feature_importances_[i]:.3f}")
        report = "\n".join(lines)

        # save the model and the column order, so a real pet can be turned into the same columns
        joblib.dump({"model": clf, "columns": list(X.columns)}, recommender.MODEL_PATH)
        recommender.REPORT_PATH.write_text(report + "\n")

        self.stdout.write(report)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Saved model to " + str(recommender.MODEL_PATH)))
