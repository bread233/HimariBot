########################
# 1️⃣ Builder 镜像
########################
FROM python:3.10-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    POETRY_HOME=/opt/poetry \
    PATH="/opt/poetry/bin:$PATH" \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# 编译期依赖（只在 builder 里）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "poetry>=1.8,<2.0" \
 && rm -rf /var/lib/apt/lists/*

# 只复制依赖定义，利用缓存
COPY pyproject.toml poetry.lock* ./

RUN poetry lock --no-update \
    && poetry install --only main --no-interaction --no-ansi -vvv \
    && pip install --no-cache-dir "nonebot2[fastapi,httpx]" \
    && pip install --no-cache-dir nonebot-adapter-onebot nonebot-adapter-qq \
    && rm -rf /root/.cache/pip /root/.cache/pypoetry

# 再复制源码
COPY . .

# 做一些清理
RUN cp .env.dev.example .env.dev \
    && find . -name '*.pyc' -delete \
    && find . -name '__pycache__' -type d -exec rm -rf {} +


########################
# 2️⃣ Runtime 镜像（真正跑的）
########################
FROM python:3.10-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    HOST=0.0.0.0 \
    PORT=8181

WORKDIR /app

# ⚠️ 这里只装运行时必须的库（不装 build-essential / gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# 从 builder 拷贝安装好的 Python 依赖和代码
# /usr/local/lib/python3.10 里是 site-packages（依赖）
# /usr/local/bin 里是可执行脚本（nonebot, uvicorn 等）
COPY --from=builder /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8181
EXPOSE 5888

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
