"""Traffic data storage and statistics."""

import json
import os
import time
from datetime import datetime

DATA_DIR = os.path.expanduser("~/Library/Application Support/ServerPulse")
DATA_FILE = os.path.join(DATA_DIR, "traffic_data.json")


class TrafficStore:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._records = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r") as f:
                    self._records = json.load(f)
                cutoff = time.time() - 90 * 86400
                self._records = [r for r in self._records if r["ts"] > cutoff]
        except Exception:
            self._records = []

    def _save(self):
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(self._records, f)
        except Exception:
            pass

    def record(self, rx_bytes, tx_bytes):
        self._records.append({"ts": time.time(), "rx": rx_bytes, "tx": tx_bytes})
        if len(self._records) % 10 == 0:
            self._save()

    def save(self):
        self._save()

    def get_stats(self, hours=None, start_dt=None, end_dt=None):
        if not self._records:
            return {"rx": 0, "tx": 0, "total": 0, "period": "无数据"}

        now = time.time()
        if start_dt and end_dt:
            ts_start, ts_end = start_dt.timestamp(), end_dt.timestamp()
            period = f"{start_dt.strftime('%m/%d %H:%M')} - {end_dt.strftime('%m/%d %H:%M')}"
        elif hours:
            ts_start, ts_end = now - hours * 3600, now
            period = f"最近 {hours}h" if hours < 24 else f"最近 {hours // 24}d"
        else:
            ts_start, ts_end = self._records[0]["ts"], now
            period = "全部"

        filtered = [r for r in self._records if ts_start <= r["ts"] <= ts_end]
        if len(filtered) < 2:
            return {"rx": 0, "tx": 0, "total": 0, "period": period}

        total_rx = total_tx = 0
        for i in range(1, len(filtered)):
            drx = filtered[i]["rx"] - filtered[i - 1]["rx"]
            dtx = filtered[i]["tx"] - filtered[i - 1]["tx"]
            if drx > 0:
                total_rx += drx
            if dtx > 0:
                total_tx += dtx

        return {"rx": total_rx, "tx": total_tx, "total": total_rx + total_tx, "period": period}

    def get_predefined_stats(self):
        ranges = [("1h", 1), ("6h", 6), ("24h", 24), ("7d", 168), ("30d", 720)]
        results = []

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = self.get_stats(start_dt=today_start, end_dt=datetime.now())
        today["label"] = "今日"
        results.append(today)

        for label, hours in ranges:
            s = self.get_stats(hours=hours)
            s["label"] = label
            results.append(s)
        return results
