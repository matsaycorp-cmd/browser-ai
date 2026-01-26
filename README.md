# browser-ai

本地浏览器AI控制程序 — 通过 Playwright 自动操控浏览器，调用 ChatGPT、Claude、DeepSeek、Gemini 等大模型完成任务，并内置质量检查与多轮重试决策引擎。

## 项目结构

```
browser-ai/
├── core/
│   ├── browser_manager.py      # 浏览器管理
│   ├── chatgpt_controller.py   # ChatGPT控制
│   ├── claude_controller.py    # Claude控制
│   ├── deepseek_controller.py  # DeepSeek控制
│   ├── quality_checker.py      # 质量检查
│   ├── decision_engine.py      # 决策引擎
│   └── ws_client.py            # WebSocket客户端
├── config/
│   └── settings.py             # 配置文件
├── browser_data/               # 浏览器登录状态保存目录
├── logs/                       # 日志目录
├── main.py                     # 主程序入口
├── requirements.txt            # 依赖
└── README.md
```

## 安装

1. 安装 Python 依赖：

```bash
pip install -r requirements.txt
```

2. 安装 Playwright 浏览器：

```bash
playwright install chromium
```

## 运行

```bash
python main.py
```
