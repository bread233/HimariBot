FROM python:3.9-slim

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
#   - build-essential / gcc: 编译 C 扩展
#   - libjpeg / zlib / libpng: Pillow 用
#   - libffi-dev: 某些加密/HTTP库用
#   - git: !!! 很关键，如果 pyproject 里有 git+https 依赖，没有 git 会直接让 poetry install 失败
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# 2. 安装 poetry
RUN pip install --no-cache-dir "poetry>=1.8,<2.0"

# 3. 先拷贝依赖文件，加速缓存
COPY pyproject.toml poetry.lock* ./

# 4. 在镜像里同步一下 lock
RUN poetry lock --no-update \
 && poetry install --only main --no-interaction --no-ansi -vvv

# 5. 再拷贝项目代码
COPY . .

# 6. 环境文件：容器内部先复制一份默认 dev 配置
#    （宿主机会用 volume 把外面的 .env.dev 覆盖进来）
RUN cp .env.dev.example .env.dev

EXPOSE 8181

VOLUME ["/app/data", "/app/log", "/root/.local/share/nonebot2"]

CMD ["python", "bot.py"]
