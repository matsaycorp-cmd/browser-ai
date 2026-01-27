# WebSocket服务器地址
WS_SERVER_URL = "ws://localhost:8765"

# AI平台URL
AI_URLS = {
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "deepseek": "https://chat.deepseek.com",
    "gemini": "https://gemini.google.com",
}

# 浏览器数据目录（保存登录状态）
BROWSER_DATA_DIR = "./browser_data"

# 质量检查配置
AUTO_APPROVE_SCORE = 85  # 自动通过分数
MIN_PASS_SCORE = 70      # 最低通过分数

# 重试配置
MAX_RETRY_ROUNDS = 4  # 最大重试轮数
AI_RETRY_ORDER = ["chatgpt", "claude", "deepseek", "gemini"]  # 重试顺序

# 执行模式: "single" | "parallel" | "race" | "best"
EXECUTION_MODE = "single"
MAX_PARALLEL = 2  # 最多同时运行的AI数量
