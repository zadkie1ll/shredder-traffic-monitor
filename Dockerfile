ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY common ./common
COPY proto ./proto

CMD ["python", "-m", "app.main"]
