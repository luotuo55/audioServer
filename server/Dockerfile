# 使用官方 Python 运行时作为父镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 将当前目录内容复制到容器的 /app 中
COPY . /app

# 创建上传目录和静态文件目录
RUN mkdir -p /app/voice /app/public

# 暴露端口 8000
EXPOSE 8000

# 运行 static_server.py 当容器启动时
CMD ["python", "static_server.py"]
