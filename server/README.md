# 音频文件服务器 V1.6

一个简单的音频文件上传和管理服务器。

## 功能特点

- 支持音频文件上传和播放
- 域名白名单管理
- 文件自动清理（1小时后自动删除）
- 完整的操作日志记录
- 管理后台功能
- Docker 支持

## 快速开始

### 使用 Docker

```bash
# 构建镜像
docker build -t audio-server:1.6 .

# 运行容器
docker run -d -p 8000:8000 -v ./voice:/app/voice -v ./logs:/app/logs audio-server:1.6