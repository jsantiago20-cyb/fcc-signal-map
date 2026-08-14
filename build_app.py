"""Concatenate app_head.html + app_body.html into index.html.

Non-ASCII inside the <script> block is rewritten as \\uXXXX so the page renders
correctly however it is served; anything outside the script must use entities.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

head = open(os.path.join(HERE, "app_head.html"), encoding="utf-8").read()
body = open(os.path.join(HERE, "app_body.html"), encoding="utf-8").read()
html = head.rstrip() + "\n\n" + body

i, j = html.index("<script>"), html.index("</script>")
pre, js, post = html[:i], html[i:j], html[j:]
js = re.sub(r"[^\x00-\x7f]", lambda m: "\\u%04x" % ord(m.group(0)), js)
outside = sum(1 for c in pre + post if ord(c) > 127)

out = os.path.join(HERE, "index.html")
open(out, "w", encoding="utf-8").write(pre + js + post)
print("built index.html  {:,} bytes{}".format(
    os.path.getsize(out),
    "  WARNING: {} non-ASCII outside <script>".format(outside) if outside else "  (pure ASCII)"))
