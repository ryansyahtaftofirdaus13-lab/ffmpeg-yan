import os
import json
import uuid
import subprocess
import threading
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = '/tmp/acf'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ============================================================
# HELPER
# ============================================================
def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr

def update_status(job_path, data):
    try:
        with open(job_path, 'w') as f:
            json.dump(data, f)
    except:
        pass

def process_video_async(job_id, input_path, features, settings):
    base = f"{UPLOAD_FOLDER}/{job_id}"
    paths = {
        "input":     input_path,
        "clean":     f"{base}_clean.mp4",
        "audio":     f"{base}_audio.mp3",
        "srt":       f"{base}.srt",
        "subtitled": f"{base}_sub.mp4",
        "final":     f"{base}_final.mp4",
        "job":       f"{base}_job.json"
    }

    def status(step, progress, extra={}):
        update_status(paths["job"], {
            "jobId": job_id, "status": "processing",
            "step": step, "progress": progress, **extra
        })

    status("started", 5)

    # 1. SILENCE REMOVAL
    if features.get("silence", True):
        status("silence_removal", 15)
        db = settings.get("threshold", "-40dB").replace("dB", "")
        cmd = (
            f'ffmpeg -i "{paths["input"]}" '
            f'-af "silenceremove=start_periods=1:start_duration=0.3:start_threshold={db}dB:detection=peak,'
            f'silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold={db}dB:detection=peak" '
            f'-c:v copy -c:a aac "{paths["clean"]}" -y 2>&1'
        )
        code, out, err = run_cmd(cmd)
        if code != 0:
            run_cmd(f'cp "{paths["input"]}" "{paths["clean"]}"')
        status("silence_done", 22)
    else:
        run_cmd(f'cp "{paths["input"]}" "{paths["clean"]}"')
        status("silence_skipped", 22)

    # 2. EXTRACT AUDIO
    if features.get("subtitle", True):
        status("extracting_audio", 28)
        run_cmd(
            f'ffmpeg -i "{paths["clean"]}" '
            f'-vn -acodec libmp3lame -ar 16000 -ac 1 "{paths["audio"]}" -y'
        )
        status("audio_extracted", 32)

    # Simpan path info untuk N8n ambil
    status("ready_for_whisper", 35, {
        "paths": paths,
        "audioPath": paths["audio"],
        "cleanPath": paths["clean"]
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "FFmpeg API", "version": "1.0"})

# ============================================================
# ENDPOINT 1: Upload & mulai proses awal
# ============================================================
@app.route("/process/start", methods=["POST"])
def process_start():
    if "video" not in request.files:
        return jsonify({"error": "No video file"}), 400

    file = request.files["video"]
    job_id = request.form.get("jobId") or ("job_" + uuid.uuid4().hex[:8])
    features = json.loads(request.form.get("features", "{}"))
    settings = json.loads(request.form.get("settings", "{}"))

    # Simpan file
    input_path = f"{UPLOAD_FOLDER}/{job_id}_input.mp4"
    file.save(input_path)

    # Proses async
    t = threading.Thread(
        target=process_video_async,
        args=(job_id, input_path, features, settings)
    )
    t.daemon = True
    t.start()

    return jsonify({
        "status": "processing",
        "jobId": job_id,
        "message": "Video diterima, sedang diproses"
    })

# ============================================================
# ENDPOINT 2: Silence removal saja
# ============================================================
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

    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-af "silenceremove=start_periods=1:start_duration=0.3:start_threshold={threshold}dB:detection=peak,'
        f'silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold={threshold}dB:detection=peak" '
        f'-c:v copy -c:a aac "{output_path}" -y 2>&1'
    )
    code, out, err = run_cmd(cmd)

    if code != 0:
        run_cmd(f'cp "{input_path}" "{output_path}"')

    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "silence_done", "progress": 25})

    return jsonify({
        "status": "done",
        "jobId": job_id,
        "outputPath": output_path,
        "success": code == 0
    })

# ============================================================
# ENDPOINT 3: Ekstrak audio untuk Whisper
# ============================================================
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

    return jsonify({
        "status": "done",
        "jobId": job_id,
        "audioPath": output_path,
        "success": code == 0
    })

# ============================================================
# ENDPOINT 4: Burn subtitle ke video
# ============================================================
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

    # Simpan SRT
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "burning_subtitle", "progress": 48})

    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-vf "subtitles=\'{srt_path}\':force_style=\'FontName=Arial,FontSize=16,'
        f'PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Bold=1,Alignment=2\'" '
        f'-c:a copy "{output_path}" -y 2>&1'
    )
    code, out, err = run_cmd(cmd)

    if code != 0:
        run_cmd(f'cp "{input_path}" "{output_path}"')

    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "subtitle_done", "progress": 58})

    return jsonify({
        "status": "done",
        "jobId": job_id,
        "outputPath": output_path,
        "srtPath": srt_path,
        "success": code == 0
    })

# ============================================================
# ENDPOINT 5: Buat Shorts (crop 9:16)
# ============================================================
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
        cmd = (
            f'ffmpeg -i "{input_path}" '
            f'-ss {m["start"]} -to {m["end"]} '
            f'-vf "scale=1080:1920:force_original_aspect_ratio=decrease,'
            f'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,crop=1080:1920" '
            f'-c:a copy "{out}" -y 2>&1'
        )
        code, out_log, err = run_cmd(cmd)
        results.append({
            "index": i+1,
            "title": m.get("title", f"Short {i+1}"),
            "outputPath": out,
            "success": code == 0
        })

    update_status(job_path, {"jobId": job_id, "status": "processing", "step": "shorts_done", "progress": 75})

    return jsonify({
        "status": "done",
        "jobId": job_id,
        "shorts": results
    })

# ============================================================
# ENDPOINT 6: Status job
# ============================================================
@app.route("/status/<job_id>", methods=["GET"])
def get_status(job_id):
    job_path = f"{UPLOAD_FOLDER}/{job_id}_job.json"
    try:
        with open(job_path, "r") as f:
            return jsonify(json.load(f))
    except:
        return jsonify({"status": "not_found", "jobId": job_id}), 404

# ============================================================
# ENDPOINT 7: Download file hasil
# ============================================================
@app.route("/file/<job_id>/<file_type>", methods=["GET"])
def get_file(job_id, file_type):
    file_map = {
        "final":    f"{UPLOAD_FOLDER}/{job_id}_sub.mp4",
        "audio":    f"{UPLOAD_FOLDER}/{job_id}_audio.mp3",
        "srt":      f"{UPLOAD_FOLDER}/{job_id}.srt",
        "clean":    f"{UPLOAD_FOLDER}/{job_id}_clean.mp4",
    }
    path = file_map.get(file_type)
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_file(path)

# ============================================================
# ENDPOINT 8: Cleanup job files
# ============================================================
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
    app.run(host="0.0.0.0", port=port, debug=False)
