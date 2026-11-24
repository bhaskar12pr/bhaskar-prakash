#!/usr/bin/env python3
"""Resolve a Verilog/SystemVerilog file list (.f) into tool-ready outputs.

One parser for every tool, so all tools see exactly the same files.

Supported in .f files:
  path/to/file.sv           source file
  -f other.f / -F other.f   nested file list
  +incdir+dir1+dir2  -I dir include directories
  +define+A=1+B      -D A=1 defines
  -v file  -y dir  +libext+.v+.sv  and any other option: passed through
  // comment   # comment   /* block comment */
  $VAR  ${VAR}  $(VAR)       environment variables (an undefined one is an error)

Relative paths are resolved against the file list that contains them
(--relative-to file, the default) or against the current directory
(--relative-to cwd). -F is always relative to the file list, as in the
commercial tools.

Outputs, written with --out PREFIX:
  PREFIX.f         flat file list with absolute paths (Icarus, Verilator,
                   Questa, VCS and Xcelium all accept it with -f)
  PREFIX.sources   one source file per line
  PREFIX.yosys     read_verilog options: -D... -I...
  PREFIX.cocotb.mk VERILOG_SOURCES / VERILOG_INCLUDE_DIRS / COMPILE_ARGS for cocotb

Exit code 2 with "file:line: message" on any problem (missing file,
undefined variable, include loop), so CI fails early with a clear reason.
"""
import argparse
import os
import re
import shlex
import sys

VAR_RE = re.compile(r"\$\{(\w+)\}|\$\((\w+)\)|\$(\w+)")


class FileListError(Exception):
    pass


class FileList(object):
    def __init__(self, relative_to="file"):
        self.relative_to = relative_to
        self.sources = []
        self.incdirs = []
        self.defines = []
        self.options = []      # passed through to the simulator only
        self.warnings = []
        self._stack = []

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _expand(token, where):
        def repl(m):
            name = m.group(1) or m.group(2) or m.group(3)
            if name not in os.environ:
                raise FileListError("%s: environment variable $%s is not set" % (where, name))
            return os.environ[name]
        return VAR_RE.sub(repl, token)

    def _path(self, token, base, where, must_exist=True, kind="file"):
        path = os.path.expanduser(self._expand(token, where))
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        path = os.path.normpath(path)
        if must_exist and not os.path.exists(path):
            raise FileListError("%s: %s not found: %s" % (where, kind, path))
        return path

    @staticmethod
    def _add(lst, item):
        if item not in lst:
            lst.append(item)

    @staticmethod
    def _tokens(text):
        """Yield (line_no, token) with comments removed."""
        # Replace block comments with blank lines so line numbers stay right.
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        for no, line in enumerate(text.splitlines(), 1):
            line = re.sub(r"(^|\s)//.*$", "", line)
            for tok in shlex.split(line, comments=True):
                yield no, tok

    # -- parsing -----------------------------------------------------------
    def parse(self, path, base=None):
        path = os.path.abspath(path)
        if path in self._stack:
            chain = " -> ".join(self._stack + [path])
            raise FileListError("file list includes itself: %s" % chain)
        if not os.path.isfile(path):
            raise FileListError("file list not found: %s" % path)
        here = os.path.dirname(path)
        if base is None:
            base = here if self.relative_to == "file" else os.getcwd()
        self._stack.append(path)
        try:
            with open(path) as f:
                tokens = list(self._tokens(f.read()))
            i = 0
            while i < len(tokens):
                no, tok = tokens[i]
                where = "%s:%d" % (path, no)

                def arg():
                    if i + 1 >= len(tokens):
                        raise FileListError("%s: %s needs an argument" % (where, tok))
                    return tokens[i + 1][1]

                if tok in ("-f", "-F"):
                    nested = self._path(arg(), here if tok == "-F" else base, where, kind="file list")
                    nested_base = os.path.dirname(nested) if self.relative_to == "file" else base
                    self.parse(nested, nested_base)
                    i += 2
                    continue
                if tok == "-I" or tok == "-D" or tok in ("-v", "-y"):
                    value = arg()
                    i += 2
                elif tok.startswith("-I") or tok.startswith("-D"):
                    value = tok[2:]
                    tok = tok[:2]
                    i += 1
                else:
                    value = None
                    i += 1

                if tok == "-I" or tok.startswith("+incdir+"):
                    dirs = [value] if tok == "-I" else tok[len("+incdir+"):].split("+")
                    for d in filter(None, dirs):
                        self._add(self.incdirs, self._path(d, base, where, kind="include dir"))
                elif tok == "-D" or tok.startswith("+define+"):
                    defs = [value] if tok == "-D" else tok[len("+define+"):].split("+")
                    for d in filter(None, defs):
                        self._add(self.defines, self._expand(d, where))
                elif tok == "-v":
                    p = self._path(value, base, where, kind="library file")
                    self.options += ["-v", p]
                    self.warnings.append("%s: -v %s is a library file; Yosys and cocotb will not see it" % (where, p))
                elif tok == "-y":
                    p = self._path(value, base, where, kind="library dir")
                    self.options += ["-y", p]
                    self.warnings.append("%s: -y %s is a library dir; Yosys and cocotb will not see it" % (where, p))
                elif tok.startswith("-") or tok.startswith("+"):
                    self.options.append(self._expand(tok, where))
                    self.warnings.append("%s: option %s is passed to the simulator only" % (where, tok))
                else:
                    self._add(self.sources, self._path(tok, base, where))
        finally:
            self._stack.pop()
        return self

    # -- outputs -----------------------------------------------------------
    def flat(self):
        lines = ["// Generated by scripts/filelist.py - do not edit"]
        lines += ["+incdir+%s" % d for d in self.incdirs]
        lines += ["+define+%s" % d for d in self.defines]
        lines += self.options
        lines += self.sources
        return "\n".join(lines) + "\n"

    def yosys(self):
        return " ".join(["-D%s" % d for d in self.defines] + ["-I%s" % d for d in self.incdirs])

    def cocotb_mk(self):
        return "\n".join([
            "# Generated by scripts/filelist.py - do not edit",
            "VERILOG_SOURCES := %s" % " ".join(self.sources),
            "VERILOG_INCLUDE_DIRS := %s" % " ".join(self.incdirs),
            "COMPILE_ARGS += %s" % " ".join("+define+%s" % d for d in self.defines),
        ]) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filelists", nargs="+", help=".f files (combined in order)")
    ap.add_argument("--out", help="output prefix (writes PREFIX.f, .sources, .yosys, .cocotb.mk)")
    ap.add_argument("--relative-to", choices=["file", "cwd"], default="file")
    ap.add_argument("--quiet", action="store_true", help="do not print warnings")
    args = ap.parse_args(argv)

    fl = FileList(args.relative_to)
    try:
        for f in args.filelists:
            fl.parse(f)
        if not fl.sources:
            raise FileListError("no source files found in %s" % " ".join(args.filelists))
    except FileListError as e:
        sys.stderr.write("filelist error: %s\n" % e)
        return 2

    if not args.quiet:
        for w in fl.warnings:
            sys.stderr.write("filelist warning: %s\n" % w)
    if args.out:
        d = os.path.dirname(args.out)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        outputs = {
            ".f": fl.flat(),
            ".sources": "\n".join(fl.sources) + "\n",
            ".yosys": fl.yosys() + "\n",
            ".cocotb.mk": fl.cocotb_mk(),
        }
        for ext, text in outputs.items():
            with open(args.out + ext, "w") as f:
                f.write(text)
    else:
        sys.stdout.write(fl.flat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
