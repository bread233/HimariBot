FROM python:3.9-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    POETRY_HOME=/opt/poetry \
    PATH="/opt/poetry/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8181

WORKDIR /app

# 基础依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Poetry
RUN pip install --no-cache-dir "poetry>=1.8,<2.0"

# 预加载依赖清单（加速构建）
COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# 拷贝完整代码
COPY . .

# 如果容器里还没有 .env.dev，则用 example 拷一份默认的
RUN if [ ! -f ".env.dev" ] && [ -f ".env.dev.example" ]; then \
      cp .env.dev.example .env.dev; \
    fi

# 暴露端口
EXPOSE 8181

# 声明数据卷
VOLUME ["/app/data", "/app/log", "/root/.local/share/nonebot2"]

# 启动命令
CMD ["python", "bot.py"]
