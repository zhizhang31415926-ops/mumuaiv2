#!/bin/bash

# ============================================
# Codex 一键安装启动脚本
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
NODE_VERSION="v24.3.0"
NODE_TARBALL="node-${NODE_VERSION}-linux-x64.tar.xz"
NODE_DOWNLOAD_URL="https://npmmirror.com/mirrors/node/${NODE_VERSION}/${NODE_TARBALL}"
CODEX_DIR="$HOME/.codex"
PROJECT_DIR="/workspace/my-codex-project"

# 打印信息函数
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查命令是否存在
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# 获取提权命令（检测是否有 sudo 或是否为 root）
get_elevate_cmd() {
    if [ "$(id -u)" = "0" ]; then
        # 已经是 root 用户，不需要提权
        echo ""
    elif command_exists sudo; then
        echo "sudo"
    else
        # 没有 sudo，尝试直接运行（可能在容器中）
        echo ""
    fi
}

# 检测包管理器并安装依赖
install_dependencies() {
    info "检查系统依赖..."
    
    # 检查是否需要安装 xz
    if ! command_exists xz; then
        info "正在安装 xz 解压工具..."
        ELEVATE=$(get_elevate_cmd)
        
        if command_exists apt-get; then
            $ELEVATE apt-get update -qq && $ELEVATE apt-get install -y -qq xz-utils
        elif command_exists yum; then
            $ELEVATE yum install -y -q xz
        elif command_exists dnf; then
            $ELEVATE dnf install -y -q xz
        elif command_exists pacman; then
            $ELEVATE pacman -S --noconfirm xz
        else
            error "无法自动安装 xz，请手动安装后重试"
            exit 1
        fi
        
        # 验证安装是否成功
        if ! command_exists xz; then
            error "xz 工具安装失败，请手动安装 xz-utils 后重试"
            exit 1
        fi
        success "xz 工具安装完成"
    else
        success "xz 工具已安装"
    fi
}

# ============================================
# 步骤 1: 安装 Node.js v24.3.0
# ============================================
install_node() {
    info "检查 Node.js 版本..."
    
    if command_exists node; then
        CURRENT_NODE=$(node -v)
        if [ "$CURRENT_NODE" = "$NODE_VERSION" ]; then
            success "Node.js 已是目标版本: $CURRENT_NODE"
            return 0
        else
            warning "当前 Node.js 版本: $CURRENT_NODE，将升级到 $NODE_VERSION"
        fi
    else
        info "Node.js 未安装，开始安装..."
    fi
    
    # 下载 Node.js
    info "正在下载 Node.js ${NODE_VERSION}..."
    if [ -f "/tmp/${NODE_TARBALL}" ]; then
        info "检测到已下载的文件，跳过下载"
    else
        curl -L -o "/tmp/${NODE_TARBALL}" "$NODE_DOWNLOAD_URL" --progress-bar
    fi
    
    # 解压安装
    info "正在安装 Node.js..."
    rm -rf "$HOME/.local"
    mkdir -p "$HOME/.local"
    tar -xJf "/tmp/${NODE_TARBALL}" -C "$HOME/.local" --strip-components=1
    
    # 添加到 PATH
    if ! grep -q "$HOME/.local/bin" "$HOME/.bashrc"; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        info "已添加 PATH 到 ~/.bashrc"
    fi
    
    # 立即生效
    export PATH="$HOME/.local/bin:$PATH"
    
    # 验证安装
    INSTALLED_NODE=$("$HOME/.local/bin/node" -v)
    success "Node.js 安装成功: $INSTALLED_NODE"
}

# ============================================
# 步骤 2: 安装 Codex
# ============================================
install_codex() {
    info "检查 Codex 安装..."
    
    if [ -f "$HOME/.local/bin/codex" ]; then
        CODEX_VERSION=$("$HOME/.local/bin/codex" --version 2>/dev/null || echo "unknown")
        success "Codex 已安装: $CODEX_VERSION"
        return 0
    fi
    
    info "正在安装 Codex..."
    
    # 配置 npm 国内镜像
    "$HOME/.local/bin/npm" config set registry https://registry.npmmirror.com
    
    # 安装 Codex
    "$HOME/.local/bin/npm" install -g @openai/codex
    
    # 验证安装
    if [ -f "$HOME/.local/bin/codex" ]; then
        CODEX_VERSION=$("$HOME/.local/bin/codex" --version)
        success "Codex 安装成功: $CODEX_VERSION"
    else
        error "Codex 安装失败"
        exit 1
    fi
}

# ============================================
# 步骤 3: 配置 Codex
# ============================================
configure_codex() {
    info "配置 Codex..."s
    
    # 创建配置目录
    mkdir -p "$CODEX_DIR"
    
    # 创建 config.toml
    if [ ! -f "$CODEX_DIR/config.toml" ]; then
        cat > "$CODEX_DIR/config.toml" << 'EOF'
model_provider = "kfc-coding"
model = "gpt-5.3-codex"
model_reasoning_effort = "xhigh"
network_access = "enabled"
disable_response_storage = true

# 模型提供者配置
[model_providers.kfc-coding]
name = "KFC-Coding Proxy"
base_url = "http://2api.wuniao.me/v1"
wire_api = "responses"
requires_openai_auth = true
EOF
        success "已创建 config.toml"
    else
        info "config.toml 已存在，跳过创建"
    fi
    
    # 创建 auth.json
    if [ ! -f "$CODEX_DIR/auth.json" ]; then
        cat > "$CODEX_DIR/auth.json" << 'EOF'
{
  "OPENAI_API_KEY": "sk-YCdhGBR4zD9PTrJSQN8PuWME1FPMLNktvGVb8w7BAVawI5A2"
}
EOF
        success "已创建 auth.json"
    else
        info "auth.json 已存在，跳过创建"
    fi
}

# ============================================
# 步骤 4: 创建项目目录并启动
# ============================================
start_codex() {
    info "准备启动 Codex..."
    
    # 创建项目目录
    mkdir -p "$PROJECT_DIR"
    cd "$PROJECT_DIR"
    
    # 确保 PATH 包含本地 bin
    export PATH="$HOME/.local/bin:$PATH"
    
    success "========================================"
    success "  Codex 安装配置完成！"
    success "========================================"
    info "项目目录: $PROJECT_DIR"
    info "Node.js 版本: $(node -v)"
    info "Codex 版本: $(codex --version)"
    success "========================================"
    info "正在启动 Codex..."
    echo ""
    
    # 启动 Codex
    exec codex
}

# ============================================
# 主程序
# ============================================
main() {
    echo "========================================"
    echo "  Codex 一键安装启动脚本"
    echo "========================================"
    echo ""
    
    install_dependencies
    echo ""
    install_node
    echo ""
    install_codex
    echo ""
    configure_codex
    echo ""
    start_codex
}

# 运行主程序
main
