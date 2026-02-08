#!/usr/bin/env python3
"""
Browser AI 集成测试

测试 WebSocket 通信和并行搜索功能
"""

import asyncio
import json
import logging
from datetime import datetime

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class MockBrowserAIServer:
    """模拟 Telegram Bot WebSocket 服务器"""

    def __init__(self, host: str = "127.0.0.1", port: int = 18765):
        self.host = host
        self.port = port
        self.clients = {}
        self.received_messages = []
        self.server = None

    async def start(self):
        """启动服务器"""
        self.server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port,
        )
        logger.info(f"Mock server started on ws://{self.host}:{self.port}")

    async def stop(self):
        """停止服务器"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def handle_client(self, websocket, path=None):
        """处理客户端连接"""
        client_id = id(websocket)
        self.clients[client_id] = websocket
        logger.info(f"Client connected: {client_id}")

        try:
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type", "")
                logger.info(f"Received: {msg_type}")
                self.received_messages.append(data)

                # 处理配置请求
                if msg_type == "request_config":
                    await websocket.send(json.dumps({
                        "type": "config_update",
                        "data": {
                            "execution_mode": "single",
                            "max_parallel": 2,
                        }
                    }))

        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        finally:
            if client_id in self.clients:
                del self.clients[client_id]

    async def send_to_all(self, msg_type: str, data: dict):
        """发送消息到所有客户端"""
        message = json.dumps({"type": msg_type, "data": data}, ensure_ascii=False)
        for ws in self.clients.values():
            await ws.send(message)


class MockBrowserAIClient:
    """模拟 Browser AI 客户端（简化版）"""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self.handlers = {}
        self.connected = False

    async def connect(self):
        """连接到服务器"""
        self.ws = await websockets.connect(self.ws_url)
        self.connected = True
        logger.info(f"Connected to {self.ws_url}")

        # 请求配置
        await self.send("request_config", {})

    async def disconnect(self):
        """断开连接"""
        if self.ws:
            await self.ws.close()
            self.connected = False

    async def send(self, msg_type: str, data: dict):
        """发送消息"""
        if self.ws:
            message = json.dumps({"type": msg_type, "data": data}, ensure_ascii=False)
            await self.ws.send(message)

    def on(self, msg_type: str, handler):
        """注册消息处理器"""
        self.handlers[msg_type] = handler

    async def receive_one(self) -> dict:
        """接收一条消息"""
        if self.ws:
            message = await self.ws.recv()
            return json.loads(message)
        return {}

    async def handle_parallel_search(self, data: dict):
        """处理并行搜索任务（模拟）"""
        task_id = data.get("task_id", "unknown")
        queries = data.get("queries", [])

        logger.info(f"Processing parallel search: {task_id} with {len(queries)} queries")

        # 发送开始通知
        await self.send("parallel_search_progress", {
            "task_id": task_id,
            "status": "started",
            "total": len(queries),
            "completed": 0,
        })

        # 模拟搜索结果
        results = []
        for i, q in enumerate(queries):
            results.append({
                "id": q.get("id"),
                "query": q.get("query"),
                "engine": q.get("engine", "google"),
                "status": "success",
                "results": [{"title": f"Result for {q.get('query')}", "snippet": "Mock result"}],
            })

            # 发送进度
            await self.send("parallel_search_progress", {
                "task_id": task_id,
                "status": "running",
                "total": len(queries),
                "completed": i + 1,
            })

        # 发送完成
        await self.send("parallel_search_complete", {
            "task_id": task_id,
            "status": "completed",
            "total": len(queries),
            "success_count": len(results),
            "error_count": 0,
            "results": results,
        })

        return results


async def test_websocket_connection():
    """测试 WebSocket 连接"""
    print("\n" + "=" * 50)
    print("测试 1: WebSocket 连接")
    print("=" * 50)

    server = MockBrowserAIServer(port=18765)
    await server.start()

    try:
        # 客户端连接
        client = MockBrowserAIClient("ws://127.0.0.1:18765")
        await client.connect()

        # 接收配置
        config = await client.receive_one()
        assert config.get("type") == "config_update", "Should receive config_update"
        print("✅ WebSocket 连接成功")
        print(f"   收到配置: {config.get('data')}")

        await client.disconnect()
        print("✅ WebSocket 断开成功")

        return True

    except Exception as e:
        print(f"❌ WebSocket 测试失败: {e}")
        return False

    finally:
        await server.stop()


async def test_parallel_search():
    """测试并行搜索功能"""
    print("\n" + "=" * 50)
    print("测试 2: 并行搜索功能")
    print("=" * 50)

    server = MockBrowserAIServer(port=18766)
    await server.start()

    try:
        # 客户端连接
        client = MockBrowserAIClient("ws://127.0.0.1:18766")
        await client.connect()

        # 接收配置
        await client.receive_one()

        # 服务器发送并行搜索任务
        task_id = f"test_{int(datetime.now().timestamp())}"
        queries = [
            {"id": "q1", "query": "阿根廷屠宰场", "engine": "google"},
            {"id": "q2", "query": "巴西屠宰场", "engine": "bing"},
            {"id": "q3", "query": "乌拉圭屠宰场", "engine": "google"},
        ]

        print(f"   发送并行搜索任务: {task_id}")
        print(f"   查询数: {len(queries)}")

        # 发送任务
        await server.send_to_all("parallel_search", {
            "task_id": task_id,
            "queries": queries,
            "max_concurrent": 3,
            "timeout_per_query": 30,
        })

        # 客户端接收任务
        task_msg = await client.receive_one()
        assert task_msg.get("type") == "parallel_search", "Should receive parallel_search"
        print("✅ 客户端收到并行搜索任务")

        # 客户端处理任务
        results = await client.handle_parallel_search(task_msg.get("data", {}))
        print(f"✅ 并行搜索完成: {len(results)} 个结果")

        # 验证服务器收到结果
        await asyncio.sleep(0.1)  # 等待消息传递

        progress_msgs = [m for m in server.received_messages if m.get("type") == "parallel_search_progress"]
        complete_msgs = [m for m in server.received_messages if m.get("type") == "parallel_search_complete"]

        print(f"   服务器收到 {len(progress_msgs)} 条进度消息")
        print(f"   服务器收到 {len(complete_msgs)} 条完成消息")

        if complete_msgs:
            result = complete_msgs[0].get("data", {})
            print(f"   最终结果: 成功={result.get('success_count')}, 失败={result.get('error_count')}")

        await client.disconnect()
        return True

    except Exception as e:
        print(f"❌ 并行搜索测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await server.stop()


async def test_browser_task():
    """测试 Browser 任务"""
    print("\n" + "=" * 50)
    print("测试 3: Browser 任务")
    print("=" * 50)

    server = MockBrowserAIServer(port=18767)
    await server.start()

    try:
        client = MockBrowserAIClient("ws://127.0.0.1:18767")
        await client.connect()
        await client.receive_one()

        # 测试浏览任务
        task_id = f"browse_{int(datetime.now().timestamp())}"
        await server.send_to_all("browser_task", {
            "task_id": task_id,
            "task_type": "browse",
            "params": {
                "url": "https://example.com",
                "extract_content": True,
            }
        })

        task_msg = await client.receive_one()
        assert task_msg.get("type") == "browser_task", "Should receive browser_task"
        print("✅ 客户端收到 Browser 任务")

        task_data = task_msg.get("data", {})
        print(f"   任务ID: {task_data.get('task_id')}")
        print(f"   任务类型: {task_data.get('task_type')}")
        print(f"   URL: {task_data.get('params', {}).get('url')}")

        # 模拟返回结果
        await client.send("browse_result", {
            "task_id": task_id,
            "task_type": "browse",
            "status": "success",
            "url": "https://example.com",
            "title": "Example Domain",
            "content": "This domain is for use in illustrative examples.",
        })
        print("✅ 已发送 browse_result")

        await asyncio.sleep(0.1)
        browse_results = [m for m in server.received_messages if m.get("type") == "browse_result"]
        assert len(browse_results) > 0, "Server should receive browse_result"
        print("✅ 服务器收到浏览结果")

        await client.disconnect()
        return True

    except Exception as e:
        print(f"❌ Browser 任务测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await server.stop()


async def test_telegram_notification():
    """测试 Telegram 通知"""
    print("\n" + "=" * 50)
    print("测试 4: Telegram 通知")
    print("=" * 50)

    server = MockBrowserAIServer(port=18768)
    await server.start()

    try:
        client = MockBrowserAIClient("ws://127.0.0.1:18768")
        await client.connect()
        await client.receive_one()

        # 发送 Telegram 通知
        await client.send("telegram_notification", {
            "notification_type": "registry_start",
            "message": "🇦🇷 <b>阿根廷屠宰场名录获取</b>\n\n流程已启动...",
            "inline_keyboard": [
                [{"text": "跳过", "callback_data": "registry_skip:AR"}],
            ]
        })
        print("✅ 已发送 Telegram 通知")

        await asyncio.sleep(0.1)
        notifications = [m for m in server.received_messages if m.get("type") == "telegram_notification"]
        assert len(notifications) > 0, "Server should receive notification"

        notif = notifications[0].get("data", {})
        print(f"   通知类型: {notif.get('notification_type')}")
        print(f"   包含内联键盘: {'inline_keyboard' in notif}")

        await client.disconnect()
        return True

    except Exception as e:
        print(f"❌ Telegram 通知测试失败: {e}")
        return False

    finally:
        await server.stop()


async def test_registry_notifier():
    """测试 Registry Notifier"""
    print("\n" + "=" * 50)
    print("测试 5: Registry Notifier")
    print("=" * 50)

    try:
        from core.registry_notifier import RegistryNotifier, COUNTRY_FLAGS

        # 测试国旗映射
        test_countries = ["AR", "BR", "US", "CN", "DE", "XX"]
        print("国旗映射测试:")
        for code in test_countries:
            flag = COUNTRY_FLAGS.get(code, "🏳️")
            print(f"   {code} → {flag}")

        # 创建通知器（不需要真实连接）
        class MockWSClient:
            async def send(self, msg_type, data):
                logger.debug(f"MockWS: {msg_type}")

        notifier = RegistryNotifier(MockWSClient())
        print("✅ RegistryNotifier 创建成功")

        return True

    except Exception as e:
        print(f"❌ Registry Notifier 测试失败: {e}")
        return False


async def test_browser_ai_client():
    """测试 BrowserAIClient"""
    print("\n" + "=" * 50)
    print("测试 6: BrowserAIClient 可复用客户端")
    print("=" * 50)

    server = MockBrowserAIServer(port=18769)
    await server.start()

    try:
        from core.browser_ai_client import BrowserAIClient

        client = BrowserAIClient("ws://127.0.0.1:18769")
        await client.connect()
        print("✅ BrowserAIClient 连接成功")

        # 测试连接状态
        assert client.connected, "Client should be connected"
        assert client.websocket is not None, "WebSocket should be connected"
        print("✅ 连接状态正常")

        await client.disconnect()
        print("✅ 断开连接成功")

        return True

    except Exception as e:
        print(f"❌ BrowserAIClient 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await server.stop()


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("  Browser AI 集成测试")
    print("=" * 60)

    results = {}

    # 运行测试
    results["WebSocket 连接"] = await test_websocket_connection()
    results["并行搜索"] = await test_parallel_search()
    results["Browser 任务"] = await test_browser_task()
    results["Telegram 通知"] = await test_telegram_notification()
    results["Registry Notifier"] = await test_registry_notifier()
    results["BrowserAIClient"] = await test_browser_ai_client()

    # 总结
    print("\n" + "=" * 60)
    print("  测试结果总结")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print()
    print(f"  总计: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
