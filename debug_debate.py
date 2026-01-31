import asyncio
import json
from datetime import datetime

class DebateDebugger:
    """对抗验证调试器"""

    def __init__(self, log_file="./logs/debate_debug.log"):
        self.log_file = log_file
        self.session_logs = {}

    def start_session(self, session_id, task_info):
        """开始调试会话"""
        self.session_logs[session_id] = {
            "task_info": task_info,
            "started_at": datetime.now().isoformat(),
            "rounds": [],
            "errors": []
        }
        self._write_log(f"\n{'='*60}")
        self._write_log(f"[SESSION START] {session_id}")
        self._write_log(f"Task: {json.dumps(task_info, ensure_ascii=False)}")

    def log_round_start(self, session_id, round_num, agent_role, ai_name):
        """记录轮次开始"""
        log_entry = {
            "round": round_num,
            "agent": agent_role,
            "ai": ai_name,
            "started_at": datetime.now().isoformat()
        }

        if session_id in self.session_logs:
            self.session_logs[session_id]["rounds"].append(log_entry)

        self._write_log(f"\n[ROUND {round_num}] {agent_role.upper()} ({ai_name}) - START")

    def log_prompt(self, session_id, round_num, prompt):
        """记录发送的Prompt"""
        self._write_log(f"\n[PROMPT] Round {round_num}")
        self._write_log("-" * 40)
        self._write_log(prompt[:1000] + "..." if len(prompt) > 1000 else prompt)
        self._write_log("-" * 40)

    def log_response(self, session_id, round_num, response):
        """记录AI响应"""
        self._write_log(f"\n[RESPONSE] Round {round_num}")
        self._write_log("-" * 40)

        if isinstance(response, dict):
            self._write_log(json.dumps(response, ensure_ascii=False, indent=2)[:2000])
        else:
            self._write_log(str(response)[:2000])

        self._write_log("-" * 40)

        # 更新session记录
        if session_id in self.session_logs:
            for r in self.session_logs[session_id]["rounds"]:
                if r["round"] == round_num and "response" not in r:
                    r["response"] = response
                    r["completed_at"] = datetime.now().isoformat()
                    break

    def log_error(self, session_id, round_num, error):
        """记录错误"""
        error_entry = {
            "round": round_num,
            "error": str(error),
            "timestamp": datetime.now().isoformat()
        }

        if session_id in self.session_logs:
            self.session_logs[session_id]["errors"].append(error_entry)

        self._write_log(f"\n[ERROR] Round {round_num}: {error}")

    def log_final_result(self, session_id, result):
        """记录最终结果"""
        if session_id in self.session_logs:
            self.session_logs[session_id]["final_result"] = result
            self.session_logs[session_id]["completed_at"] = datetime.now().isoformat()

        self._write_log(f"\n[FINAL RESULT]")
        self._write_log(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
        self._write_log(f"\n[SESSION END] {session_id}")
        self._write_log("=" * 60)

    def get_session_summary(self, session_id):
        """获取会话摘要"""
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
            "rounds_summary": []
        }

        for r in session["rounds"]:
            round_summary = {
                "round": r["round"],
                "agent": r["agent"],
                "ai": r["ai"],
                "has_response": "response" in r,
                "duration": self._calc_duration(r.get("started_at"), r.get("completed_at"))
            }
            summary["rounds_summary"].append(round_summary)

        return summary

    def _calc_duration(self, start, end):
        """计算耗时"""
        if not start or not end:
            return None
        try:
            s = datetime.fromisoformat(start)
            e = datetime.fromisoformat(end)
            return (e - s).total_seconds()
        except:
            return None

    def _write_log(self, message):
        """写入日志文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"

        print(log_line)  # 同时打印到控制台

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except:
            pass

    def export_session(self, session_id, output_file=None):
        """导出会话详情"""
        if session_id not in self.session_logs:
            return None

        if not output_file:
            output_file = f"./logs/debate_session_{session_id}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.session_logs[session_id], f, ensure_ascii=False, indent=2)

        return output_file


# 全局调试器实例
debugger = DebateDebugger()
