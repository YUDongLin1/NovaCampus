FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "mcp==2.2.0"
COPY server.py .
ENV WEEKLY_DATA_DIR=/data WEEKLY_PORT=8000
RUN mkdir -p /data/reports
EXPOSE 8000
CMD ["python", "server.py"]
