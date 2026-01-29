# Browser AI 控制程序

本地浏览器AI控制程序 - 通过 Playwright 自动操控浏览器，调用 ChatGPT、Claude、DeepSeek、Gemini 等大模型完成任务，并内置质量检查与多轮重试决策引擎。

## 功能

- 自动控制 ChatGPT / Claude / DeepSeek 浏览器
- 搜索屠宰场联系方式
- 生成询价邮件
- 智能质量检查和自动重试
- 多AI并行/竞速执行模式
- 服务器动态配置更新
- 任务持久化和崩溃恢复

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
│   ├── ws_client.py            # WebSocket客户端
│   ├── rate_limiter.py         # 速率限制
│   ├── task_persistence.py     # 任务持久化
│   └── parallel_executor.py    # 并行执行器
├── config/
│   └── settings.py             # 配置文件
├── browser_data/               # 浏览器登录状态保存目录
├── logs/                       # 日志目录
├── main.py                     # 主程序入口
├── start.py                    # 启动菜单
├── test_connection.py          # 连接测试工具
├── install.bat                 # Windows安装脚本
├── install.sh                  # Mac/Linux安装脚本
├── run.bat                     # Windows运行脚本
├── run.sh                      # Mac/Linux运行脚本
├── requirements.txt            # 依赖
└── README.md
```

## 安装

### Windows

双击 `install.bat` 或在命令行运行：

```cmd
install.bat
```

### Mac/Linux

```bash
chmod +x install.sh
./install.sh
```

### 手动安装

1. 安装 Python 依赖：

```bash
pip install -r requirements.txt
```

2. 安装 Playwright 浏览器：

```bash
playwright install chromium
```

## 运行

### Windows

双击 `run.bat` 或在命令行运行：

```cmd
run.bat
```

### Mac/Linux

```bash
chmod +x run.sh
./run.sh
```

### 直接运行

```bash
python start.py
```

## 启动菜单

运行程序后会显示启动菜单：

```
====================================
     🤖 Browser AI 控制程序
====================================

  1. 启动完整程序
  2. 仅测试连接
  3. 仅登录AI（不执行任务）
  4. 查看配置
  5. 退出

====================================
```

## 首次使用

1. 运行程序，选择 "3. 仅登录AI"
2. 浏览器会自动打开各AI平台页面
3. 手动登录 ChatGPT、Claude、DeepSeek
4. 登录状态会自动保存到 `browser_data/` 目录
5. 下次启动无需重复登录

## 测试连接

运行连接测试检查各组件状态：

```bash
python test_connection.py
```

或在启动菜单中选择 "2. 仅测试连接"

测试内容：
- 浏览器是否正常启动
- 各AI平台登录状态
- WebSocket服务器连接

## 配置

编辑 `config/settings.py` 修改配置：

```python
# 服务器地址
WS_SERVER_URL = "ws://your-server:8765"

# AI优先顺序
AI_RETRY_ORDER = ["chatgpt", "claude", "deepseek", "gemini"]

# 质量控制
AUTO_APPROVE_SCORE = 80    # 自动通过分数
MIN_PASS_SCORE = 60        # 最低通过分数
MAX_RETRY_ROUNDS = 3       # 最大重试轮数

# 执行模式: single, parallel, race, best
EXECUTION_MODE = "single"
MAX_PARALLEL = 2

# 速率限制
RATE_LIMITS = {
    "chatgpt": {"per_hour": 50, "min_interval": 8},
    "claude": {"per_hour": 40, "min_interval": 10},
    "deepseek": {"per_hour": 60, "min_interval": 5},
    "gemini": {"per_hour": 40, "min_interval": 8},
}
```

配置也可以通过服务器动态更新。

## 执行模式说明

| 模式 | 说明 |
|------|------|
| single | 单AI执行，失败后按顺序切换 |
| parallel | 多AI同时执行，合并结果 |
| race | 多AI竞速，返回最快的结果 |
| best | 多AI执行，返回得分最高的结果 |

## 日志

日志文件保存在 `logs/` 目录，包含：
- 任务执行记录
- AI响应内容
- 错误信息
- 质量评分详情

## 常见问题

### 浏览器启动失败

运行以下命令安装浏览器：

```bash
playwright install chromium
```

### WebSocket连接失败

检查：
1. 服务器地址是否正确
2. 服务器是否运行
3. 网络是否连通

### AI登录状态丢失

删除 `browser_data/` 目录后重新登录：

```bash
rm -rf browser_data/
python start.py  # 选择 "3. 仅登录AI"
```

## 开发

### 添加新的AI平台

1. 在 `core/` 目录创建新的控制器文件
2. 实现 `send_message`、`wait_response`、`get_last_response` 方法
3. 在 `config/settings.py` 添加URL配置
4. 在 `main.py` 注册控制器

### 添加新的任务类型

1. 在 `quality_checker.py` 添加任务类型检查器
2. 在 TaskRunner 中添加任务处理逻辑
