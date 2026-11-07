"""Parse timetable pages of one date -> events.json: list of {tx, stop, line, time, dest, d}"""
import glob, html, json, os, re, sys

D, DATE = sys.argv[1], sys.argv[2]
ev = {}
LI = re.compile(r'data-dest="([^"]*)">\s*<a href="/timetable/route-bus/bus\?tx=([^&]+)&amp;sf=(\d+)&amp;dw=[^&]*&amp;dt=(\d+)&amp;departure=(\d{3,4})&amp;SFF=(\d+)&amp;d=(\d+)"')
for f in glob.glob(os.path.join(D, "tt", DATE, "*.html")):
    t = open(f, encoding="utf-8", errors="replace").read()
    for dest, tx, sf, dt, dep, line, d in LI.findall(t):
        if dt != DATE:
            continue
        dep = dep.zfill(4)
        ev[(tx, sf, dep)] = {"tx": tx, "stop": sf, "line": line, "time": f"{dep[:2]}:{dep[2:]}",
                        "dest": html.unescape(dest), "d": d}
json.dump(list(ev.values()), open(os.path.join(D, f"events_{DATE}.json"), "w"), ensure_ascii=False)
print(len(ev), "events", len({e['tx'] for e in ev.values()}), "trips")
