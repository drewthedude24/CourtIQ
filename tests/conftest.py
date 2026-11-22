import os

# Point the backend at the test database before anything imports it,
# so running pytest never wipes the real local data.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://courtiq:courtiq@localhost:5432/courtiq_test",
)
