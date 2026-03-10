#!/usr/bin/env python3
"""
ServerPulse - macOS Menu Bar Monitor
Beautiful, compact server performance monitoring.
"""

import rumps
import requests
import threading
import json
import base64
import os
import time

import objc
from AppKit import (
    NSAttributedString, NSFont, NSFontAttributeName,
    NSForegroundColorAttributeName, NSColor, NSMutableAttributedString,
    NSImage,
)
from Foundation import NSSize, NSMakePoint

from traffic_store import TrafficStore

# ─── Config ───
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/ServerPulse")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
POLL_INTERVAL = 3

# ─── Fixed Colors (explicit RGBA, not system semantic colors) ───
CLR_BLACK = NSColor.colorWithSRGBRed_green_blue_alpha_(0.0, 0.0, 0.0, 1.0)
CLR_DARK = NSColor.colorWithSRGBRed_green_blue_alpha_(0.25, 0.25, 0.25, 1.0)
CLR_BLUE = NSColor.colorWithSRGBRed_green_blue_alpha_(0.0, 0.35, 0.85, 1.0)
CLR_RED = NSColor.colorWithSRGBRed_green_blue_alpha_(0.85, 0.15, 0.15, 1.0)
CLR_GREEN = NSColor.colorWithSRGBRed_green_blue_alpha_(0.15, 0.70, 0.15, 1.0)
CLR_YELLOW = NSColor.colorWithSRGBRed_green_blue_alpha_(0.80, 0.65, 0.0, 1.0)
CLR_ORANGE = NSColor.colorWithSRGBRed_green_blue_alpha_(0.90, 0.45, 0.0, 1.0)
CLR_WHITE = NSColor.whiteColor()

# Font weights
WEIGHT_MEDIUM = 0.23    # Medium
WEIGHT_SEMIBOLD = 0.3   # Semibold
WEIGHT_BOLD = 0.4       # Bold


# ─── Formatting ───

def fmt_bytes(b):
    if b < 0:
        b = 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            if b >= 100:
                return f"{b:.0f} {unit}"
            elif b >= 10:
                return f"{b:.1f} {unit}"
            else:
                return f"{b:.2f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def fmt_speed(bps):
    if bps < 0:
        bps = 0
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 * 1024:
        v = bps / 1024
        return f"{v:.1f} K/s" if v >= 10 else f"{v:.2f} K/s"
    else:
        v = bps / 1024 / 1024
        return f"{v:.1f} M/s" if v >= 10 else f"{v:.2f} M/s"


def fmt_speed_short(bps):
    if bps < 0:
        bps = 0
    if bps < 1024:
        return f"{bps:.0f}B"
    elif bps < 1024 * 1024:
        v = bps / 1024
        return f"{v:.0f}K" if v >= 10 else f"{v:.1f}K"
    else:
        v = bps / 1024 / 1024
        return f"{v:.0f}M" if v >= 10 else f"{v:.1f}M"


def bar_text(pct, width=20):
    filled = int(width * pct / 100)
    return "■" * filled + "□" * (width - filled)


def color_for_pct(pct):
    if pct < 40:
        return CLR_GREEN
    elif pct < 65:
        return CLR_YELLOW
    elif pct < 85:
        return CLR_ORANGE
    else:
        return CLR_RED


# ─── Attributed String Helpers ───

def make_attr(segments):
    """Create NSAttributedString from [(text, size, weight, color), ...]"""
    result = NSMutableAttributedString.alloc().init()
    for text, size, weight, color in segments:
        attrs = {
            NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(size, weight),
            NSForegroundColorAttributeName: color,
        }
        part = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        result.appendAttributedString_(part)
    return result


def set_item_attr(item, segments):
    """Set attributed title. segments = [(text, size, weight, color), ...]"""
    try:
        item._menuitem.setAttributedTitle_(make_attr(segments))
    except Exception:
        pass


# ─── Menu Bar Speed Image ───

def create_speed_image(rx_speed, tx_speed):
    rx_text = f"↓{fmt_speed_short(rx_speed)}"
    tx_text = f"↑{fmt_speed_short(tx_speed)}"

    font = NSFont.monospacedSystemFontOfSize_weight_(9.0, WEIGHT_BOLD)
    measure = {NSFontAttributeName: font}
    w1 = NSAttributedString.alloc().initWithString_attributes_(rx_text, measure).size().width
    w2 = NSAttributedString.alloc().initWithString_attributes_(tx_text, measure).size().width
    width = max(w1, w2) + 2
    height = 22

    img = NSImage.alloc().initWithSize_(NSSize(width, height))
    img.lockFocus()

    draw_attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: CLR_WHITE}
    NSAttributedString.alloc().initWithString_attributes_(rx_text, draw_attrs).drawAtPoint_(NSMakePoint(0, 10))
    NSAttributedString.alloc().initWithString_attributes_(tx_text, draw_attrs).drawAtPoint_(NSMakePoint(0, 0))

    img.unlockFocus()
    img.setTemplate_(False)
    return img


