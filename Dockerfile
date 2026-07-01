FROM python:3.12-slim

ARG TORCH_VARIANT=cuda
ARG TORCH_CUDA_INDEX_URL=https://download.pytorch.org/whl/cu121

RUN apt-get update && apt-get install -y \
    ffmpeg \
    espeak-ng \
    tesseract-ocr \
    tesseract-ocr-eng \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch first so we control CPU vs CUDA builds explicitly.
# Default is CUDA because this project is running on an NVIDIA workstation.
# Override with: docker compose build --build-arg TORCH_VARIANT=cpu
RUN if [ "$TORCH_VARIANT" = "cuda" ]; then \
        pip install --no-cache-dir --index-url "$TORCH_CUDA_INDEX_URL" torch; \
    else \
        pip install --no-cache-dir torch; \
    fi

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

COPY app/ /app/

CMD ["python", "pdf_to_mp3.py"]
