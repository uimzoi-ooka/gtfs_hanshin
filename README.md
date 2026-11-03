# 阪神バス 尼崎市内線 GTFS

阪神バス（尼崎市内線：幹線・地域線 全42系統）のGTFSを生成するためのデータとスクリプトです。

## 現状

| ファイル | 状態 |
|---|---|
| feed_info.txt | 作成済み（株式会社AMANE / 2024-04-01〜2028-03-31 / version 2026.10） |
| agency.txt | 作成済み（agency001_hanshinbus / 阪神バス株式会社） |
| stops.txt | 作成済み（停留所CSVのうち尼崎市内線が通る232標柱） |
| routes.txt | 作成済み（42系統。route_long_name は未設定） |
| calendar.txt | 作成済み（平日 / 土曜 / 日祝の3種類） |
| calendar_dates.txt | 作成済み（祝日を日祝ダイヤに振替） |
| trips.txt / stop_times.txt | **未作成**（時刻表の投入待ち） |

## ビルド

```bash
python3 scripts/build_gtfs.py
```

`dist/` に各 .txt と `hanshin_amagasaki_gtfs.zip` が出力されます。外部ライブラリは不要です。

## 入力データ（data/）

- `stops_source.csv` … 停留所エクセル（CSV）。stop_id は尼崎市内線が通る行を上から順に `S001`… と採番します。
- `routes.csv` … 系統一覧。`source_label` は停留所CSVの routes 列の表記です。
- `calendar.csv` … `holiday_service` 列に、祝日にその曜日のダイヤの代わりに走らせる service_id を書きます。
- `timetables/index.csv` … 時刻表ファイルの一覧です。

  ```
  file,route_short_name,direction_id,service_id,trip_headsign
  12_0_weekday.csv,12,0,weekday,阪神尼崎行
  ```

- `timetables/<file>.csv` … 経路順の停留所×便の時刻表です（`TEMPLATE.csv.example` を参照）。
  - 1行目は `stop_name,便1,便2,...` です。
  - 任意の `_headsign` 行で、便ごとに行先を上書きできます。
  - 時刻が空欄の停留所は、その便では停車しない扱いになります。
  - 同名の標柱が複数ある停留所（東園田8丁目、城ノ堀、小田南生涯学習プラザ前）は、系統から自動判別します。判別できない場合は `城ノ堀#S087` のように stop_id を指定してください。
