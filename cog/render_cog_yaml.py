from __future__ import annotations

import argparse
import base64
from pathlib import Path


def render_cog_yaml(template_path: Path, setup_script_path: Path, output_path: Path) -> None:
    template = template_path.read_text()
    encoded_script = base64.b64encode(setup_script_path.read_bytes()).decode("ascii")
    output_path.write_text(template.replace("ENCODED_SCRIPT", encoded_script))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render cog.yaml from a template and setup script")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--setup-script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    render_cog_yaml(
        template_path=args.template.resolve(),
        setup_script_path=args.setup_script.resolve(),
        output_path=args.output.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
