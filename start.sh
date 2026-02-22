#!/bin/bash
#
# A股量化交易系统 - 一键启动脚本
#
# 使用方法:
#   ./start.sh              # 启动仪表盘
#   ./start.sh update       # 更新数据后启动仪表盘
#   ./start.sh dashboard    # 仅启动仪表盘
#   ./start.sh data         # 仅更新数据
#   ./start.sh test         # 运行测试
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 虚拟环境目录
VENV_DIR="$PROJECT_DIR/venv"

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示横幅
show_banner() {
    echo -e "${GREEN}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║            📈 A股量化交易系统 v1.0                         ║"
    echo "║                                                            ║"
    echo "║   Phase 1: 数据层      ✅ 43 tests                        ║"
    echo "║   Phase 2: 策略层      ✅ 160 tests                       ║"
    echo "║   Phase 3: 风控层      ✅ 62 tests                        ║"
    echo "║   Phase 4: 仪表盘      ✅ 40 tests                        ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# 检查Python环境
check_python() {
    print_info "检查Python环境..."

    if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
        print_error "Python未安装，请先安装Python 3.11+"
        exit 1
    fi

    # 优先使用python3
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    else
        PYTHON_CMD="python"
    fi

    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
    print_success "Python版本: $PYTHON_VERSION"
}

# 设置虚拟环境
setup_venv() {
    print_info "检查虚拟环境..."

    # 如果已经在虚拟环境中，跳过
    if [ -n "$VIRTUAL_ENV" ]; then
        print_success "已在虚拟环境中: $VIRTUAL_ENV"
        return 0
    fi

    # 检查虚拟环境是否存在
    if [ ! -d "$VENV_DIR" ]; then
        print_warning "虚拟环境不存在，正在创建..."
        $PYTHON_CMD -m venv "$VENV_DIR"
        print_success "虚拟环境创建完成: $VENV_DIR"
    fi

    # 激活虚拟环境
    print_info "激活虚拟环境..."
    source "$VENV_DIR/bin/activate"
    print_success "虚拟环境已激活"

    # 升级pip
    pip install --upgrade pip -q
}

# 安装依赖
install_dependencies() {
    print_info "安装依赖..."
    pip install -r requirements.txt
    print_success "依赖安装完成"
}

# 检查依赖
check_dependencies() {
    print_info "检查依赖..."

    # 检查关键包
    MISSING=""
    python -c "import pandas" 2>/dev/null || MISSING="$MISSING pandas"
    python -c "import streamlit" 2>/dev/null || MISSING="$MISSING streamlit"
    python -c "import plotly" 2>/dev/null || MISSING="$MISSING plotly"
    python -c "import xgboost" 2>/dev/null || MISSING="$MISSING xgboost"

    if [ -n "$MISSING" ]; then
        print_warning "缺少依赖:$MISSING"
        print_info "正在安装所有依赖..."
        pip install -r requirements.txt
    fi

    print_success "依赖检查完成"
}

# 检查配置文件
check_config() {
    print_info "检查配置文件..."

    if [ ! -f "config/config.yaml" ]; then
        print_warning "配置文件不存在，正在创建..."
        mkdir -p config
        cat > config/config.yaml << 'EOF'
# A股量化交易系统配置文件

# 数据源配置
data_sources:
  tushare:
    token: "YOUR_TUSHARE_TOKEN"  # 请替换为您的TuShare Token

# 数据存储路径
storage:
  parquet_dir: "data/parquet"
  database_path: "data/stockagent.db"
  log_dir: "logs"

# 风险控制参数
risk_control:
  fixed_stop_pct: 0.05        # 固定止损 5%
  atr_multiplier: 2.0         # ATR倍数
  max_position_pct: 0.25      # 单只股票最大仓位 25%
  target_total_pct: 0.60      # 目标总仓位 60%
  max_stocks: 10              # 最多持有股票数

# 信号参数
signals:
  min_score: 60               # 最低信号分数
  swing_weight: 0.35          # 波段策略权重
  trend_weight: 0.35          # 趋势策略权重
  ml_weight: 0.30             # ML策略权重

# 仪表盘配置
dashboard:
  host: "0.0.0.0"
  port: 8501
EOF
        print_warning "请编辑 config/config.yaml 填入您的 TuShare Token"
    fi

    print_success "配置文件检查完成"
}

# 创建必要目录
create_directories() {
    print_info "创建必要目录..."

    mkdir -p data/parquet
    mkdir -p data/signal_cache
    mkdir -p data/news_cache
    mkdir -p logs
    mkdir -p models

    print_success "目录创建完成"
}

# 更新数据
update_data() {
    print_info "更新市场数据..."

    python -c "
from src.daily_updater import DailyUpdater
from src.config import Config

try:
    config = Config('config/config.yaml')
    updater = DailyUpdater(config)
    updater.run_full_update()
    print('数据更新完成')
except Exception as e:
    print(f'数据更新失败: {e}')
    print('请检查 TuShare Token 配置')
"
}

# 启动新闻后台服务
start_news_service() {
    print_info "启动新闻后台服务..."

    # 设置环境变量
    if [ -d "/opt/homebrew/opt/libomp/lib" ]; then
        export DYLD_LIBRARY_PATH="/opt/homebrew/opt/libomp/lib:$DYLD_LIBRARY_PATH"
    fi
    export NO_PROXY='*'

    # 后台启动新闻服务
    python -c "
from src.services.news_service import start_news_service
import time
import signal
import sys

service = start_news_service()
print('新闻服务已启动')

def handler(sig, frame):
    service.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, handler)
signal.signal(signal.SIGINT, handler)

while True:
    time.sleep(1)
" &
    NEWS_SERVICE_PID=$!
    echo $NEWS_SERVICE_PID > "$PROJECT_DIR/.news_service.pid"
    print_success "新闻后台服务已启动 (PID: $NEWS_SERVICE_PID)"
}

