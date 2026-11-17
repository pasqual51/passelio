FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 passelio \
    && useradd --uid 10001 --gid 10001 --no-create-home passelio \
    && mkdir /data && chown 10001:10001 /data
COPY app.py mailer.py branding.py themes.py worker.py ./
COPY third_party/ ./third_party/
COPY static/ ./static/
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=3)"
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--no-control-socket", "--workers", "2", "--worker-class", "gthread", "--threads", "4", "--timeout", "300", "--worker-tmp-dir", "/tmp", "app:create_app()"]
