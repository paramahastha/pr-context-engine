"""Unit tests for src/analyzers/risk_scorer.py."""

from src.analyzers.diff_parser import FileChange, Hunk
from src.analyzers.risk_scorer import score


def _new_file_change(path: str, num_lines: int) -> FileChange:
    lines = [f"+    x_{i} = {i}" for i in range(num_lines)]
    h = Hunk(old_start=0, old_count=0, new_start=1, new_count=num_lines, lines=lines)
    added = [ln[1:] for ln in lines]
    return FileChange(
        path=path,
        language="python",
        added_lines=added,
        removed_lines=[],
        hunks=[h],
        is_new_file=True,
    )


def _hunk(old_start: int, new_start: int, lines: list[str]) -> Hunk:
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    return Hunk(
        old_start=old_start,
        old_count=removed,
        new_start=new_start,
        new_count=added,
        lines=lines,
    )


def _change(path: str, hunks: list[Hunk], language: str = "python") -> FileChange:
    added = [ln[1:] for h in hunks for ln in h.lines if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for h in hunks for ln in h.lines if ln.startswith("-") and not ln.startswith("---")]
    return FileChange(
        path=path,
        language=language,
        added_lines=added,
        removed_lines=removed,
        hunks=hunks,
    )


# ── touches_migration ────────────────────────────────────────────────────────

def test_migration_path_detected():
    c = _change("migrations/0002_add_email.sql", [])
    flags = score([c])
    assert any(f.flag == "touches_migration" for f in flags)


def test_alembic_path_detected():
    c = _change("alembic/versions/abc123_create_table.py", [])
    flags = score([c])
    assert any(f.flag == "touches_migration" for f in flags)


def test_sql_extension_detected():
    c = _change("scripts/seed_data.sql", [])
    flags = score([c])
    assert any(f.flag == "touches_migration" for f in flags)


def test_no_false_positive_migration():
    c = _change("src/models.py", [])
    flags = score([c])
    assert not any(f.flag == "touches_migration" for f in flags)


# ── modifies_auth ─────────────────────────────────────────────────────────────

def test_auth_keyword_in_added_line():
    h = _hunk(10, 10, ['+    token = request.headers.get("Authorization")'])
    c = _change("src/auth.py", [h])
    flags = score([c])
    auth_flags = [f for f in flags if f.flag == "modifies_auth"]
    assert len(auth_flags) == 1
    assert auth_flags[0].line == 10
    assert "token" in auth_flags[0].snippet


def test_password_keyword_flagged():
    h = _hunk(5, 5, ['+    hashed = bcrypt.hash(password)'])
    c = _change("src/users.py", [h])
    flags = score([c])
    assert any(f.flag == "modifies_auth" for f in flags)


def test_auth_in_removed_line_not_flagged():
    h = _hunk(5, 5, ['-    token = old_token'])
    c = _change("src/auth.py", [h])
    flags = score([c])
    # removed lines are not flagged as modifies_auth
    assert not any(f.flag == "modifies_auth" for f in flags)


def test_auth_keyword_case_insensitive():
    h = _hunk(1, 1, ['+    AUTH_SECRET = os.environ["AUTH_SECRET"]'])
    c = _change("src/config.py", [h])
    flags = score([c])
    assert any(f.flag == "modifies_auth" for f in flags)


# ── changes_config ────────────────────────────────────────────────────────────

def test_dotenv_file_flagged():
    c = _change(".env", [])
    flags = score([c])
    assert any(f.flag == "changes_config" for f in flags)


def test_dotenv_local_flagged():
    c = _change(".env.local", [])
    flags = score([c])
    assert any(f.flag == "changes_config" for f in flags)


def test_root_yaml_flagged():
    c = _change("docker-compose.yaml", [])
    flags = score([c])
    assert any(f.flag == "changes_config" for f in flags)


def test_nested_yaml_not_flagged():
    c = _change("src/fixtures/data.yaml", [])
    flags = score([c])
    assert not any(f.flag == "changes_config" for f in flags)


def test_root_config_dot_flagged():
    c = _change("config.toml", [])
    flags = score([c])
    assert any(f.flag == "changes_config" for f in flags)


# ── deletes_public_api ────────────────────────────────────────────────────────

def test_deleted_top_level_python_function():
    h = _hunk(20, 20, ['-def compute_hash(data: bytes) -> str:'])
    c = _change("src/utils.py", [h])
    flags = score([c])
    api_flags = [f for f in flags if f.flag == "deletes_public_api"]
    assert len(api_flags) == 1
    assert api_flags[0].line == 20
    assert "compute_hash" in api_flags[0].snippet


def test_deleted_method_not_flagged():
    # indented = class method, not top-level
    h = _hunk(30, 30, ['-    def _private_helper(self):'])
    c = _change("src/models.py", [h])
    flags = score([c])
    assert not any(f.flag == "deletes_public_api" for f in flags)


