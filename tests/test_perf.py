from __future__ import annotations

import time

import pytest

from archdiag.cli import main

REPOS, COBOL, JCL, JAVA = 50, 30, 20, 10


def _make_estate(root):
    for r in range(REPOS):
        repo = root / ("repo%02d" % r)
        (repo / ".git").mkdir(parents=True)
        nxt = (r + 1) % REPOS
        for i in range(COBOL):
            body = [
                "       IDENTIFICATION DIVISION.",
                "       PROGRAM-ID. P%02d%03d." % (r, i),
                "       PROCEDURE DIVISION.",
            ]
            for k in range(40):
                body.append("           MOVE A%d TO B%d." % (k, k))
            body.append("           CALL 'P%02d%03d'." % (r, (i + 1) % COBOL))
            body.append("           CALL 'P%02d%03d'." % (nxt, i))
            body.append("           EXEC SQL SELECT A FROM T%02d.TAB%d END-EXEC." % (r, i % 5))
            body.append("           STOP RUN.")
            (repo / ("P%02d%03d.cbl" % (r, i))).write_text("\n".join(body) + "\n", encoding="utf-8")
        for i in range(JCL):
            jcl = [
                "//J%02d%03d JOB (ACCT),'X',CLASS=A" % (r, i),
                "//S1 EXEC PGM=P%02d%03d" % (r, i),
                "//IN DD DSN=PROD.R%02d.DATA%d,DISP=SHR" % (r, i % 7),
                "//OUT DD DSN=PROD.R%02d.OUT%d,DISP=(NEW,CATLG)" % (nxt, i % 7),
                "//S2 EXEC PGM=P%02d%03d" % (nxt, i),
            ]
            (repo / ("J%02d%03d.jcl" % (r, i))).write_text("\n".join(jcl) + "\n", encoding="utf-8")
        for i in range(JAVA):
            java = [
                "package com.x.r%02d;" % r,
                "import org.springframework.web.bind.annotation.*;",
                "@RestController",
                "public class Svc%d {" % i,
                '  @GetMapping("/r%02d/item%d")' % (r, i),
                "  public String get() { return \"x\"; }",
                "}",
            ]
            (repo / ("Svc%d.java" % i)).write_text("\n".join(java) + "\n", encoding="utf-8")


@pytest.mark.slow
def test_large_estate_under_120s(tmp_path, capsys):
    _make_estate(tmp_path)
    t0 = time.time()
    assert main(["scan", "--workspace", str(tmp_path)]) == 0
    assert main(["draw", "--workspace", str(tmp_path), "--level", "landscape"]) == 0
    elapsed = time.time() - t0
    out = capsys.readouterr().out
    assert elapsed < 120, "took %.1fs" % elapsed
    import re
    n = int(re.search(r"Summary: (\d+) nodes", out).group(1))
    assert n <= 40
