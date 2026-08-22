"""用 AST 保证低层协议模块不反向依赖具体 Provider。"""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2] / "web_llm_bridge"


class DependencyDirectionTests(unittest.TestCase):
    def test_protocol_does_not_depend_on_provider_or_session_layers(self) -> None:
        tree = ast.parse((ROOT / "protocol.py").read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any("provider" in module or "session" in module for module in imports))

    def test_public_session_does_not_open_extension_transport(self) -> None:
        tree = ast.parse((ROOT / "session" / "model.py").read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertNotIn("transport", " ".join(imports))
