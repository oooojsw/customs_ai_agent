# -------------------------------------------------------------------
# 阶段 1: 构建环境
# -------------------------------------------------------------------
# 使用一个官方的、轻量级的 Python 3.11 镜像作为基础
FROM python:3.11-slim as builder

# 设置工作目录，后续所有操作都在这个目录下进行
WORKDIR /app

# 设置 PIP 环境变量，提升安装速度并避免日志过长
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# 安装构建 FAISS 和其他库可能需要的系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 仅复制 requirements.txt 文件，利用 Docker 的层缓存机制
# 只要这个文件不变，下面的 pip install 就不会重复执行，大大加快后续构建速度
COPY requirements.txt .

# 安装所有 Python 依赖
# 注意：我们使用 faiss-cpu 因为在通用服务器上部署不需要 GPU 支持
RUN pip install --no-cache-dir -r requirements.txt

# -------------------------------------------------------------------
# 阶段 2: 生产环境
# -------------------------------------------------------------------
# 再次使用轻量级 Python 镜像，以减小最终镜像体积
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 从构建环境中复制已安装的 Python 依赖库
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制您项目的所有源代码到工作目录
COPY . .

# 暴露应用程序运行的端口 8000
EXPOSE 8000

# 定义容器启动时要执行的命令
# 使用 uvicorn 启动您的 FastAPI 应用，并监听所有网络接口
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]