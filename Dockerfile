# Stage 1 builds the React page into static files. Node stays out of the final image.
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

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

# OpenVINO runs the same trained models about 2x faster on a CPU, with identical detections.
RUN pip install --no-cache-dir openvino

COPY backend backend
COPY vision vision
COPY db db
COPY models models

# Convert the model to OpenVINO (next to the .pt file). vision/yolo_detector.py uses it
# whenever there is no Mac GPU. dynamic=True because the code runs two image sizes.
RUN python -c "from ultralytics import YOLO; \
YOLO('models/basketball_yolo.pt').export(format='openvino', dynamic=True)"

COPY --from=frontend /frontend/dist frontend/dist

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
