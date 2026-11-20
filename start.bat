@echo off
REM Windows：双击运行（首次会自动安装必需依赖 jsonschema）
cd /d "%~dp0"
python product\app\start.py --setup %*
pause
