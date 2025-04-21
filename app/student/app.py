# app.py
from flask import Flask, render_template, request, redirect, url_for, Response
from pymongo import MongoClient
import gridfs
from dotenv import load_dotenv
import os

# Setup
load_dotenv()
app = Flask(__name__)
app.secret_key = "supersecretkey"

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["video_app"]
fs = gridfs.GridFS(db)

@app.route("/")
def student_home():
    return render_template("student_home.html")

@app.route("/playlist", methods=["GET", "POST"])
def playlist():
    videos = []
    professor_id = None

    if request.method == "POST":
        professor_id = request.form.get("professor_id")

    if professor_id:
        videos = [file.filename for file in fs.find({"metadata.user_id": professor_id})]
    else:
        videos = [file.filename for file in fs.find().sort("uploadDate", -1)]

    return render_template("student_playlist.html", videos=videos, from_mongo=True, professor_id=professor_id)

@app.route("/video/<filename>")
def stream_video(filename):
    file = fs.find_one({"filename": filename})
    if not file:
        return "Video not found", 404
    return Response(file.read(), mimetype="video/mp4")

if __name__ == "__main__":
    app.run(debug=True)
