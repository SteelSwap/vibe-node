FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    paddlepaddle \
    paddleocr \
    pymupdf \
    flask

COPY server.py /app/server.py

WORKDIR /app
EXPOSE 8080

CMD ["python", "server.py"]
