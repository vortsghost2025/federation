"""Sandbox validation tests for the write_code builder.

Covers the AST allowlist (allowed subset vs. the bypass attempts that defeated
the old regex blacklist: dunder introspection, name aliasing of pre-imported
modules, __builtins__ tricks, format-string attribute walks) and end-to-end
execution (legit code runs, denied code is rejected before execution, runaway
code is killed by the timeout).

Gitignored like the other npc-agent tests; run with:
    python -m pytest npc-agent/test_sandbox.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from npc_actions import _validate_sandbox_code, _execute_sandboxed_python  # noqa: E402


def _allowed(code):
    return _validate_sandbox_code(code) is None


def _denied(code):
    err = _validate_sandbox_code(code)
    return err is not None, err


# ── Allowed: pure computation ──
def test_plain_computation_allowed():
    assert _allowed("x = 1 + 2\nprint(x * 3)")


def test_loops_and_containers_allowed():
    assert _allowed("total = 0\nfor i in range(5):\n    total += i\nprint(total)")
    assert _allowed("d = {'a': 1, 'b': 2}\nprint(d['a'] + sum(d.values()))")
    assert _allowed("print([i * i for i in range(4)])")


def test_method_calls_on_safe_objects_allowed():
    assert _allowed("s = '  hello  '\nprint(s.strip().upper())")
    assert _allowed("xs = []\nfor i in range(3):\n    xs.append(i * i)\nprint(xs)")
    assert _allowed("print('-'.join(['a', 'b', 'c']))")


def test_functions_and_fstrings_allowed():
    assert _allowed("def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\nprint(fib(7))")
    assert _allowed("n = 4\nprint(f'n = {n}, sq = {n * n}')")


# ── Denied: the old regex bypasses and other escapes ──
def test_imports_denied():
    for code in ("import os", "import os as x", "from os import system",
                 "import sys", "import subprocess", "import importlib"):
        denied, err = _denied(code)
        assert denied, code
        assert err, code


def test_dunder_introspection_denied():
    for code in (
        "''.__class__",
        "''.__class__.__base__.__subclasses__()",
        "().__class__.__mro__[1].__subclasses__()",
        "x = ''.__class__\nprint(x)",
        "print(''.__dict__)",
    ):
        assert _denied(code)[0], code


def test_name_aliasing_denied():
    # The old wrapper pre-imported sys/time/resource into scope; aliasing
    # bypassed the "sys." pattern. Now bare names are checked too.
    for code in ("s = sys", "s = sys\nprint(s.modules['os'])",
                 "g = globals()", "g = globals\ng()['sys']",
                 "t = time", "r = resource"):
        assert _denied(code)[0], code


def test_builtins_tricks_denied():
    for code in (
        "__import__('os')",
        "__builtins__['__import__']('os')",
        "eval('1+1')",
        "exec('x = 1')",
        "compile('1', '<s>', 'eval')",
        "getattr('', '__class__')",
        "vars()",
        "dir()",
        "open('/etc/passwd')",
        "breakpoint()",
        "input()",
    ):
        assert _denied(code)[0], code


def test_os_sys_via_names_denied():
    for code in ("os.system('id')", "sys.modules['os']", "os.environ",
                 "subprocess.run(['id'])"):
        assert _denied(code)[0], code


def test_type_construction_denied():
    # type is deliberately NOT in the allowed builtins.
    assert _denied("type('X', (Exception,), {})")[0]
    assert _denied("type('')")[0]


def test_while_classes_async_with_denied():
    for code in ("while True:\n    pass", "while x < 5:\n    x += 1",
                 "class X:\n    pass", "with open('/etc/passwd') as f:\n    pass",
                 "async def f():\n    return 1"):
        assert _denied(code)[0], code


def test_format_string_dunder_walk_denied():
    # str.format()'s mini-language walks attributes by NAME, bypassing the AST
    # attribute check — the constant-string scan must catch it.
    for code in (
        "'{0.__class__}'.format(1)",
        "s = '{0.__init__.__globals__}'\nprint(s.format(1))",
        "print('{0.__class__.__base__.__subclasses__}'.format(1))",
    ):
        assert _denied(code)[0], code


def test_frame_traceback_attrs_denied():
    assert _denied("(i for i in range(1)).gi_frame")[0]
    assert _denied("(i for i in range(1)).gi_frame.f_globals")[0]
    assert _denied("(x for x in [1]).gi_frame.f_locals")[0]


def test_unknown_names_denied():
    assert _denied("print(open)")[0]
    assert _denied("x = unknown_var")[0]
    assert _denied("print(resource)")[0]


# ── End-to-end execution ──
def test_exec_ok_legit_code():
    ok, out = _execute_sandboxed_python("print(6 * 7)")
    assert ok and "42" in out


def test_exec_ok_loops():
    ok, out = _execute_sandboxed_python("total = 0\nfor i in range(1, 101):\n    total += i\nprint(total)")
    assert ok and "5050" in out


def test_exec_denied_before_running():
    ok, out = _execute_sandboxed_python("import os\nos.system('id')")
    assert not ok and "code_denied" in out


def test_exec_dunder_denied_before_running():
    ok, out = _execute_sandboxed_python("print(''.__class__.__base__.__subclasses__())")
    assert not ok and "code_denied" in out


def test_exec_recursion_capped():
    # Allowed by AST but must die quickly (RecursionError), not hang.
    ok, out = _execute_sandboxed_python("def f():\n    return f()\nf()")
    assert not ok


def test_exec_cpu_hang_killed():
    # Legit-looking unbounded loop: must be killed by the hard timeout.
    ok, out = _execute_sandboxed_python(
        "x = 0\nfor i in range(10**9):\n    x += i\nprint(x)", timeout=1)
    assert not ok and ("code_timeout" in out or "code_error" in out)


def test_exec_env_clean():
    # No env passthrough: sandboxed code must not see the agent's variables.
    ok, out = _execute_sandboxed_python("import os\nprint(os.environ)")
    assert not ok
