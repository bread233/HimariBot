FROM python:3.10-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    POETRY_HOME=/opt/poetry \
    PATH="/opt/poetry/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8181 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# 1. 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# 2. 升级 pip（你要求的关键新增）
RUN pip install --upgrade pip

# 3. 安装 poetry
RUN pip install --no-cache-dir "poetry>=1.8,<2.0"

# 4. 先拷贝依赖文件，加速缓存
COPY pyproject.toml poetry.lock* ./

# 5. 在镜像里同步 lock + 安装 nonebot
RUN poetry lock --no-update \
    && poetry install --only main --no-interaction --no-ansi -vvv \
    && pip install "nonebot2[fastapi]"

# 6. 拷贝项目代码
COPY . .

# 7. 拷贝默认 env 配置
RUN cp .env.dev.example .env.dev

EXPOSE 8181

VOLUME ["/app/data", "/app/log", "/root/.local/share/nonebot2"]

CMD ["python", "bot.py"]
