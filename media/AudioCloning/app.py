import os
import re
import base64
import time
import subprocess
from tqdm import tqdm
from PIL import Image
import fitz  # PyMuPDF
from openai import OpenAI
import requests
import json
from pyht import Client, TTSOptions, Format
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from werkzeug.utils import secure_filename
import pymupdf  # Correct import for PyMuPDF
from flask import Response
from mongo_setup import save_video_to_mongo, get_all_video_filenames, get_video_file_by_name, fs


# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'mp3'}

# Helper function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Helper function to encode images to base64
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
        print(f"Encoded Image (first 100 chars): {encoded_image[:100]}")  # Debug print
        return encoded_image

# Function to generate slide script using OpenAI
def generate_slide_script(image_path, slide_number, total_slides, previous_content=None, api_key=None):
    
    print(f"Using API Key: {api_key}")  # Debug print

    client = OpenAI(api_key=api_key)
    base64_image = encode_image(image_path)
    
    system_message = {
        "role": "system",
        "content": """You are an expert computer science lecturer delivering clear, concise explanations.
        Rules:
        1. ONLY explain visible content
        2. Use natural speech patterns
        3. No meta-references or slide mentions
        4. Skip irrelevant metadata (names, dates, institutions)
        5. Maintain logical flow between slides
        6. Keep explanations focused and precise
        7. Explain concepts concisely based on the visible content only
        8. Never say "Title:..."

        Speaking style:
        - Conversational and engaging
        - Direct and clear
        - Professional but approachable
        - Concise yet thorough
        """
    }
    
    position_instructions = {
        "first": "Just mention the name of the algorithm or topic we will explore. Duration: 2-5 seconds.",
        "middle": ("Continue the technical explanation, connecting with previous concepts. "
                   "Typically 40-90 seconds, but if the slide is mostly a short title or an outline, keep it 4-15 seconds."),
        "last": "Conclude the visible content naturally."
    }

    if slide_number == 1:
        position = "first"
    elif slide_number == total_slides:
        position = "last"
    else:
        position = "middle"
    
    user_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"""Generate a teaching script following these parameters:
1. Content scope: Only explain visible elements and avoid mentioning what we will come in coming slides
2. Position context: {position_instructions[position]}
3. Technical accuracy: Maintain precise terminology
4. Flow: Natural transitions between concepts
5. Avoid repeating 'Building upon'"""
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            }
        ]
    }
    
    messages = [system_message]
    if previous_content:
        messages.extend(previous_content)
    messages.append(user_message)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Ensure this is the correct model
            messages=messages,
            max_tokens=350,
            temperature=0.7
        )
        print(f"API Response: {response}")  # Debug print
        script_text = response.choices[0].message.content
        print(f"Generated Script: {script_text}")  # Debug print
        return script_text, messages
    except Exception as e:
        print(f"Error generating script for slide {slide_number}: {str(e)}")
        return "", messages
# Function to generate audio using OpenAI or Play.ht
def generate_audio(script_text, slide_number, output_dir, api_key, user_id=None, custom_voice_id=None):
    audio_path = os.path.join(output_dir, f"slide_{slide_number}.mp3")
    
    if custom_voice_id:
        # Use Play.ht for custom cloned voice
        print(f"Generating audio for slide {slide_number} with user_id: {user_id}, api_key: {api_key}, voice_id: {custom_voice_id}")  # Debug print

        client = Client(user_id, api_key)  # PlayHT client

        # Configure the TTS options
        options = TTSOptions(
            voice=custom_voice_id,  # Use custom voice ID
            format=Format.FORMAT_MP3,
            speed=0.9,
            temperature=0.1,
            quality='Premium',
            voice_guidance=1,
            style_guidance=1,
            sample_rate=24000
        )

        # Split the script text into chunks for processing
        text_chunks = split_text_into_chunks(script_text)

        # Generate the audio for each chunk and save it to the file
        with open(audio_path, "wb") as audio_file:
            for chunk_text in text_chunks:
                if chunk_text.strip():  # Ensure chunk is not empty
                    try:
                        # Send the chunk to Play.ht and write the audio stream to the file
                        for chunk in client.tts(text=chunk_text, voice_engine="Play3.0-mini", options=options):
                            audio_file.write(chunk)
                    except Exception as e:
                        print(f"Error processing chunk for slide {slide_number}: {repr(chunk_text)}")
                        print(f"Exception: {e}")

        print(f"Audio for slide {slide_number} generated using Play.ht.")
    else:
        # Use OpenAI's default TTS
        client = OpenAI(api_key=api_key)
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=script_text
        )
        response.stream_to_file(audio_path)
    
    time.sleep(1)  # Small delay to ensure file is written
    return audio_path

