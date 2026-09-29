# P3a 模拟校园系统共用镜像:SERVICE 构建参数决定装配 jiaowu 或 ykt
FROM python:3.12-slim

ARG SERVICE
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    SIM_SERVICE=${SERVICE} \
    SERVICE=${SERVICE}

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY common.py ./
COPY ${SERVICE}/ /app/${SERVICE}/

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn ${SERVICE}.app:app --host 0.0.0.0 --port 8000"]
