import os
import sys

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_MINIO_SECRET_KEY", "minioadmin123")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
