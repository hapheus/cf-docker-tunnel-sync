import urllib.request
import sys

try:
    urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=2)
    sys.exit(0)
except Exception:
    sys.exit(1)
