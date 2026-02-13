#!/bin/bash

# Claude Code 一键安装脚本
# 支持 macOS 和 Linux

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
    else
        log_error "不支持的操作系统: $OSTYPE"
        exit 1
    fi
    log_info "检测到操作系统: $OS"
}

# 检查并安装依赖
check_dependencies() {
    log_info "检查依赖..."
    
    # 检查 curl
    if ! command -v curl &> /dev/null; then
        log_error "curl 未安装，请先安装 curl"
        exit 1
    fi
    
    # 获取提权命令
    local ELEVATE=""
    if [ "$(id -u)" != "0" ] && command -v sudo &> /dev/null; then
        ELEVATE="sudo"
    fi

    # 检查 unzip
    if ! command -v unzip &> /dev/null; then
        log_warn "unzip 未安装，尝试安装..."
        if [[ "$OS" == "linux" ]]; then
            if command -v apt-get &> /dev/null; then
                $ELEVATE apt-get update && $ELEVATE apt-get install -y unzip
            elif command -v yum &> /dev/null; then
                $ELEVATE yum install -y unzip
            elif command -v dnf &> /dev/null; then
                $ELEVATE dnf install -y unzip
            elif command -v pacman &> /dev/null; then
                $ELEVATE pacman -S --noconfirm unzip
            else
                log_error "无法自动安装 unzip，请手动安装"
                exit 1
            fi
        elif [[ "$OS" == "macos" ]]; then
            if command -v brew &> /dev/null; then
                brew install unzip
            else
                log_error "请先安装 Homebrew 或手动安装 unzip"
                exit 1
            fi
        fi
    fi

    # 检查 xz（Linux 下解压 .tar.xz 需要）
    if [[ "$OS" == "linux" ]] && ! command -v xz &> /dev/null; then
        log_warn "xz 未安装，尝试安装..."
        if command -v apt-get &> /dev/null; then
            $ELEVATE apt-get update && $ELEVATE apt-get install -y xz-utils
        elif command -v yum &> /dev/null; then
            $ELEVATE yum install -y xz
        elif command -v dnf &> /dev/null; then
            $ELEVATE dnf install -y xz
        elif command -v pacman &> /dev/null; then
            $ELEVATE pacman -S --noconfirm xz
        else
            log_error "无法自动安装 xz，请手动安装"
            exit 1
        fi
    fi
    
    log_success "依赖检查完成"
}

# 安装 fnm
install_fnm() {
    log_info "安装 fnm (Fast Node Manager)..."
    
    if command -v fnm &> /dev/null; then
        log_warn "fnm 已安装，跳过"
        return
    fi
    
    curl -fsSL https://fnm.vercel.app/install | bash
    
    # 设置环境变量
    export FNM_PATH="$HOME/.local/share/fnm"
    if [ -d "$FNM_PATH" ]; then
        export PATH="$FNM_PATH:$PATH"
        eval "$(fnm env)"
    fi
    
    log_success "fnm 安装完成"
}

