"""Parse ekitan busstop pages -> busstops.json {id: {name, lines: {line_id: [route_label,...]}}}"""
import glob, html, json, os, re, sys, unicodedata

D = sys.argv[1]
out = {}
for f in glob.glob(os.path.join(D, "bs", "*.html")):
    t = open(f, encoding="utf-8", errors="replace").read()
    m = re.search(r"<title>阪神バス「(.+?)」のバス時刻表", t)
    if not m:
        continue
    sid = os.path.basename(f)[:-5]
    lines = {}
    for li in re.findall(r"<li>\s*<span class=\"bus-route\">(.*?)</span>\s*<span class=\"destination-col\">(.*?)</span>.*?href=\"/timetable/route-bus/company/5160/\d+/(\d+)/d(\d+)\"", t, re.S):
        route, dest, line, d = li
        route = unicodedata.normalize("NFKC", html.unescape(route)).replace("−", "-").strip()
        lines.setdefault(line, {"route": route, "dirs": {}})["dirs"][d] = html.unescape(dest).strip()
    out[sid] = {"name": html.unescape(m.group(1)), "lines": lines}
json.dump(out, open(os.path.join(D, "busstops.json"), "w"), ensure_ascii=False, indent=0)
print(len(out))
