import os
import re
import time
import uuid
import base64
import fitz  # PyMuPDF
from tqdm import tqdm
from PIL import Image
import subprocess

from datetime import datetime
from flask import Flask, Response, request, session, send_file, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_cors import CORS

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from langchain_openai import OpenAIEmbeddings, OpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

load_dotenv()

app = Flask(__name__)
app.secret_key = "..."

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_HTTPONLY=True
)

CORS(
    app,
    resources={
        r"/*": {
            "origins": ["http://localhost", "http://localhost:80"],
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type"],
            "supports_credentials": True
        }
    }
)

@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ["http://localhost:3000", "http://127.0.0.1:3000"]:
        response.headers.update({
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        })
    return response

qa_chain = None
content_filter = None
scripts_global = None

def setup_directories():
    """Create necessary directories on startup, if they don't exist."""
    for d in ["uploads", "output/images", "output/scripts", "output/audio", "static"]:
        os.makedirs(d, exist_ok=True)

with app.app_context():
    setup_directories()

def clean_directories(keep_video=None):
    """
    cleanup policy: removes old files from directories when a new file is uploaded.
    :param keep_video: path to the final MP4 we do NOT want to remove.
    """
    # remove all previous uploaded pdfs
    uploads_dir = "uploads"
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            if f.endswith(".pdf"):
                os.remove(os.path.join(uploads_dir, f))

    # remove all processing directories
    for output_dir in ["output/images", "output/scripts", "output/audio"]:
        if os.path.exists(output_dir):
            for f in os.listdir(output_dir):
                os.remove(os.path.join(output_dir, f))

    # clean static directory
    static_dir = "static"
    if os.path.exists(static_dir):
        for f in os.listdir(static_dir):
            if f.endswith(".mp4"):
                file_path = os.path.join(static_dir, f)

                if keep_video and os.path.abspath(file_path) != os.path.abspath(keep_video):
                    os.remove(file_path)

# helper functions
def save_uploaded_file(uploaded_file, unique_id):
    """Save uploaded PDF to 'uploads' with a unique ID prefix."""
    uploads_dir = "uploads"
    os.makedirs(uploads_dir, exist_ok=True)
    
    original_filename = secure_filename(uploaded_file.filename)
    unique_filename = f"{unique_id}_{original_filename}"
    file_path = os.path.join(uploads_dir, unique_filename)
    
    uploaded_file.save(file_path)
    return file_path

def encode_image(image_path):
    """
    Helper function to convert an image to base64.
    """
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def generate_slide_script(image_path, slide_number, total_slides, previous_content=None, api_key=None):
    """
    generates a teaching script
    """
    from openai import OpenAI
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
            model="gpt-4o",
            messages=messages,
            max_tokens=350,
            temperature=0.7
        )
        script_text = response.choices[0].message.content
        return script_text, messages
    except Exception as e:
        print(f"Error generating script for slide {slide_number}: {str(e)}")
        return "", messages