# 安装 Node.js
install_node() {
    local NODE_VERSION="24.3.0"
    local MIRROR="https://npmmirror.com/mirrors/node"
    
    log_info "安装 Node.js v${NODE_VERSION}（使用国内镜像）..."
    
    # 检测架构
    local ARCH=$(uname -m)
    case $ARCH in
        x86_64) ARCH="x64" ;;
        aarch64) ARCH="arm64" ;;
        armv7l) ARCH="armv7l" ;;
        *)
            log_error "不支持的架构: $ARCH"
            exit 1
            ;;
    esac
    
    log_info "检测到架构: $ARCH"
    
    # 构建文件名
    local FILENAME=""
    if [[ "$OS" == "linux" ]]; then
        FILENAME="node-v${NODE_VERSION}-linux-${ARCH}.tar.xz"
    elif [[ "$OS" == "macos" ]]; then
        FILENAME="node-v${NODE_VERSION}-darwin-${ARCH}.tar.gz"
    fi
    
    local DOWNLOAD_URL="${MIRROR}/v${NODE_VERSION}/${FILENAME}"
    log_info "下载地址: $DOWNLOAD_URL"
    
    # 创建临时目录
    local TMP_DIR=$(mktemp -d)
    cd "$TMP_DIR"
    
    # 下载 Node.js
    if ! curl -L -o "$FILENAME" "$DOWNLOAD_URL"; then
        log_error "下载 Node.js 失败"
        rm -rf "$TMP_DIR"
        exit 1
    fi
    
    # 解压到 ~/.local
    mkdir -p "$HOME/.local"
    log_info "解压到 $HOME/.local..."
    
    if [[ "$OS" == "linux" ]]; then
        tar -xJf "$FILENAME" -C "$HOME/.local" --strip-components=1
    elif [[ "$OS" == "macos" ]]; then
        tar -xzf "$FILENAME" -C "$HOME/.local" --strip-components=1
    fi
    
    # 清理临时文件
    cd - > /dev/null
    rm -rf "$TMP_DIR"
    
    # 更新 PATH
    export PATH="$HOME/.local/bin:$PATH"
    
    log_success "Node.js v${NODE_VERSION} 安装完成"
    log_info "Node 版本: $(node -v)"
    log_info "NPM 版本: $(npm -v)"
}

# 安装 Claude Code
install_claude_code() {
    log_info "安装 Claude Code..."
    
    # 确保 Node.js 环境
    export PATH="$HOME/.local/bin:$PATH"
    
    if command -v claude &> /dev/null; then
        log_warn "Claude Code 已安装，版本: $(claude --version)"
        log_info "更新到最新版本..."
    fi
    
    npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com
    
    log_success "Claude Code 安装完成"
    log_info "版本: $(claude --version)"
}

# 初始化配置
init_config() {
    log_info "初始化 Claude Code 配置..."
    
    # 确保 Node.js 环境
    export PATH="$HOME/.local/bin:$PATH"
    
    node << 'EOF'
const fs = require('fs');
const os = require('os');
const path = require('path');

const homeDir = os.homedir();
const filePath = path.join(homeDir, '.claude.json');

let config = {};
if (fs.existsSync(filePath)) {
    try {
        config = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    } catch (e) {
        console.log('配置文件读取失败，创建新配置');
    }
}

config.hasCompletedOnboarding = true;
fs.writeFileSync(filePath, JSON.stringify(config, null, 2), 'utf-8');
console.log('配置文件已更新:', filePath);
EOF
    
    log_success "配置完成"
}

# 添加永久环境变量
setup_shell_config() {
    log_info "配置 shell 环境..."
    
    local SHELL_CONFIG=""
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        SHELL_CONFIG="$HOME/.bashrc"
    else
        SHELL_CONFIG="$HOME/.bashrc"
    fi
    
    # 检查是否已添加 Node.js PATH
    if ! grep -q "HOME/.local/bin" "$SHELL_CONFIG" 2>/dev/null; then
        log_info "添加 Node.js PATH 到 $SHELL_CONFIG"
        cat >> "$SHELL_CONFIG" << 'EOF'

# Node.js (手动安装)
export PATH="$HOME/.local/bin:$PATH"
EOF
    fi
    
    log_success "Shell 配置完成"
}

# 主函数
main() {
    echo "========================================"
    echo "  Claude Code 一键安装脚本"
    echo "========================================"
    echo ""
    
    detect_os
    check_dependencies
    install_node
    install_claude_code
    init_config
    setup_shell_config
    
    echo ""
    echo "========================================"
    log_success "Claude Code 安装成功！"
    echo "========================================"
    echo ""
    echo "使用方法:"
    echo "  1. 重新打开终端或运行: source ~/.bashrc (或 ~/.zshrc)"
    echo "  2. 在项目目录运行: claude"
    echo ""
    echo "当前版本:"
    echo "  Node.js: $(export PATH="$HOME/.local/bin:$PATH" && node -v 2>/dev/null || echo '请重新打开终端')"
    echo "  Claude Code: $(export PATH="$HOME/.local/bin:$PATH" && claude --version 2>/dev/null || echo '请重新打开终端')"
    echo ""
}

# 运行主函数
main "$@"
