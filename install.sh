#!/bin/bash
echo "===================================="
echo "  Browser AI 安装程序"
echo "===================================="
echo ""
echo "正在安装Python依赖..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "依赖安装失败，请检查Python和pip是否正确安装"
    exit 1
fi
echo ""
echo "正在安装Playwright浏览器..."
playwright install chromium
if [ $? -ne 0 ]; then
    echo ""
    echo "浏览器安装失败"
    exit 1
fi
echo ""
echo "===================================="
echo "  安装完成！"
echo "===================================="
echo ""
echo "请运行 ./run.sh 启动程序"
echo ""
