"""Fetch today's per-stop timetable page (robots-allowed, no query) for every (stop, 市内線 line).
usage: crawl_tt.py <ekdir> <YYYYMMDD expected JST date> [workers]"""
import json, os, re, subprocess, sys, time, threading, queue

D, DATE = sys.argv[1], sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 3
bs = json.load(open(os.path.join(D, "busstops.json")))
CITY = re.compile(r"^(\d+(-\d+)?A?|AD\d+)$")
out_dir = os.path.join(D, "tt", DATE)
os.makedirs(out_dir, exist_ok=True)
jobs = queue.Queue()
for sid, s in bs.items():
    for line, v in s["lines"].items():
        if CITY.match(v["route"]):
            jobs.put((sid, line, min(v["dirs"], key=int)))
total = jobs.qsize()
print("jobs", total, flush=True)
bad = []


def worker():
    while True:
        try:
            sid, line, d = jobs.get_nowait()
        except queue.Empty:
            return
        f = os.path.join(out_dir, f"{sid}_{line}.html")
        if not (os.path.exists(f) and os.path.getsize(f) > 10000):
            for attempt in range(3):
                subprocess.run(["curl", "-sS", "-m", "30", "-A", "Mozilla/5.0", "-o", f,
                                f"https://ekitan.com/timetable/route-bus/company/5160/{sid}/{line}/d{d}"])
                if os.path.exists(f) and os.path.getsize(f) > 10000:
                    break
                time.sleep(3)
            time.sleep(1)
        t = open(f, encoding="utf-8", errors="replace").read() if os.path.exists(f) else ""
        dts = set(re.findall(r"dt=(\d{8})", t))
        if dts and dts != {DATE}:
            bad.append((sid, line, sorted(dts)))


ths = [threading.Thread(target=worker) for _ in range(W)]
[t.start() for t in ths]
[t.join() for t in ths]
print("done", total, "date-mismatch", bad[:10], len(bad), flush=True)
