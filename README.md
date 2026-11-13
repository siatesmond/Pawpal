# Pawpal

Pawpal is a pet care web app for Singapore pet owners: book grooming, daycare, boarding and training, shop for pet supplies, and hire a freelance pet sitter, all from one account.

Built with **Python + Django 5.2** and **SQLite**. IS2108 AY2026/27 Semester 1 pair project.

---

## 1. What you need

- **Python 3.10 or newer** (check with `python --version` or `python3 --version`)
- **Git**
- An internet connection (only for the pet sitter map and distance features)

---

## 2. Set up the project (first time only)

**Step 1. Download the project and go into it**

```bash
git clone https://github.com/siatesmond/Pawpal.git
cd Pawpal
```

**Step 2. Create a virtual environment**

macOS:
```bash
python3 -m venv venv
```

Windows:
```bash
python -m venv venv
```

**Step 3. Activate the virtual environment**

macOS:
```bash
source venv/bin/activate
```

Windows:
```bash
venv\Scripts\activate.bat
```

You should now see `(venv)` at the start of the terminal line.

**Step 4. Install the packages**

```bash
pip install -r Pawpalproj/requirements.txt
```

**Step 5. Go into the Django project folder** (the one with `manage.py`)

```bash
cd Pawpalproj
```

**Step 6. Create the database**

```bash
python manage.py migrate
```

---

## 3. Run Pawpal

**Step 1. Start the server**

```bash
python manage.py runserver
```

**Step 2. Load the demo data** (shops, services, pets, bookings, orders and demo accounts)

Open this link in your browser once the server is running:

**http://127.0.0.1:8000/core/loadData/**

You should see *"Data loaded successfully into the database."*

**Step 3. Open the website**

**http://127.0.0.1:8000/**

Next time you only need to activate the virtual environment, `cd Pawpalproj`, and run `python manage.py runserver`.

---

## 4. Demo accounts

Every demo account uses the password **`Pawpal123!`**. Log in with the **email**.

| Role | Email | What you can try |
|---|---|---|
| Pet owner (customer) | `amy.tan@example.com` | Book a service, shop and check out, find a pet sitter, track bookings and orders, review a sitter |
| Pet owner (customer) | `jason.lee@example.com` | A second customer with different pets and history |
| Staff | `sarah@pawpal.sg` | Daily bookings, post booking updates, orders and stock, products |
| Business owner | `pawpal.sg.demo@gmail.com` | Revenue dashboard and CSV export, customers and points, staff accounts, sitter approvals |
| Pet sitter (approved) | `grace@example.com` | Find jobs on the map, accept jobs, post updates, earnings, profile |
| Pet sitter (pending) | `emily@example.com` | Application waiting for the owner's approval |
| Pet sitter (rejected) | `marcus@example.com` | Rejected application with the reason, and resubmit |

**Loading the demo data again resets everything** (all accounts, bookings and orders go back to the starting state, and any accounts you registered are removed). Open **http://127.0.0.1:8000/core/loadData/** whenever you want a clean start.

---

## 5. Registering a new account (verification code)

New customers and pet sitters must enter a **6-digit verification code** after signing up.

By default the email is **not sent**. Instead it is printed in the **terminal where `runserver` is running**, like this:

```
Subject: Your Pawpal verification code
...
Your Pawpal verification code is 197897. It expires in 5 minutes.
```

Copy the code from the terminal into the verification page.

### Optional: send real emails through Gmail

To send real emails, Pawpal needs a Gmail address and a Gmail **App Password**. (An App Password is a 16-character password made in *Google Account → Security → 2-Step Verification → App passwords*. It is not your normal Gmail password.)

**Step 1.** Create a file called `export.txt` in the top `Pawpal` folder (next to this README) with these two lines:

macOS:
```bash
export EMAIL_HOST_USER="your.address@gmail.com"
export EMAIL_HOST_PASSWORD="your-16-character-app-password"
```

Windows (save it as `export.bat` instead):
```bash
set EMAIL_HOST_USER=your.address@gmail.com
set EMAIL_HOST_PASSWORD=your-16-character-app-password
```

**Step 2.** Load the file in the terminal, then start the server from the `Pawpalproj` folder:

macOS:
```bash
source ../export.txt
```

Windows:
```bash
..\export.bat
```

```bash
python manage.py runserver
```

If both values are set, Pawpal sends emails through Gmail. If not, the code is printed in the terminal as above. The values only last until the terminal window is closed, so load the file again each time.

> **Keep it private.** `export.txt` and `export.bat` are listed in `.gitignore`, so they are never uploaded to GitHub. Never put the App Password in the code.

---

## 6. Product recommender (machine learning)

The "Picked for your pets" products on the customer home page, the shop page and the pop-up after login come from a **Decision Tree** model (scikit-learn). It looks at each pet's type, age, weight, life stage, health needs and food allergy, then suggests the 3 products the owner is most likely to buy. Safety rules then remove products the pet is allergic to, out-of-stock products and products already in the cart.

The trained model is already included, so **nothing needs to be done to use it**. To train it again (from the `Pawpalproj` folder, after loading the demo data):

```bash
python manage.py make_training_data
python manage.py train_recommender
```

| File | What it is |
|---|---|
| `user/ml/pet_purchases.csv` | Mock training data: 10,000 pets and the product each owner bought |
| `user/ml/recommender.joblib` | The trained Decision Tree, loaded by `user/recommender.py` |
| `user/ml/report.txt` | Accuracy results from the last training run |

---

## 7. Run the automated tests

From the `Pawpalproj` folder:

```bash
python manage.py test
```

The tests use their own temporary database, so your demo data is not changed.

---

## 8. Problems?

| Problem | Fix |
|---|---|
| `python` is not found | Use `python3` (macOS) or `py` (Windows) instead |
| "Incorrect email or password" for a demo account | Open **/core/loadData/** again, then log in with the password typed by hand: `Pawpal123!` |
| "no such table" error | Run `python manage.py migrate` in the `Pawpalproj` folder |
| "That port is already in use" | Another server is still running. Stop it with `Ctrl + C`, or run `python manage.py runserver 8001` and use port 8001 |
| Page looks unstyled after an update | Hard-refresh the browser: `Cmd + Shift + R` (macOS) or `Ctrl + Shift + R` (Windows) |
| Pet sitter map is empty or shows no distances | The map and distances need an internet connection |
| Never received the verification email | Check the `runserver` terminal for the code (see section 5). If you use Gmail, check that `export.txt` was loaded in the **same** terminal before `runserver` |
| Gmail says "Username and Password not accepted" | Use an App Password, not your normal Gmail password, and remove any spaces in it |

---

## 9. Project structure

```
Pawpal/
├── README.md
├── .gitignore
├── export.txt               your Gmail settings (private, not on GitHub)
└── Pawpalproj/              Django project folder (run commands here)
    ├── manage.py
    ├── requirements.txt
    ├── Pawpalproj/          settings, main URLs, shared templates and CSS
    ├── core/                business owner pages, outlets, demo data (loadData)
    ├── user/                accounts, login, OTP, profile, pets, cart, bookings, orders
    ├── inventory/           shop products, staff bookings, orders and stock
    ├── service/             booking a service with live time slots
    ├── payment/             checkout, payments and membership points
    ├── sitting/             pet sitters and pet sitting requests
    └── review/              ratings and reviews
```
