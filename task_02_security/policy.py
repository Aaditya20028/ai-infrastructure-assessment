"""Assessment policy is intentionally separate from authentication."""

from .config import Role


def may_call_tool(role: Role, tool_name: str) -> bool:
    return role in {"admin", "viewer"} and (role == "admin" or not tool_name.startswith("admin_"))
