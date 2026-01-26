# 任务持久化模块

import json
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)


class TaskPersistence:
    """将任务状态持久化到 JSON 文件，支持崩溃后恢复。"""

    def __init__(self, file_path: str = "./data/pending_tasks.json"):
        self.file_path = file_path
        self.archive_path = os.path.join(
            os.path.dirname(file_path), "completed_tasks.json"
        )
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # 加载已有任务
        self.tasks: dict[str, dict] = self._load_from_file()
        logger.info("已加载 %d 个任务记录", len(self.tasks))

    # ── 写入 ─────────────────────────────────────────────

    def save_task(
        self,
        task_id: str,
        task_type: str,
        params: dict,
        status: str = "pending",
    ):
        """保存新任务。"""
        now = time.time()
        self.tasks[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "params": params,
            "status": status,
            "current_ai": None,
            "retry_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self._save_to_file()
        logger.info("已保存任务: %s (%s)", task_id, task_type)

    def update_task(self, task_id: str, **updates):
        """更新任务字段，自动刷新 updated_at。"""
        task = self.tasks.get(task_id)
        if task is None:
            logger.warning("更新失败，任务不存在: %s", task_id)
            return
        task.update(updates)
        task["updated_at"] = time.time()
        self._save_to_file()

    def complete_task(self, task_id: str, result):
        """标记任务完成，并归档到 completed_tasks.json。"""
        task = self.tasks.get(task_id)
        if task is None:
            return
        task["status"] = "completed"
        task["result"] = result
        task["updated_at"] = time.time()

        # 归档
        self._archive_task(task)

        # 从待处理列表移除
        del self.tasks[task_id]
        self._save_to_file()
        logger.info("任务已完成并归档: %s", task_id)

    def fail_task(self, task_id: str, error: str):
        """标记任务失败。"""
        task = self.tasks.get(task_id)
        if task is None:
            return
        task["status"] = "failed"
        task["error"] = error
        task["updated_at"] = time.time()
        self._save_to_file()
        logger.warning("任务失败: %s — %s", task_id, error)

    def remove_task(self, task_id: str):
        """从待处理列表中移除任务。"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_to_file()
            logger.info("已移除任务: %s", task_id)

    # ── 查询 ─────────────────────────────────────────────

    def get_pending_tasks(self) -> list[dict]:
        """返回所有 pending 或 running 状态的任务。"""
        return [
            t for t in self.tasks.values()
            if t.get("status") in ("pending", "running")
        ]

    def get_task(self, task_id: str) -> dict | None:
        """获取单个任务详情。"""
        return self.tasks.get(task_id)

    # ── 文件 I/O ─────────────────────────────────────────

    def _save_to_file(self):
        """原子写入：先写临时文件，再 rename 替换，防止写中断损坏。"""
        dir_name = os.path.dirname(self.file_path)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.file_path)
        except Exception as e:
            logger.error("保存任务文件失败: %s", e)

    def _load_from_file(self) -> dict:
        """从文件加载任务，文件不存在则返回空字典。"""
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            logger.error("加载任务文件失败: %s", e)
            return {}

    def _archive_task(self, task: dict):
        """将完成的任务追加到归档文件。"""
        archive: list = []
        if os.path.exists(self.archive_path):
            try:
                with open(self.archive_path, "r", encoding="utf-8") as f:
                    archive = json.load(f)
            except (json.JSONDecodeError, OSError):
                archive = []

        archive.append(task)

        try:
            dir_name = os.path.dirname(self.archive_path)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(archive, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.archive_path)
        except Exception as e:
            logger.error("归档任务失败: %s", e)
