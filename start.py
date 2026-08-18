# -*- coding: utf-8 -*-
"""FieldFactor — точка входу. Запускається з ЗАПУСК.bat."""

import os
import sys

БАЗА = os.path.dirname(os.path.abspath(__file__))
if БАЗА not in sys.path:
    sys.path.insert(0, БАЗА)

from app.main import запустити  # noqa: E402

if __name__ == "__main__":
    запустити(БАЗА)
