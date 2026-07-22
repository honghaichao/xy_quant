#!/usr/bin/env python3
"""Flask Dashboard 入口 — 确保项目根在 sys.path 最前面。"""
import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from web.app import app
port = int(os.environ.get('PORT', 5004))
debug = os.environ.get('WEB_DEBUG', '0') == '1'
print(f"XY Quant Dashboard: http://0.0.0.0:{port}")
app.run(debug=debug, port=port, host='0.0.0.0')