# ─── Connection Code ───

def decode_connection_code(code):
    padding = 4 - len(code) % 4
    if padding < 4:
        code += "=" * padding
    data = json.loads(base64.urlsafe_b64decode(code))
    return data["h"], data["p"], data["t"]


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def save_config(host, port, token):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"host": host, "port": port, "token": token}, f)


# ─── Main App ───

SZ = 12.5       # Main font size
SM = 10.5       # Small font size
W = WEIGHT_MEDIUM
WB = WEIGHT_SEMIBOLD


class ServerPulseApp(rumps.App):
    def __init__(self):
        super().__init__("ServerPulse", quit_button=None)
        self.title = "⏳"

        self.host = self.port = self.token = None
        self.traffic_store = TrafficStore()
        self._pending = None
        self._collecting = False
        self._connected = False
        self._first_data = True

        cfg = load_config()
        if cfg:
            self.host, self.port, self.token = cfg["host"], cfg["port"], cfg["token"]

        # ── Menu Items ──
        self.header_item = rumps.MenuItem("")
        self.sep1 = rumps.separator

        self.cpu_item = rumps.MenuItem("  CPU   ──")
        self.mem_item = rumps.MenuItem("  内存  ──")
        self.disk_item = rumps.MenuItem("  硬盘  ──")
        self.net_item = rumps.MenuItem("  网络  ──")
        self.sep_detail = rumps.separator
        self.load_item = rumps.MenuItem("  负载  ──")
        self.uptime_item = rumps.MenuItem("  运行  ──")

        self.sep2 = rumps.separator

        # Traffic section: header + individual time range items
        self.traffic_header = rumps.MenuItem("📊  流量统计")
        self.traffic_items = []
        for _ in range(6):  # today, 1h, 6h, 24h, 7d, 30d
            item = rumps.MenuItem("")
            self.traffic_items.append(item)

        self.sep3 = rumps.separator
        self.connect_item = rumps.MenuItem("🔗  输入连接码", callback=self.on_connect)
        self.reconnect_item = rumps.MenuItem("🔄  重新连接", callback=self.on_reconnect)
        self.quit_item = rumps.MenuItem("⏻   退出", callback=self.on_quit)

        menu_items = [
            self.header_item, self.sep1,
            self.cpu_item, self.mem_item, self.disk_item, self.net_item,
            self.sep_detail,
            self.load_item, self.uptime_item,
            self.sep2,
            self.traffic_header,
        ]
        menu_items.extend(self.traffic_items)
        menu_items.extend([
            self.sep3,
            self.connect_item, self.reconnect_item, self.quit_item,
        ])
        self.menu = menu_items

        if self.host:
            self.header_item.title = f"  {self.host} · 连接中..."
        else:
            self.header_item.title = "  未配置 · 请输入连接码"
            threading.Timer(1.0, lambda: rumps.Timer(0, lambda _: self.on_connect(None)).start()).start()

    # ── Connection Code ──
    def on_connect(self, _):
        resp = rumps.Window(
            title="ServerPulse",
            message="请粘贴服务器连接码：\n(在服务器运行 install.sh 后获取)",
            default_text="",
            ok="连接",
            cancel="取消",
            dimensions=(360, 24),
        ).run()
        if resp.clicked:
            code = resp.text.strip()
            if code:
                try:
                    h, p, t = decode_connection_code(code)
                    self.host, self.port, self.token = h, p, t
                    save_config(h, p, t)
                    self.header_item.title = f"  {h} · 连接中..."
                    self._connected = False
                    self._first_data = True
                except Exception:
                    rumps.alert("错误", "无效的连接码，请检查后重试")

    # ── Polling ──
    @rumps.timer(POLL_INTERVAL)
    def poll(self, _):
        if not self.host or self._collecting:
            return

        def do_fetch():
            self._collecting = True
            try:
                url = f"http://{self.host}:{self.port}/metrics"
                r = requests.get(url, headers={"Authorization": f"Bearer {self.token}"}, timeout=8)
                self._pending = ("ok", r.json()) if r.status_code == 200 else ("err", None)
            except Exception:
                self._pending = ("err", None)
            finally:
                self._collecting = False

        threading.Thread(target=do_fetch, daemon=True).start()

    @rumps.timer(1)
    def check_pending(self, _):
        if self._pending is None:
            return
        status, data = self._pending
        self._pending = None

        if status == "ok" and data:
            self._connected = True
            net = data.get("net", {})
            self.traffic_store.record(net.get("rx_bytes", 0), net.get("tx_bytes", 0))
            if self._first_data:
                self._first_data = False
                return
            self._update_ui(data)
        else:
            self._connected = False
            self.title = "⚠️"
            try:
                self._nsapp.nsstatusitem.button().setImage_(None)
            except Exception:
                pass
            set_item_attr(self.header_item, [
                (f"  {self.host}", 13, WB, CLR_BLACK),
                ("  ●  断开", 12, W, CLR_RED),
            ])

    # ── UI Update ──
    def _update_ui(self, m):
        net = m.get("net", {})
        rx_speed = net.get("rx_speed", 0)
        tx_speed = net.get("tx_speed", 0)

        # Menu bar icon
        self.title = ""
        try:
            img = create_speed_image(rx_speed, tx_speed)
            self._nsapp.nsstatusitem.button().setImage_(img)
        except Exception:
            self.title = f"↓{fmt_speed_short(rx_speed)} ↑{fmt_speed_short(tx_speed)}"

        # Header
        hostname = m.get("hostname", self.host)
        set_item_attr(self.header_item, [
            (f"  {hostname}", 13, WB, CLR_BLACK),
            (f"  ({self.host})", 11, W, CLR_DARK),
            ("  ●", 11, W, CLR_GREEN),
        ])

        # CPU
        cpu_pct = m.get("cpu", {}).get("usage", 0)
        set_item_attr(self.cpu_item, [
            ("  CPU    ", SZ, WB, CLR_BLACK),
            (f"{cpu_pct:5.1f}%  ", SZ, WB, color_for_pct(cpu_pct)),
            (bar_text(cpu_pct), 9, W, color_for_pct(cpu_pct)),
        ])

        # Memory
        mem = m.get("mem", {})
        mem_pct = mem.get("usage", 0)
        set_item_attr(self.mem_item, [
            ("  内存   ", SZ, WB, CLR_BLACK),
            (f"{mem_pct:5.1f}%  ", SZ, WB, color_for_pct(mem_pct)),
            (bar_text(mem_pct), 9, W, color_for_pct(mem_pct)),
            (f"  {fmt_bytes(mem.get('used', 0))}/{fmt_bytes(mem.get('total', 0))}", SM, W, CLR_DARK),
        ])

        # Disk
        disk = m.get("disk", {})
        disk_pct = disk.get("usage", 0)
        set_item_attr(self.disk_item, [
            ("  硬盘   ", SZ, WB, CLR_BLACK),
            (f"{disk_pct:5.1f}%  ", SZ, WB, color_for_pct(disk_pct)),
            (bar_text(disk_pct), 9, W, color_for_pct(disk_pct)),
            (f"  {fmt_bytes(disk.get('used', 0))}/{fmt_bytes(disk.get('total', 0))}", SM, W, CLR_DARK),
        ])

        # Network
        set_item_attr(self.net_item, [
            ("  网络   ", SZ, WB, CLR_BLACK),
            (f"↓ {fmt_speed(rx_speed)}", SZ, WB, CLR_BLUE),
            ("  ", SZ, W, CLR_BLACK),
            (f"↑ {fmt_speed(tx_speed)}", SZ, WB, CLR_RED),
            (f"  ({net.get('iface', '?')})", SM, W, CLR_DARK),
        ])

        # Load
        load = m.get("load", {})
        set_item_attr(self.load_item, [
            ("  负载   ", SZ, WB, CLR_BLACK),
            (f"{load.get('1m', '?')}  {load.get('5m', '?')}  {load.get('15m', '?')}", SZ, W, CLR_BLACK),
        ])

        # Uptime
        set_item_attr(self.uptime_item, [
            ("  运行   ", SZ, WB, CLR_BLACK),
            (m.get("uptime", "N/A"), SZ, W, CLR_BLACK),
        ])

        # Traffic
        self._update_traffic()

    def _update_traffic(self):
        set_item_attr(self.traffic_header, [
            ("📊  流量统计", SZ, WB, CLR_BLACK),
        ])

        stats = self.traffic_store.get_predefined_stats()
        for i, item in enumerate(self.traffic_items):
            if i < len(stats):
                s = stats[i]
                set_item_attr(item, [
                    (f"    {s['label']:6s}", 11.5, W, CLR_BLACK),
                    (f"  ↓ {fmt_bytes(s['rx']):>10s}", 11.5, W, CLR_BLUE),
                    (f"  ↑ {fmt_bytes(s['tx']):>10s}", 11.5, W, CLR_RED),
                    (f"  Σ {fmt_bytes(s['total']):>10s}", 11.5, WB, CLR_BLACK),
                ])
            else:
                item.title = ""

    def on_reconnect(self, _):
        self.title = "⏳"
        self.header_item.title = f"  {self.host} · 重新连接中..."
        self._connected = False
        self._first_data = True

    def on_quit(self, _):
        self.traffic_store.save()
        rumps.quit_application()


if __name__ == "__main__":
    ServerPulseApp().run()
