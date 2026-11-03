#!/bin/bash
# 駅探の「当日」停留所別時刻表から1日分のダイヤを取り込む。
# 使い方: tools/ekitan/run.sh <service_id: weekday|saturday|holiday> [作業ディレクトリ]
# 取得されるダイヤは実行日(JST)のもの。平日は平日に、土曜は土曜に、日祝は日祝に実行すること。
set -euo pipefail
SERVICE="$1"
WORK="${2:-/tmp/ekitan_work}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATE="$(TZ=Asia/Tokyo date +%Y%m%d)"
mkdir -p "$WORK"
[ -f "$WORK/busstops.json" ] || cp "$REPO/tools/ekitan/busstops.json" "$WORK/"
python3 -I "$REPO/tools/ekitan/crawl_tt.py" "$WORK" "$DATE" 3
python3 -I "$REPO/tools/ekitan/parse_tt.py" "$WORK" "$DATE"
python3 -I "$REPO/tools/ekitan/assemble.py" "$WORK" "$DATE" "$SERVICE" "$REPO"
python3 "$REPO/scripts/build_gtfs.py"