def generate_audio(script_text, slide_number, output_dir, api_key=None):
    """
    Create an MP3 from script_text using your specialized TTS endpoint.
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=script_text
    )
    
    audio_path = os.path.join(output_dir, f"slide_{slide_number}.mp3")
    response.stream_to_file(audio_path)
    time.sleep(1)  # small delay to ensure file is written
    return audio_path

def natural_sort_key(s):
    """
    For sorting 'page_1.png', 'page_2.png', etc.
    """
    
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', s)]

def convert_pdf_to_images(pdf_path):
    """
    Convert PDF to images in output/images/.
    """
    images_dir = "output/images"
    os.makedirs(images_dir, exist_ok=True)

    pdf_document = fitz.open(pdf_path)
    page_count = pdf_document.page_count
    for page_number in tqdm(range(pdf_document.page_count), desc="Converting PDF pages", unit="page"):
        page = pdf_document[page_number]
        zoom = 300 / 72
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        img_data = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        output_path = os.path.join(images_dir, f'page_{page_number + 1}.png')
        img_data.save(output_path, 'PNG')
    
    pdf_document.close()
    return page_count

def generate_scripts_for_images(images_dir, api_key):
    """
    Generate a text script for each image (slide), building a conversation context across them.
    """
    scripts_dir = "output/scripts"
    os.makedirs(scripts_dir, exist_ok=True)

    # sort images in natural order
    image_files = sorted(
        [os.path.join(images_dir, f) for f in os.listdir(images_dir) if f.endswith(".png")],
        key=natural_sort_key
    )

    total_slides = len(image_files)
    conversation_history = []
    scripts_list = []

    for i, image_file in enumerate(image_files, start=1):
        script_text, updated_history = generate_slide_script(
            image_file,
            slide_number=i,
            total_slides=total_slides,
            previous_content=conversation_history,
            api_key=api_key
        )
        # update conversation
        conversation_history = updated_history
        conversation_history.append({"role": "assistant", "content": script_text})
        
        # save script to file
        script_path = os.path.join(scripts_dir, f"slide_{i}_script.txt")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_text)
        
        scripts_list.append(script_text)

    return scripts_list

def generate_audio_files(scripts_list, api_key):
    """
    Generate MP3 audio for each script, saved in output/audio/.
    """
    audio_dir = "output/audio"
    os.makedirs(audio_dir, exist_ok=True)

    for i, script_text in enumerate(scripts_list, start=1):
        if not script_text.strip():
            print(f"Warning: Script for slide {i} is empty. Skipping audio generation.")
            continue
        audio_path = generate_audio(script_text, i, audio_dir, api_key=api_key)
        if not (os.path.exists(audio_path) and os.path.getsize(audio_path) > 0):
            print(f"Warning: Audio file {audio_path} not created properly")

    return audio_dir

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

    # only pair files with matching numbers
    return [(os.path.join(images_dir, img), os.path.join(audio_dir, aud))
            for img, aud in zip(images, audio_files)
            if int(re.search(r'page_(\d+)', img).group(1)) == 
               int(re.search(r'slide_(\d+)', aud).group(1))]

def create_video_ffmpeg(images_dir, audio_dir, output_path="slideshow.mp4"):
    """
    Create final video with proper synchronization between slides and audio.
    Each slide is shown exactly for the duration of its corresponding audio track.
    """

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    pairs = get_sorted_pairs(images_dir, audio_dir)
    if not pairs:
        raise ValueError("No valid image-audio pairs found")

    filter_complex = []
    inputs = []
    
    for i, (img, aud) in enumerate(pairs):
        inputs.extend(['-loop', '1', '-i', img, '-i', aud])
        duration = get_audio_duration(aud)
        filter_complex.extend([
            f'[{2*i}:v]trim=duration={duration},setpts=PTS-STARTPTS[v{i}];',
            f'[{2*i+1}:a]acopy[a{i}];'
        ])

    concat_parts = []
    for i in range(len(pairs)):
        concat_parts.append(f'[v{i}][a{i}]')
    
    filter_complex.append(
        f'{"".join(concat_parts)}concat=n={len(pairs)}:v=1:a=1[outv][outa]'
    )

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
    
    print(f"Running FFmpeg command to create video: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr}")
        raise RuntimeError(f"Failed to create video: {result.stderr}")
    
    if not os.path.exists(output_path):
        raise RuntimeError(f"Video file was not created at {output_path}")
        
    print(f"Video created successfully at: {output_path}")

def encode(path: str):
    return '*#*'.join(path.split('/'))
    
def decode(path: str):
    return '/'.join(path.split('*#*'))
# flask endpoints

@app.route("/setup_api", methods=["POST", "OPTIONS"])
def setup_api():
    if request.method == "OPTIONS":
        return jsonify({"success": True}), 200
    
    data = request.get_json() or {}
    api_key = data.get('api_key', '').strip()
    if not api_key:
        return jsonify({"error": "API key cannot be empty"}), 400
    if not api_key.startswith('sk-'):
        return jsonify({"error": "Invalid API key format. Must start with 'sk-'"}), 400

    session['api_key'] = api_key
    session.modified = True
    return jsonify({"success": True, "message": "API key set successfully"})

@app.route("/check_session", methods=["GET"])
def check_session():
    """Check if the session has an API key."""
    api_key = session.get('api_key')
    return jsonify({
        "has_session": bool(api_key),
        "api_key_set": bool(api_key),
        "status": "active",
        "server_time": datetime.now().isoformat()
    })

@app.route('/upload_file', methods=['POST'])
def upload_file():
    """Handle PDF upload and video generation."""
    if not session.get('api_key'):
        return jsonify({"error": "API key not set"}), 401

    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['pdf_file']
    if not file.filename.endswith('.pdf'):
        return jsonify({"error": "Only PDF files are allowed"}), 400

    try:
        # unique ID for this upload
        unique_id = str(uuid.uuid4())
        # video_filename = f"{unique_id}_slideshow.mp4"
        filename = file.filename.split('.')[0]
        video_filename = f"{filename}.mp4"
        output_path = os.path.join(os.path.abspath("static"), video_filename)
        clean_directories(keep_video=output_path)
        pdf_path = save_uploaded_file(file, unique_id)

        video_filename = encode(video_filename)
        output_path = encode(output_path)
        pdf_path = encode(pdf_path)

        return jsonify({
            'pdf_path': pdf_path,
            'output_path': output_path,
            'video_filename': video_filename
        })
    except Exception as e:
        print(f"Error during upload: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload_progress/<pdf_path>/<output_path>/<video_filename>')
def upload_progress(pdf_path, output_path, video_filename):
    pdf_path = decode(pdf_path)
    output_path = decode(output_path)
    video_filename = decode(video_filename)
    api_key = session.get('api_key')
    def generate():
        try:
            # PDF to images
            yield "data: 1\n\n"
            images = convert_pdf_to_images(pdf_path)
            if images < 10:
                time.sleep(2)
            # create scripts for each image
            yield "data: 2\n\n"
            scripts = generate_scripts_for_images("output/images", api_key)

            yield "data: 3\n\n"
            generate_audio_files(scripts, api_key)

            # produce final video
            yield "data: 4\n\n"
            create_video_ffmpeg("output/images", "output/audio", output_path)
            yield "data: 5\n\n"

            if not os.path.exists(output_path):
                raise RuntimeError(f"Video was not created at {output_path}")
            
            # setup QA system with the generated scripts
            setup_qa_for_chat(scripts, api_key)
            
            # video URL used by the frontend
            video_url = f"/api/static/{video_filename}"
            time.sleep(2)
            yield f"data: Process complete. Video available at: {video_url}\n\n"
            
        except Exception as e:
            yield f"data: Error: {str(e)}--{pdf_path}\n\n"
            # optionally break out of the generator
            return
        
    return Response(generate(), mimetype='text/event-stream')

@app.route("/download_video", methods=["GET"])
def download_video():
    if "api_key" not in session:
        return redirect(url_for("setup_api"))

    video_path = request.args.get("video_path") or session.get("generated_video_path")
    
    if not video_path:
        return "Video path not provided.", 400
    
    # Clean up the path to avoid double static
    video_path = video_path.replace('/api/static/', '/').replace('//static/', '/').replace('static/', '')
    video_path = os.path.join('static', video_path)
    
    if not os.path.exists(video_path):
        return f"Video not found on server. Path: {video_path}", 404

    return send_file(video_path, as_attachment=True)

@app.route("/clear_session", methods=["POST", "OPTIONS"])
def clear_session():
    if request.method == "OPTIONS":
        return jsonify({"success": True}), 200
    
    session.clear()
    # remove all leftover files.
    clean_directories(keep_video=None)

    global qa_chain, content_filter, scripts_global
    qa_chain = None
    content_filter = None
    scripts_global = None
    
    return jsonify({"success": True, "message": "Session cleared successfully"})

@app.route('/progress')
def get_progress():
    return jsonify({
        'stage': session.get('current_stage', 'Starting processing'),
        'progress': session.get('progress', 0),
        'details': session.get('stage_details', '')
    })

def update_progress(stage, progress, details=""):
    session['current_stage'] = stage
    session['progress'] = progress
    session['stage_details'] = details
    session.modified = True

# chat QA
@app.route("/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS":
        return jsonify({"success": True}), 200
    
    api_key = session.get('api_key')
    if not api_key:
        return jsonify({"error": "API key not set"}), 401
    
    global qa_chain, content_filter
    
    data = request.get_json() or {}
    user_question = data.get("question", "").strip()
    if not user_question:
        return jsonify({"error": "Question cannot be empty"}), 400
    
    # content_filter check
    if content_filter and not content_filter(user_question):
        return jsonify({
            "error": "I can only answer questions related to the lecture content."
        }), 400

    if not qa_chain:
        return jsonify({"error": "QA system not initialized."}), 400

    try:
        # ensure QA chain has updated safety instructions
        if scripts_global:
            safety_instructions = session.get('safety_instructions')
            if safety_instructions:
                setup_qa_for_chat(scripts_global, api_key, safety_instructions)
        
        answer = qa_chain.invoke(user_question)
        return jsonify({"success": True, "answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# QA setup
@app.route("/update_qa_settings", methods=["POST", "OPTIONS"])
def update_qa_settings():
    if request.method == "OPTIONS":
        return jsonify({"success": True}), 200
    
    data = request.get_json() or {}
    threshold = data.get("threshold", 0.04)
    safety_instructions = data.get("safety_instructions", "")
    
    # threshold range
    try:
        threshold = float(threshold)
        if not (0.01 <= threshold <= 0.10):
            return jsonify({"error": "Threshold must be between 0.01 and 0.10"}), 400
    except ValueError:
        return jsonify({"error": "Invalid threshold value"}), 400
    
    # store in session
    session['qa_threshold'] = threshold
    session['safety_instructions'] = safety_instructions
    
    # update the QA chain with new safety instructions
    global qa_chain, content_filter, scripts_global
    if scripts_global:
        content_filter = create_content_filter(scripts_global, threshold)
        setup_qa_for_chat(scripts_global, session.get('api_key'), safety_instructions)
    
    return jsonify({"success": True, "message": "QA settings updated"})

def setup_qa_for_chat(scripts, api_key, safety_instructions=None):
    """Sets up a simple QA system using a vectorstore + OpenAI."""
    global qa_chain, content_filter, scripts_global

    print(f"[QA Setup] Setting up QA chain with safety instructions: {bool(safety_instructions)}")
    
    scripts_global = scripts
    try:
        threshold = session.get('qa_threshold', 0.04)
        print(f"[QA Setup] Creating content filter with threshold: {threshold}")
        content_filter = create_content_filter(scripts, threshold)
    except Exception as e:
        print(f"Warning: Content filter creation failed: {str(e)}")
        content_filter = lambda _: True
    
    # retrieval QA
    embeddings = OpenAIEmbeddings(api_key=api_key)
    vector_store = FAISS.from_texts(scripts, embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    llm = OpenAI(api_key=api_key)
    
    base_prompt = """
