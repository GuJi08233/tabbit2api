FROM python:3.11-slim

LABEL maintainer="Tabbit2API"
LABEL description="Tabbit2API - Tabbit to OpenAI/Claude Compatible API"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN rm -rf __pycache__ core/__pycache__ routes/__pycache__ \
    && find . -name "*.pyc" -delete \
    && chmod +x docker-entrypoint.sh

VOLUME ["/app/data"]

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8800/v1/models', timeout=5)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
