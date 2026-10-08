import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sublime_stub import fake_sublime  # noqa: E402,F401  (installs the stub)

from liveserverplus_lib.ignore import matches_ignore  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
