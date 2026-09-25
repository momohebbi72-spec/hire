"""Backward-compatible entry point: python3 app.py  →  dashboard on http://127.0.0.1:3000"""
from radar.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["serve"]))
