"""演示账号口令的统一读取入口（开源前脱敏引入）。

背景：开源前清理要求**源码、脚本、文档中不出现任何明文口令**。
本项目已不再提供默认口令，演示账号由部署方通过环境变量自行指定：

    NOVA_DEMO_PASSWORD=<口令>                     # 三个角色共用
    NOVA_SEED_ADMIN_PASSWORD=<口令>               # 或按角色分别指定（优先级更高）
    NOVA_SEED_COUNSELOR_PASSWORD=<口令>
    NOVA_SEED_STUDENT_PASSWORD=<口令>

本模块提供 `demo_password(role)` 与 `demo_passwords()` 两个函数，
供测试、评测与探针脚本调用；若未配置则抛出带明确指引的 RuntimeError。
"""
from __future__ import annotations

import os

_ROLES = ("admin", "counselor", "student")


def demo_password(role: str) -> str:
    """返回指定角色的演示口令。

    优先取 `NOVA_SEED_<ROLE>_PASSWORD`，回退到 `NOVA_DEMO_PASSWORD`。
    两者都未设置时抛 RuntimeError（而不是静默用一个默认值）。
    """
    role = role.lower()
    if role not in _ROLES:
        raise ValueError(f"未知角色: {role}")
    pwd = (os.environ.get(f"NOVA_SEED_{role.upper()}_PASSWORD")
           or os.environ.get("NOVA_DEMO_PASSWORD", ""))
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令。请先在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"（或 NOVA_SEED_{role.upper()}_PASSWORD），并确保该进程能读到它。")
    return pwd


def demo_passwords() -> dict[str, str]:
    """返回 {'admin': ..., 'counselor': ..., 'student': ...} 的口令映射。"""
    return {r: demo_password(r) for r in _ROLES}
