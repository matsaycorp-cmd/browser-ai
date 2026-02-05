"""
官方屠宰场名录获取流程 Telegram 通知模块

在执行名录获取流程的关键节点发送 Telegram 通知。
"""

import time
from typing import Optional

# 国家代码到国旗 emoji 映射
COUNTRY_FLAGS = {
    "AR": "🇦🇷", "BR": "🇧🇷", "CO": "🇨🇴", "VE": "🇻🇪", "MX": "🇲🇽",
    "CL": "🇨🇱", "PE": "🇵🇪", "UY": "🇺🇾", "PY": "🇵🇾", "EC": "🇪🇨",
    "BO": "🇧🇴", "CR": "🇨🇷", "PA": "🇵🇦", "GT": "🇬🇹", "HN": "🇭🇳",
    "NI": "🇳🇮", "SV": "🇸🇻", "DO": "🇩🇴", "CU": "🇨🇺", "PR": "🇵🇷",
    "US": "🇺🇸", "CA": "🇨🇦", "AU": "🇦🇺", "NZ": "🇳🇿", "GB": "🇬🇧",
    "IE": "🇮🇪", "FR": "🇫🇷", "DE": "🇩🇪", "ES": "🇪🇸", "IT": "🇮🇹",
    "PT": "🇵🇹", "NL": "🇳🇱", "BE": "🇧🇪", "PL": "🇵🇱", "RU": "🇷🇺",
    "UA": "🇺🇦", "IN": "🇮🇳", "CN": "🇨🇳", "JP": "🇯🇵", "KR": "🇰🇷",
    "TH": "🇹🇭", "VN": "🇻🇳", "ID": "🇮🇩", "MY": "🇲🇾", "PH": "🇵🇭",
    "ZA": "🇿🇦", "EG": "🇪🇬", "NG": "🇳🇬", "KE": "🇰🇪", "MA": "🇲🇦",
}


def get_flag(country_code: str) -> str:
    """获取国家旗帜 emoji。"""
    return COUNTRY_FLAGS.get(country_code.upper(), "🏳️")


def get_confidence_indicator(confidence: float) -> str:
    """获取置信度指示器。"""
    if confidence >= 0.8:
        return "🟢 高"
    elif confidence >= 0.5:
        return "🟡 中"
    else:
        return "🔴 低"


def format_duration(seconds: float) -> str:
    """格式化持续时间。"""
    if seconds < 60:
        return f"{seconds:.0f}秒"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}分{secs}秒"


