# 多阶段构建 Dockerfile for AI Story Creator
# 支持多架构构建: linux/amd64, linux/arm64

# 构建参数
ARG USE_CN_MIRROR=false

# 阶段1: 构建前端
FROM node:22-alpine AS frontend-builder

ARG USE_CN_MIRROR

WORKDIR /frontend

# 复制前端依赖文件
COPY frontend/package*.json ./

# 根据参数决定是否使用国内npm镜像
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        npm config set registry https://registry.npmmirror.com; \
    fi

# 删除 package-lock.json 以避免因镜像源不一致导致的 404 错误
RUN rm -f package-lock.json

# 安装依赖
RUN npm install

# 复制前端源代码
COPY frontend/ ./

# 临时修改vite配置，使其输出到dist目录（而不是../backend/static）
RUN sed -i "s|outDir: '../backend/static'|outDir: 'dist'|g" vite.config.ts

# 构建前端
RUN npm run build

# 阶段2: 构建最终镜像
FROM python:3.11-slim

ARG USE_CN_MIRROR
ARG TARGETPLATFORM
ARG TARGETARCH
ARG PRELOAD_EMBEDDING_MODEL=false

# 设置工作目录
WORKDIR /app

# 根据参数决定是否使用国内镜像源
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    fi

# 安装系统依赖（添加数据库工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# 复制后端依赖文件
COPY backend/requirements.txt ./

# 根据架构安装PyTorch CPU版本
# arm64架构使用pip直接安装，amd64使用PyTorch官方CPU源
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu || \
        pip install --no-cache-dir torch; \
    else \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu || \
        pip install --no-cache-dir torch; \
    fi

# 安装其他Python依赖
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# 创建embedding目录
RUN mkdir -p /app/embedding

# 设置 Sentence-Transformers 缓存目录
ENV SENTENCE_TRANSFORMERS_HOME=/app/embedding

# 下载 embedding 模型（从 HuggingFace）
# 使用 Python 脚本预下载模型，这样运行时不需要网络。
# 本地联调默认跳过预下载，避免构建阶段长时间卡在模型拉取。
RUN if [ "$PRELOAD_EMBEDDING_MODEL" = "true" ]; then \
      python -c "\
from sentence_transformers import SentenceTransformer; \
import os; \
os.environ['SENTENCE_TRANSFORMERS_HOME'] = '/app/embedding'; \
print('Downloading sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2...'); \
model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); \
print('Model downloaded successfully!'); \
"; \
    else \
      echo "Skipping embedding model predownload (PRELOAD_EMBEDDING_MODEL=$PRELOAD_EMBEDDING_MODEL)"; \
    fi

# 复制后端代码（不包含embedding，因为已经下载了）
COPY backend/ ./

# 从前端构建阶段复制构建好的静态文件
COPY --from=frontend-builder /frontend/dist ./static

# 复制 Alembic 迁移配置和脚本（PostgreSQL）
COPY backend/alembic-postgres.ini ./alembic.ini
COPY backend/alembic/postgres ./alembic
COPY backend/scripts/entrypoint.sh /app/entrypoint.sh
COPY backend/scripts/migrate.py ./scripts/migrate.py

# 赋予执行权限
RUN chmod +x /app/entrypoint.sh

# 创建必要的目录
RUN mkdir -p /app/data /app/logs

# 暴露端口
EXPOSE 8000

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000

# 若构建时预下载模型，则运行时启用离线模式；否则允许在线拉取模型
ENV TRANSFORMERS_OFFLINE=${PRELOAD_EMBEDDING_MODEL}
ENV HF_DATASETS_OFFLINE=${PRELOAD_EMBEDDING_MODEL}
ENV HF_HUB_OFFLINE=${PRELOAD_EMBEDDING_MODEL}

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

# 使用 entrypoint 脚本启动（自动执行迁移）
ENTRYPOINT ["/app/entrypoint.sh"]
