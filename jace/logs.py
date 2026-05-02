from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import TextIO


def log(message: str, *, level: str = "INFO", stream: TextIO | None = None) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    output = stream or sys.stdout
    print(f"{timestamp} UTC [{os.getpid()}] {level}: {message}", file=output)