class RegistryNotifier:
    """官方名录获取流程的 Telegram 通知器。"""

    def __init__(self, ws_client):
        """
        初始化通知器。

        Args:
            ws_client: WebSocket 客户端实例
        """
        self.ws_client = ws_client
        self.start_time: Optional[float] = None
        self.current_country_code: Optional[str] = None
        self.current_country_name: Optional[str] = None

    async def notify_start(self, country_code: str, country_name: str):
        """
        通知流程开始。

        Args:
            country_code: 国家代码
            country_name: 国家名称
        """
        self.start_time = time.time()
        self.current_country_code = country_code
        self.current_country_name = country_name

        flag = get_flag(country_code)
        message = (
            f"🚀 <b>开始获取官方屠宰场名录</b>\n"
            f"国家: {flag} {country_name} ({country_code})"
        )

        await self._send_notification("registry_start", {
            "country_code": country_code,
            "country_name": country_name,
            "message": message,
        })

    async def notify_baseline_complete(
        self,
        total_count: int,
        main_language: str,
        confidence: float,
        data_sources: list = None
    ):
        """
        通知基准数据获取完成。

        Args:
            total_count: 屠宰场总数估计
            main_language: 主要语言
            confidence: 数据置信度 (0.0-1.0)
            data_sources: 数据来源列表
        """
        flag = get_flag(self.current_country_code or "")
        confidence_indicator = get_confidence_indicator(confidence)

        message = (
            f"📊 <b>基准数据获取完成</b> {flag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"屠宰场总数: ~{total_count} 家\n"
            f"主要语言: {main_language}\n"
            f"数据置信度: {confidence_indicator}"
        )

        if data_sources:
            sources_text = "\n".join(f"  • {s}" for s in data_sources[:3])
            message += f"\n\n📎 数据来源:\n{sources_text}"

        await self._send_notification("registry_baseline", {
            "country_code": self.current_country_code,
            "total_count": total_count,
            "main_language": main_language,
            "confidence": confidence,
            "message": message,
        })

    async def notify_search_complete(
        self,
        registries_found: int,
        top_registry_name: str = None,
        top_registry_score: float = None
    ):
        """
        通知名录搜索完成。

        Args:
            registries_found: 找到的名录数量
            top_registry_name: 最高评分名录名称
            top_registry_score: 最高评分
        """
        flag = get_flag(self.current_country_code or "")

        message = (
            f"🔍 <b>名录搜索完成</b> {flag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"找到名录: {registries_found} 份"
        )

        if top_registry_name and top_registry_score is not None:
            score_bar = "█" * int(top_registry_score / 10) + "░" * (10 - int(top_registry_score / 10))
            message += (
                f"\n\n🏆 最佳匹配:\n"
                f"  {top_registry_name}\n"
                f"  评分: [{score_bar}] {top_registry_score:.0f}"
            )

        await self._send_notification("registry_search_complete", {
            "country_code": self.current_country_code,
            "registries_found": registries_found,
            "top_registry_name": top_registry_name,
            "top_registry_score": top_registry_score,
            "message": message,
        })

    async def notify_manual_download_needed(
        self,
        registry_id: str,
        registry_name: str,
        file_format: str,
        failure_reason: str,
        download_url: str
    ):
        """
        通知需要手动下载。

        Args:
            registry_id: 名录ID
            registry_name: 名录名称
            file_format: 文件格式
            failure_reason: 失败原因
            download_url: 下载链接
        """
        flag = get_flag(self.current_country_code or "")

        message = (
            f"⚠️ <b>需要手动下载</b> {flag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"名录: {registry_name}\n"
            f"格式: {file_format}\n"
            f"原因: {failure_reason}\n"
            f"\n🔗 <a href=\"{download_url}\">下载链接</a>"
        )

        # 内联按钮配置
        inline_keyboard = [
            [
                {"text": "🔗 打开链接", "url": download_url},
            ],
            [
                {"text": "⏭️ 跳过", "callback_data": f"registry_skip:{registry_id}"},
                {"text": "🔄 重试", "callback_data": f"registry_retry:{registry_id}"},
            ]
        ]

        await self._send_notification("registry_manual_download", {
            "country_code": self.current_country_code,
            "registry_id": registry_id,
            "registry_name": registry_name,
            "file_format": file_format,
            "failure_reason": failure_reason,
            "download_url": download_url,
            "message": message,
            "inline_keyboard": inline_keyboard,
        })

    async def notify_download_progress(
        self,
        current: int,
        total: int,
        current_name: str,
        status: str = "downloading"
    ):
        """
        通知下载进度。

        Args:
            current: 当前进度
            total: 总数
            current_name: 当前下载的名录名称
            status: 状态 (downloading/success/failed)
        """
        flag = get_flag(self.current_country_code or "")
        progress_bar = "█" * int(current / total * 10) + "░" * (10 - int(current / total * 10))

        status_icons = {
            "downloading": "⬇️",
            "success": "✅",
            "failed": "❌"
        }
        status_icon = status_icons.get(status, "⬇️")

        message = (
            f"📥 <b>下载进度</b> {flag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"[{progress_bar}] {current}/{total}\n"
            f"\n{status_icon} {current_name}"
        )

        await self._send_notification("registry_download_progress", {
            "country_code": self.current_country_code,
            "current": current,
            "total": total,
            "current_name": current_name,
            "status": status,
            "message": message,
        })

    async def notify_complete(
        self,
        success_count: int,
        pending_count: int,
        failed_count: int,
        slaughterhouses_obtained: int,
        baseline_count: int,
        errors: list = None
    ):
        """
        通知流程完成。

        Args:
            success_count: 成功下载数量
            pending_count: 待下载数量
            failed_count: 失败数量
            slaughterhouses_obtained: 获取到的屠宰场数量
            baseline_count: 基准屠宰场数量
            errors: 错误列表
        """
        flag = get_flag(self.current_country_code or "")
        country_name = self.current_country_name or "未知"

        # 计算耗时
        duration = time.time() - (self.start_time or time.time())
        duration_str = format_duration(duration)

        # 计算覆盖率
        coverage = (slaughterhouses_obtained / baseline_count * 100) if baseline_count > 0 else 0

        # 确定状态
        if failed_count == 0 and pending_count == 0:
            status = "✅ 全部成功"
        elif failed_count == 0:
            status = "⏳ 部分待下载"
        else:
            status = "⚠️ 部分失败"

        message = (
            f"📝 <b>获取完成 - {country_name}</b> {flag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"状态: {status}\n"
        )

        # 下载统计
        if success_count > 0:
            message += f"\n✅ 成功下载: {success_count} 份"
        if pending_count > 0:
            message += f"\n⏳ 待下载: {pending_count} 份"
        if failed_count > 0:
            message += f"\n❌ 失败: {failed_count} 份"

        # 数据统计
        message += (
            f"\n\n📊 屠宰场数据:\n"
            f"   获取: {slaughterhouses_obtained} 家\n"
            f"   基准: {baseline_count} 家\n"
            f"   覆盖率: {coverage:.1f}%"
        )

        # 耗时
        message += f"\n\n⏱️ 耗时: {duration_str}"

        # 错误信息
        if errors:
            error_text = "\n".join(f"  • {e}" for e in errors[:3])
            message += f"\n\n⚠️ 错误:\n{error_text}"

        await self._send_notification("registry_complete", {
            "country_code": self.current_country_code,
            "country_name": country_name,
            "success_count": success_count,
            "pending_count": pending_count,
            "failed_count": failed_count,
            "slaughterhouses_obtained": slaughterhouses_obtained,
            "baseline_count": baseline_count,
            "coverage": coverage,
            "duration": duration,
            "message": message,
        })

        # 重置状态
        self.start_time = None
        self.current_country_code = None
        self.current_country_name = None

    async def notify_error(self, error_message: str, details: str = None):
        """
        通知发生错误。

        Args:
            error_message: 错误信息
            details: 详细信息
        """
        flag = get_flag(self.current_country_code or "")

        message = (
            f"❌ <b>名录获取错误</b> {flag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{error_message}"
        )

        if details:
            message += f"\n\n详情: {details}"

        await self._send_notification("registry_error", {
            "country_code": self.current_country_code,
            "error_message": error_message,
            "details": details,
            "message": message,
        })

    async def _send_notification(self, notification_type: str, data: dict):
        """
        发送通知到 Telegram。

        Args:
            notification_type: 通知类型
            data: 通知数据
        """
        if not self.ws_client or not self.ws_client.connected:
            print(f"⚠️ WebSocket 未连接，无法发送通知: {notification_type}")
            return

        await self.ws_client.send("telegram_notification", {
            "notification_type": notification_type,
            **data
        })
