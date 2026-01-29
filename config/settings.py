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

# AI 速率限制默认配置
RATE_LIMITS = {
    "chatgpt": {"per_hour": 50, "min_interval": 8},
    "claude": {"per_hour": 40, "min_interval": 10},
    "deepseek": {"per_hour": 60, "min_interval": 5},
    "gemini": {"per_hour": 40, "min_interval": 8},
}


class ConfigManager:
    """动态配置管理器，支持服务器下发配置更新。"""

    def __init__(self):
        # 从模块级常量加载默认配置
        self.config = {
            "ws_server_url": WS_SERVER_URL,
            "ai_urls": dict(AI_URLS),
            "browser_data_dir": BROWSER_DATA_DIR,
            "auto_approve_score": AUTO_APPROVE_SCORE,
            "min_pass_score": MIN_PASS_SCORE,
            "max_retry_rounds": MAX_RETRY_ROUNDS,
            "ai_retry_order": list(AI_RETRY_ORDER),
            "execution_mode": EXECUTION_MODE,
            "max_parallel": MAX_PARALLEL,
            "rate_limits": dict(RATE_LIMITS),
        }

    def update(self, key: str, value):
        """更新单个配置项。"""
        self.config[key] = value
        print(f"⚙️ 配置更新: {key} = {value}")

    def batch_update(self, configs: dict):
        """批量更新配置。"""
        for key, value in configs.items():
            self.config[key] = value
        if configs:
            print(f"⚙️ 批量更新 {len(configs)} 项配置")

    def get(self, key: str, default=None):
        """获取配置值。"""
        return self.config.get(key, default)

    def get_all(self) -> dict:
        """返回所有配置。"""
        return dict(self.config)


# 全局配置管理器实例
config_manager = ConfigManager()
