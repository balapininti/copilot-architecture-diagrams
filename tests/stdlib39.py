"""The top-level module names of the Python 3.9 standard library, fixed (not derived at run time,
so the 'stdlib only' test means the same on every Python).

Built from the macOS system Python 3.9.6 (every module in its stdlib folder, lib-dynload and
sys.builtin_module_names) joined with the 3.14 ``sys.stdlib_module_names`` ones that also exist
in 3.9, plus four public 3.9 modules neither source has (taken from the 3.9 module index):
msilib (Windows only), spwd and ossaudiodev (Linux only; both removed in 3.13) and xxlimited
(the limited-API example module). Left out because they are newer than 3.9: tomllib (3.11), annotationlib and compression
(3.14), and every private module added after 3.9 (_colorize, _pyrepl, _zstd and the like).
Kept although later removed: asyncore, asynchat, imp, distutils, smtpd, binhex, formatter,
cgi, cgitb, telnetlib and the other "dead batteries" removed in 3.10 to 3.13. Windows-only
modules (msvcrt, winreg, winsound, nt, _winapi, _overlapped) are kept: the clients run on Windows.
Only public names plus __future__, __main__, _thread and _winapi are listed; no other private
module is a legitimate import for this package.
"""

STDLIB_39 = frozenset([
    "__future__", "__main__", "_thread", "_winapi", "abc", "aifc", "antigravity", "argparse",
    "array", "ast", "asynchat", "asyncio", "asyncore", "atexit", "audioop", "base64", "bdb",
    "binascii", "binhex", "bisect", "builtins", "bz2", "cProfile", "calendar", "cgi", "cgitb",
    "chunk", "cmath", "cmd", "code", "codecs", "codeop", "collections", "colorsys",
    "compileall", "concurrent", "configparser", "contextlib", "contextvars", "copy", "copyreg",
    "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
    "dis", "distutils", "doctest", "email", "encodings", "ensurepip", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "formatter", "fractions",
    "ftplib", "functools", "gc", "genericpath", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib",
    "imghdr", "imp", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox", "mailcap", "marshal",
    "math", "mimetypes", "mmap", "modulefinder", "msilib", "msvcrt", "multiprocessing", "netrc", "nis",
    "nntplib", "nt", "ntpath", "nturl2path", "numbers", "opcode", "operator", "optparse", "os",
    "ossaudiodev",
    "parser", "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd",
    "py_compile", "pyclbr", "pydoc", "pydoc_data", "pyexpat", "queue", "quopri", "random", "re",
    "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
    "socket", "socketserver", "spwd", "sqlite3", "sre_compile", "sre_constants", "sre_parse", "ssl",
    "stat", "statistics", "string", "stringprep", "struct", "subprocess", "sunau", "symbol",
    "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
    "termios", "textwrap", "this", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "unicodedata", "unittest", "urllib", "uu", "uuid", "venv", "warnings", "wave",
    "weakref", "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc", "xxlimited",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo"
])
