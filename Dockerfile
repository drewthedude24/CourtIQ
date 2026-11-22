FROM python:3.12-slim

# ffmpeg converts the annotated video to H.264 so browsers can play it.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch. The default build bundles GPU libraries (gigabytes) a server without a GPU never uses.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Ultralytics pulls in opencv-python, which needs desktop graphics libraries.
# The headless build is the same OpenCV without the window code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless

COPY backend backend
COPY vision vision
COPY db db
COPY models models
COPY yolo26n-pose.pt .

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