def split_text_into_chunks(text, max_lines=6, max_chars=500):
    lines = re.split(r'(?<=\]) ', text)  # Split while preserving section headers and timestamps
    chunks = []
    chunk = []
    char_count = 0

    for line in lines:
        if char_count + len(line) <= max_chars and len(chunk) < max_lines:
            chunk.append(line)
            char_count += len(line)
        else:
            chunks.append(" ".join(chunk))
            chunk = [line]
            char_count = len(line)

    if chunk:
        chunks.append(" ".join(chunk))

    return chunks


# Function to convert PDF to images

def convert_pdf_to_images(pdf_path):
    images_dir = os.path.join(app.config['OUTPUT_FOLDER'], 'images')
    os.makedirs(images_dir, exist_ok=True)
    
    pdf_document = pymupdf.open(pdf_path)  # Use pymupdf.open instead of fitz.open
    for page_number in tqdm(range(pdf_document.page_count), desc="Converting PDF pages", unit="page"):
        page = pdf_document[page_number]
        zoom = 300 / 72  # Scale factor for high-resolution images
        matrix = pymupdf.Matrix(zoom, zoom)  # Use pymupdf.Matrix
        pixmap = page.get_pixmap(matrix=matrix)
        img_data = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        output_path = os.path.join(images_dir, f'page_{page_number + 1}.png')
        img_data.save(output_path, 'PNG')
    
    pdf_document.close()
    return images_dir


# Function to generate scripts for images
def generate_scripts_for_images(images_dir, api_key):
    scripts_dir = os.path.join(app.config['OUTPUT_FOLDER'], 'scripts')
    os.makedirs(scripts_dir, exist_ok=True)
    
    image_files = sorted(
        [os.path.join(images_dir, f) for f in os.listdir(images_dir) if f.endswith(".png")],
        key=lambda x: int(re.search(r'page_(\d+)', x).group(1))
    )
    
    total_slides = len(image_files)
    conversation_history = []
    scripts_list = []
    
    for i, image_file in enumerate(image_files, start=1):
        print(f"Processing slide {i}/{total_slides}: {image_file}")  # Debug print
        script_text, updated_history = generate_slide_script(
            image_file,
            slide_number=i,
            total_slides=total_slides,
            previous_content=conversation_history,
            api_key=api_key
        )
        conversation_history = updated_history
        conversation_history.append({"role": "assistant", "content": script_text})
        
        script_path = os.path.join(scripts_dir, f"slide_{i}_script.txt")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_text)
        
        scripts_list.append(script_text)
    
    return scripts_list

# Function to generate audio files
def generate_audio_files(scripts_list, openai_api_key, playht_api_key=None, user_id=None, custom_voice_id=None):
    """
    Generate audio files for the given scripts using either OpenAI TTS or Play.ht custom voice.
        str: Path to the directory containing the generated audio files.
    """
    audio_dir = os.path.join(app.config['OUTPUT_FOLDER'], 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    
    for i, script_text in enumerate(scripts_list, start=1):
        if not script_text.strip():
            print(f"Warning: Script for slide {i} is empty. Skipping audio generation.")
            continue
        
        try:
            if custom_voice_id:
                # Use Play.ht for custom voice
                if not playht_api_key or not user_id:
                    raise ValueError("Play.ht API key and user ID are required for custom voice generation.")
                audio_path = generate_audio(
                    script_text, i, audio_dir, playht_api_key, user_id, custom_voice_id
                )
            else:
                # Use OpenAI TTS for default voice
                audio_path = generate_audio(
                    script_text, i, audio_dir, openai_api_key
                )
            
            # Verify the audio file was created
            if not (os.path.exists(audio_path) and os.path.getsize(audio_path) > 0):
                print(f"Warning: Audio file {audio_path} not created properly")
        except Exception as e:
            print(f"Error generating audio for slide {i}: {e}")
    
    return audio_dir

# Function to create video using FFmpeg

def get_audio_duration(audio_path):
    """
    Get audio duration using ffprobe.
    """
    
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
        capture_output=True,
        text=True
    )
    return float(result.stdout.strip()) if result.stdout.strip() else 0.0

