# 使用官方 Python 运行时作为父镜像
FROM python:3.9-slim

# 设置版本信息
LABEL version="1.6" \
      description="音频文件服务器" \
      maintainer="Your Name <your.email@example.com>"

# 设置工作目录
WORKDIR /app

# 复制项目文件到容器中
COPY . /app/

# 创建必要的目录
RUN mkdir -p /app/voice /app/logs

# 设置环境变量
ENV VERSION=1.6 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# 暴露端口
EXPOSE ${PORT}

# 设置容器启动时执行的命令
CMD ["python", "static_server.py"]

# 添加健康检查
HEALTHCHECK --interval=30s --timeout=3s \
    CMD curl -f http://localhost:${PORT}/ || exit 1
