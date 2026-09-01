#!/bin/sh
set -e

# 确保挂载目录存在
mkdir -p /app/data
mkdir -p /app/log

# 外置资源检查（不自动下载/不自动拷贝）
MISSING=0

if [ ! -f /app/data/resources/tarot/tarot.json ]; then
  echo "⚠️  [HimariBot] 缺少 Tarot 资源文件: /app/data/resources/tarot/tarot.json"
  MISSING=1
fi

if [ ! -d /app/data/resources/tarot/resource ]; then
  echo "⚠️  [HimariBot] 缺少 Tarot 资源目录: /app/data/resources/tarot/resource"
  MISSING=1
fi

if [ ! -d /app/data/xiuxian ]; then
  echo "⚠️  [HimariBot] 缺少修仙数据目录: /app/data/xiuxian"
  MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
  echo "⚠️  [HimariBot] 当前镜像不内置大体积 data/resources。"
  echo "⚠️  [HimariBot] 请前往 GitHub Release 下载 himaribot-data.zip（或仅 Tarot 使用 tarot-resources.zip）。"
  echo "⚠️  [HimariBot] 将压缩包解压到宿主机映射目录（例如 ./data），并挂载到容器 /app/data。"
  echo "⚠️  [HimariBot] 解压后容器内应可见：/app/data/resources/tarot 和 /app/data/xiuxian"
fi

# nonebot-plugin-orm: 非交互环境下启动前自动执行数据库迁移，避免容器重启循环。
# 如需临时跳过，可设置 HIMARIBOT_ORM_AUTO_UPGRADE=0。
if [ "${HIMARIBOT_ORM_AUTO_UPGRADE:-1}" = "1" ]; then
  if command -v nb >/dev/null 2>&1; then
    echo "[HimariBot] Running ORM migrations: nb orm upgrade"
    nb orm upgrade
  else
    echo "⚠️  [HimariBot] nb command not found, skip ORM auto upgrade."
  fi
fi

# 启动 NoneBot
exec "$@"
