# Image for the per-world emulated providers + edge proxy + reset helper.
FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27" "pydantic>=2.7"
WORKDIR /srv
COPY app.py /srv/app.py
ENV RH_PROVIDER_DATA=/data RH_PORT=9000 RH_SMTP_PORT=2525
EXPOSE 9000 2525
CMD ["python", "/srv/app.py"]
