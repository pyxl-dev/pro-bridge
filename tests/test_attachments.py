import os
import tempfile
import unittest

from pro_bridge.attachments import normalize_file_paths


class AttachmentPathTests(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(normalize_file_paths(None), [])
        self.assertEqual(normalize_file_paths([]), [])

    def test_existing_file_is_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("hello")

            result = normalize_file_paths([path])
            self.assertEqual(result, [os.path.abspath(path)])

    def test_duplicates_are_removed_preserving_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "a.txt")
            second = os.path.join(tmp, "b.txt")
            for path in (first, second):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(path)

            result = normalize_file_paths([first, second, first])
            self.assertEqual(result, [os.path.abspath(first), os.path.abspath(second)])

    def test_missing_file_rejected(self):
        with self.assertRaises(FileNotFoundError):
            normalize_file_paths(["/definitely/not/here/pro-bridge-test.txt"])

    def test_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                normalize_file_paths([tmp])

    def test_blank_path_rejected(self):
        with self.assertRaises(ValueError):
            normalize_file_paths(["   "])


if __name__ == "__main__":
    unittest.main()
