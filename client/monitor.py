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
    NSImage, NSBezierPath,
)
from Foundation import NSSize, NSMakeRect, NSMakePoint

from traffic_store import TrafficStore

# ─── Config ───
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/ServerPulse")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
POLL_INTERVAL = 3


# ─── Formatting Helpers ───

def fmt_bytes(b):
    if b < 0:
        b = 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            if b >= 100:
                return f"{b:.0f}{unit}"
            elif b >= 10:
                return f"{b:.1f}{unit}"
            else:
                return f"{b:.2f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


def fmt_speed(bps):
    if bps < 0:
        bps = 0
    if bps < 1024:
        return f"{bps:.0f}B/s"
    elif bps < 1024 * 1024:
        v = bps / 1024
        return f"{v:.1f}K/s" if v >= 10 else f"{v:.2f}K/s"
    else:
        v = bps / 1024 / 1024
        return f"{v:.1f}M/s" if v >= 10 else f"{v:.2f}M/s"


def fmt_speed_short(bps):
    """Compact format for menu bar."""
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
    """Green -> Yellow -> Orange -> Red based on percentage."""
    if pct < 40:
        return NSColor.systemGreenColor()
    elif pct < 65:
        return NSColor.systemYellowColor()
    elif pct < 85:
        return NSColor.systemOrangeColor()
    else:
        return NSColor.systemRedColor()


# ─── Styled Menu Helpers ───

def make_attributed(lines):
    """Create NSAttributedString from [(text, font_size, color), ...]"""
    result = NSMutableAttributedString.alloc().init()
    for text, size, color in lines:
        attrs = {
            NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(size, 0.0),
            NSForegroundColorAttributeName: color,
        }
        part = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        result.appendAttributedString_(part)
    return result


def set_attr(item, lines):
    """Set attributed title on a rumps MenuItem."""
    attr_str = make_attributed(lines)
    try:
        item._menuitem.setAttributedTitle_(attr_str)
    except Exception:
        pass


# ─── Stacked Speed Image for Menu Bar ───

def create_speed_image(rx_speed, tx_speed):
    """Create compact NSImage with stacked ↓/↑ speeds."""
    rx_text = f"↓{fmt_speed_short(rx_speed)}"
    tx_text = f"↑{fmt_speed_short(tx_speed)}"

    # Calculate tight width
    font = NSFont.monospacedSystemFontOfSize_weight_(9.0, 0.5)
    measure_attrs = {NSFontAttributeName: font}
    rx_as = NSAttributedString.alloc().initWithString_attributes_(rx_text, measure_attrs)
    tx_as = NSAttributedString.alloc().initWithString_attributes_(tx_text, measure_attrs)
    w1 = rx_as.size().width
    w2 = tx_as.size().width
    width = max(w1, w2) + 2  # Tight fit, minimal padding
    height = 22

    img = NSImage.alloc().initWithSize_(NSSize(width, height))
    img.lockFocus()

    white = NSColor.whiteColor()
    draw_attrs = {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: white,
    }

    # Download speed (top half)
    top = NSAttributedString.alloc().initWithString_attributes_(rx_text, draw_attrs)
    top.drawAtPoint_(NSMakePoint(0, 10))

    # Upload speed (bottom half)
    bot = NSAttributedString.alloc().initWithString_attributes_(tx_text, draw_attrs)
    bot.drawAtPoint_(NSMakePoint(0, 0))

    img.unlockFocus()
    img.setTemplate_(False)
    return img


# ─── Connection Code ───