# 停止新闻后台服务
stop_news_service() {
    if [ -f "$PROJECT_DIR/.news_service.pid" ]; then
        PID=$(cat "$PROJECT_DIR/.news_service.pid")
        if kill -0 $PID 2>/dev/null; then
            print_info "停止新闻后台服务 (PID: $PID)..."
            kill $PID 2>/dev/null
            rm -f "$PROJECT_DIR/.news_service.pid"
            print_success "新闻后台服务已停止"
        else
            rm -f "$PROJECT_DIR/.news_service.pid"
        fi
    fi
}

# 启动仪表盘
start_dashboard() {
    print_info "启动仪表盘..."
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  仪表盘启动中...${NC}"
    echo -e "${GREEN}  访问地址: http://localhost:8501${NC}"
    echo -e "${GREEN}  默认账号: admin / admin123${NC}"
    echo -e "${GREEN}  观察账号: viewer / viewer123${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
    echo ""

    # 设置 XGBoost 所需的 OpenMP 库路径 (macOS)
    if [ -d "/opt/homebrew/opt/libomp/lib" ]; then
        export DYLD_LIBRARY_PATH="/opt/homebrew/opt/libomp/lib:$DYLD_LIBRARY_PATH"
    fi

    # 禁用代理，直连国内数据源
    export NO_PROXY='*'

    # 先启动新闻后台服务
    start_news_service

    # 确保退出时停止新闻服务
    trap stop_news_service EXIT

    streamlit run src/dashboard/app.py \
        --server.address=0.0.0.0 \
        --server.port=8501 \
        --browser.gatherUsageStats=false
}

# 运行测试
run_tests() {
    print_info "运行测试..."

    python -m pytest tests/ -v --tb=short

    print_success "测试完成"
}

# 显示帮助
show_help() {
    echo "使用方法: ./start.sh [命令]"
    echo ""
    echo "命令:"
    echo "  (无参数)    启动仪表盘"
    echo "  install     安装所有依赖"
    echo "  update      更新数据后启动仪表盘"
    echo "  dashboard   仅启动仪表盘"
    echo "  data        仅更新数据"
    echo "  test        运行测试"
    echo "  help        显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  ./start.sh install      # 首次使用，安装依赖"
    echo "  ./start.sh              # 启动仪表盘"
    echo "  ./start.sh update       # 更新数据并启动"
    echo "  ./start.sh test         # 运行所有测试"
}

# 主函数
main() {
    show_banner

    case "${1:-dashboard}" in
        install)
            check_python
            setup_venv
            install_dependencies
            check_config
            create_directories
            print_success "安装完成！运行 ./start.sh 启动系统"
            ;;
        update)
            check_python
            setup_venv
            check_dependencies
            check_config
            create_directories
            update_data
            start_dashboard
            ;;
        dashboard)
            check_python
            setup_venv
            check_dependencies
            check_config
            create_directories
            start_dashboard
            ;;
        data)
            check_python
            setup_venv
            check_dependencies
            check_config
            create_directories
            update_data
            print_success "数据更新完成"
            ;;
        test)
            check_python
            setup_venv
            check_dependencies
            run_tests
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $1"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
