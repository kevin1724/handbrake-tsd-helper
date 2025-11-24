FROM python:3.12-slim

# Install HandBrakeCLI and some helpers from Debian repos
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        handbrake-cli ffmpeg mediainfo gnupg wget && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the web UI app
COPY app.py /app/app.py

# Install Flask
RUN pip install flask

EXPOSE 8080

CMD ["python", "app.py"]
