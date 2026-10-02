Step 1. Change to the PetCare folder

Step 2. Create virtual environment:

python -m venv venv

OR

python3 -m venv venv

Step 3. Activate virtual environment:

For Window:
.\venv\Scripts\activate.bat

For MacOS:
source ./venv/bin/activate

Step 4. Restore Python packages:

pip install -r requirements.txt

Step 5. Run the project on the development server:

cd [project folder]
python manage.py runserver
