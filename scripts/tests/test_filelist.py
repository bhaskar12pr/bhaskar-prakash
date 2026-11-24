"""Unit tests for scripts/filelist.py. Run: make selftest"""
import os
import shutil
import tempfile
import unittest

import filelist


class FileListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, rel, text=""):
        path = os.path.join(self.tmp, rel)
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_nested_incdir_define_comments(self):
        a = self.write("rtl/a.sv")
        b = self.write("rtl/b.sv")
        inc = os.path.join(self.tmp, "rtl/inc")
        os.makedirs(inc)
        self.write("lists/rtl.f", "// design\n+incdir+../rtl/inc\n+define+W=8+FAST\n../rtl/a.sv  # trailing\n/* old\n../rtl/gone.sv\n*/\n")
        top = self.write("lists/top.f", "-f rtl.f\n-D DEBUG\n../rtl/b.sv\n../rtl/a.sv\n")
        fl = filelist.FileList().parse(top)
        self.assertEqual(fl.sources, [a, b])          # order kept, duplicate removed
        self.assertEqual(fl.incdirs, [inc])
        self.assertEqual(fl.defines, ["W=8", "FAST", "DEBUG"])
        self.assertIn("-DW=8", fl.yosys())
        self.assertIn("+incdir+" + inc, fl.flat())

    def test_env_vars(self):
        a = self.write("ip/x.sv")
        os.environ["FLTEST_ROOT"] = self.tmp
        self.addCleanup(os.environ.pop, "FLTEST_ROOT")
        top = self.write("t.f", "${FLTEST_ROOT}/ip/x.sv\n$(FLTEST_ROOT)/ip/x.sv\n")
        self.assertEqual(filelist.FileList().parse(top).sources, [a])

    def test_undefined_env_var_is_error(self):
        top = self.write("t.f", "$FLTEST_NOT_SET/x.sv\n")
        with self.assertRaisesRegex(filelist.FileListError, r"t\.f:1: .*FLTEST_NOT_SET"):
            filelist.FileList().parse(top)

    def test_missing_file_reports_line(self):
        top = self.write("t.f", "// header\n\nmissing.sv\n")
        with self.assertRaisesRegex(filelist.FileListError, r"t\.f:3: file not found"):
            filelist.FileList().parse(top)

    def test_include_loop(self):
        self.write("a.f", "-f b.f\n")
        self.write("b.f", "-f a.f\n")
        with self.assertRaisesRegex(filelist.FileListError, "includes itself"):
            filelist.FileList().parse(os.path.join(self.tmp, "a.f"))

    def test_relative_to_cwd(self):
        a = self.write("src/a.sv")
        top = self.write("lists/t.f", "src/a.sv\n")
        old = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.assertEqual(filelist.FileList("cwd").parse(top).sources, [a])
        finally:
            os.chdir(old)

    def test_unknown_options_pass_through_with_warning(self):
        self.write("a.sv")
        top = self.write("t.f", "-timescale=1ns/1ps\na.sv\n")
        fl = filelist.FileList().parse(top)
        self.assertEqual(fl.options, ["-timescale=1ns/1ps"])
        self.assertTrue(fl.warnings)

    def test_cli_writes_outputs(self):
        self.write("a.sv")
        top = self.write("t.f", "a.sv\n")
        out = os.path.join(self.tmp, "out/rtl")
        self.assertEqual(filelist.main([top, "--out", out, "--quiet"]), 0)
        for ext in (".f", ".sources", ".yosys", ".cocotb.mk"):
            self.assertTrue(os.path.exists(out + ext), ext)
        self.assertEqual(filelist.main([os.path.join(self.tmp, "nope.f")]), 2)


if __name__ == "__main__":
    unittest.main()
