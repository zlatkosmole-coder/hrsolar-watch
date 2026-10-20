"""When do HOPS's day-ahead solar forecast and the ENTSO-E day-ahead load forecast for tomorrow appear?

Runs on GitHub Actions every 15-30 minutes (.github/workflows/watch.yml). Each run logs in to the
ENTSO-E File Library (secrets ENTSOE_TP_USER / ENTSOE_TP_PASSWORD), downloads the current monthly
export of two items and counts the rows of tomorrow (local day, Europe/Zagreb):
  - GenerationForecastsForWindAndSolar_14.1.D_r3, HR, Solar, DayAheadGenerationForecast[MW]
  - DayAheadTotalLoadForecast_6.1.B_r3, HR and the coupled zones
One line per item and run goes to logs/<item>/<tomorrow>.txt; the first time HOPS's solar forecast is
complete its values are saved to logs/hops_solar_values/<tomorrow>_first_seen.csv, and the latest seen
values to <tomorrow>_latest.csv, so a later revision can be detected. The File Library is an export of
the Transparency Platform: the first run that sees a forecast gives an upper bound of its publication.
Copied from hrsolar's entsoe_fms client (2026-10-20); read-only towards ENTSO-E.
"""
from __future__ import annotations

import io
import os
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

KEYCLOAK_URL = "https://keycloak.tp.entsoe.eu/realms/tp/protocol/openid-connect/token"
FMS_URL = "https://fms.tp.entsoe.eu"
TZ = "Europe/Zagreb"
HR = "10YHR-HEP------M"
ZONES = {"HR": HR, "SI": "10YSI-ELES-----O", "HU": "10YHU-MAVIR----U", "AT": "10YAT-APG------L",
         "DE_LU": "10Y1001A1001A82H", "IT_NORD": "10Y1001A1001A73I"}
LOGS = Path(__file__).parent / "logs"


class Fms:
    def __init__(self, user, password):
        self.s = requests.Session()
        r = self.s.post(KEYCLOAK_URL, data={"client_id": "tp-fms-public", "grant_type": "password",
                                            "username": user, "password": password}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"login failed: HTTP {r.status_code} (check the secrets; the TP password expires every 183 days)")
        self.h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def post(self, endpoint, payload, timeout=120):
        time.sleep(0.7)
        r = self.s.post(f"{FMS_URL}{endpoint}", headers=self.h, json=payload, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"{endpoint}: HTTP {r.status_code}")
        return r

    def latest(self, folder, month):
        body = self.post("/listFolder", {"path": f"/TP_export/{folder}/",
                                         "sorterList": [{"key": "periodCovered.from", "ascending": True}],
                                         "pageInfo": {"pageIndex": 0, "pageSize": 5000}}).json()
        files = [i for i in body.get("contentItemList", []) if "fileId" in i and i["name"].startswith(month)]
        if not files:
            return None, None
        f = max(files, key=lambda i: i["lastUpdatedTimestamp"])
        raw = self.post("/downloadFileContent", {"fileIdList": [f["fileId"]], "topLevelFolder": "TP_export",
                                                 "downloadAsZip": True}, timeout=300).content
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            (member,) = z.namelist()
            data = pd.read_csv(io.BytesIO(z.read(member)), sep="\t")
        return f, data


def log(item, tomorrow, line):
    path = LOGS / item / f"{tomorrow}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(line + "\n")
    print(f"{item}: {line}")


def main():
    now = pd.Timestamp.now(tz=TZ)
    tomorrow = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    start = pd.Timestamp(tomorrow).tz_localize(TZ).tz_convert("UTC")
    end = (pd.Timestamp(tomorrow) + pd.Timedelta(days=1)).tz_localize(TZ).tz_convert("UTC")
    month = start.tz_convert(TZ).strftime("%Y_%m")
    stamp = now.strftime("%Y-%m-%d %H:%M")
    fms = Fms(os.environ["ENTSOE_TP_USER"], os.environ["ENTSOE_TP_PASSWORD"])

    def rows_of(df, area):
        d = df[df["AreaCode"] == area].copy()
        d["ts"] = pd.to_datetime(d["DateTime(UTC)"]).dt.tz_localize("UTC")
        return d[(d.ts >= start) & (d.ts < end)]

    try:
        f, df = fms.latest("GenerationForecastsForWindAndSolar_14.1.D_r3", month)
        if f is None:
            log("hops_solar", tomorrow, f"{stamp} no file for {month}")
        else:
            d = rows_of(df, HR)
            d = d[d["ProductionType"] == "Solar"]
            upd = pd.Timestamp(f["lastUpdatedTimestamp"]).tz_convert(TZ).strftime("%Y-%m-%d %H:%M")
            row_upd = (pd.to_datetime(d["UpdateTime(UTC)"]).max() if len(d) else None)
            log("hops_solar", tomorrow, f"{stamp} {f['name']} UpdateTime {upd} local; tomorrow's quarters {len(d)}; "
                                        f"rows' UpdateTime(UTC) max {row_upd}")
            if len(d) >= 92:
                vals = d[["DateTime(UTC)", "DayAheadGenerationForecast[MW]", "UpdateTime(UTC)"]].sort_values("DateTime(UTC)")
                out = LOGS / "hops_solar_values"
                out.mkdir(parents=True, exist_ok=True)
                first = out / f"{tomorrow}_first_seen.csv"
                if not first.exists():
                    vals.assign(seen_at=stamp).to_csv(first, index=False)
                vals.assign(seen_at=stamp).to_csv(out / f"{tomorrow}_latest.csv", index=False)
    except Exception as e:  # noqa: BLE001 - a watcher logs and goes on
        log("hops_solar", tomorrow, f"{stamp} ERROR {type(e).__name__}: {str(e)[:150]}")

    try:
        f, df = fms.latest("DayAheadTotalLoadForecast_6.1.B_r3", month)
        if f is None:
            log("load_forecast", tomorrow, f"{stamp} no file for {month}")
        else:
            upd = pd.Timestamp(f["lastUpdatedTimestamp"]).tz_convert(TZ).strftime("%Y-%m-%d %H:%M")
            counts = ", ".join(f"{z} {len(rows_of(df, code))}" for z, code in ZONES.items())
            log("load_forecast", tomorrow, f"{stamp} {f['name']} UpdateTime {upd} local; tomorrow's rows: {counts}")
    except Exception as e:  # noqa: BLE001
        log("load_forecast", tomorrow, f"{stamp} ERROR {type(e).__name__}: {str(e)[:150]}")


if __name__ == "__main__":
    sys.exit(main())
