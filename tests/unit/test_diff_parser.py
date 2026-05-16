"""Unit tests for src/analyzers/diff_parser.py."""

from src.analyzers.diff_parser import parse_diff

_SIMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index abc1234..def5678 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,4 +1,5 @@
 def old_func():
-    return 1
+    return 2
+    # added comment

 x = 1
"""

_NEW_FILE_DIFF = """\
diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,3 @@
+def hello():
+    pass
+
"""

_DELETED_FILE_DIFF = """\
diff --git a/src/old.py b/src/old.py
deleted file mode 100644
index abc1234..0000000
--- a/src/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def goodbye():
-    pass
"""

_MULTI_FILE_DIFF = """\
diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
diff --git a/src/b.go b/src/b.go
index 3333333..4444444 100644
--- a/src/b.go
+++ b/src/b.go
@@ -5,3 +5,4 @@
 func main() {
+    fmt.Println("hello")
 }
"""


def test_simple_modification():
    changes = parse_diff(_SIMPLE_DIFF)
    assert len(changes) == 1
    c = changes[0]
    assert c.path == "src/foo.py"
    assert c.language == "python"
    assert not c.is_new_file
    assert not c.is_deleted_file
    assert "    return 2" in c.added_lines
    assert "    # added comment" in c.added_lines
    assert "    return 1" in c.removed_lines


def test_new_file():
    changes = parse_diff(_NEW_FILE_DIFF)
    assert len(changes) == 1
    c = changes[0]
    assert c.path == "src/new_module.py"
    assert c.is_new_file
    assert not c.is_deleted_file
    assert "def hello():" in c.added_lines
    assert c.removed_lines == []


def test_deleted_file():
    changes = parse_diff(_DELETED_FILE_DIFF)
    assert len(changes) == 1
    c = changes[0]
    assert c.path == "src/old.py"
    assert c.is_deleted_file
    assert "def goodbye():" in c.removed_lines
    assert c.added_lines == []


def test_multiple_files():
    changes = parse_diff(_MULTI_FILE_DIFF)
    assert len(changes) == 2
    paths = [c.path for c in changes]
    assert "src/a.py" in paths
    assert "src/b.go" in paths


def test_language_detection():
    changes = parse_diff(_MULTI_FILE_DIFF)
    by_path = {c.path: c for c in changes}
    assert by_path["src/a.py"].language == "python"
    assert by_path["src/b.go"].language == "go"


def test_hunk_line_numbers():
    changes = parse_diff(_SIMPLE_DIFF)
    c = changes[0]
    assert len(c.hunks) == 1
    h = c.hunks[0]
    assert h.old_start == 1
    assert h.new_start == 1


def test_empty_diff():
    assert parse_diff("") == []


def test_hunk_raw_lines_populated():
    changes = parse_diff(_SIMPLE_DIFF)
    hunk = changes[0].hunks[0]
    assert any(line.startswith("+") for line in hunk.lines)
    assert any(line.startswith("-") for line in hunk.lines)