You are an expert lecturer. Below is some context from the lecture:
{context}

Now, answer the following question:
Question: {question}

If the question requires further explanation beyond what is in the provided lecture notes, feel free to include additional relevant details from your expertise. However, if the question is completely off-topic, reply with: 'I can only answer questions related to the lecture content.'
"""
    
    # inject safety instructions after the base instructions
    if safety_instructions:
        print(f"[QA Setup] Adding safety instructions to prompt (length: {len(safety_instructions)})")
        base_prompt += f"\nAdditional Instructions:\n{safety_instructions}"
    
    base_prompt += "\nAnswer:"
    print("[QA Setup] Final prompt template created")
    
    prompt = ChatPromptTemplate.from_template(base_prompt)
    
    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    qa_chain = chain
    print("[QA Setup] QA chain setup complete")

def create_content_filter(scripts, threshold=0.04):
    """Create a more robust content filter that checks if user queries match the lecture content."""
    combined_text = " ".join(scripts)
    vectorizer = TfidfVectorizer(
        stop_words='english',
        ngram_range=(1, 2),
        min_df=1,
        max_df=1.0,
        lowercase=True,
        strip_accents='unicode'
    )
    texts_to_fit = scripts + [combined_text]
    vectorizer.fit(texts_to_fit)
    
    def filter_func(question):
        """Filter out questions that are not related to the lecture content."""
        try:
            question = question.strip().lower()
            if not question:
                return False
            question_tfidf = vectorizer.transform([question])
            texts_tfidf = vectorizer.transform(texts_to_fit)
            sims = cosine_similarity(question_tfidf, texts_tfidf).flatten()
            max_sim = np.max(sims)
            print(f"[ContentFilter] Max similarity = {max_sim:.4f} for question '{question}'")
            return max_sim > threshold
        except Exception as e:
            print(f"Content filter error: {str(e)}")
            return True  

    return filter_func

def format_docs(docs):
    return "\n\n".join([d.page_content for d in docs])

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_file(os.path.join('static', filename))

if __name__ == '__main__':
    setup_directories()
    app.run(host='0.0.0.0', port=8080)
