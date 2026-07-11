FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ENV PIP_TRUSTED_HOST=mirrors.cloud.tencent.com

RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.tencentyun.com/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.tencentyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
