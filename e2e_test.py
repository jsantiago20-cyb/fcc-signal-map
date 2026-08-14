"""End-to-end test of the deployed map: real mouse/keyboard events, live URL."""
import base64, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome

URL = "https://jsantiago20-cyb.github.io/fcc-signal-map/"
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews")
os.makedirs(SHOTS, exist_ok=True)

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(detail)) if detail else ""))


def flat(s):
    return " ".join(x.strip() for x in (s or "").splitlines() if x.strip())


def mouse(ch, kind, x, y, btn="left", clicks=1):
    ch.cmd("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y,
                                        "button": btn if kind != "mouseMoved" else "none",
                                        "buttons": 1 if kind == "mouseMoved" else 0,
                                        "clickCount": clicks})


def shot(ch, name):
    d = ch.cmd("Page.captureScreenshot", {"format": "png"})
    p = os.path.join(SHOTS, name)
    open(p, "wb").write(base64.b64decode(d["data"]))
    return p


ch = Chrome(port=9700, profile=os.path.join(tempfile.gettempdir(), "nbm_e2e"))
try:
    ch.cmd("Emulation.setDeviceMetricsOverride",
           {"width": 1500, "height": 1150, "deviceScaleFactor": 1, "mobile": False})
    print("loading", URL)
    ch.navigate(URL, settle=12)

    # ---------------------------------------------------------------- 1. load
    title = ch.eval("document.title")
    hexes = ch.eval("document.querySelectorAll('#hexes use').length")
    roads = ch.eval("document.getElementById('l-hw0').children.length + "
                    "document.getElementById('l-hw1').children.length")
    trails = ch.eval("document.getElementById('l-trmaj').children.length + "
                     "document.getElementById('l-trmin').children.length")
    check("page loads with correct title", title == "Custer County Signal Map", title)
    check("coverage hexes rendered", hexes == 1459, hexes)
    check("OSM roads rendered", roads > 1000, roads)
    check("OSM trails rendered", trails > 2000, trails)
    check("terrain image inlined", ch.eval(
        "document.getElementById('terrain').getAttribute('href').slice(0,24)")
        .startswith("data:image/webp"))
    ch.eval("document.documentElement.setAttribute('data-theme','light')")
    time.sleep(.6)
    shot(ch, "e2e_1_loaded.png")

    # ------------------------------------------------- 2. coverage % up front
    stats = flat(ch.eval("document.getElementById('stats').innerText"))
    summary = flat(ch.eval("document.getElementById('readout').innerText"))
    check("survey coverage percentages shown", "%" in stats and "carrier" in stats, stats[:90])
    check("distribution breakdown shown", "%" in summary, summary[:80])

    # ------------------------------------------------------- 3. click a point
    r = ch.eval("(function(){var b=document.getElementById('map').getBoundingClientRect();"
                "return [b.left,b.top,b.width,b.height]})()")
    mx, my = r[0] + r[2] * 0.52, r[1] + r[3] * 0.46
    mouse(ch, "mouseMoved", mx, my)
    time.sleep(.4)
    mouse(ch, "mousePressed", mx, my)
    mouse(ch, "mouseReleased", mx, my)
    time.sleep(.6)
    head = ch.eval("document.getElementById('rt').textContent")
    body = flat(ch.eval("document.getElementById('readout').innerText"))
    check("clicking a hex pins a point", "Pinned" in head, head)
    check("pinned point lists carriers",
          all(c in body for c in ("AT&T", "T-Mobile", "Verizon", "Viaero")), body[:110])
    check("pinned point shows signal strengths", "-1" in body or "-9" in body, body[:130])
    check("pinned point shows a technology rating",
          any(t in body for t in ("4G LTE", "5G 7/1", "5G 35/3", "none")), body[:130])
    check("FCC deep link present",
          "broadbandmap.fcc.gov" in ch.eval(
              "(document.querySelector('.fcclink')||{}).href||''"))
    shot(ch, "e2e_2_pinned.png")

    # ------------------------------------------------------------- 4. panning
    vb0 = ch.eval("document.getElementById('map').getAttribute('viewBox')")
    mouse(ch, "mousePressed", mx, my)
    for i in range(1, 6):
        mouse(ch, "mouseMoved", mx - i * 22, my - i * 14)
        time.sleep(.05)
    mouse(ch, "mouseReleased", mx - 110, my - 70)
    time.sleep(.5)
    vb1 = ch.eval("document.getElementById('map').getAttribute('viewBox')")
    check("dragging pans the map", vb0 != vb1, vb1)

    # ------------------------------------------------------------- 5. zooming
    z0 = ch.eval("document.getElementById('zlvl').textContent")
    for _ in range(6):
        ch.cmd("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": mx, "y": my,
                                            "deltaX": 0, "deltaY": -120})
        time.sleep(.12)
    time.sleep(.5)
    z1 = ch.eval("document.getElementById('zlvl').textContent")
    check("scroll wheel zooms in", z0 != z1 and float(z1.rstrip("×")) > 1.0, z0 + " -> " + z1)
    upx = float(ch.eval("getComputedStyle(document.documentElement).getPropertyValue('--upx')"))
    check("line widths rescale with zoom", upx < 0.1, "--upx=" + str(upx))
    shot(ch, "e2e_3_zoomed.png")

    # ------------------------------------------- 6. coordinate entry (typed)
    for query, expect_in in [("38.1339, -105.4675", "mi from center"),
                             ("(38.2461363, -105.6641888)", "mi from center"),
                             ("38.25228°N 105.66813°W", "mi from center"),
                             ("N38 15 8.2 W105 40 5.3", "mi from center"),
                             ("39.7392, -104.9847", "beyond this")]:
        box = ch.eval("(function(){var b=document.getElementById('findbox')"
                      ".getBoundingClientRect();return [b.left+b.width/2,b.top+b.height/2]})()")
        mouse(ch, "mousePressed", box[0], box[1], clicks=1)
        mouse(ch, "mouseReleased", box[0], box[1], clicks=1)
        ch.eval("document.getElementById('findbox').select()")
        ch.cmd("Input.insertText", {"text": query})
        typed = ch.eval("document.getElementById('findbox').value")
        ch.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter",
                                          "code": "Enter", "windowsVirtualKeyCode": 13})
        ch.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter",
                                          "code": "Enter", "windowsVirtualKeyCode": 13})
        time.sleep(.6)
        msg = flat(ch.eval("document.getElementById('findmsg').textContent"))
        check("typed coordinate '" + query + "'", typed == query and expect_in in msg, msg)

    ch.eval("document.getElementById('findbox').select()")
    ch.cmd("Input.insertText", {"text": "38.1339, -105.4675"})
    ch.eval("document.getElementById('findgo').click()")
    time.sleep(.8)
    body = flat(ch.eval("document.getElementById('readout').innerText"))
    check("coordinate jump pins and reports a point",
          "Pinned" in ch.eval("document.getElementById('rt').textContent") and "AT&T" in body,
          body[:110])
    check("query crosshair drawn",
          ch.eval("document.getElementById('querymark').children.length") > 0)
    shot(ch, "e2e_4_coordjump.png")

    # -------------------------------------------------------- 7. view facets
    labels = ch.eval("Array.from(document.querySelectorAll('#viewseg button'))"
                     ".map(b=>b.textContent).join(',')")
    check("all six views present", labels.count(",") == 5, labels)
    ch.eval("document.querySelectorAll('#viewseg button')[1].click()")
    time.sleep(.5)
    leg = flat(ch.eval("document.getElementById('legend').innerText"))
    check("Best tech view relabels legend", "5G" in leg, leg[:80])
    ch.eval("document.querySelectorAll('#viewseg button')[2].click()")
    time.sleep(.5)
    check("per-carrier view selectable",
          ch.eval("document.querySelectorAll('#viewseg button')[2].getAttribute('aria-pressed')") == "true")
    ch.eval("document.querySelectorAll('#viewseg button')[0].click()")
    time.sleep(.4)

    # ------------------------------------------------------ 8. signal filter
    before = flat(ch.eval("document.getElementById('stats').innerText"))
    ch.eval("var s=document.getElementById('sig');s.value='-100';"
            "s.dispatchEvent(new Event('change'))")
    time.sleep(.7)
    after = flat(ch.eval("document.getElementById('stats').innerText"))
    check("signal filter changes coverage percentages", before != after,
          before[:26] + "  =>  " + after[:26])
    ch.eval("var s=document.getElementById('sig');s.value='-999';"
            "s.dispatchEvent(new Event('change'))")
    time.sleep(.5)

    # ------------------------------------------------------------ 9. layers
    ch.eval("var c=document.getElementById('l-trails');c.checked=false;"
            "c.dispatchEvent(new Event('change'))")
    time.sleep(.4)
    check("layer toggle hides trails",
          ch.eval("document.getElementById('l-trmin').style.display") == "none")
    ch.eval("var c=document.getElementById('l-trails');c.checked=true;"
            "c.dispatchEvent(new Event('change'))")
    time.sleep(.3)

    # ------------------------------------------------- 10. reset + coverage table
    ch.eval("document.getElementById('zrst').click()")
    time.sleep(.5)
    check("reset returns to full view",
          ch.eval("document.getElementById('zlvl').textContent").startswith("1.0"))
    ch.eval("document.querySelector('details').open=true")
    time.sleep(.4)
    tbl = flat(ch.eval("document.getElementById('fulltable').innerText"))
    check("coverage table populated", "%" in tbl and "AT&T" in tbl, tbl[:120])
    shot(ch, "e2e_5_table.png")

    # ------------------------------------------------------ 11. console clean
    check("no horizontal overflow",
          ch.eval("document.documentElement.scrollWidth <= window.innerWidth + 1"))

finally:
    ch.close()

print("\n%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    print("FAILED:", "; ".join(failed))
sys.exit(1 if failed else 0)
