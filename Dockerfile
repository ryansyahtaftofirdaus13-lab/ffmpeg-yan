FROM python:3.11-slim

# Install FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .
RUN mkdir -p /tmp/acf

EXPOSE 8000
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:8000", "--timeout=300", "main:app"]
