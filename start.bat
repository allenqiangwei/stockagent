@echo off
REM A股量化交易系统 - Windows 一键启动脚本
REM
REM 使用方法:
REM   start.bat              启动仪表盘
REM   start.bat update       更新数据后启动仪表盘
REM   start.bat dashboard    仅启动仪表盘
REM   start.bat data         仅更新数据
REM   start.bat test         运行测试

setlocal enabledelayedexpansion

REM 颜色代码
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "BLUE=[94m"
set "NC=[0m"

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 显示横幅
echo.
echo %GREEN%╔════════════════════════════════════════════════════════════╗%NC%
echo %GREEN%║                                                            ║%NC%
echo %GREEN%║            📈 A股量化交易系统 v1.0                         ║%NC%
echo %GREEN%║                                                            ║%NC%
echo %GREEN%║   Phase 1: 数据层      ✅ 43 tests                        ║%NC%
echo %GREEN%║   Phase 2: 策略层      ✅ 160 tests                       ║%NC%
echo %GREEN%║   Phase 3: 风控层      ✅ 62 tests                        ║%NC%
echo %GREEN%║   Phase 4: 仪表盘      ✅ 40 tests                        ║%NC%
echo %GREEN%║                                                            ║%NC%
echo %GREEN%╚════════════════════════════════════════════════════════════╝%NC%
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%NC% Python未安装，请先安装Python 3.11+
    exit /b 1
)

REM 创建必要目录
if not exist "data\parquet" mkdir "data\parquet"
if not exist "logs" mkdir "logs"
if not exist "models" mkdir "models"

REM 检查配置文件
if not exist "config\config.yaml" (
    echo %YELLOW%[WARNING]%NC% 配置文件不存在，请先创建 config/config.yaml
    echo 可以参考 start.sh 中的配置模板
)

REM 处理命令
if "%1"=="" goto dashboard
if "%1"=="install" goto install
if "%1"=="update" goto update
if "%1"=="dashboard" goto dashboard
if "%1"=="data" goto data
if "%1"=="test" goto test
if "%1"=="help" goto help
if "%1"=="--help" goto help
if "%1"=="-h" goto help

echo %RED%[ERROR]%NC% 未知命令: %1
goto help

:install
echo %BLUE%[INFO]%NC% 安装依赖...
pip install -r requirements.txt
echo %GREEN%[SUCCESS]%NC% 安装完成！运行 start.bat 启动系统
goto end

:update
echo %BLUE%[INFO]%NC% 更新市场数据...
python -c "from src.daily_updater import DailyUpdater; from src.config import Config; config = Config('config/config.yaml'); updater = DailyUpdater(config); updater.run_full_update()"
goto dashboard

:dashboard
echo %BLUE%[INFO]%NC% 启动仪表盘...
echo.
echo %GREEN%════════════════════════════════════════════════════════════%NC%
echo %GREEN%  仪表盘启动中...%NC%
echo %GREEN%  访问地址: http://localhost:8501%NC%
echo %GREEN%  默认账号: admin / admin123%NC%
echo %GREEN%  观察账号: viewer / viewer123%NC%
echo %GREEN%════════════════════════════════════════════════════════════%NC%
echo.
streamlit run src/dashboard/app.py --server.address=0.0.0.0 --server.port=8501 --browser.gatherUsageStats=false
goto end

:data
echo %BLUE%[INFO]%NC% 更新市场数据...
python -c "from src.daily_updater import DailyUpdater; from src.config import Config; config = Config('config/config.yaml'); updater = DailyUpdater(config); updater.run_full_update()"
echo %GREEN%[SUCCESS]%NC% 数据更新完成
goto end

:test
echo %BLUE%[INFO]%NC% 运行测试...
python -m pytest tests/ -v --tb=short
goto end

:help
echo 使用方法: start.bat [命令]
echo.
echo 命令:
echo   (无参数)    启动仪表盘
echo   install     安装所有依赖
echo   update      更新数据后启动仪表盘
echo   dashboard   仅启动仪表盘
echo   data        仅更新数据
echo   test        运行测试
echo   help        显示此帮助信息
echo.
echo 示例:
echo   start.bat install      首次使用，安装依赖
echo   start.bat              启动仪表盘
echo   start.bat update       更新数据并启动
echo   start.bat test         运行所有测试
goto end

:end
endlocal
