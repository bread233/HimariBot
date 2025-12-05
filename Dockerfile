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

# 1️⃣ 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# 2️⃣ 升级 pip
RUN pip install --upgrade pip

# 3️⃣ 安装 poetry
RUN pip install --no-cache-dir "poetry>=1.8,<2.0"

# 4️⃣ 优化构建缓存
COPY pyproject.toml poetry.lock* ./

# 5️⃣ 安装依赖 + NoneBot 驱动
RUN poetry lock --no-update \
    && poetry install --only main --no-interaction --no-ansi -vvv \
    && pip install "nonebot2[fastapi,httpx]" \
    && pip install nonebot-adapter-onebot nonebot-adapter-qq

# 6️⃣ 拷贝应用源码
COPY . .

# 7️⃣ 默认环境变量模板
RUN cp .env.dev.example .env.dev

# 8️⃣ 复制默认资源到备份目录（不要直接放 /app/data！）
#COPY resources/data/ /app/resources-default/

# 9️⃣ 拷贝入口脚本
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8181
EXPOSE 5888

# 10️⃣ 正确入口：先处理默认资源再启动程序
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
