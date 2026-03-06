import os
import json
import uuid
import subprocess
import threading
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
UPLOAD_FOLDER = '/tmp/acf'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr

def update_status(job_path, data):
    try:
        with open(job_path, 'w') as f:
            json.dump(data, f)
    except:
        pass

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "FFmpeg API"})

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "message": "FFmpeg API running"})

@app.route("/process/silence", methods=["POST"])
def process_silence():
    data = request.json or {}
    job_id = data.get("jobId")
    input_path = data.get("inputPath")
    threshold = data.get("threshold", "-40dB").replace("dB","")
    if not job_id or not input_path:
        return jsonify({"error": "jobId and inputPath required"}), 400
    output_path = f"{UPLOAD_FOLDER}/{job_id}_clean.mp4"
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "silence_removal", "progress": 15})
    cmd = (f'ffmpeg -i "{input_path}" '
           f'-af "silenceremove=start_periods=1:start_duration=0.3:start_threshold={threshold}dB:detection=peak,'
           f'silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold={threshold}dB:detection=peak" '
           f'-c:v copy -c:a aac "{output_path}" -y 2>&1')
    code, out, err = run_cmd(cmd)
    if code != 0:
        run_cmd(f'cp "{input_path}" "{output_path}"')
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "silence_done", "progress": 25})
    return jsonify({"status": "done", "jobId": job_id, "outputPath": output_path, "success": code == 0})

@app.route("/process/extract-audio", methods=["POST"])
def extract_audio():
    data = request.json or {}
    job_id = data.get("jobId")
    input_path = data.get("inputPath")
    if not job_id or not input_path:
        return jsonify({"error": "jobId and inputPath required"}), 400
    output_path = f"{UPLOAD_FOLDER}/{job_id}_audio.mp3"
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "extracting_audio", "progress": 30})
    cmd = f'ffmpeg -i "{input_path}" -vn -acodec libmp3lame -ar 16000 -ac 1 "{output_path}" -y'
    code, out, err = run_cmd(cmd)
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "audio_done", "progress": 35})
    return jsonify({"status": "done", "jobId": job_id, "audioPath": output_path, "success": code == 0})

@app.route("/process/burn-subtitle", methods=["POST"])
def burn_subtitle():
    data = request.json or {}
    job_id = data.get("jobId")
    input_path = data.get("inputPath")
    srt_content = data.get("srtContent", "")
    if not job_id or not input_path:
        return jsonify({"error": "jobId and inputPath required"}), 400
    srt_path = f"{UPLOAD_FOLDER}/{job_id}.srt"
    output_path = f"{UPLOAD_FOLDER}/{job_id}_sub.mp4"
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "burning_subtitle", "progress": 48})
    cmd = (f'ffmpeg -i "{input_path}" '
           f'-vf "subtitles=\'{srt_path}\':force_style=\'FontName=Arial,FontSize=16,'
           f'PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Bold=1,Alignment=2\'" '
           f'-c:a copy "{output_path}" -y 2>&1')
    code, out, err = run_cmd(cmd)
    if code != 0:
        run_cmd(f'cp "{input_path}" "{output_path}"')
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "subtitle_done", "progress": 58})
    return jsonify({"status": "done", "jobId": job_id, "outputPath": output_path, "success": code == 0})

@app.route("/process/make-shorts", methods=["POST"])
def make_shorts():
    data = request.json or {}
    job_id = data.get("jobId")
    input_path = data.get("inputPath")
    moments = data.get("moments", [])
    if not job_id or not input_path:
        return jsonify({"error": "jobId and inputPath required"}), 400
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "creating_shorts", "progress": 65})
    results = []
    for i, m in enumerate(moments):
        out = f"{UPLOAD_FOLDER}/{job_id}_short_{i+1}.mp4"
        cmd = (f'ffmpeg -i "{input_path}" -ss {m["start"]} -to {m["end"]} '
               f'-vf "scale=1080:1920:force_original_aspect_ratio=decrease,'
               f'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,crop=1080:1920" '
               f'-c:a copy "{out}" -y 2>&1')
        code, _, _ = run_cmd(cmd)
        results.append({"index": i+1, "title": m.get("title", f"Short {i+1}"), "outputPath": out, "success": code == 0})
    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "shorts_done", "progress": 75})
    return jsonify({"status": "done", "jobId": job_id, "shorts": results})

@app.route("/status/<job_id>", methods=["GET"])
def get_status(job_id):
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    try:
        with open(job_path, "r") as f:
            return jsonify(json.load(f))
    except:
        return jsonify({"status": "not_found", "jobId": job_id}), 404

@app.route("/status/save", methods=["POST"])
def save_status():
    data = request.json or {}
    job_id = data.get("jobId")
    if not job_id:
        return jsonify({"error": "jobId required"}), 400
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    update_status(job_path, data)
    return jsonify({"status": "saved"})

@app.route("/file/<job_id>/<file_type>", methods=["GET"])
def get_file(job_id, file_type):
    file_map = {
        "final": f"{UPLOAD_FOLDER}/{job_id}_sub.mp4",
        "audio": f"{UPLOAD_FOLDER}/{job_id}_audio.mp3",
        "srt":   f"{UPLOAD_FOLDER}/{job_id}.srt",
        "clean": f"{UPLOAD_FOLDER}/{job_id}_clean.mp4",
    }
    path = file_map.get(file_type)
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_file(path)

@app.route("/cleanup/<job_id>", methods=["DELETE"])
def cleanup(job_id):
    patterns = ["_input.mp4","_clean.mp4","_audio.mp3",".srt","_sub.mp4","_final.mp4","_thumb.jpg"]
    deleted = []
    for p in patterns:
        path = f"{UPLOAD_FOLDER}/{job_id}{p}"
        if os.path.exists(path):
            os.remove(path)
            deleted.append(path)
    return jsonify({"status": "cleaned", "deleted": deleted})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
