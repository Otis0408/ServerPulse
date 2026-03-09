"""py2app build configuration for ServerPulse."""

from setuptools import setup

APP = ["monitor.py"]
DATA_FILES = []

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "ServerPulse",
        "CFBundleDisplayName": "ServerPulse",
        "CFBundleIdentifier": "com.serverpulse.monitor",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "11.0",
        "LSUIElement": True,  # Menu bar app, no dock icon
        "NSHighResolutionCapable": True,
    },
    "packages": ["rumps", "requests", "certifi", "charset_normalizer", "idna", "urllib3"],
    "includes": ["objc", "AppKit", "Foundation"],
}

setup(
    name="ServerPulse",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
