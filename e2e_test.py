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


def mouse(ch, kind, x, y, btn="left", clicks=1, buttons=None):
    if buttons is None:
        buttons = 1 if kind == "mousePressed" else 0
    ch.cmd("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": btn,
                                        "buttons": buttons,
                                        "clickCount": 0 if kind == "mouseMoved" else clicks})


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
    check("page title is Cellular Signal Map", title == "Cellular Signal Map", title)
    check("h1 is Cellular Signal Map",
          ch.eval("document.querySelector('h1').textContent") == "Cellular Signal Map")
    eyebrow = ch.eval("document.querySelector('.eyebrow').textContent")
    check("header eyebrow has no 'Replicated' and no dot",
          "Replicated" not in eyebrow and "·" not in eyebrow, eyebrow)
    check("coverage table open by default",
          ch.eval("document.getElementById('tabledetails').open") is True)
    check("survey list rendered",
          ch.eval("document.querySelectorAll('.spill').length") >= 1,
          ch.eval("Array.from(document.querySelectorAll('.spill')).map(b=>b.textContent).join(', ')"))
    check("coverage hexes rendered", hexes == 1459, hexes)
    roadpts = ch.eval("Array.from(document.querySelectorAll('#l-hw0 path,#l-hw1 path,#l-rd path'))"
                      ".reduce((n,p)=>n+p.getAttribute('d').split('L').length,0)")
    check("OSM roads rendered", roads > 10 and roadpts > 2000,
          str(roads) + " chained ways, " + str(roadpts) + " vertices")
    check("OSM trails rendered", trails > 500, trails)
    thref = ch.eval("document.getElementById('terrain').getAttribute('href')")
    check("terrain loaded from the survey pack",
          thref.startswith("surveys/") and thref.endswith("terrain.webp"), thref)
    check("terrain file actually fetches",
          ch.eval("fetch(document.getElementById('terrain').getAttribute('href'))"
                  ".then(r=>r.ok).catch(()=>false)") is True)
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

    # ------------------------------------------------------------- 4. zooming
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

    # ---- 5. panning. Only meaningful once zoomed: at 1x the whole circle is
    #        already in frame, so the view centre is clamped to the origin.
    vb_full = ch.eval("document.getElementById('map').getAttribute('viewBox')")
    ch.eval("document.getElementById('zrst').click()")
    time.sleep(.4)
    mouse(ch, "mousePressed", mx, my, buttons=1)
    mouse(ch, "mouseMoved", mx - 90, my - 60, buttons=1)
    mouse(ch, "mouseReleased", mx - 90, my - 60, buttons=0)
    time.sleep(.4)
    check("pan is clamped at 1x (whole circle already visible)",
          ch.eval("document.getElementById('map').getAttribute('viewBox')").startswith("-53"))
    for _ in range(6):
        ch.cmd("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": mx, "y": my,
                                            "deltaX": 0, "deltaY": -120})
        time.sleep(.12)
    time.sleep(.4)
    vb0 = ch.eval("document.getElementById('map').getAttribute('viewBox')")
    pin_before = ch.eval("(document.querySelector('#readout .coord')||{}).textContent||''")
    mouse(ch, "mousePressed", mx, my, buttons=1)
    for i in range(1, 9):
        mouse(ch, "mouseMoved", mx - i * 18, my - i * 11, buttons=1)
        time.sleep(.04)
    mouse(ch, "mouseReleased", mx - 144, my - 88, buttons=0)
    time.sleep(.5)
    vb1 = ch.eval("document.getElementById('map').getAttribute('viewBox')")
    check("dragging pans the map when zoomed", vb0 != vb1, vb1[:44])
    pin_after = ch.eval("(document.querySelector('#readout .coord')||{}).textContent||''")
    check("a drag does not change the pinned point", pin_before == pin_after,
          repr(pin_before) + " -> " + repr(pin_after))

    # ------------------------------------------- 6. coordinate entry (typed)
    for query, expect_in in [("38.1339, -105.4675", "mi from the centre"),
                             ("(38.2461363, -105.6641888)", "mi from the centre"),
                             ("38.25228°N 105.66813°W", "mi from the centre"),
                             ("N38 15 8.2 W105 40 5.3", "mi from the centre"),
                             ("39.0, -98.5", "no survey covers"),
                             ("51.5074, -0.1278", "outside the United States")]:
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

    # the out-of-survey state must offer a way to build one
    ch.eval("document.getElementById('findbox').select()")
    ch.cmd("Input.insertText", {"text": "39.0, -98.5"})       # central Kansas: US, unsurveyed
    ch.eval("document.getElementById('findgo').click()")
    time.sleep(.9)
    empty = flat(ch.eval("document.getElementById('state-empty').innerText"))
    check("out-of-survey US point explains and offers a build",
          "No survey covers" in empty and "nbm_site.py" in empty, empty[:120])
    check("build-on-Actions link present",
          "build-survey.yml" in ch.eval(
              "Array.from(document.querySelectorAll('#state-empty a')).map(a=>a.href).join(' ')"))

    ch.eval("document.getElementById('findbox').select()")
    ch.cmd("Input.insertText", {"text": "38.1339, -105.4675"})
    ch.eval("document.getElementById('findgo').click()")
    time.sleep(1.4)
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

    # ------------------------------------------- 12. switching to another survey
    pills = ch.eval("document.querySelectorAll('.spill').length")
    check("more than one survey published", pills >= 2, pills)
    if pills >= 2:
        before = ch.eval("Array.from(document.querySelectorAll('#viewseg button'))"
                         ".map(b=>b.textContent).join(',')")
        ch.eval("document.getElementById('findbox').value='39.7392, -104.9847'")
        ch.eval("document.getElementById('findgo').click()")
        time.sleep(3.0)
        msg = flat(ch.eval("document.getElementById('findmsg').textContent"))
        after = ch.eval("Array.from(document.querySelectorAll('#viewseg button'))"
                        ".map(b=>b.textContent).join(',')")
        check("a coordinate in another survey loads that survey",
              "Denver" in msg and ch.eval("document.querySelectorAll('#hexes use').length") > 0, msg)
        check("carrier list adapts to the new survey", before != after, after)
        check("new survey has its own stats",
              "%" in flat(ch.eval("document.getElementById('stats').innerText")))
        check("new survey terrain loads",
              ch.eval("fetch(document.getElementById('terrain').getAttribute('href'))"
                      ".then(r=>r.ok).catch(()=>false)") is True)
        shot(ch, "e2e_7_denver.png")

finally:
    ch.close()

print("\n%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    print("FAILED:", "; ".join(failed))
sys.exit(1 if failed else 0)
