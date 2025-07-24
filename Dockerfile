# Dockerfile following runpod-wan approach with separate start.sh
FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

# Essential environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /workspace

# Install system dependencies (including OpenGL for opencv)
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11=3.11.13-1+jammy1 \
    python3.11-venv \
    python3.11-dev \
    curl \
    wget \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy project files (they'll be copied to network storage by start.sh)
COPY workflow/ /tmp/workflow/
COPY prompts/ /tmp/prompts/
COPY src/handler.py /rp_handler.py

# Copy and make start script executable
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Set working directory and use the start script
WORKDIR /
CMD ["/start.sh"]