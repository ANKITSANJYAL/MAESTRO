# clear_videos.py

from pymongo import MongoClient
import gridfs
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['video_app']
fs = gridfs.GridFS(db)

# Find all video files
file_ids = [file._id for file in fs.find()]
print(f"🧹 Found {len(file_ids)} file(s) in GridFS. Deleting...")

# Delete each one
for file_id in file_ids:
    fs.delete(file_id)
    print(f"✅ Deleted video with _id: {file_id}")

print("🎉 All videos cleared from MongoDB GridFS.")
