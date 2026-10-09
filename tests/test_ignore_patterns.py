import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sublime_stub import fake_sublime  # noqa: E402,F401  (installs the stub)

from liveserverplus_lib.ignore import matches_ignore, matches_ignore_under  # noqa: E402


DEFAULTS = ["**/node_modules/**", "**/.git/**", "**/__pycache__/**"]


class IgnorePatternTests(unittest.TestCase):
    def test_default_patterns_match_nested_files(self):
        """PurePosixPath.match only matched files directly inside the directory."""
        self.assertTrue(matches_ignore("/proj/node_modules/foo.js", DEFAULTS))
        self.assertTrue(matches_ignore("/proj/node_modules/pkg/dist/foo.js", DEFAULTS))
        self.assertTrue(matches_ignore("/proj/.git/objects/ab/cdef", DEFAULTS))
        self.assertTrue(matches_ignore("/proj/sub/__pycache__/x.pyc", DEFAULTS))

    def test_default_patterns_match_the_directory_itself(self):
        """Needed so a directory listing of /.git/ can be refused too."""
        self.assertTrue(matches_ignore("/proj/.git", DEFAULTS))
        self.assertTrue(matches_ignore("/proj/node_modules/", DEFAULTS))

    def test_unrelated_paths_do_not_match(self):
        self.assertFalse(matches_ignore("/proj/src/app.js", DEFAULTS))
        self.assertFalse(matches_ignore("/proj/node_modules_notes.md", DEFAULTS))
        self.assertFalse(matches_ignore("/proj/.github/workflows/ci.yml", DEFAULTS))

    def test_bare_directory_name_covers_its_contents(self):
        self.assertTrue(matches_ignore("/proj/dist/bundle.js", ["dist"]))
        self.assertTrue(matches_ignore("/proj/a/b/dist/x/y.js", ["dist"]))
        self.assertFalse(matches_ignore("/proj/distro/x.js", ["dist"]))

    def test_extension_pattern_matches_at_any_depth(self):
        self.assertTrue(matches_ignore("/proj/a/b/c.map", ["*.map"]))
        self.assertTrue(matches_ignore("/proj/c.map", ["**/*.map"]))
        self.assertFalse(matches_ignore("/proj/c.mapx", ["*.map"]))

    def test_double_star_in_the_middle(self):
        self.assertTrue(matches_ignore("/proj/dist/a.js", ["dist/**/*.js"]))
        self.assertTrue(matches_ignore("/proj/dist/x/y/a.js", ["dist/**/*.js"]))
        self.assertFalse(matches_ignore("/proj/dist/a.css", ["dist/**/*.js"]))

    def test_leading_slash_anchors_to_the_start(self):
        self.assertTrue(matches_ignore("/proj/x.js", ["/proj/*.js"]))
        self.assertFalse(matches_ignore("/other/proj/x.js", ["/proj/*.js"]))

    def test_question_mark_matches_one_character(self):
        self.assertTrue(matches_ignore("/p/file1.txt", ["file?.txt"]))
        self.assertFalse(matches_ignore("/p/file12.txt", ["file?.txt"]))

    def test_windows_paths_and_patterns(self):
        self.assertTrue(matches_ignore(r"C:\proj\node_modules\x.js", DEFAULTS))
        self.assertTrue(matches_ignore(r"C:\proj\build\x.js", [r"**\build\**"]))

    def test_empty_and_junk_input(self):
        self.assertFalse(matches_ignore("", DEFAULTS))
        self.assertFalse(matches_ignore("/p/x.js", []))
        self.assertFalse(matches_ignore("/p/x.js", ["", None, 3]))
        self.assertTrue(matches_ignore("/p/x.js", ["**"]))


class IgnoreUnderRootTests(unittest.TestCase):
    """Patterns apply below the served folder, never to its ancestors."""

    def _tree(self, tmp, *parts):
        import os
        root = os.path.join(tmp, *parts)
        os.makedirs(root, exist_ok=True)
        return root

    def test_project_inside_an_ignored_directory_is_not_ignored(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, "node_modules", "some-lib", "examples")
            page = os.path.join(root, "index.html")
            nested = os.path.join(root, "node_modules", "dep", "x.js")

            self.assertFalse(matches_ignore_under(page, [root], DEFAULTS))
            self.assertFalse(matches_ignore_under(root, [root], DEFAULTS))
            self.assertTrue(matches_ignore_under(nested, [root], DEFAULTS))

    def test_pattern_matching_an_ancestor_of_the_root_does_nothing(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, "build", "site")
            page = os.path.join(root, "index.html")

            self.assertFalse(matches_ignore_under(page, [root], ["build"]))
            self.assertTrue(matches_ignore_under(os.path.join(root, "build", "a.js"), [root], ["build"]))

    def test_anchored_pattern_is_relative_to_the_root(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, "site")
            self.assertTrue(matches_ignore_under(os.path.join(root, "dist", "a.js"), [root], ["/dist"]))
            self.assertFalse(matches_ignore_under(os.path.join(root, "src", "dist", "a.js"), [root], ["/dist"]))

    def test_path_outside_every_root_falls_back_to_absolute_matching(self):
        self.assertTrue(matches_ignore_under("/elsewhere/node_modules/x.js", ["/proj"], DEFAULTS))
        self.assertFalse(matches_ignore_under("/elsewhere/src/x.js", ["/proj"], DEFAULTS))

    def test_first_containing_root_wins(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            a = self._tree(tmp, "a")
            b = self._tree(tmp, "b")
            f = os.path.join(b, "dist", "x.js")
            self.assertTrue(matches_ignore_under(f, [a, b], ["/dist"]))


if __name__ == "__main__":
    unittest.main()
