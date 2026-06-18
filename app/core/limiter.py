"""
app/core/limiter.py — Shared SlowAPI rate limiter instance

แยกออกมาเป็นไฟล์กลาง เพื่อแก้ circular import:
  main.py  → import auth.py
  auth.py  → import limiter
  solution → ทั้งคู่ import limiter จากไฟล์นี้แทน
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
