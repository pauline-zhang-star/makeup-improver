FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/mpl PYTHONPATH=/app/src
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libegl1 libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir . 'mediapipe==0.10.35'

# Same Google Face Landmarker asset verified in local testing; fail the build if it changes.
RUN mkdir -p models /tmp/mpl /var/data && \
    curl -fsSL 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task' \
      -o models/face_landmarker.task && \
    echo '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff  models/face_landmarker.task' | sha256sum -c -

CMD ["python", "-m", "makeup_refine.web_app", "--host", "0.0.0.0"]
