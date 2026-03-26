from __future__ import annotations

import base64

from cog.render_config import render_cog_config


def test_render_cog_config_embeds_base64_setup_script(tmp_path) -> None:
    template_path = tmp_path / "cog.template.yaml"
    setup_path = tmp_path / "setup.sh"
    output_path = tmp_path / "cog.yaml"

    template_path.write_text("run:\n  - echo ENCODED_SCRIPT\n")
    setup_path.write_text("#!/usr/bin/env bash\necho hello\n")

    render_cog_config(template_path, setup_path, output_path)

    encoded_script = base64.b64encode(setup_path.read_bytes()).decode("ascii")
    assert output_path.read_text() == f"run:\n  - echo {encoded_script}\n"
