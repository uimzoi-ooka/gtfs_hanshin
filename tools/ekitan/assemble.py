"""events_<DATE>.json + busstops.json -> repo data/timetables/*.csv (+ index rows) for one service_id.
usage: assemble.py <ekdir> <DATE> <service_id> <repo>"""
import csv, collections, itertools, json, math, os, re, statistics, sys, unicodedata

D, DATE, SERVICE, REPO = sys.argv[1:5]
bs = json.load(open(os.path.join(D, "busstops.json")))
events = json.load(open(os.path.join(D, f"events_{DATE}.json")))
CITY = re.compile(r"^(\d+(-\d+)?A?|AD\d+)$")


def norm(s):
    s = unicodedata.normalize("NFKC", s).replace("[", "(").replace("]", ")").replace(" ", "")
    s = s.replace("ケ", "ヶ").replace("ヵ", "ヶ")
    s = re.sub(r"\((尼崎市?|西宮市?|伊丹市?|宝塚市?)\)$", "", s)
    return ALIAS.get(s, s)


# ekitan name -> CSV name (表記ゆれ・改称). 系統と位置で照合済み
ALIAS = {
    "JR猪名寺(東口)": "JR猪名寺", "JR猪名寺(西口)": "JR猪名寺", "アミング潮江": "アミング潮江前", "園田学園大学": "園田学園女子大学",
    "時友": "時友(高架下)", "武庫小学校前": "武庫小学校", "竹谷小学校": "竹谷小学校前",
    "労災病院": "労災病院前", "昭和通8丁目": "昭和通八丁目", "稲葉荘1丁目": "稲葉荘一丁目",
    # 表記ゆれ (国土数値情報P11で同名停留所が同じ系統を持つことを確認)
    "武庫之郷": "武庫の郷", "武庫之荘西口": "武庫荘駅西口", "南武庫之荘7丁目": "南武庫荘七丁目",
    # 改称と推定 (国土数値情報P11(2022)の旧名・同一系統・前後停留所・位置が一致)
    "大庄北生涯学習プラザ前": "大島2丁目", "浜田町4丁目": "南警察署西分庁舎",
}


# ---- GTFS stops (same numbering as build_gtfs.py)
src = list(csv.DictReader(open(os.path.join(REPO, "data/stops_source.csv"), encoding="utf-8-sig")))
extra_path = os.path.join(REPO, "data/stops_extra.csv")
extra = list(csv.DictReader(open(extra_path, encoding="utf-8-sig"))) if os.path.exists(extra_path) else []
gstops = []
for r in src:
    labels = [l for l in r["routes"].split(";") if l.startswith("尼崎市内線")]
    if labels:
        gstops.append({"id": f"S{len(gstops) + 1:03d}", "name": r["stop_name"].strip(), "labels": labels,
                       "lat": float(r["lat"]), "lon": float(r["lon"])})
csv_by_norm = collections.defaultdict(list)
for g in gstops:
    csv_by_norm[norm(g["name"])].append(g)
# stops in the source CSV not served by 市内線 per CSV (still usable when ekitan says so)
other_src = {norm(r["stop_name"]): r for r in src}

line_route = {}
for s in bs.values():
    for l, v in s["lines"].items():
        line_route[l] = v["route"]
name_of = {sid: s["name"] for sid, s in bs.items()}
ek_by_norm = collections.defaultdict(list)
for sid, s in bs.items():
    ek_by_norm[norm(s["name"])].append(sid)

# ---- trips
trips = collections.defaultdict(list)
for e in events:
    if CITY.match(line_route.get(e["line"], "")):
        trips[e["tx"]].append(e)


