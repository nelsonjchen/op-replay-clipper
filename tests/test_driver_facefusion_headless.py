from __future__ import annotations

import json
import sys
from pathlib import Path

from core import driver_facefusion_headless


def test_disable_content_analysis_installs_stub_module_without_importing_real_module(
    monkeypatch,
    tmp_path: Path,
) -> None:
    facefusion_root = tmp_path / "facefusion-root"
    package_dir = facefusion_root / "facefusion"
    package_dir.mkdir(parents=True)

    imported_marker = tmp_path / "real-module-imported.txt"
    package_dir.joinpath("__init__.py").write_text("")
    package_dir.joinpath("content_analyser.py").write_text(
        f"from pathlib import Path\nPath({str(imported_marker)!r}).write_text('imported')\n"
    )

    monkeypatch.delitem(sys.modules, "facefusion", raising=False)
    monkeypatch.delitem(sys.modules, "facefusion.content_analyser", raising=False)

    driver_facefusion_headless._disable_content_analysis(facefusion_root)

    assert not imported_marker.exists()
    stub = sys.modules["facefusion.content_analyser"]
    assert stub.pre_check() is True
    assert stub.create_static_model_set("full") == {}
    assert stub.collect_model_downloads() == ({}, {})
    assert stub.get_inference_pool() == {}
    assert stub.clear_inference_pool() is None
    assert stub.detect_nsfw(object()) is False
    assert stub.analyse_frame(object()) is False
    assert stub.analyse_image("frame.png") is False
    assert stub.analyse_stream(object(), 20) is False
    assert stub.analyse_video("clip.mp4", 0, 100) is False


def test_main_runs_facefusion_with_stubbed_content_analyser(monkeypatch, tmp_path: Path) -> None:
    facefusion_root = tmp_path / "facefusion-root"
    package_dir = facefusion_root / "facefusion"
    package_dir.mkdir(parents=True)

    imported_marker = tmp_path / "real-module-imported.txt"
    observed_path = tmp_path / "observed.json"
    package_dir.joinpath("__init__.py").write_text("")
    package_dir.joinpath("content_analyser.py").write_text(
        f"from pathlib import Path\nPath({str(imported_marker)!r}).write_text('imported')\n"
    )
    facefusion_root.joinpath("facefusion.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "from pathlib import Path",
                "from facefusion.content_analyser import analyse_video, collect_model_downloads, pre_check",
                f"out = Path({str(observed_path)!r})",
                "payload = {",
                "  'argv': sys.argv[1:],",
                "  'pre_check': pre_check(),",
                "  'downloads': collect_model_downloads(),",
                "  'analyse_video': analyse_video('clip.mp4', 10, 20),",
                "}",
                "out.write_text(json.dumps(payload))",
            ]
        )
    )

    monkeypatch.delitem(sys.modules, "facefusion", raising=False)
    monkeypatch.delitem(sys.modules, "facefusion.content_analyser", raising=False)

    exit_code = driver_facefusion_headless.main(
        [
            "--facefusion-root",
            str(facefusion_root),
            "--target-path",
            "target.mp4",
        ]
    )

    assert exit_code == 0
    assert not imported_marker.exists()
    observed = json.loads(observed_path.read_text())
    assert observed == {
        "argv": ["--target-path", "target.mp4"],
        "pre_check": True,
        "downloads": [{}, {}],
        "analyse_video": False,
    }

