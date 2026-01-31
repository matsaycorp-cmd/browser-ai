#!/usr/bin/env python3
"""Browser AI 启动脚本 - 提供简化的启动菜单。"""

import asyncio
import subprocess
import sys


def check_dependencies() -> bool:
    """检查Python依赖是否安装。"""
    required = ["playwright", "websockets", "aiohttp"]
    missing = []

    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"❌ 缺少依赖: {', '.join(missing)}")
        print("请运行: pip install -r requirements.txt")
        return False

    return True


def check_playwright_browser() -> bool:
    """检查Playwright浏览器是否安装。"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium.executable_path; p.stop()"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def show_menu():
    """显示启动菜单。"""
    print()
    print("=" * 40)
    print("     🤖 Browser AI 控制程序")
    print("=" * 40)
    print()
    print("  1. 启动完整程序")
    print("  2. 仅测试连接")
    print("  3. 仅登录AI（不执行任务）")
    print("  4. 查看配置")
    print("  5. 测试对抗验证系统")
    print("  6. 调试工具")
    print("  0. 退出")
    print()
    print("=" * 40)


def show_config():
    """显示当前配置。"""
    try:
        from config.settings import (
            AI_RETRY_ORDER,
            AI_URLS,
            AUTO_APPROVE_SCORE,
            BROWSER_DATA_DIR,
            EXECUTION_MODE,
            MAX_PARALLEL,
            MAX_RETRY_ROUNDS,
            MIN_PASS_SCORE,
            RATE_LIMITS,
            WS_SERVER_URL,
        )

        print()
        print("=" * 40)
        print("         📋 当前配置")
        print("=" * 40)
        print()
        print(f"服务器地址: {WS_SERVER_URL}")
        print(f"浏览器数据: {BROWSER_DATA_DIR}")
        print()
        print("AI平台:")
        for name, url in AI_URLS.items():
            print(f"  - {name}: {url}")
        print()
        print(f"AI优先顺序: {' → '.join(AI_RETRY_ORDER)}")
        print()
        print("质量控制:")
        print(f"  - 自动通过分数: {AUTO_APPROVE_SCORE}")
        print(f"  - 最低通过分数: {MIN_PASS_SCORE}")
        print(f"  - 最大重试轮数: {MAX_RETRY_ROUNDS}")
        print()
        print(f"执行模式: {EXECUTION_MODE}")
        print(f"最大并行数: {MAX_PARALLEL}")
        print()
        print("速率限制:")
        for ai_name, limits in RATE_LIMITS.items():
            print(f"  - {ai_name}: {limits['per_hour']}次/小时, 间隔{limits['min_interval']}秒")
        print()
        print("=" * 40)

    except Exception as e:
        print(f"❌ 读取配置失败: {e}")


async def run_full_program():
    """启动完整程序。"""
    print("\n🚀 正在启动完整程序...\n")
    try:
        from main import main
        await main()
    except KeyboardInterrupt:
        print("\n\n👋 程序已停止")
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")


async def run_connection_test():
    """运行连接测试。"""
    try:
        from test_connection import test_all
        await test_all()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")


async def run_login_mode():
    """运行登录模式。"""
    try:
        from test_connection import interactive_login
        await interactive_login()
    except Exception as e:
        print(f"\n❌ 登录失败: {e}")


async def run_debate_test():
    """运行对抗验证测试。"""
    try:
        from test_debate import interactive_menu
        await interactive_menu()
    except Exception as e:
        print(f"\n❌ 对抗测试失败: {e}")


def run_debug_tool():
    """运行调试工具。"""
    try:
        from debug_debate import interactive_debug_menu
        interactive_debug_menu()
    except Exception as e:
        print(f"\n❌ 调试工具失败: {e}")


def main():
    """主函数。"""
    print("\n🔍 正在检查环境...")

    # 检查依赖
    if not check_dependencies():
        input("\n按 Enter 键退出...")
        return

    print("✅ Python依赖已安装")

    # 检查浏览器
    print("🔍 检查Playwright浏览器...")
    if not check_playwright_browser():
        print("⚠️  Playwright浏览器未安装")
        print("请运行: playwright install chromium")
        choice = input("\n是否现在安装? (y/n): ").strip().lower()
        if choice == "y":
            print("\n正在安装浏览器...")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
            print()
        else:
            input("\n按 Enter 键退出...")
            return
    else:
        print("✅ Playwright浏览器已安装")

    # 主循环
    while True:
        show_menu()
        choice = input("请选择 (0-6): ").strip()

        if choice == "1":
            asyncio.run(run_full_program())
        elif choice == "2":
            asyncio.run(run_connection_test())
            input("\n按 Enter 键返回菜单...")
        elif choice == "3":
            asyncio.run(run_login_mode())
            input("\n按 Enter 键返回菜单...")
        elif choice == "4":
            show_config()
            input("\n按 Enter 键返回菜单...")
        elif choice == "5":
            asyncio.run(run_debate_test())
            input("\n按 Enter 键返回菜单...")
        elif choice == "6":
            run_debug_tool()
            input("\n按 Enter 键返回菜单...")
        elif choice == "0":
            print("\n👋 再见！\n")
            break
        else:
            print("\n⚠️  无效选择，请输入 0-6")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 再见！\n")
