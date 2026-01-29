@echo off
chcp 65001 >nul
echo ====================================
echo   Browser AI 安装程序
echo ====================================
echo.
echo 正在安装Python依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo 依赖安装失败，请检查Python和pip是否正确安装
    pause
    exit /b 1
)
echo.
echo 正在安装Playwright浏览器...
playwright install chromium
if errorlevel 1 (
    echo.
    echo 浏览器安装失败
    pause
    exit /b 1
)
echo.
echo ====================================
echo   安装完成！
echo ====================================
echo.
echo 请运行 run.bat 启动程序
echo.
pause