def get_sorted_pairs(images_dir, audio_dir):
    """
    Match images with audio files ensuring proper synchronization.
    """
    images = sorted([f for f in os.listdir(images_dir) if f.endswith(".png")],
                   key=lambda x: int(re.search(r'page_(\d+)', x).group(1)))
    audio_files = sorted([f for f in os.listdir(audio_dir) if f.endswith(".mp3")],
                        key=lambda x: int(re.search(r'slide_(\d+)', x).group(1)))

    print(f"Images found: {images}")  # Debug print
    print(f"Audio files found: {audio_files}")  # Debug print

    # only pair files with matching numbers
    pairs = [(os.path.join(images_dir, img), os.path.join(audio_dir, aud))
            for img, aud in zip(images, audio_files)
            if int(re.search(r'page_(\d+)', img).group(1)) == 
               int(re.search(r'slide_(\d+)', aud).group(1))]

    print(f"Pairs found: {pairs}")  # Debug print
    return pairs

#adding subtitles to the video:

def create_video_ffmpeg(images_dir, audio_dir, output_path="output/slideshow.mp4"):
    """
    Create final video with proper synchronization between slides and audio.
    Each slide is shown exactly for the duration of its corresponding audio track.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Check if directories are empty
    if not os.listdir(images_dir):
        raise ValueError(f"No images found in {images_dir}")
    if not os.listdir(audio_dir):
        raise ValueError(f"No audio files found in {audio_dir}")

    # Get sorted pairs of images and audio files
    pairs = get_sorted_pairs(images_dir, audio_dir)
    if not pairs:
        raise ValueError("No valid image-audio pairs found")

    # Prepare FFmpeg inputs and filter complex
    inputs = []
    filter_complex = []

    for i, (img, aud) in enumerate(pairs):
        inputs.extend(['-loop', '1', '-i', img, '-i', aud])
        duration = get_audio_duration(aud)
        filter_complex.extend([
            f'[{2*i}:v]trim=duration={duration},setpts=PTS-STARTPTS[v{i}];',
            f'[{2*i+1}:a]acopy[a{i}];'
        ])

    # Concatenate all video and audio streams
    concat_parts = []
    for i in range(len(pairs)):
        concat_parts.append(f'[v{i}][a{i}]')

    filter_complex.append(
        f'{"".join(concat_parts)}concat=n={len(pairs)}:v=1:a=1[outv][outa]'
    )

    # FFmpeg command
    cmd = [
        'ffmpeg', '-y',
        *inputs,
        '-filter_complex', ''.join(filter_complex),
        '-map', '[outv]',
        '-map', '[outa]',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        output_path
    ]

    print(f"Running FFmpeg command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr}")
        raise RuntimeError(f"Failed to create video: {result.stderr}")

    if not os.path.exists(output_path):
        raise RuntimeError(f"Video file was not created at {output_path}")

    print(f"Video created successfully at: {output_path}")
    return output_path

def get_voice_id(audio_path, api_key, user_id):
    url = "https://api.play.ht/api/v2/cloned-voices/instant"

    files = {"sample_file": (os.path.basename(audio_path), open(audio_path, "rb"), "audio/mpeg")}
    payload = {"voice_name": "custom-voice"}
    headers = {
        "accept": "application/json",
        "AUTHORIZATION": api_key,
        "X-USER-ID": user_id
    }

    response = requests.post(url, data=payload, files=files, headers=headers)
    response_data = response.json()
    voice_id = response_data.get("id")
    return voice_id


# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/home', methods=['POST'])
def home():
    if 'openai_key' not in request.form:
        flash("Missing API credentials. Please enter your API keys and user ID.", "error")
        return redirect(url_for('index'))
    
    # Store the API keys and user ID in the session
    session['openai_key'] = request.form['openai_key']
    session['user_id'] = request.form['user_id']
    # session['playht_user_id'] = request.form['playht_user_id']
    # session['playht_api_key'] = request.form['playht_api_key']
    
    return render_template('home.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    # Retrieve the OpenAI API key and Play.ht credentials from the session
    if 'openai_key' not in session:
        flash("OpenAI API key is missing. Please enter your API key again.", "error")
        return redirect(url_for('index'))
    
    openai_key = session['openai_key']
    playht_user_id = "jWK4UiQgtyaC3vc4ugbYu0rPGks2"  # Optional for default voice
    playht_api_key = "5ba9a3abbbd641709b0d6445ce09269e"  # Optional for default voice
    video_name = request.form.get("video_name")

    voice_type = request.form['voice_type']
    pdf_file = request.files['pdf']
    custom_voice_file = request.files.get('custom_voice')
    voice_source = request.form.get('voice_source')  # 'upload' or 'record'
    
    safe_video_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    
    session['video_name'] = safe_video_name

    if pdf_file and allowed_file(pdf_file.filename):
        # Save the PDF file
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(pdf_file.filename))
        pdf_file.save(pdf_path)

        # Convert PDF to images
        images_dir = convert_pdf_to_images(pdf_path)
        
        # Generate scripts for images
        scripts_list = generate_scripts_for_images(images_dir, openai_key)
        
        # Handle custom voice
        custom_voice_id = None
        if voice_type == 'custom':
            if voice_source == 'upload' and custom_voice_file and allowed_file(custom_voice_file.filename):
                # Save the uploaded custom voice file
                custom_voice_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(custom_voice_file.filename))
                custom_voice_file.save(custom_voice_path)
            elif voice_source == 'record' and custom_voice_file and allowed_file(custom_voice_file.filename):
                # Save the recorded custom voice file
                custom_voice_path = os.path.join(app.config['UPLOAD_FOLDER'], 'recorded_voice.mp3')
                custom_voice_file.save(custom_voice_path)
            
            # Get the custom voice ID
            custom_voice_id = get_voice_id(custom_voice_path, playht_api_key, playht_user_id)
            if not custom_voice_id:
                flash("Failed to generate custom voice ID. Falling back to OpenAI TTS.", "warning")
        
        # Generate audio files
        audio_dir = generate_audio_files(
            scripts_list,
            openai_api_key=openai_key,
            playht_api_key=playht_api_key,
            user_id=playht_user_id,
            custom_voice_id=custom_voice_id
        )
        
        # Generate a unique video filename
        timestamp = int(time.time())
        filename = f"{safe_video_name}.mp4"
        video_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        
        # Create the video
        create_video_ffmpeg(images_dir, audio_dir, output_path=video_path)
        
        # Pass the unique video filename to the result page
        return redirect(url_for('result', video_filename=filename))
    
    flash("Invalid file uploaded. Please upload a PDF file.", "error")
    return redirect(url_for('home'))

@app.route('/result')
def result():
    video_filename = request.args.get('video_filename')
    if not video_filename:
        flash("Video not found. Please try again.", "error")
        return redirect(url_for('home'))

    video_path = os.path.join(app.config['OUTPUT_FOLDER'], video_filename)
    if not os.path.exists(video_path):
        flash("Video not found. Please try again.", "error")
        return redirect(url_for('home'))

    # Save to MongoDB (only if not already saved)
    user_id = session['user_id']  
    save_video_to_mongo(video_path, video_filename, user_id)


    video_url = url_for('serve_video', filename=video_filename)
    return render_template('result.html', video_url=video_url)


@app.route('/video/<filename>')
def serve_video(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

@app.route('/mongo_video/<filename>')
def serve_mongo_video(filename):
    file = get_video_file_by_name(filename)
    if not file:
        flash("Video not found in database.", "error")
        return redirect(url_for('playlist'))
    return Response(file.read(), mimetype='video/mp4')


@app.route('/playlist', methods=["GET", "POST"])
def playlist():
    user_id = None
    videos = []

    if request.method == "POST":
        user_id = request.form.get("user_id")

    if user_id:
        # Fetch videos linked to that user_id
        videos = [
            file.filename for file in fs.find({"metadata.user_id": user_id})
        ]
    else:
        # Default: show top 5 most recent
        videos = [
            file.filename for file in fs.find().sort("uploadDate", -1).limit(5)
        ]

    return render_template("playlist.html", videos=videos, from_mongo=True)


# Run the app
if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    app.run(debug=True)