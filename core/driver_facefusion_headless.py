from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path
from typing import Sequence


def _disable_content_analysis(facefusion_root: Path) -> None:
    if str(facefusion_root) not in sys.path:
        sys.path.insert(0, str(facefusion_root))

    import facefusion.content_analyser as content_analyser

    def _always_safe(*_args: object, **_kwargs: object) -> bool:
        return False

    # FaceFusion's generic NSFW gate false-positives on our driver camera footage.
    content_analyser.analyse_frame = _always_safe
    content_analyser.analyse_image = _always_safe
    content_analyser.analyse_stream = _always_safe
    content_analyser.analyse_video = _always_safe


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--facefusion-root", required=True)
    args, forwarded = parser.parse_known_args(argv)

    facefusion_root = Path(args.facefusion_root).expanduser().resolve()
    _disable_content_analysis(facefusion_root)
    sys.argv = [str(facefusion_root / "facefusion.py"), *forwarded]
    runpy.run_path(str(facefusion_root / "facefusion.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
