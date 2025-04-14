# test_mongo_connection.py

from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    print("❌ MONGO_URI not found in .env file")
    exit()

try:
    client = MongoClient(MONGO_URI)
    db = client["video_app"]
    print("✅ Connected to MongoDB!")
    print("📂 Available Collections:", db.list_collection_names())
except Exception as e:
    print("❌ Failed to connect:", e)