def mins(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


seg = collections.defaultdict(list)
tripseq = {}
for tx, evs in trips.items():
    for e in evs:
        e["m"] = mins(e["time"])
    if max(e["m"] for e in evs) - min(e["m"] for e in evs) > 12 * 60:
        for e in evs:
            if e["m"] < 12 * 60:
                e["m"] += 24 * 60
    evs.sort(key=lambda e: e["m"])
    tripseq[tx] = evs
    for a, b in zip(evs, evs[1:]):
        seg[(a["stop"], b["stop"])].append(b["m"] - a["m"])

def ek_coord(sid):
    nm = norm(name_of.get(sid, ""))
    c = csv_by_norm.get(nm)
    if c:
        return c[0]["lat"], c[0]["lon"]
    r = other_src.get(nm)
    if r:
        return float(r["lat"]), float(r["lon"])
    r = extra_by_norm.get(nm)
    if r and r["lat"] and r["lon"]:
        return float(r["lat"]), float(r["lon"])
    return None


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.0, (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0])))


# 同じ「分」に並ぶ停留所の順序: 前後の停留所を含めた走行距離が最短になる順 (座標が無い時は他便での前後関係)
extra_by_norm = {norm(r["stop_name"]): r for r in extra}
prec = collections.Counter()
for evs in tripseq.values():
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            if b["m"] > a["m"]:
                prec[(a["line"], a["dest"], a["stop"], b["stop"])] += 1


def order_run(run, prev, nxt):
    if len(run) > 7:
        return run
    best, bestv = run, None
    for perm in itertools.permutations(run):
        chain = ([prev] if prev else []) + list(perm) + ([nxt] if nxt else [])
        cs = [ek_coord(e["stop"]) for e in chain]
        if all(cs):
            v = (0, sum(km(a, b) for a, b in zip(cs, cs[1:])))
        else:
            v = (1, -sum(prec[(e["line"], e["dest"], a["stop"], b["stop"])] for a, b in zip(perm, perm[1:])))
        if bestv is None or v < bestv:
            best, bestv = list(perm), v
    return best


for tx, evs in tripseq.items():
    out, i = [], 0
    while i < len(evs):
        j = i
        while j + 1 < len(evs) and evs[j + 1]["m"] == evs[i]["m"]:
            j += 1
        run = evs[i:j + 1]
        if len(run) > 1:
            e = run[0]
            run = order_run(run, out[-1] if out else None, evs[j + 1] if j + 1 < len(evs) else None)
        out.extend(run)
        i = j + 1
    tripseq[tx] = out

seg = collections.defaultdict(list)
for evs in tripseq.values():
    for a, b in zip(evs, evs[1:]):
        seg[(a["stop"], b["stop"])].append(b["m"] - a["m"])


def est_minutes(a, b):
    """終点到着の所要分を推定: ①同区間の実績 ②距離 (直線×1.3, 時速15km) ③逆方向の実績 (距離推定と大差ない場合のみ) ④2分"""
    if seg.get((a, b)):
        return max(1, round(statistics.median(seg[(a, b)]))), "segment"
    ca, cb = ek_coord(a), ek_coord(b)
    dist = max(1, round(km(ca, cb) * 1.3 / 15 * 60)) if ca and cb else None
    if seg.get((b, a)):
        rev = max(1, round(statistics.median(seg[(b, a)])))
        if dist is None or abs(rev - dist) <= max(2, dist):
            return rev, "reverse"
    if dist is not None:
        return dist, "distance"
    return 2, "default"


report = collections.Counter()
unknown_dest = collections.Counter()
for tx, evs in tripseq.items():
    dest = evs[-1]["dest"]
    dname = norm(re.sub(r"行き?$", "", dest))
    cands = ek_by_norm.get(dname, [])
    line = evs[0]["line"]
    cands = [c for c in cands if line in bs[c]["lines"]] or cands
    if not cands and dname in csv_by_norm:  # 降車専用の終点 (駅探に時刻表ページが無い)
        pid = "CSV:" + csv_by_norm[dname][0]["name"]
        name_of[pid] = csv_by_norm[dname][0]["name"]
        cands = [pid]
    if not cands:
        unknown_dest[dest] += 1
        continue
    term = cands[0]
    if evs[-1]["stop"] == term:
        continue
    m, how = est_minutes(evs[-1]["stop"], term)
    report[how] += 1
    evs.append({"tx": tx, "stop": term, "line": line, "m": evs[-1]["m"] + m, "dest": dest, "est": how})


