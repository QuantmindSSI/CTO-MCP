#!/usr/bin/env python3
"""Test suite for the constitution-xast engine (persona_constitution.ast_bridge).

Two layers:
  1. Environment-independent tests: language normalization, the inactive
     contract, and the constant-drift guards that keep ast_bridge's failure
     classes and finding texts byte-identical to scanner.PROSE_RULES, which
     is what makes cross-engine deduplication work.
  2. Tree-sitter-dependent tests, skipped with an explicit reason when the
     optional `ast` extra is not installed, covering each rule and each
     deliberate exemption per language.

Run: python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import ast_bridge, scanner  # noqa: E402 - path first.

XAST_ACTIVE = ast_bridge.xast_findings("function probe() {\n}\n", "javascript")[1]
NEEDS_TREE_SITTER = unittest.skipUnless(
    XAST_ACTIVE, "optional `ast` extra (tree-sitter + grammars) not installed"
)


class TestConstantsStayAlignedWithScanner(unittest.TestCase):
    """Dedup keys on (line, class, finding); any drift breaks the upgrade path."""

    def test_failure_classes_match(self):
        self.assertEqual(ast_bridge.CLASS_FRAMEWORK, scanner.CLASS_FRAMEWORK)
        self.assertEqual(ast_bridge.CLASS_CONFIDENCE, scanner.CLASS_CONFIDENCE)

    def test_finding_texts_match_prose_rules(self):
        prose_texts = {description for _, _, description, _, _ in scanner.PROSE_RULES}
        for text in (
            ast_bridge.TEXT_EMPTY_FUNCTION,
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.TEXT_EMPTY_CATCH,
            ast_bridge.TEXT_NOT_IMPLEMENTED,
            ast_bridge.TEXT_PANIC_STUB,
            ast_bridge.TEXT_RUST_MACRO,
        ):
            self.assertIn(text, prose_texts)


class TestNormalizeLanguage(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(ast_bridge.normalize_language("TSX"), "typescript")
        self.assertEqual(ast_bridge.normalize_language("golang"), "go")
        self.assertEqual(ast_bridge.normalize_language("C++"), "cpp")
        self.assertEqual(ast_bridge.normalize_language(" js "), "javascript")

    def test_unknown_and_absent(self):
        self.assertIsNone(ast_bridge.normalize_language(None))
        self.assertIsNone(ast_bridge.normalize_language(""))
        self.assertIsNone(ast_bridge.normalize_language("cobol"))


class TestInactiveContract(unittest.TestCase):
    """An engine that cannot run must say so and contribute nothing."""

    def test_unsupported_language_is_inactive(self):
        findings, active = ast_bridge.xast_findings("SELECT 1;", "sql")
        self.assertEqual(findings, [])
        self.assertFalse(active)

    def test_python_is_out_of_scope(self):
        findings, active = ast_bridge.xast_findings("def f():\n    pass\n", "python")
        self.assertEqual(findings, [])
        self.assertFalse(active)

    @NEEDS_TREE_SITTER
    def test_parse_errors_deactivate_the_engine(self):
        findings, active = ast_bridge.xast_findings("function broken( {{{", "javascript")
        self.assertEqual(findings, [])
        self.assertFalse(active)


@NEEDS_TREE_SITTER
class TestStubDetections(unittest.TestCase):
    def assert_violation(self, code, language, expected_text, expected_class):
        findings, active = ast_bridge.xast_findings(code, language)
        self.assertTrue(active)
        matches = [f for f in findings if f["finding"] == expected_text]
        self.assertEqual(len(matches), 1, f"expected exactly one {expected_text!r} finding, got {findings!r}")
        self.assertEqual(matches[0]["class"], expected_class)
        self.assertEqual(matches[0]["severity"], "violation")
        self.assertEqual(matches[0]["source"], "constitution-xast")

    def assert_clean(self, code, language):
        findings, active = ast_bridge.xast_findings(code, language)
        self.assertTrue(active)
        self.assertEqual(findings, [], f"expected no findings, got {findings!r}")

    def test_js_hardcoded_null_return(self):
        self.assert_violation(
            "function getUser(id) {\n  return null;\n}\n",
            "javascript",
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_js_empty_named_function(self):
        self.assert_violation(
            "function handler(req, res) {\n}\n",
            "javascript",
            ast_bridge.TEXT_EMPTY_FUNCTION,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_js_method_always_true(self):
        self.assert_violation(
            "class Auth {\n  isValid(token) {\n    return true;\n  }\n}\n",
            "javascript",
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_js_empty_catch_comment_only(self):
        self.assert_violation(
            "try { work(); } catch (e) { /* ignore */ }\n",
            "javascript",
            ast_bridge.TEXT_EMPTY_CATCH,
            ast_bridge.CLASS_CONFIDENCE,
        )

    def test_ts_template_literal_throw(self):
        self.assert_violation(
            "function migrate(): void {\n  throw new Error(`not implemented`);\n}\n",
            "typescript",
            ast_bridge.TEXT_NOT_IMPLEMENTED,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_java_unsupported_operation(self):
        self.assert_violation(
            "class S {\n  void save(User u) {\n    throw new UnsupportedOperationException();\n  }\n}\n",
            "java",
            ast_bridge.TEXT_NOT_IMPLEMENTED,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_java_null_return(self):
        self.assert_violation(
            "class R {\n  Object find(String key) {\n    return null;\n  }\n}\n",
            "java",
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_go_nil_return(self):
        self.assert_violation(
            "package db\nfunc GetUser(id int) *User {\n\treturn nil\n}\n",
            "go",
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_go_panic_stub(self):
        self.assert_violation(
            'package m\nfunc Save(u User) error {\n\tpanic("not implemented")\n}\n',
            "go",
            ast_bridge.TEXT_PANIC_STUB,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_rust_todo_macro(self):
        self.assert_violation(
            "fn parse(s: &str) -> i32 {\n    todo!()\n}\n",
            "rust",
            ast_bridge.TEXT_RUST_MACRO,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_ruby_empty_method(self):
        self.assert_violation(
            "def process(record)\nend\n",
            "ruby",
            ast_bridge.TEXT_EMPTY_FUNCTION,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_c_null_return(self):
        self.assert_violation(
            "char *lookup(int id) { return NULL; }\n",
            "c",
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.CLASS_FRAMEWORK,
        )

    def test_cpp_nullptr_return(self):
        self.assert_violation(
            "Widget *find() { return nullptr; }\n",
            "cpp",
            ast_bridge.TEXT_HARDCODED_RETURN,
            ast_bridge.CLASS_FRAMEWORK,
        )


@NEEDS_TREE_SITTER
class TestDeliberateExemptions(unittest.TestCase):
    """Idioms the engine must never accuse."""

    def assert_clean(self, code, language):
        findings, active = ast_bridge.xast_findings(code, language)
        self.assertTrue(active)
        self.assertEqual(findings, [], f"expected no findings, got {findings!r}")

    def test_anonymous_noop_callback(self):
        self.assert_clean("emitter.on('error', function () {});\n", "javascript")

    def test_arrow_function_constant(self):
        self.assert_clean("const nothing = () => null;\n", "javascript")

    def test_js_class_constructor(self):
        self.assert_clean("class A {\n  constructor() {\n  }\n}\n", "javascript")

    def test_java_empty_constructor(self):
        self.assert_clean("public class Widget {\n    public Widget() {\n    }\n}\n", "java")

    def test_java_interface_method_has_no_body(self):
        self.assert_clean("interface Repo {\n    byte[] get(String key);\n}\n", "java")

    def test_cpp_empty_body_exempt(self):
        self.assert_clean("struct S {\n  S() {}\n  ~S() {}\n};\n", "cpp")

    def test_catch_with_real_handling(self):
        self.assert_clean(
            "try { work(); } catch (e) { report(e); }\n",
            "javascript",
        )

    def test_real_function_with_logic(self):
        self.assert_clean(
            "function add(a, b) {\n  if (typeof a !== 'number') throw new TypeError('a');\n"
            "  return a + b;\n}\n",
            "javascript",
        )

    def test_rust_real_function(self):
        self.assert_clean("fn double(x: i32) -> i32 {\n    x * 2\n}\n", "rust")


@NEEDS_TREE_SITTER
class TestDeepLogicRules(unittest.TestCase):
    """Declarator-named stubs, empty loops, identical branches, Po10 metrics."""

    def findings(self, code, language):
        findings, active = ast_bridge.xast_findings(code, language)
        self.assertTrue(active)
        return findings

    def test_named_arrow_stub_is_a_violation(self):
        findings = self.findings("const getUser = (id) => {\n  return null;\n};\n", "javascript")
        self.assertEqual([f["severity"] for f in findings], ["violation"])
        self.assertEqual(findings[0]["finding"], ast_bridge.TEXT_HARDCODED_RETURN)

    def test_named_function_expression_stub_is_a_violation(self):
        findings = self.findings("const isValid = function (t) {\n  return true;\n};\n", "javascript")
        self.assertEqual([f["severity"] for f in findings], ["violation"])

    def test_noop_default_arrow_is_exempt(self):
        self.assertEqual(self.findings("const onClose = () => {};\n", "javascript"), [])

    def test_expression_bodied_arrow_is_exempt(self):
        self.assertEqual(self.findings("const nothing = () => null;\n", "javascript"), [])

    def test_empty_loop_bodies_warn(self):
        for code, language in [
            ("function f() {\n  while (busy()) {}\n  return 1;\n}\n", "javascript"),
            ("package m\nfunc f() {\n\tfor busy() {}\n}\n", "go"),
            ("class A { void f() { while (busy()) {} } }", "java"),
        ]:
            findings = self.findings(code, language)
            texts = [f["finding"] for f in findings]
            self.assertIn(ast_bridge.TEXT_EMPTY_LOOP, texts, f"{language}: {texts}")
            loop = next(f for f in findings if f["finding"] == ast_bridge.TEXT_EMPTY_LOOP)
            self.assertEqual(loop["severity"], "warning")

    def test_identical_branches_warn_and_else_if_is_exempt(self):
        findings = self.findings("function f(a) {\n  if (a) { doIt(); } else { doIt(); }\n}\n", "javascript")
        self.assertIn(ast_bridge.TEXT_IDENTICAL_BRANCHES, [f["finding"] for f in findings])
        clean = self.findings("function f(a, b) {\n  if (a) { x(); } else if (b) { x(); }\n}\n", "javascript")
        self.assertEqual(clean, [])

    def test_rust_identical_branches_warn(self):
        findings = self.findings("fn f(a: bool) -> i32 {\n    if a { g() } else { g() }\n}\n", "rust")
        self.assertIn(ast_bridge.TEXT_IDENTICAL_BRANCHES, [f["finding"] for f in findings])

    def test_complexity_limit_warns_with_bound_name(self):
        body = "".join(f"  if (x === {i}) {{ handle{i}(x); }}\n" for i in range(12))
        findings = self.findings(f"const route = (x) => {{\n{body}}};\n", "javascript")
        metric = [f for f in findings if f["class"] == ast_bridge.CLASS_PO10_COMPLEXITY]
        self.assertEqual(len(metric), 1, findings)
        self.assertIn("'route'", metric[0]["finding"])
        self.assertEqual(metric[0]["severity"], "warning")

    def test_length_limit_warns(self):
        body = "".join(f"  const a{i} = {i};\n" for i in range(55))
        findings = self.findings(f"function long_one() {{\n{body}  return a0;\n}}\n", "javascript")
        metric = [f for f in findings if f["class"] == ast_bridge.CLASS_PO10_LENGTH]
        self.assertEqual(len(metric), 1, findings)

    def test_nested_functions_are_separate_scopes(self):
        # Twelve branches inside a nested callback must not indict the outer.
        inner = "".join(f"    if (v === {i}) {{ h{i}(); }}\n" for i in range(12))
        code = f"function outer(xs) {{\n  xs.forEach(function inner(v) {{\n{inner}  }});\n  return xs;\n}}\n"
        findings = self.findings(code, "javascript")
        indicted = {
            f["finding"].split("'")[1] for f in findings if f["class"] == ast_bridge.CLASS_PO10_COMPLEXITY
        }
        self.assertEqual(indicted, {"inner"})


@NEEDS_TREE_SITTER
class TestScannerIntegration(unittest.TestCase):
    """scan_code must union, dedupe, and upgrade regex warnings to violations."""

    def test_js_null_return_now_fails(self):
        result = scanner.scan_code("function getUser(id) {\n  return null;\n}\n", language="javascript")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("constitution-xast", result["engines"])

    def test_dedupe_upgrades_regex_warning_in_place(self):
        result = scanner.scan_code("function getUser(id) {\n  return null;\n}\n", language="javascript")
        hardcoded = [f for f in result["findings"] if f["finding"] == ast_bridge.TEXT_HARDCODED_RETURN]
        self.assertEqual(len(hardcoded), 1, "regex warning and xast violation must collapse to one")
        self.assertEqual(hardcoded[0]["severity"], "violation")

    def test_clean_js_still_passes(self):
        result = scanner.scan_code(
            "function handler(req, res) {\n  const id = req.params.id;\n  res.json({ id });\n}\n",
            language="javascript",
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertIn("constitution-xast", result["engines"])

    def test_python_input_does_not_engage_xast(self):
        result = scanner.scan_code("def add(a, b):\n    return a + b\n", language="python")
        self.assertNotIn("constitution-xast", result["engines"])


if __name__ == "__main__":
    unittest.main()
