FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]==0.32.*" httpx==0.28.* "psycopg[binary]==3.2.*"
WORKDIR /app
COPY app.py .
USER 1000:1000
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
