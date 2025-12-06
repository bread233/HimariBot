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

# 安装项目依赖 + NoneBot 相关
RUN poetry lock --no-update \
    && poetry install --only main --no-interaction --no-ansi -vvv \
    && pip install --no-cache-dir "nonebot2[fastapi,httpx]" \
    && pip install --no-cache-dir nonebot-adapter-onebot nonebot-adapter-qq \
    && rm -rf /root/.cache/pip /root/.cache/pypoetry

# 再复制源码
COPY . .

# 预备默认环境变量文件（容器里没有也不报错）
RUN cp .env.dev.example .env.dev || true

# 🔧 GenshinUID 依赖预装（等价于它平时 auto_install 干的事情）
# CORE_PATH 默认：/app/gsuid_core
# GSUID_PATH：/app/gsuid_core/gsuid_core/plugins/GenshinUID
RUN git clone --depth 1 \
       https://ghproxy.com/https://github.com/Genshin-bots/gsuid_core.git \
       /app/gsuid_core \
 && mkdir -p /app/gsuid_core/gsuid_core/plugins \
 && git clone --depth 1 --branch v4 \
       https://ghproxy.com/https://github.com/KimigaiiWuyi/GenshinUID.git \
       /app/gsuid_core/gsuid_core/plugins/GenshinUID \
 && cd /app/gsuid_core \
 && poetry install --no-interaction --no-ansi \
 # 清理 pyc / __pycache__
 && find /app -name '*.pyc' -delete \
 && find /app -name '__pycache__' -type d -exec rm -rf {} +

########################
# 2️⃣ Runtime 镜像（真正跑的）
########################
FROM python:3.10-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    HOST=0.0.0.0 \
    PORT=8181 \
    GIT_PYTHON_REFRESH=quiet \
    LANG=zh_CN.UTF-8 \
    LANGUAGE=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8

WORKDIR /app

# 运行时依赖：
# - git：给 GenshinUID / GitPython 用
# - 各种图形/字体/音频依赖：给 Playwright / htmlrender 用（参考插件文档和你的日志）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    locales \
    locales-all \
    # Playwright / htmlrender 相关依赖（字体 + 图形库）
    fontconfig \
    fonts-noto \
    fonts-noto-color-emoji \
    fonts-unifont \
    fonts-wqy-zenhei \
    libnss3 \
    libxss1 \
    libasound2t64 \
    libxrandr2 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libgtk-3-0t64 \
    libgbm1 \
    libxshmfence1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libdrm2 \
    libxkbcommon0 \
    libx11-6 \
    libx11-xcb1 \
    libxext6 \
    libxfixes3 \
    libxrender1 \
    libxau6 \
    libxdmcp6 \
    # 你原来就需要的这些库
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# 生成中文 locale（给 htmlrender / Playwright 用）
RUN locale-gen zh_CN.UTF-8 || true

# 从 builder 拷贝 Python 依赖和项目代码
COPY --from=builder /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# 🔧 在镜像构建阶段安装 Playwright Chromium 浏览器
# 这样 nonebot_plugin_htmlrender 首次启动时就不会再下载/装浏览器了
RUN python -m playwright install chromium

# entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8181
EXPOSE 5888

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
