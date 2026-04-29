from __future__ import annotations

import argparse
import base64
from pathlib import Path
import subprocess


ROOT_DIR = Path(__file__).resolve().parents[1]


def resolve_clipper_git_describe(repo_root: Path = ROOT_DIR) -> str:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def render_cog_config(
    template_path: Path,
    setup_script_path: Path,
    output_path: Path,
    *,
    clipper_git_describe: str | None = None,
) -> None:
    template = template_path.read_text()
    encoded_script = base64.b64encode(setup_script_path.read_bytes()).decode("ascii")
    git_describe = resolve_clipper_git_describe() if clipper_git_describe is None else clipper_git_describe
    rendered = template.replace("ENCODED_SCRIPT", encoded_script)
    rendered = rendered.replace("__CLIPPER_GIT_DESCRIBE__", git_describe)
    output_path.write_text(rendered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render cog.yaml from a template and bootstrap script")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--setup-script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    render_cog_config(
        template_path=args.template.resolve(),
        setup_script_path=args.setup_script.resolve(),
        output_path=args.output.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
