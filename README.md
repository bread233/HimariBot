# 🐱 HimariBot

轻量、易部署的 QQ 机器人  
使用 NoneBot2 + 官方 QQ Webhook / Lagrange OneBot 协议

> ✨ 适用于家庭 NAS / 云服务器 7×24h 稳定运行

---

## 🚀 快速部署

建议使用 Docker + docker-compose，确保数据不会丢失。

---

### ✔ 推荐方式：Docker Compose 部署

#### 1️⃣ 准备宿主机目录

```bash
mkdir -p 宿主机目录/{data,log}

```

cd 宿主机目录
#### 2️⃣ 拷贝配置文件
从示例文件复制并按需修改：

```bash
复制代码
cp 宿主机目录/.env.dev.example .env.dev
vim .env.dev
⚠️ .env.dev 内包含 Bot Token、AppID 等敏感信息
请妥善保管，勿提交至 GitHub

```

#### 3️⃣ 创建 docker-compose.yml

```bash
version: "3.9"

services:
  himaribot:
    image: xmb233/himaribot:latest
    container_name: himaribot
    restart: always

    working_dir: /app
    ports:
      - "8181:8181"  # 宿主 8181 → 容器 8181
      - "5888:5888"  # 宿主 5888 → 容器 5888

    volumes:
      - 宿主机/data:/app/data
      - 宿主机/log:/app/log
      - 宿主机/.env.dev:/app/.env.dev:ro
      
```

#### 4️⃣ 启动服务
```bash
复制代码
docker compose up -d
```

#### 5️⃣ 查看日志
```bash
复制代码
docker compose logs -f
🎉 你的 HimariBot 已成功运行！
```
🔸 方式二：docker run 启动
```bash
docker run -d \
  --name himaribot \
  --restart=always \
  -p 8181:8181 \
  -p 5888:5888 \
  -v 宿主机/data:/app/data \
  -v 宿主机/log:/app/log \
  -v 宿主机/.env.dev:/app/.env.dev:ro \
  xmb233/himaribot:latest
```
#### 🔄 更新/重启服务
```bash
复制代码
docker compose pull
docker compose up -d
若修改 .env.dev 后需重启容器：
```
```bash
docker compose restart
```
#### 📁 数据存储说明
```bash
容器路径	说明	是否挂载
/app/data	数据库、插件数据	✔ 推荐
/app/log	日志文件	✔ 推荐
/app/.env.dev	环境配置	✔ 必须

挂载后容器升级不会丢数据 🛡
```
### 🧩 技术栈
Python 3.10

NoneBot2

官方 QQ Webhook / OneBot v11

### Docker 容器部署

### 📦 首次部署资源包

镜像不包含大体积资源与运行数据目录。首次部署前，请先准备外置 data 资源包。

1. 前往 GitHub Release 下载 `himaribot-data.zip`。
2. 将资源包解压到宿主机的 `data` 映射目录。
3. 使用 Docker Compose 挂载 `./data:/app/data`。

docker compose volume 示例：

```yaml
services:
  himaribot:
    volumes:
      - ./data:/app/data
```

Synology 示例路径：

```text
/volume1/docker/himaribot/himari/data
```

解压后目录结构示例：

```text
data/resources/tarot/tarot.json
data/resources/tarot/resource/BilibiliTarot
data/xiuxian
```

如果你只需要 Tarot 资源，也可以下载 `tarot-resources.zip`，并解压到：

```text
data/resources
```

特别提醒：

- `himaribot-data.zip` 压缩包顶层已经是 `autoreply/`、`resources/`、`xiuxian/` 等目录。
- 请直接在宿主机 `data` 映射目录内解压，不要再多套一层 `data/`。

正确路径示例：

```text
/volume1/docker/himaribot/himari/data/resources/tarot/tarot.json
/volume1/docker/himaribot/himari/data/xiuxian
```

错误路径示例（多套一层 data）：

```text
/volume1/docker/himaribot/himari/data/data/resources/tarot/tarot.json
/volume1/docker/himaribot/himari/data/data/xiuxian
```

### ⚠️ 使用声明
本项目仅供学习交流
禁止用于违反法律法规及 QQ 协议的行为！

### ⭐ 支持与反馈
如果 HimariBot 对你有帮助，请点亮 ⭐ 支持一下！

### GitHub 项目地址
👉 https://github.com/bread233/HimariBot/tree/a01