#!/usr/bin/env python3
"""连接测试工具 - 测试各组件是否正常工作。"""

import asyncio
import sys

from config.settings import AI_URLS, BROWSER_DATA_DIR, WS_SERVER_URL
from core.browser_manager import BrowserManager
from core.ws_client import WSClient


async def test_browser() -> bool:
    """测试浏览器启动。"""
    print("\n[1/3] 测试浏览器启动...")
    try:
        browser_manager = BrowserManager(BROWSER_DATA_DIR)
        await browser_manager.launch(headless=True)
        print("✅ 浏览器启动成功")
        await browser_manager.close()
        return True
    except Exception as e:
        print(f"❌ 浏览器启动失败: {e}")
        return False


async def test_ai_login(ai_name: str) -> bool:
    """测试指定AI平台的登录状态。"""
    if ai_name not in AI_URLS:
        print(f"❌ 未知的AI平台: {ai_name}")
        return False

    url = AI_URLS[ai_name]
    print(f"\n检测 {ai_name} 登录状态...")

    try:
        browser_manager = BrowserManager(BROWSER_DATA_DIR)
        await browser_manager.launch(headless=False)
        page = await browser_manager.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        is_logged_in = await browser_manager.check_login(ai_name, page)

        if is_logged_in:
            print(f"✅ {ai_name} 已登录")
        else:
            print(f"⚠️  {ai_name} 未登录，请手动登录")

        await browser_manager.close()
        return is_logged_in

    except Exception as e:
        print(f"❌ {ai_name} 检测失败: {e}")
        return False


async def test_all_ai_logins() -> dict:
    """测试所有AI平台的登录状态。"""
    print("\n[2/3] 测试AI平台登录状态...")
    results = {}

    try:
        browser_manager = BrowserManager(BROWSER_DATA_DIR)
        await browser_manager.launch(headless=False)

        for ai_name, url in AI_URLS.items():
            print(f"  检测 {ai_name}...")
            try:
                page = await browser_manager.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                is_logged_in = await browser_manager.check_login(ai_name, page)
                results[ai_name] = is_logged_in

                if is_logged_in:
                    print(f"  ✅ {ai_name} 已登录")
                else:
                    print(f"  ⚠️  {ai_name} 未登录")

                await page.close()

            except Exception as e:
                print(f"  ❌ {ai_name} 检测失败: {e}")
                results[ai_name] = False

        await browser_manager.close()

    except Exception as e:
        print(f"❌ 浏览器启动失败: {e}")

    return results


async def test_websocket(server_url: str | None = None) -> bool:
    """测试WebSocket连接。"""
    url = server_url or WS_SERVER_URL
    print(f"\n[3/3] 测试WebSocket连接 ({url})...")

    try:
        ws_client = WSClient(url)

        # 设置超时连接
        connected = await asyncio.wait_for(ws_client.connect(), timeout=10)

        if connected:
            print("✅ WebSocket连接成功")

            # 发送测试消息
            await ws_client.send("ping", {"test": True})
            print("✅ 测试消息已发送")

            await ws_client.disconnect()
            return True
        else:
            print("❌ WebSocket连接失败")
            return False

    except asyncio.TimeoutError:
        print("❌ WebSocket连接超时")
        return False
    except Exception as e:
        print(f"❌ WebSocket连接错误: {e}")
        return False


async def test_all():
    """依次测试所有组件并汇总报告。"""
    print("=" * 50)
    print("🔍 Browser AI 连接测试")
    print("=" * 50)

    results = {
        "browser": False,
        "ai_logins": {},
        "websocket": False,
    }

    # 1. 测试浏览器
    results["browser"] = await test_browser()

    # 2. 测试AI登录状态
    if results["browser"]:
        results["ai_logins"] = await test_all_ai_logins()

    # 3. 测试WebSocket
    results["websocket"] = await test_websocket()

    # 汇总报告
    print("\n" + "=" * 50)
    print("📊 测试报告")
    print("=" * 50)

    print(f"\n浏览器: {'✅ 正常' if results['browser'] else '❌ 异常'}")

    print("\nAI平台登录状态:")
    if results["ai_logins"]:
        for ai_name, logged_in in results["ai_logins"].items():
            status = "✅ 已登录" if logged_in else "⚠️  未登录"
            print(f"  - {ai_name}: {status}")
    else:
        print("  (未测试)")

    print(f"\nWebSocket: {'✅ 正常' if results['websocket'] else '❌ 异常'}")

    # 总结
    all_ok = (
        results["browser"]
        and results["websocket"]
        and any(results["ai_logins"].values())
    )

    print("\n" + "=" * 50)
    if all_ok:
        print("✅ 所有核心组件正常，可以启动程序")
    else:
        print("⚠️  部分组件异常，请检查后重试")
        if not results["browser"]:
            print("   - 请运行: playwright install chromium")
        if not any(results["ai_logins"].values()):
            print("   - 请在浏览器中登录至少一个AI平台")
        if not results["websocket"]:
            print("   - 请检查服务器地址和网络连接")
    print("=" * 50)

    return all_ok


async def interactive_login():
    """交互式登录模式 - 打开浏览器让用户手动登录。"""
    print("\n" + "=" * 50)
    print("🔐 AI平台登录模式")
    print("=" * 50)
    print("\n浏览器将打开各AI平台，请手动登录。")
    print("登录完成后，状态会自动保存。")
    print("按 Ctrl+C 退出。\n")

    try:
        browser_manager = BrowserManager(BROWSER_DATA_DIR)
        await browser_manager.launch(headless=False)

        for ai_name, url in AI_URLS.items():
            print(f"正在打开 {ai_name}...")
            page = await browser_manager.new_page()
            await page.goto(url, wait_until="domcontentloaded")

        print("\n✅ 所有平台已打开，请在浏览器中完成登录。")
        print("登录完成后按 Enter 键继续，或按 Ctrl+C 退出...")

        # 等待用户确认
        await asyncio.get_event_loop().run_in_executor(None, input)

        # 检查登录状态
        print("\n检查登录状态...")
        pages = browser_manager.context.pages if browser_manager.context else []
        for page in pages:
            url = page.url
            for ai_name, ai_url in AI_URLS.items():
                if ai_url in url:
                    is_logged_in = await browser_manager.check_login(ai_name, page)
                    status = "✅ 已登录" if is_logged_in else "❌ 未登录"
                    print(f"  {ai_name}: {status}")

        await browser_manager.close()
        print("\n✅ 登录状态已保存")

    except KeyboardInterrupt:
        print("\n\n已取消")
    except Exception as e:
        print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "browser":
            asyncio.run(test_browser())
        elif cmd == "websocket":
            url = sys.argv[2] if len(sys.argv) > 2 else None
            asyncio.run(test_websocket(url))
        elif cmd == "login":
            ai_name = sys.argv[2] if len(sys.argv) > 2 else None
            if ai_name:
                asyncio.run(test_ai_login(ai_name))
            else:
                asyncio.run(interactive_login())
        else:
            print(f"未知命令: {cmd}")
            print("用法: python test_connection.py [browser|websocket|login]")
    else:
        asyncio.run(test_all())
