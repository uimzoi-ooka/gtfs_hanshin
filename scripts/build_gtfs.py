#!/usr/bin/env python3
"""阪神バス 尼崎市内線 GTFS ビルドスクリプト.

入力 (data/):
  feed_info.csv, agency.csv          GTFS形式そのまま
  stops_source.csv                   停留所エクセル(CSV)。尼崎市内線が通る停留所を抽出
  routes.csv                         系統一覧 (route_id, route_short_name, ...)
  calendar.csv                       運行日。holiday_service 列 = 祝日に振り替える service_id
  timetables/index.csv               時刻表ファイルの一覧
      file,route_short_name,direction_id,service_id,trip_headsign
  timetables/<file>.csv              1行目: stop_name,便1,便2,...
                                     (任意) _headsign 行: 便ごとの行先上書き
                                     以降: 経路順の停留所名と HH:MM (空欄=通過/非経由)
                                     同名で標柱が複数ある停留所は "名前#S012" で stop_id を指定

出力: dist/*.txt と dist/hanshin_amagasaki_gtfs.zip
使い方: python3 scripts/build_gtfs.py
"""
import csv
import datetime as dt
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")
ROUTE_PREFIX = "尼崎市内線"


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_txt(name, fields, rows):
    with open(os.path.join(DIST, name), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(fields)
        for r in rows:
            w.writerow([r.get(k, "") for k in fields])


# ---------------------------------------------------------------- 祝日
def _equinox(year, spring):
    base, c = (20.8431, 0.242194) if spring else (23.2488, 0.242194)
    return int(base + c * (year - 1980) - int((year - 1980) / 4))


def _nth_monday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(7 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def japanese_holidays(year):
    """2020年以降の祝日法に基づく祝日・振替休日・国民の休日 (1980-2099年で有効)."""
    h = {
        dt.date(year, 1, 1), dt.date(year, 2, 11), dt.date(year, 2, 23),
        dt.date(year, 3, _equinox(year, True)), dt.date(year, 4, 29),
        dt.date(year, 5, 3), dt.date(year, 5, 4), dt.date(year, 5, 5),
        dt.date(year, 8, 11), dt.date(year, 9, _equinox(year, False)),
        dt.date(year, 11, 3), dt.date(year, 11, 23),
        _nth_monday(year, 1, 2), _nth_monday(year, 7, 3),
        _nth_monday(year, 9, 3), _nth_monday(year, 10, 2),
    }
    # 国民の休日 (祝日に挟まれた平日)
    for d in sorted(h):
        mid = d + dt.timedelta(days=1)
        if mid not in h and mid + dt.timedelta(days=1) in h and mid.weekday() != 6:
            h.add(mid)
    # 振替休日
    for d in sorted(h):
        if d.weekday() == 6:
            s = d + dt.timedelta(days=1)
            while s in h:
                s += dt.timedelta(days=1)
            h.add(s)
    return h


# ---------------------------------------------------------------- 時刻
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def norm_time(s):
    m = TIME_RE.match(s.strip())
    if not m:
        raise ValueError(f"時刻の形式が不正です: {s!r}")
    return f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or '00'}"


def secs(t):
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s


def main():
    os.makedirs(DIST, exist_ok=True)
    errors, warnings = [], []

    feed_info = read_csv(os.path.join(DATA, "feed_info.csv"))
    agency = read_csv(os.path.join(DATA, "agency.csv"))
    agency_id = agency[0]["agency_id"]
    routes = read_csv(os.path.join(DATA, "routes.csv"))
    calendar = read_csv(os.path.join(DATA, "calendar.csv"))

    # stops: 尼崎市内線が通る停留所のみ。ID は元CSVの行順で採番 (元CSVが変わらない限り不変)
    src = read_csv(os.path.join(DATA, "stops_source.csv"))
    stops = []
    for r in src:
        labels = [l for l in r["routes"].split(";") if l.startswith(ROUTE_PREFIX)]
        if not labels:
            continue
        stops.append({
            "stop_id": f"S{len(stops) + 1:03d}",
            "stop_name": r["stop_name"].strip(),
            "stop_lat": r["lat"].strip(),
            "stop_lon": r["lon"].strip(),
            "zone_id": "",
            "stop_desc": "",
            "_labels": labels,
        })
    by_name = {}
    for s in stops:
        by_name.setdefault(s["stop_name"], []).append(s)
    by_id = {s["stop_id"]: s for s in stops}
    route_by_short = {r["route_short_name"]: r for r in routes}

    def resolve_stop(cell, route):
        name, _, sid = cell.partition("#")
        name, sid = name.strip(), sid.strip()
        if sid:
            if sid not in by_id:
                raise ValueError(f"stop_id {sid} がありません")
            return sid
        cands = by_name.get(name)
        if not cands:
            raise ValueError(f"停留所 {name!r} が停留所データにありません")
        if len(cands) > 1:
            label = route["source_label"]
            cands = [c for c in cands if label in c["_labels"]] or cands
        if len(cands) > 1:
            ids = ", ".join(c["stop_id"] for c in cands)
            raise ValueError(f"停留所 {name!r} は標柱が複数あります ({ids})。'{name}#S000' 形式で指定してください")
        return cands[0]["stop_id"]

    # calendar_dates: 祝日 → holiday_service へ振替
    service_ids = {c["service_id"] for c in calendar}
    cal_dates = []
    wd_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for c in calendar:
        alt = c.get("holiday_service", "").strip()
        if not alt:
            continue
        if alt not in service_ids:
            errors.append(f"calendar.csv: holiday_service {alt} が未定義")
            continue
        start = dt.datetime.strptime(c["start_date"], "%Y%m%d").date()
        end = dt.datetime.strptime(c["end_date"], "%Y%m%d").date()
        hol = set()
        for y in range(start.year, end.year + 1):
            hol |= japanese_holidays(y)
        for d in sorted(hol):
            if start <= d <= end and c[wd_cols[d.weekday()]] == "1":
                ds = d.strftime("%Y%m%d")
                cal_dates.append({"service_id": c["service_id"], "date": ds, "exception_type": "2"})
                cal_dates.append({"service_id": alt, "date": ds, "exception_type": "1"})
    cal_dates.sort(key=lambda r: (r["date"], r["exception_type"]))

    # trips / stop_times
    trips, stop_times = [], []
    index = read_csv(os.path.join(DATA, "timetables", "index.csv"))
    for ent in index:
        fname = ent["file"].strip()
        where = f"timetables/{fname}"
        route = route_by_short.get(ent["route_short_name"].strip())
        if not route:
            errors.append(f"{where}: 系統 {ent['route_short_name']} が routes.csv にありません")
            continue
        if ent["service_id"] not in service_ids:
            errors.append(f"{where}: service_id {ent['service_id']} が calendar.csv にありません")
            continue
        with open(os.path.join(DATA, "timetables", fname), encoding="utf-8-sig", newline="") as f:
            grid = [row for row in csv.reader(f) if any(c.strip() for c in row)]
        header, body = grid[0], grid[1:]
        ntrips = len(header) - 1
        headsigns = [ent["trip_headsign"].strip()] * ntrips
        if body and body[0][0].strip() == "_headsign":
            for i, v in enumerate(body[0][1:ntrips + 1]):
                if v.strip():
                    headsigns[i] = v.strip()
            body = body[1:]
        try:
            stop_ids = [resolve_stop(row[0], route) for row in body]
        except ValueError as e:
            errors.append(f"{where}: {e}")
            continue
        base = os.path.splitext(fname)[0]
        for t in range(ntrips):
            trip_id = f"{base}_{header[t + 1].strip() or t + 1}"
            seq, prev = 0, None
            rows = []
            for r_i, row in enumerate(body):
                cell = row[t + 1].strip() if t + 1 < len(row) else ""
                if not cell:
                    continue
                try:
                    tm = norm_time(cell)
                except ValueError as e:
                    errors.append(f"{where} 便{t + 1} {row[0]}: {e}")
                    continue
                if prev is not None and secs(tm) < secs(prev):
                    errors.append(f"{where} 便{t + 1} {row[0]}: 時刻が前の停留所より早い ({prev} → {tm})")
                prev = tm
                seq += 1
                rows.append({"trip_id": trip_id, "arrival_time": tm, "departure_time": tm,
                             "stop_id": stop_ids[r_i], "stop_sequence": seq})
            if len(rows) < 2:
                warnings.append(f"{where} 便{t + 1}: 停車が2か所未満のため除外")
                continue
            trips.append({"route_id": route["route_id"], "service_id": ent["service_id"],
                          "trip_id": trip_id, "trip_headsign": headsigns[t],
                          "direction_id": ent["direction_id"].strip(), "shape_id": ""})
            stop_times.extend(rows)

    # 検証
    for s in stops:
        if not s["stop_lat"] or not s["stop_lon"]:
            errors.append(f"stops: {s['stop_name']} の緯度経度が空です")
    if not trips:
        warnings.append("時刻表が未投入のため trips.txt / stop_times.txt が空です (GTFSとしては未完成)")
    used_routes = {t["route_id"] for t in trips}
    if trips:
        missing = [r["route_short_name"] for r in routes if r["route_id"] not in used_routes]
        if missing:
            warnings.append("時刻表が無い系統: " + ", ".join(missing))

    # 出力
    write_txt("feed_info.txt", list(feed_info[0].keys()), feed_info)
    write_txt("agency.txt", list(agency[0].keys()), agency)
    write_txt("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon", "zone_id", "stop_desc"], stops)
    for r in routes:
        r["agency_id"] = agency_id
        r["route_type"] = "3"
    write_txt("routes.txt", ["route_id", "agency_id", "route_short_name", "route_long_name", "route_desc",
                             "route_type", "route_color", "route_text_color"], routes)
    write_txt("calendar.txt", ["service_id"] + wd_cols + ["start_date", "end_date"], calendar)
    write_txt("calendar_dates.txt", ["service_id", "date", "exception_type"], cal_dates)
    write_txt("trips.txt", ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"], trips)
    write_txt("stop_times.txt", ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"], stop_times)

    names = ["feed_info.txt", "agency.txt", "stops.txt", "routes.txt", "calendar.txt",
             "calendar_dates.txt", "trips.txt", "stop_times.txt"]
    with zipfile.ZipFile(os.path.join(DIST, "hanshin_amagasaki_gtfs.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.write(os.path.join(DIST, n), n)

    print(f"stops={len(stops)} routes={len(routes)} trips={len(trips)} "
          f"stop_times={len(stop_times)} calendar_dates={len(cal_dates)}")
    for w in warnings:
        print("WARN:", w)
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
