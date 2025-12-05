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
### 📁 数据存储说明
```bash
容器路径	说明	是否挂载
/app/data	数据库、插件数据	✔ 推荐
/app/log	日志文件	✔ 推荐
/app/.env.dev	环境配置	✔ 必须

挂载后容器升级不会丢数据 🛡
```

---

### 🪟 Windows 系统使用说明（无 Docker）

适用于 Windows Server / Windows 10+
自动构建的 .exe 版本支持直接运行 HimariBot

#### 1️⃣ 下载发布的 Windows 版本

前往 Releases 页面，下载 ZIP 包：

👉 https://github.com/bread233/HimariBot/releases

下载后解压，将会包含：
```bash
HimariBot.exe
.env.dev.example
data/（首次无，可自行创建）
log/（首次无，可自行创建）
```

#### 2️⃣ 配置 .env.dev
将示例配置复制：
```go
copy .env.dev.example .env.dev
```
并填入你的：
| 项目              |        必填       |
| --------------- | :-------------: |
| QQ Bot Token    |        ✔        |
| NapCat 反向 WS 地址 |        ✔        |
| AppID / Secret  | 若使用 Webhook 时必填 |

#### 3️⃣ 启动机器人
在解压目录运行：
```powershell
.\HimariBot.exe
```
看到以下日志即代表连接成功：
```powershell
Bot connected: <你的QQ号>
```

#### 4️⃣ 后台常驻运行（推荐）

Windows Server 可使用以下方式常驻：

任务计划程序 开机自启

使用 NSSM 注册为系统服务

使用 WinSW 作为后台守护进程

如需，我可以为你生成 Windows 服务安装脚本 👌

---

### 🧩 技术栈
Python 3.10

NoneBot2

官方 QQ Webhook / OneBot v11

Docker（推荐生产环境）

Windows EXE（便携运行）

---

### ⚠️ 使用声明
本项目仅供学习交流
禁止用于违反法律法规及 QQ 协议的行为！

---

### 🏆 鸣谢 NapCatQQ
感谢 NapCatQQ 提供稳定的 OneBot 协议支持
使 HimariBot 能高效地与 QQ 进行数据交互

🔗 https://github.com/NapNeko/NapCatQQ

> 开源社区使一切变得更好 💖


---

### ⭐ 支持与反馈
如果 HimariBot 对你有帮助，请点亮 ⭐ 支持一下！

---

### GitHub 项目地址
👉 https://github.com/bread233/HimariBot/tree/a01