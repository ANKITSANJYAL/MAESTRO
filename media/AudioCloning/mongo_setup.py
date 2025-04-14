# mongo_setup.py

from pymongo import MongoClient
import gridfs
import os
from dotenv import load_dotenv

load_dotenv()
# Connect to MongoDB (replace with your MongoDB Atlas URI if using cloud)
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['video_app']
fs = gridfs.GridFS(db)

def save_video_to_mongo(filepath, filename=None, user_id=None):
    if not filename:
        filename = os.path.basename(filepath)

    if fs.exists({"filename": filename}):
        print(f"{filename} already exists.")
        return

    with open(filepath, "rb") as f:
        fs.put(f, filename=filename, metadata={"user_id": user_id})
        print(f"Saved {filename} for user {user_id}")

def get_all_video_filenames():
    return [file.filename for file in fs.find()]

def get_video_file_by_name(filename):
    return fs.find_one({"filename": filename})
