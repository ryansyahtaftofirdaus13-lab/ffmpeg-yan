# FFmpeg API untuk AI Content Factory

## Deploy ke Railway

1. Buka railway.app → New Project → Deploy from GitHub
2. Upload folder ini atau connect GitHub repo
3. Railway auto-detect Dockerfile dan deploy
4. Dapat URL seperti: https://ffmpeg-api-xxx.railway.app

## Endpoints

| Method | URL | Fungsi |
|--------|-----|--------|
| GET | /health | Cek status API |
| POST | /process/silence | Hapus silence dari video |
| POST | /process/extract-audio | Ekstrak audio MP3 |
| POST | /process/burn-subtitle | Burn SRT ke video |
| POST | /process/make-shorts | Buat Shorts 9:16 |
| GET | /status/{jobId} | Cek status job |
| GET | /file/{jobId}/{type} | Download file hasil |
| DELETE | /cleanup/{jobId} | Hapus file temp |

## Contoh Request

### Silence Removal
```json
POST /process/silence
{
  "jobId": "job_123",
  "inputPath": "/tmp/acf/job_123_input.mp4",
  "threshold": "-40dB"
}
```

### Burn Subtitle
```json
POST /process/burn-subtitle
{
  "jobId": "job_123",
  "inputPath": "/tmp/acf/job_123_clean.mp4",
  "srtContent": "1\n00:00:01,000 --> 00:00:03,000\nHalo semuanya!"
}
```
