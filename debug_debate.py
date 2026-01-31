#!/usr/bin/env python3
"""对抗验证调试工具 - 详细记录和分析对抗验证过程。"""

import json
import os
from datetime import datetime


class DebateDebugger:
    """对抗验证调试器 - 记录详细的调试信息。"""

    def __init__(self, log_file: str = "./logs/debate_debug.log"):
        self.log_file = log_file
        self.session_logs: dict = {}
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        """确保日志目录存在。"""
        log_dir = os.path.dirname(self.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

    def start_session(self, session_id: str, task_info: dict):
        """开始调试会话。"""
        self.session_logs[session_id] = {
            "task_info": task_info,
            "started_at": datetime.now().isoformat(),
            "rounds": [],
            "errors": [],
            "warnings": [],
        }

        self._write_log(f"\n{'='*60}")
        self._write_log(f"[SESSION START] {session_id}")
        self._write_log(f"Task: {json.dumps(task_info, ensure_ascii=False)}")
        self._write_log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._write_log(f"{'='*60}")

    def log_round_start(
        self,
        session_id: str,
        round_num: int,
        agent_role: str,
        ai_name: str,
    ):
        """记录轮次开始。"""
        log_entry = {
            "round": round_num,
            "agent": agent_role,
            "ai": ai_name,
            "started_at": datetime.now().isoformat(),
            "prompts": [],
            "responses": [],
        }

        if session_id in self.session_logs:
            self.session_logs[session_id]["rounds"].append(log_entry)

        self._write_log(f"\n[ROUND {round_num}] {agent_role.upper()} ({ai_name}) - START")
        self._write_log(f"Time: {datetime.now().strftime('%H:%M:%S')}")

    def log_prompt(self, session_id: str, round_num: int, prompt: str):
        """记录发送的Prompt。"""
        self._write_log(f"\n[PROMPT] Round {round_num}")
        self._write_log("-" * 40)

        # 截断过长的prompt
        display_prompt = prompt[:2000] + "..." if len(prompt) > 2000 else prompt
        self._write_log(display_prompt)
        self._write_log("-" * 40)

        # 保存到session
        if session_id in self.session_logs:
            for r in self.session_logs[session_id]["rounds"]:
                if r["round"] == round_num:
                    r["prompts"].append({
                        "content": prompt,
                        "timestamp": datetime.now().isoformat(),
                        "length": len(prompt),
                    })
                    break

    def log_response(self, session_id: str, round_num: int, response):
        """记录AI响应。"""
        self._write_log(f"\n[RESPONSE] Round {round_num}")
        self._write_log("-" * 40)

        if isinstance(response, dict):
            display = json.dumps(response, ensure_ascii=False, indent=2)[:3000]
        else:
            display = str(response)[:3000]

        self._write_log(display)
        if len(str(response)) > 3000:
            self._write_log("... (已截断)")
        self._write_log("-" * 40)

        # 更新session记录
        if session_id in self.session_logs:
            for r in self.session_logs[session_id]["rounds"]:
                if r["round"] == round_num:
                    r["responses"].append({
                        "content": response,
                        "timestamp": datetime.now().isoformat(),
                    })
                    r["completed_at"] = datetime.now().isoformat()
                    break

    def log_round_complete(
        self,
        session_id: str,
        round_num: int,
        agent_role: str,
        duration: float,
        success: bool = True,
    ):
        """记录轮次完成。"""
        status = "SUCCESS" if success else "FAILED"
        self._write_log(f"\n[ROUND {round_num}] {agent_role.upper()} - {status}")
        self._write_log(f"Duration: {duration:.2f}s")

    def log_error(self, session_id: str, round_num: int, error: str | Exception):
        """记录错误。"""
        error_entry = {
            "round": round_num,
            "error": str(error),
            "timestamp": datetime.now().isoformat(),
        }

        if session_id in self.session_logs:
            self.session_logs[session_id]["errors"].append(error_entry)

        self._write_log(f"\n[ERROR] Round {round_num}")
        self._write_log(f"Error: {error}")

    def log_warning(self, session_id: str, message: str):
        """记录警告。"""
        if session_id in self.session_logs:
            self.session_logs[session_id]["warnings"].append({
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })

        self._write_log(f"\n[WARNING] {message}")

    def log_parse_result(
        self,
        session_id: str,
        round_num: int,
        raw_response: str,
        parsed_result: dict,
        parse_success: bool,
    ):
        """记录JSON解析结果。"""
        self._write_log(f"\n[PARSE] Round {round_num}")
        self._write_log(f"Parse Success: {parse_success}")

        if not parse_success:
            self._write_log(f"Raw response (first 500 chars): {raw_response[:500]}")

    def log_final_result(self, session_id: str, result: dict):
        """记录最终结果。"""
        if session_id in self.session_logs:
            self.session_logs[session_id]["final_result"] = result
            self.session_logs[session_id]["completed_at"] = datetime.now().isoformat()

        self._write_log(f"\n{'='*60}")
        self._write_log("[FINAL RESULT]")
        self._write_log("-" * 40)

        display = json.dumps(result, ensure_ascii=False, indent=2)[:5000]
        self._write_log(display)

        self._write_log("-" * 40)
        self._write_log(f"[SESSION END] {session_id}")
        self._write_log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._write_log(f"{'='*60}")

    def get_session_summary(self, session_id: str) -> dict | None:
        """获取会话摘要。"""
        if session_id not in self.session_logs:
            return None

        session = self.session_logs[session_id]

        summary = {
            "session_id": session_id,
            "task": session["task_info"],
            "started_at": session["started_at"],
            "completed_at": session.get("completed_at"),
            "rounds_count": len(session["rounds"]),
            "errors_count": len(session["errors"]),
            "warnings_count": len(session.get("warnings", [])),
            "rounds_summary": [],
        }

        for r in session["rounds"]:
            round_summary = {
                "round": r["round"],
                "agent": r["agent"],
                "ai": r["ai"],
                "prompts_count": len(r.get("prompts", [])),
                "responses_count": len(r.get("responses", [])),
                "has_response": len(r.get("responses", [])) > 0,
                "duration": self._calc_duration(r.get("started_at"), r.get("completed_at")),
            }
            summary["rounds_summary"].append(round_summary)

        # 计算总耗时
        summary["total_duration"] = self._calc_duration(
            session["started_at"],
            session.get("completed_at"),
        )

        return summary

    def _calc_duration(self, start: str | None, end: str | None) -> float | None:
        """计算耗时（秒）。"""
        if not start or not end:
            return None
        try:
            s = datetime.fromisoformat(start)
            e = datetime.fromisoformat(end)
            return (e - s).total_seconds()
        except (ValueError, TypeError):
            return None

    def _write_log(self, message: str):
        """写入日志文件。"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"

        # 打印到控制台
        print(log_line)

        # 写入文件
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except OSError:
            pass  # 忽略文件写入错误

    def export_session(self, session_id: str, output_file: str | None = None) -> str | None:
        """导出会话详情到JSON文件。"""
        if session_id not in self.session_logs:
            return None

        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"./logs/debate_session_{session_id}_{timestamp}.json"

        # 确保目录存在
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.session_logs[session_id], f, ensure_ascii=False, indent=2)

        print(f"📄 会话已导出到: {output_file}")
        return output_file

    def print_session_summary(self, session_id: str):
        """打印会话摘要。"""
        summary = self.get_session_summary(session_id)
        if not summary:
            print(f"❌ 未找到会话: {session_id}")
            return

        print(f"\n{'='*60}")
        print(f"📊 会话摘要: {session_id}")
        print(f"{'='*60}")

        task = summary["task"]
        print(f"任务类型: {task.get('task_type', 'N/A')}")
        print(f"公司: {task.get('company_name', 'N/A')}")
        print(f"国家: {task.get('country', 'N/A')}")

        print(f"\n开始时间: {summary['started_at']}")
        print(f"结束时间: {summary.get('completed_at', '未完成')}")

        if summary.get("total_duration"):
            print(f"总耗时: {summary['total_duration']:.1f}秒")

        print(f"\n轮次数: {summary['rounds_count']}")
        print(f"错误数: {summary['errors_count']}")
        print(f"警告数: {summary['warnings_count']}")

        if summary["rounds_summary"]:
            print(f"\n{'─'*40}")
            print("各轮详情:")
            for r in summary["rounds_summary"]:
                status = "✅" if r["has_response"] else "❌"
                duration = f"{r['duration']:.1f}s" if r["duration"] else "N/A"
                print(f"  {status} Round {r['round']}: {r['agent']} ({r['ai']}) - {duration}")

        print(f"{'='*60}")

    def clear_session(self, session_id: str):
        """清除会话记录。"""
        if session_id in self.session_logs:
            del self.session_logs[session_id]
            print(f"✅ 已清除会话: {session_id}")

    def list_sessions(self) -> list:
        """列出所有会话。"""
        sessions = []
        for sid, data in self.session_logs.items():
            sessions.append({
                "session_id": sid,
                "task_type": data["task_info"].get("task_type"),
                "started_at": data["started_at"],
                "completed": "completed_at" in data,
                "rounds": len(data["rounds"]),
                "errors": len(data["errors"]),
            })
        return sessions

    def print_all_sessions(self):
        """打印所有会话列表。"""
        sessions = self.list_sessions()
        if not sessions:
            print("📭 没有会话记录")
            return

        print(f"\n{'='*60}")
        print(f"📋 所有会话 ({len(sessions)})")
        print(f"{'='*60}")

        for s in sessions:
            status = "✅" if s["completed"] else "🔄"
            errors = f" ❌{s['errors']}" if s["errors"] > 0 else ""
            print(f"  {status} {s['session_id']}: {s['task_type']} - {s['rounds']}轮{errors}")


# 全局调试器实例
debugger = DebateDebugger()


def get_debugger() -> DebateDebugger:
    """获取全局调试器实例。"""
    return debugger


# === 交互式调试菜单 ===

def interactive_debug_menu():
    """交互式调试菜单。"""
    dbg = get_debugger()

    while True:
        print(f"\n{'='*60}")
        print("🔧 对抗验证调试工具")
        print(f"{'='*60}")
        print("1. 查看所有会话")
        print("2. 查看会话摘要")
        print("3. 导出会话详情")
        print("4. 清除会话")
        print("5. 查看日志文件")
        print("6. 清空日志文件")
        print("0. 退出")
        print(f"{'='*60}")

        choice = input("请选择 (0-6): ").strip()

        if choice == "1":
            dbg.print_all_sessions()

        elif choice == "2":
            session_id = input("会话ID: ").strip()
            if session_id:
                dbg.print_session_summary(session_id)
            else:
                print("⚠️ 请输入会话ID")

        elif choice == "3":
            session_id = input("会话ID: ").strip()
            if session_id:
                output = input("输出文件路径（直接回车使用默认）: ").strip() or None
                dbg.export_session(session_id, output)
            else:
                print("⚠️ 请输入会话ID")

        elif choice == "4":
            session_id = input("会话ID（输入 'all' 清除所有）: ").strip()
            if session_id == "all":
                confirm = input("确认清除所有会话? (y/n): ").strip().lower()
                if confirm == "y":
                    dbg.session_logs.clear()
                    print("✅ 已清除所有会话")
            elif session_id:
                dbg.clear_session(session_id)

        elif choice == "5":
            log_file = dbg.log_file
            if os.path.exists(log_file):
                print(f"\n📄 日志文件: {log_file}")
                print("-" * 40)
                try:
                    with open(log_file, encoding="utf-8") as f:
                        lines = f.readlines()
                        # 显示最后50行
                        for line in lines[-50:]:
                            print(line.rstrip())
                except OSError as e:
                    print(f"❌ 读取失败: {e}")
            else:
                print("📭 日志文件不存在")

        elif choice == "6":
            confirm = input("确认清空日志文件? (y/n): ").strip().lower()
            if confirm == "y":
                try:
                    with open(dbg.log_file, "w", encoding="utf-8") as f:
                        f.write("")
                    print("✅ 日志文件已清空")
                except OSError as e:
                    print(f"❌ 清空失败: {e}")

        elif choice == "0":
            print("👋 退出调试工具")
            break

        else:
            print("⚠️ 无效选择")

        input("\n按 Enter 键继续...")


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║           🔧 对抗验证调试工具                              ║
    ║                                                           ║
    ║   查看和分析对抗验证会话的详细日志                         ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    interactive_debug_menu()
