from __future__ import annotations

import json
import sys
import inspect
from pathlib import Path

from core import driver_facefusion_headless


def test_disable_content_analysis_overrides_real_module_entrypoints(
    monkeypatch,
    tmp_path: Path,
) -> None:
    facefusion_root = tmp_path / "facefusion-root"
    package_dir = facefusion_root / "facefusion"
    package_dir.mkdir(parents=True)

    package_dir.joinpath("__init__.py").write_text("")
    package_dir.joinpath("content_analyser.py").write_text(
        "\n".join(
            [
                "def pre_check():",
                "    raise AssertionError('real pre_check should not run')",
                "",
                "def create_static_model_set(_scope='full'):",
                "    raise AssertionError('real create_static_model_set should not run')",
                "",
                "def collect_model_downloads():",
                "    raise AssertionError('real collect_model_downloads should not run')",
                "",
                "def get_inference_pool():",
                "    raise AssertionError('real get_inference_pool should not run')",
                "",
                "def clear_inference_pool():",
                "    raise AssertionError('real clear_inference_pool should not run')",
                "",
                "def detect_nsfw(_frame):",
                "    raise AssertionError('real detect_nsfw should not run')",
                "",
                "def analyse_frame(_frame):",
                "    raise AssertionError('real analyse_frame should not run')",
                "",
                "def analyse_image(_path):",
                "    raise AssertionError('real analyse_image should not run')",
                "",
                "def analyse_stream(_frame, _fps):",
                "    raise AssertionError('real analyse_stream should not run')",
                "",
                "def analyse_video(_path, _start, _end):",
                "    raise AssertionError('real analyse_video should not run')",
                "",
                "def resolve_execution_providers(_providers=None):",
                "    return ['cpu']",
            ]
        )
    )

    monkeypatch.delitem(sys.modules, "facefusion", raising=False)
    monkeypatch.delitem(sys.modules, "facefusion.content_analyser", raising=False)

    driver_facefusion_headless._disable_content_analysis(facefusion_root)

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
    assert inspect.getsource(stub)


def test_main_runs_facefusion_with_stubbed_content_analyser(monkeypatch, tmp_path: Path) -> None:
    facefusion_root = tmp_path / "facefusion-root"
    package_dir = facefusion_root / "facefusion"
    package_dir.mkdir(parents=True)

    observed_path = tmp_path / "observed.json"
    package_dir.joinpath("__init__.py").write_text("")
    package_dir.joinpath("content_analyser.py").write_text(
        "\n".join(
            [
                "def pre_check():",
                "    raise AssertionError('real pre_check should not run')",
                "",
                "def collect_model_downloads():",
                "    raise AssertionError('real collect_model_downloads should not run')",
                "",
                "def analyse_video(_path, _start, _end):",
                "    raise AssertionError('real analyse_video should not run')",
            ]
        )
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
    observed = json.loads(observed_path.read_text())
    assert observed == {
        "argv": ["--target-path", "target.mp4"],
        "pre_check": True,
        "downloads": [{}, {}],
        "analyse_video": False,
    }
