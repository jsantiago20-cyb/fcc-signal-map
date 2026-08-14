"""Rewrite every non-ASCII character inside template.html's <script> block as a
\\uXXXX escape, so the page renders correctly even when it is served without an
explicit charset. HTML text outside the script must already use entities.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "template.html")

src = open(path, encoding="utf-8").read()
i, j = src.index("<script>"), src.index("</script>")
head, body, tail = src[:i], src[i:j], src[j:]

escaped = re.sub(r"[^\x00-\x7f]", lambda m: "\\u%04x" % ord(m.group(0)), body)
n_body = sum(1 for c in body if ord(c) > 127)
n_out = sum(1 for c in head + tail if ord(c) > 127)

open(path, "w", encoding="utf-8").write(head + escaped + tail)
print(f"escaped {n_body} characters inside <script>")
if n_out:
    print(f"WARNING: {n_out} non-ASCII characters outside the script block - "
          f"convert those to HTML entities")
else:
    print("no non-ASCII outside the script block")