def test_deleted_go_func_flagged():
    h = _hunk(10, 10, ['-func ProcessEvent(e Event) error {'])
    c = _change("pkg/handler.go", [h], language="go")
    flags = score([c])
    assert any(f.flag == "deletes_public_api" for f in flags)


def test_added_function_not_flagged_as_delete():
    h = _hunk(1, 1, ['+def new_func():'])
    c = _change("src/new.py", [h])
    flags = score([c])
    assert not any(f.flag == "deletes_public_api" for f in flags)


# ── line number tracking ──────────────────────────────────────────────────────

def test_line_number_advances_correctly():
    lines = [
        " def context_line():",   # context: new=5, old=5
        "+    x = auth_token",    # added at new_lineno=6
        " ",                      # context
    ]
    h = _hunk(old_start=5, new_start=5, lines=lines)
    c = _change("src/app.py", [h])
    flags = score([c])
    auth = [f for f in flags if f.flag == "modifies_auth"]
    assert auth[0].line == 6


# ── clean change produces no flags ───────────────────────────────────────────

def test_no_flags_for_plain_change():
    h = _hunk(1, 1, ['-x = 1', '+x = 2'])
    c = _change("src/constants.py", [h])
    flags = score([c])
    assert flags == []


# ── comment and type-decl false-positive suppression ─────────────────────────

def test_python_comment_without_space_not_flagged():
    # Previously `#\s` required a space, so `#token` slipped through.
    h = _hunk(1, 1, ['+#auth_token = request.headers.get("X-Token")'])
    c = _change("src/auth.py", [h])
    assert not any(f.flag == "modifies_auth" for f in score([c]))


def test_python_comment_with_space_not_flagged():
    h = _hunk(1, 1, ['+# store the auth token here'])
    c = _change("src/auth.py", [h])
    assert not any(f.flag == "modifies_auth" for f in score([c]))


def test_go_line_comment_not_flagged():
    h = _hunk(1, 1, ['+// token is validated upstream'])
    c = _change("pkg/handler.go", [h], language="go")
    assert not any(f.flag == "modifies_auth" for f in score([c]))


def test_go_struct_decl_not_flagged():
    h = _hunk(1, 1, ['+type AuthStore struct {'])
    c = _change("pkg/store.go", [h], language="go")
    assert not any(f.flag == "modifies_auth" for f in score([c]))


def test_python_class_decl_not_flagged():
    h = _hunk(1, 1, ['+class AuthManager:'])
    c = _change("src/auth.py", [h])
    assert not any(f.flag == "modifies_auth" for f in score([c]))


def test_python_class_with_base_not_flagged():
    h = _hunk(1, 1, ['+class AuthManager(BaseManager):'])
    c = _change("src/auth.py", [h])
    assert not any(f.flag == "modifies_auth" for f in score([c]))


# ── modifies_auth deduplication ───────────────────────────────────────────────

def test_auth_deduped_within_file():
    lines = ['+    token_a = get_token()', '+    token_b = get_token()', '+    password = "secret"']
    h = _hunk(1, 1, lines)
    c = _change("src/auth.py", [h])
    auth_flags = [f for f in score([c]) if f.flag == "modifies_auth"]
    assert len(auth_flags) == 1


def test_auth_not_deduped_across_files():
    h = _hunk(1, 1, ['+    token = get_token()'])
    c1 = _change("src/auth.py", [h])
    c2 = _change("src/user.py", [h])
    auth_flags = [f for f in score([c1, c2]) if f.flag == "modifies_auth"]
    assert len(auth_flags) == 2


def test_auth_dedup_preserves_first_match_line():
    lines = ['+    password_a = "x"', '+    password_b = "y"']
    h = _hunk(10, 10, lines)
    c = _change("src/auth.py", [h])
    auth_flags = [f for f in score([c]) if f.flag == "modifies_auth"]
    assert auth_flags[0].line == 10


# ── large_new_file ────────────────────────────────────────────────────────────

def test_large_new_file_flagged():
    c = _new_file_change("src/new_store.py", 300)
    assert any(f.flag == "large_new_file" for f in score([c]))


def test_boundary_new_file_flagged():
    c = _new_file_change("src/new_store.py", 301)
    assert any(f.flag == "large_new_file" for f in score([c]))


def test_small_new_file_not_flagged():
    c = _new_file_change("src/tiny.py", 50)
    assert not any(f.flag == "large_new_file" for f in score([c]))


def test_large_existing_file_not_flagged():
    lines = [f"+    x_{i} = {i}" for i in range(300)]
    h = _hunk(1, 1, lines)
    c = _change("src/existing.py", [h])
    assert not any(f.flag == "large_new_file" for f in score([c]))
