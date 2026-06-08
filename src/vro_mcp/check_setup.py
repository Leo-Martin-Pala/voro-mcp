from __future__ import annotations

import json

from .config import load_settings
from .tools import VroTools


def main() -> None:
    tools = VroTools(load_settings())
    print(json.dumps(tools.check_setup(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

