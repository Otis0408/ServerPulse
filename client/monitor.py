#!/usr/bin/env python3
"""
ServerPulse - macOS Menu Bar Monitor
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

# Colors for accent elements only
CLR_GREEN = NSColor.colorWithSRGBRed_green_blue_alpha_(0.15, 0.68, 0.15, 1.0)
CLR_YELLOW = NSColor.colorWithSRGBRed_green_blue_alpha_(0.80, 0.65, 0.0, 1.0)
CLR_ORANGE = NSColor.colorWithSRGBRed_green_blue_alpha_(0.90, 0.40, 0.0, 1.0)
CLR_RED = NSColor.colorWithSRGBRed_green_blue_alpha_(0.88, 0.12, 0.12, 1.0)
CLR_BLUE = NSColor.colorWithSRGBRed_green_blue_alpha_(0.0, 0.35, 0.85, 1.0)


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


# ─── Attributed String (uses system menu font to match native items) ───

def _menu_font(size=0, bold=False):
    """Get the system menu font. size=0 means system default."""
    if bold:
        return NSFont.boldSystemFontOfSize_(size)
    return NSFont.menuFontOfSize_(size)


def _mono_font(size=10):
    return NSFont.monospacedSystemFontOfSize_weight_(size, 0.0)


def set_title(item, segments):
    """Set attributed title on a menu item.
    segments = [(text, color_or_None, mono_size_or_None), ...]
    color=None means controlTextColor (system default black).
    mono_size=None means use system menu font, otherwise monospaced at given size.
    """
    result = NSMutableAttributedString.alloc().init()
    default_color = NSColor.controlTextColor()

    for seg in segments:
        text, color, mono = seg
        attrs = {}
        if mono:
            attrs[NSFontAttributeName] = _mono_font(mono)
        else:
            attrs[NSFontAttributeName] = _menu_font()
        attrs[NSForegroundColorAttributeName] = color if color else default_color
        part = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        result.appendAttributedString_(part)

    try:
        item._menuitem.setAttributedTitle_(result)
    except Exception:
        pass


# ─── Menu Bar Speed Image ───

def create_speed_image(rx_speed, tx_speed):
    rx_text = f"↓{fmt_speed_short(rx_speed)}"
    tx_text = f"↑{fmt_speed_short(tx_speed)}"

    font = NSFont.monospacedSystemFontOfSize_weight_(9.0, 0.4)
    measure = {NSFontAttributeName: font}
    w1 = NSAttributedString.alloc().initWithString_attributes_(rx_text, measure).size().width
    w2 = NSAttributedString.alloc().initWithString_attributes_(tx_text, measure).size().width
    width = max(w1, w2) + 2
    height = 22

    img = NSImage.alloc().initWithSize_(NSSize(width, height))
    img.lockFocus()
    draw = {NSFontAttributeName: font, NSForegroundColorAttributeName: NSColor.whiteColor()}
    NSAttributedString.alloc().initWithString_attributes_(rx_text, draw).drawAtPoint_(NSMakePoint(0, 10))
    NSAttributedString.alloc().initWithString_attributes_(tx_text, draw).drawAtPoint_(NSMakePoint(0, 0))
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

        # Menu Items
        self.header_item = rumps.MenuItem("")
        self.sep1 = rumps.separator

        self.cpu_item = rumps.MenuItem("CPU  ──")
        self.mem_item = rumps.MenuItem("内存  ──")
        self.disk_item = rumps.MenuItem("硬盘  ──")
        self.net_item = rumps.MenuItem("网络  ──")
        self.sep_detail = rumps.separator
        self.load_item = rumps.MenuItem("负载  ──")
        self.uptime_item = rumps.MenuItem("运行  ──")

        self.sep2 = rumps.separator
        self.traffic_today = rumps.MenuItem("今日流量  ──")
        self.traffic_total = rumps.MenuItem("累计流量  ──")

        self.sep3 = rumps.separator
        self.connect_item = rumps.MenuItem("🔗 输入连接码", callback=self.on_connect)
        self.reconnect_item = rumps.MenuItem("🔄 重新连接", callback=self.on_reconnect)
        self.quit_item = rumps.MenuItem("退出", callback=self.on_quit)

        self.menu = [
            self.header_item, self.sep1,
            self.cpu_item, self.mem_item, self.disk_item, self.net_item,
            self.sep_detail,
            self.load_item, self.uptime_item,
            self.sep2,
            self.traffic_today, self.traffic_total,
            self.sep3,
            self.connect_item, self.reconnect_item, self.quit_item,
        ]

        if self.host:
            self.header_item.title = f"{self.host} · 连接中..."
        else:
            self.header_item.title = "未配置 · 请输入连接码"
            threading.Timer(1.0, lambda: rumps.Timer(0, lambda _: self.on_connect(None)).start()).start()

    def on_connect(self, _):
        resp = rumps.Window(
            title="ServerPulse",
            message="请粘贴服务器连接码：\n(在服务器运行 install.sh 后获取)",
            default_text="", ok="连接", cancel="取消",
            dimensions=(360, 24),
        ).run()
        if resp.clicked:
            code = resp.text.strip()
            if code:
                try:
                    h, p, t = decode_connection_code(code)
                    self.host, self.port, self.token = h, p, t
                    save_config(h, p, t)
                    self.header_item.title = f"{h} · 连接中..."
                    self._connected = False
                    self._first_data = True
                except Exception:
                    rumps.alert("错误", "无效的连接码，请检查后重试")

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
            self.header_item.title = f"{self.host} · 连接断开"

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

        # Header: hostname (ip) ●
        hostname = m.get("hostname", self.host)
        set_title(self.header_item, [
            (f"{hostname}  ({self.host})  ", None, None),
            ("●", CLR_GREEN, None),
        ])

        # CPU
        cpu_pct = m.get("cpu", {}).get("usage", 0)
        cc = color_for_pct(cpu_pct)
        set_title(self.cpu_item, [
            ("CPU   ", None, None),
            (f"{cpu_pct:.1f}%  ", cc, None),
            (bar_text(cpu_pct), cc, 9),
        ])

        # Memory
        mem = m.get("mem", {})
        mem_pct = mem.get("usage", 0)
        mc = color_for_pct(mem_pct)
        set_title(self.mem_item, [
            ("内存   ", None, None),
            (f"{mem_pct:.1f}%  ", mc, None),
            (bar_text(mem_pct), mc, 9),
            (f"  {fmt_bytes(mem.get('used', 0))}/{fmt_bytes(mem.get('total', 0))}", None, None),
        ])

        # Disk
        disk = m.get("disk", {})
        disk_pct = disk.get("usage", 0)
        dc = color_for_pct(disk_pct)
        set_title(self.disk_item, [
            ("硬盘   ", None, None),
            (f"{disk_pct:.1f}%  ", dc, None),
            (bar_text(disk_pct), dc, 9),
            (f"  {fmt_bytes(disk.get('used', 0))}/{fmt_bytes(disk.get('total', 0))}", None, None),
        ])

        # Network
        set_title(self.net_item, [
            ("网络   ", None, None),
            (f"↓ {fmt_speed(rx_speed)}", CLR_BLUE, None),
            ("  ", None, None),
            (f"↑ {fmt_speed(tx_speed)}", CLR_RED, None),
        ])

        # Load
        load = m.get("load", {})
        self.load_item.title = f"负载   {load.get('1m', '?')}  {load.get('5m', '?')}  {load.get('15m', '?')}"

        # Uptime
        self.uptime_item.title = f"运行   {m.get('uptime', 'N/A')}"

        # Traffic
        self._update_traffic()

    def _update_traffic(self):
        from datetime import datetime
        today_stats = self.traffic_store.get_stats(
            start_dt=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            end_dt=datetime.now(),
        )
        total_stats = self.traffic_store.get_stats()

        set_title(self.traffic_today, [
            ("今日流量   ", None, None),
            (f"↓ {fmt_bytes(today_stats['rx'])}", CLR_BLUE, None),
            ("  ", None, None),
            (f"↑ {fmt_bytes(today_stats['tx'])}", CLR_RED, None),
            (f"  共 {fmt_bytes(today_stats['total'])}", None, None),
        ])

        set_title(self.traffic_total, [
            ("累计流量   ", None, None),
            (f"↓ {fmt_bytes(total_stats['rx'])}", CLR_BLUE, None),
            ("  ", None, None),
            (f"↑ {fmt_bytes(total_stats['tx'])}", CLR_RED, None),
            (f"  共 {fmt_bytes(total_stats['total'])}", None, None),
        ])

    def on_reconnect(self, _):
        self.title = "⏳"
        self.header_item.title = f"{self.host} · 重新连接中..."
        self._connected = False
        self._first_data = True

    def on_quit(self, _):
        self.traffic_store.save()
        rumps.quit_application()


if __name__ == "__main__":
    ServerPulseApp().run()
