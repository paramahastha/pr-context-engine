"""Unit tests for src/analyzers/ast_walker.py."""

from src.analyzers.diff_parser import FileChange
from src.analyzers.ast_walker import extract_changed_symbols


def _make_change(path: str, added: list[str], removed: list[str] | None = None) -> FileChange:
    language_map = {".py": "python", ".go": "go", ".ts": "typescript", ".js": "javascript"}
    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    return FileChange(
        path=path,
        language=language_map.get(ext, "unknown"),
        added_lines=added,
        removed_lines=removed or [],
        hunks=[],
    )


def test_python_function_detection():
    change = _make_change(
        "src/utils.py",
        added=["def new_helper(x, y):", "    return x + y"],
    )
    assert "new_helper" in extract_changed_symbols(change)


def test_python_class_detection():
    change = _make_change(
        "src/models.py",
        added=["class UserProfile:", "    pass"],
    )
    assert "UserProfile" in extract_changed_symbols(change)


def test_python_async_function():
    change = _make_change(
        "src/tasks.py",
        added=["async def fetch_data(url: str) -> dict:", "    ..."],
    )
    assert "fetch_data" in extract_changed_symbols(change)


def test_python_removed_function_detected():
    change = _make_change(
        "src/old.py",
        added=[],
        removed=["def deprecated_func():", "    pass"],
    )
    assert "deprecated_func" in extract_changed_symbols(change)


def test_go_function_detection():
    change = _make_change(
        "pkg/server.go",
        added=["func HandleRequest(w http.ResponseWriter, r *http.Request) {"],
    )
    assert "HandleRequest" in extract_changed_symbols(change)


def test_go_method_detection():
    change = _make_change(
        "pkg/server.go",
        added=["func (s *Server) Start() error {"],
    )
    assert "Start" in extract_changed_symbols(change)


def test_typescript_function_detection():
    change = _make_change(
        "src/api.ts",
        added=["export async function fetchUser(id: string): Promise<User> {"],
    )
    assert "fetchUser" in extract_changed_symbols(change)


def test_deduplication():
    change = _make_change(
        "src/utils.py",
        added=["def foo():", "    pass", "def foo():", "    return 1"],
    )
    symbols = extract_changed_symbols(change)
    assert symbols.count("foo") == 1


def test_no_symbols_returns_empty():
    change = _make_change(
        "src/constants.py",
        added=["MAX_RETRIES = 3", "TIMEOUT = 30"],
    )
    assert extract_changed_symbols(change) == []


def test_unknown_language_falls_back():
    change = _make_change(
        "scripts/setup.sh",
        added=["function setup_env() {", "    echo hello", "}"],
    )
    # unknown language uses python patterns as fallback — no crash expected
    result = extract_changed_symbols(change)
    assert isinstance(result, list)