def decode_connection_code(code):
    padding = 4 - len(code) % 4
    if padding < 4:
        code += "=" * padding
    raw = base64.urlsafe_b64decode(code)
    data = json.loads(raw)
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

        # ── Menu Items ──
        self.header_item = rumps.MenuItem("")
        self.sep1 = rumps.separator

        self.cpu_item = rumps.MenuItem("  CPU    ──")
        self.mem_item = rumps.MenuItem("  内存   ──")
        self.disk_item = rumps.MenuItem("  硬盘   ──")
        self.net_item = rumps.MenuItem("  网络   ──")
        self.sep_detail = rumps.separator
        self.load_item = rumps.MenuItem("  负载   ──")
        self.uptime_item = rumps.MenuItem("  运行   ──")

        self.sep2 = rumps.separator
        self.traffic_menu = rumps.MenuItem("📊  流量统计")

        self.sep3 = rumps.separator
        self.connect_item = rumps.MenuItem("🔗  输入连接码", callback=self.on_connect)
        self.reconnect_item = rumps.MenuItem("🔄  重新连接", callback=self.on_reconnect)
        self.quit_item = rumps.MenuItem("⏻   退出", callback=self.on_quit)

        self.menu = [
            self.header_item, self.sep1,
            self.cpu_item, self.mem_item, self.disk_item, self.net_item,
            self.sep_detail,
            self.load_item, self.uptime_item,
            self.sep2, self.traffic_menu,
            self.sep3,
            self.connect_item, self.reconnect_item, self.quit_item,
        ]

        if self.host:
            self.header_item.title = f"  {self.host} · 连接中..."
        else:
            self.header_item.title = "  未配置 · 请输入连接码"
            threading.Timer(1.0, lambda: rumps.Timer(0, lambda _: self.on_connect(None)).start()).start()

    # ── Connection Code Dialog ──
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
            set_attr(self.header_item, [
                (f"  {self.host}", 13, NSColor.blackColor()),
                ("  ●  断开", 12, NSColor.systemRedColor()),
            ])

    # ── UI Update ──
    def _update_ui(self, m):
        net = m.get("net", {})
        rx_speed = net.get("rx_speed", 0)
        tx_speed = net.get("tx_speed", 0)

        # ── Menu Bar: stacked speed icon ──
        self.title = ""
        try:
            img = create_speed_image(rx_speed, tx_speed)
            self._nsapp.nsstatusitem.button().setImage_(img)
        except Exception:
            self.title = f"↓{fmt_speed_short(rx_speed)} ↑{fmt_speed_short(tx_speed)}"

        # ── Colors for menu items ──
        # Force high-contrast colors for readability
        black = NSColor.blackColor()              # Primary text - always black
        darkgray = NSColor.darkGrayColor()        # Secondary text
        cyan = NSColor.systemBlueColor()          # Download (blue more readable than cyan)
        pink = NSColor.systemRedColor()           # Upload (red more readable than pink)
        green = NSColor.systemGreenColor()
        sz = 12.5   # Main font size
        sm = 10.5   # Small font size

        # Header
        hostname = m.get("hostname", self.host)
        set_attr(self.header_item, [
            (f"  {hostname}", 13, black),
            (f"  ({self.host})", 11, darkgray),
            ("  ●", 11, green),
        ])

        # CPU
        cpu_pct = m.get("cpu", {}).get("usage", 0)
        cpu_c = color_for_pct(cpu_pct)
        set_attr(self.cpu_item, [
            ("  CPU    ", sz, black),
            (f"{cpu_pct:5.1f}%  ", sz, cpu_c),
            (bar_text(cpu_pct), 9, cpu_c),
        ])

        # Memory
        mem = m.get("mem", {})
        mem_pct = mem.get("usage", 0)
        mem_c = color_for_pct(mem_pct)
        set_attr(self.mem_item, [
            ("  内存   ", sz, black),
            (f"{mem_pct:5.1f}%  ", sz, mem_c),
            (bar_text(mem_pct), 9, mem_c),
            (f"  {fmt_bytes(mem.get('used', 0))}/{fmt_bytes(mem.get('total', 0))}", sm, darkgray),
        ])

        # Disk
        disk = m.get("disk", {})
        disk_pct = disk.get("usage", 0)
        disk_c = color_for_pct(disk_pct)
        set_attr(self.disk_item, [
            ("  硬盘   ", sz, black),
            (f"{disk_pct:5.1f}%  ", sz, disk_c),
            (bar_text(disk_pct), 9, disk_c),
            (f"  {fmt_bytes(disk.get('used', 0))}/{fmt_bytes(disk.get('total', 0))}", sm, darkgray),
        ])

        # Network
        set_attr(self.net_item, [
            ("  网络   ", sz, black),
            (f"↓{fmt_speed(rx_speed)}", sz, cyan),
            ("  ", sz, black),
            (f"↑{fmt_speed(tx_speed)}", sz, pink),
            (f"  ({net.get('iface', '?')})", sm, darkgray),
        ])

        # Load
        load = m.get("load", {})
        set_attr(self.load_item, [
            ("  负载   ", sz, black),
            (f"{load.get('1m', '?')}  {load.get('5m', '?')}  {load.get('15m', '?')}", sz, black),
        ])

        # Uptime
        set_attr(self.uptime_item, [
            ("  运行   ", sz, black),
            (m.get("uptime", "N/A"), sz, black),
        ])

        # Traffic
        self._build_traffic_submenu()

    def _build_traffic_submenu(self):
        try:
            self.traffic_menu.clear()
        except Exception:
            return

        label = NSColor.blackColor()
        sub = NSColor.darkGrayColor()
        cyan = NSColor.systemBlueColor()
        pink = NSColor.systemRedColor()

        for s in self.traffic_store.get_predefined_stats():
            item = rumps.MenuItem("")
            set_attr(item, [
                (f"  {s['label']:6s}", 12, sub),
                (f"  ↓{fmt_bytes(s['rx']):>9s}", 12, cyan),
                (f"  ↑{fmt_bytes(s['tx']):>9s}", 12, pink),
                (f"  Σ{fmt_bytes(s['total']):>9s}", 12, label),
            ])
            self.traffic_menu.add(item)

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
