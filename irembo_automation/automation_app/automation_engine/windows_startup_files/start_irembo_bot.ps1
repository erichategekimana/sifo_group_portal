# Step 1: Navigate to the root directory
cd "C:\Program Files\irembo_bot"

# Step 2: Activate the virtual environment explicitly
.\venv\Scripts\Activate.ps1

# Step 3: Move into the automation folder
cd .\irembo_automation\

# Step 4: Launch Django server
python .\manage.py runserver