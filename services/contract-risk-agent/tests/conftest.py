import os
import sys

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_ESIGN_WEBHOOK_SECRET", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