# ---- map ekitan stop -> GTFS stop key "name#Sxxx"
route_label = lambda r: [l for l in set(sum((g["labels"] for g in gstops), [])) if re.search(rf"(幹線|地域線){re.escape(r)}番", l) or (r in ("13", "13-2") and "13番・13-2番" in l)]
missing = collections.Counter()


def gkey(sid, route):
    nm = name_of.get(sid, sid)
    c = csv_by_norm.get(norm(nm) + f"({route}系統)") or csv_by_norm.get(norm(nm))
    if not c:
        missing[nm] += 1
        return nm  # resolved via stops_extra.csv
    if len(c) > 1:
        labels = route_label(route)
        c2 = [g for g in c if any(l in g["labels"] for l in labels)]
        c = c2 or c
    return f"{c[0]['name']}#{c[0]['id']}"


# ---- group by route, assign direction, merge patterns
by_route = collections.defaultdict(list)
for tx, evs in tripseq.items():
    by_route[line_route[evs[0]["line"]]].append(tx)


def lcs_merge(base, seq):
    n, m = len(base), len(seq)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if base[i] == seq[j] else max(dp[i + 1][j], dp[i][j + 1])
    out, i, j = [], 0, 0
    while i < n or j < m:
        if i < n and j < m and base[i] == seq[j]:
            out.append(base[i]); i += 1; j += 1
        elif j >= m or (i < n and dp[i + 1][j] >= dp[i][j + 1]):
            out.append(base[i]); i += 1
        else:
            out.append(seq[j]); j += 1
    return out


def align(rows, seq):
    """positions of seq inside rows (rows is a supersequence)."""
    pos, i = [], 0
    for s in seq:
        while rows[i] != s:
            i += 1
        pos.append(i); i += 1
    return pos


tt_dir = os.path.join(REPO, "data/timetables")
index_rows = []
for route, txs in sorted(by_route.items()):
    seqs = {tx: [gkey(e["stop"], route) for e in tripseq[tx]] for tx in txs}
    ref = max(txs, key=lambda t: len(seqs[t]))
    refpos = {}
    for i, k in enumerate(seqs[ref]):
        refpos.setdefault(k, i)
    groups = collections.defaultdict(list)
    for tx in txs:
        p = [refpos[k] for k in dict.fromkeys(seqs[tx]) if k in refpos]
        fwd = sum(1 for a, b in zip(p, p[1:]) if b > a)
        bwd = sum(1 for a, b in zip(p, p[1:]) if b < a)
        groups[0 if fwd >= bwd else 1].append(tx)
    for direction, gtx in sorted(groups.items()):
        gtx.sort(key=lambda t: tripseq[t][0]["m"])
        rows = []
        for tx in sorted(gtx, key=lambda t: -len(seqs[t])):
            rows = lcs_merge(rows, seqs[tx])
        fname = f"{route}_{direction}_{SERVICE}.csv"
        grid = [[r] + [""] * len(gtx) for r in rows]
        heads = []
        for c, tx in enumerate(gtx):
            for p, e in zip(align(rows, seqs[tx]), tripseq[tx]):
                h, m = divmod(e["m"], 60)
                grid[p][c + 1] = f"{h:02d}:{m:02d}" + ("*" if e.get("est") else "")
            heads.append(re.sub(r"行き?$", "", tripseq[tx][-1]["dest"]))
        common = collections.Counter(heads).most_common(1)[0][0]
        with open(os.path.join(tt_dir, fname), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["stop_name"] + [str(i + 1) for i in range(len(gtx))])
            w.writerow(["_headsign"] + [h if h != common else "" for h in heads])
            w.writerows(grid)
        index_rows.append([fname, route, direction, SERVICE, common])

idx = os.path.join(tt_dir, "index.csv")
old = [r for r in csv.reader(open(idx, encoding="utf-8"))][1:] if os.path.exists(idx) else []
old = [r for r in old if r[3] != SERVICE]
with open(idx, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["file", "route_short_name", "direction_id", "service_id", "trip_headsign"])
    w.writerows(sorted(old + index_rows))
print("trips", len(tripseq), "files", len(index_rows), "terminal-est", dict(report))
print("unknown dest", dict(unknown_dest))
print("stops not in CSV", dict(missing))
