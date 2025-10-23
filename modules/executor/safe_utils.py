# safe_utils.py
from __future__ import annotations
import ast
from typing import Tuple

MAX_CODE_LENGTH = 1000

# имена и атрибуты, которые однозначно запрещаем
BANNED_NAMES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "ctypes",
    "mmap",
    "pickle",
    "importlib",
    "gc",
    "psutil",
    "threading",
    "multiprocessing",
    "__import__",
    "open",
    "eval",
    "exec",
    "compile",
    "globals",
    "locals",
    "vars",
    "object",
}

BANNED_ATTR_NAMES = {
    "system",
    "popen",
    "exec",
    "execv",
    "execve",
    "fork",
    "forkpty",
    "open",
    "read",
    "write",
    "socket",
    "connect",
    "accept",
}


class _ASTInspector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.reason: str | None = None

    def _ban(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason

    def visit_Import(self, node: ast.Import) -> None:
        self._ban("import")
        # no need to go deeper
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._ban("import_from")
    def visit_Call(self, node: ast.Call) -> None:
        # detect direct calls to eval/exec/compile/__import__ etc.
        func = node.func
        if isinstance(func, ast.Name) and func.id in BANNED_NAMES:
            self._ban(f"call_banned_name:{func.id}")
        elif isinstance(func, ast.Attribute):
            # attr chain like module.func()
            attr = func.attr
            if attr in BANNED_ATTR_NAMES:
                self._ban(f"call_banned_attr:{attr}")
        # also check keywords/args
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # catching possible attempts to access dangerous attributes
        if isinstance(node.attr, str) and node.attr in BANNED_ATTR_NAMES:
            self._ban(f"attr_banned:{node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BANNED_NAMES:
            self._ban(f"name_banned:{node.id}")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # subclass trick vectors often use metaclasses; disallow classdefs that set weird bases?
        # keep visiting but flag suspicious base names
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in BANNED_NAMES:
                self._ban(f"class_base_banned:{base.id}")
        self.generic_visit(node)

    def visit_Exec(self, node: ast.Exec) -> None:  # py2 fallback, rarely hit
        self._ban("exec_node")

def ast_sanitize(code: str) -> Tuple[bool, str]:
    """
    Возвращает (is_allowed, reason). False + reason = отказ.
    """
    if not code or not code.strip():
        return False, "empty"
    if len(code) > MAX_CODE_LENGTH:
        return False, "too_long"

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax_error:{exc}"

    inspector = _ASTInspector()
    inspector.visit(tree)
    if inspector.reason:
        return False, inspector.reason

    src = code.lower()
    if "__dict__" in src or "__class__" in src or "__mro__" in src:
        return False, "dunder_usage"

    return True, ""
