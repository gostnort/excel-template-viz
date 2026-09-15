"""python -m paddle_ocr.pdf2md"""

from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
from paddle_ocr.pdf2md.api import main

raise SystemExit(main())
