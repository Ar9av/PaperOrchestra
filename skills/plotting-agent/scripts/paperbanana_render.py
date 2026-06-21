#!/usr/bin/env python3
"""
paperbanana_render.py — Optional PaperBanana backbone for the plotting-agent's
render step.

PaperBanana (Zhu et al., 2026 — https://github.com/dwzhu-pku/PaperBanana) is the
default backbone used by the PaperOrchestra paper (arXiv:2604.05018, §4 Step 2)
for generating publication-quality diagrams and plots.  This wrapper bridges the
plotting-agent's figure spec format to PaperBanana's
Retriever → Planner → Stylist → Visualizer → Critic pipeline.

SETUP (one-time):
    1. Clone PaperBanana:
           git clone https://github.com/dwzhu-pku/PaperBanana
    2. Install its dependencies:
           cd PaperBanana && uv pip install -r requirements.txt
    3. Copy & fill in the config:
           cp configs/model_config.template.yaml configs/model_config.yaml
           # add google_api_key or openrouter_api_key
    4. Export the path:
           export PAPERBANANA_PATH="/path/to/PaperBanana"

OPTIONAL model overrides (read from environment):
    PAPERBANANA_MAIN_MODEL        (default: value in model_config.yaml)
    PAPERBANANA_IMAGE_MODEL       (default: value in model_config.yaml)

Usage:
    # preflight check — prints backend status and exits
    python paperbanana_render.py --check-backend

    # render a diagram figure
    python paperbanana_render.py \\
        --figure-id fig_overview \\
        --caption "Figure 1: Overview of our framework." \\
        --content-file workspace/inputs/idea.md \\
        --task diagram \\
        --aspect-ratio "16:9" \\
        --out workspace/figures/fig_overview.png

    # render a plot figure with fewer critic rounds
    python paperbanana_render.py \\
        --figure-id fig_results \\
        --caption "Figure 2: Comparison of baselines." \\
        --content-file workspace/inputs/experimental_log.md \\
        --task plot \\
        --aspect-ratio "5:4" \\
        --max-critic-rounds 1 \\
        --out workspace/figures/fig_results.png

Exit codes:
    0   image saved successfully
    1   PaperBanana pipeline error
    2   PAPERBANANA_PATH not set or invalid — caller should fall back to matplotlib
"""

import argparse
import asyncio
import base64
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ASPECT_RATIOS = {
    "1:1", "1:4", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "9:16", "16:9", "21:9",
}


def _paperbanana_path() -> Path | None:
    for key in ("PAPERBANANA_PATH", "PAPERVIZAGENT_PATH"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        p = Path(raw)
        # Sanity-check that it looks like a PaperBanana / PaperVizAgent clone
        if (p / "utils" / "paperviz_processor.py").exists():
            return p
    return None


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _load_runtime_env() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    for path in (
        Path.home() / ".paperorchestra" / "config",
        repo_root / ".env",
        Path("/Users/jeff/Codex_projects/PaperBanana/.env"),
    ):
        _load_env_file(path)


def _maybe_reexec_with_paperbanana_python() -> None:
    pb = _paperbanana_path()
    if pb is None:
        return
    python = pb / ".venv" / "bin" / "python"
    if not python.exists():
        return
    if Path(sys.executable).resolve() == python.resolve():
        return
    os.execve(str(python), [str(python), __file__, *sys.argv[1:]], os.environ.copy())


def _dependency_status(pb: Path) -> list[tuple[str, bool, str]]:
    import importlib.util

    sys.path.insert(0, str(pb))
    modules = [
        "yaml",
        "numpy",
        "PIL",
        "google.genai",
        "aiofiles",
        "json_repair",
        "anthropic",
        "openai",
        "matplotlib",
        "huggingface_hub",
        "tqdm",
        "utils.paperviz_processor",
        "agents.vanilla_agent",
        "agents.planner_agent",
        "agents.visualizer_agent",
        "agents.stylist_agent",
        "agents.critic_agent",
        "agents.retriever_agent",
        "agents.polish_agent",
    ]
    status: list[tuple[str, bool, str]] = []
    for module in modules:
        try:
            found = importlib.util.find_spec(module) is not None
            status.append((module, found, "" if found else "not found"))
        except Exception as exc:
            status.append((module, False, f"{type(exc).__name__}: {exc}"))
    return status


def _model_api_key_configured(pb: Path) -> bool:
    if any(
        os.environ.get(key, "").strip()
        for key in ("GOOGLE_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    ):
        return True
    config_path = pb / "configs" / "model_config.yaml"
    if not config_path.exists():
        return False
    try:
        import yaml

        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    api_keys = payload.get("api_keys") or {}
    return any(
        str(api_keys.get(key, "") or "").strip()
        for key in ("google_api_key", "openrouter_api_key", "openai_api_key", "anthropic_api_key")
    )


def _env_bool(key: str, default: bool = True) -> bool:
    raw_value = str(os.environ.get(key, "") or "").strip().lower()
    if not raw_value:
        return default
    return raw_value not in {"0", "false", "no", "off"}


def _codex_handoff_enabled() -> bool:
    return _env_bool("PAPERBANANA_CODEX_IMAGE_HANDOFF", default=True)


def _codex_model() -> str:
    return (
        os.environ.get("PAPERBANANA_CODEX_MODEL", "").strip()
        or os.environ.get("PAPERORCHESTRA_CODEX_MODEL", "").strip()
        or "gpt-5.5"
    )


def _codex_reasoning_effort() -> str:
    return (
        os.environ.get("PAPERBANANA_CODEX_REASONING_EFFORT", "").strip()
        or os.environ.get("PAPERORCHESTRA_CODEX_REASONING_EFFORT", "").strip()
        or "xhigh"
    )


def _codex_timeout_seconds() -> float:
    raw_value = (
        os.environ.get("PAPERBANANA_CODEX_TIMEOUT_SECONDS", "").strip()
        or os.environ.get("PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS", "").strip()
        or "900"
    )
    try:
        return max(float(raw_value), 1.0)
    except ValueError:
        return 900.0


def _build_codex_image_prompt(
    *,
    figure_id: str,
    caption: str,
    content: str,
    task: str,
    aspect_ratio: str,
    out_path: Path,
) -> str:
    return f"""Create one publication-quality academic {task} figure as a PNG.

You are the Codex image-generation handoff for PaperOrchestra/PaperBanana. Use local code generation to create the image artifact directly at the required path. Prefer Python with matplotlib/Pillow; use clean academic styling, readable labels, and a restrained color palette. Do not require network access, do not ask follow-up questions, and do not write anywhere except the requested output path and small adjacent verification artifacts if needed.

Model requirement from caller: GPT-5.5 with xhigh reasoning.

Figure id: {figure_id}
Task: {task}
Aspect ratio: {aspect_ratio}
Caption/objective:
{caption}

Source content:
{content}

Required output path:
{out_path}

Acceptance criteria:
- Create the exact file at the required output path.
- The file must be a valid PNG.
- The image should be at least 1024 bytes.
- Text must be readable and not overlap.
- Use the aspect ratio requested above.
- Verify the PNG exists before finishing.
"""


def _run_codex_image_handoff(
    *,
    figure_id: str,
    caption: str,
    content: str,
    content_file: Path,
    task: str,
    aspect_ratio: str,
    out_path: Path,
) -> int:
    out_path = out_path.expanduser().resolve()
    artifact_dir = out_path.parent / ".paperbanana_codex_handoff"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = artifact_dir / f"{out_path.stem}.prompt.md"
    transcript_path = artifact_dir / f"{out_path.stem}.codex-message.txt"
    log_path = artifact_dir / f"{out_path.stem}.codex.log"
    prompt = _build_codex_image_prompt(
        figure_id=figure_id,
        caption=caption,
        content=content,
        task=task,
        aspect_ratio=aspect_ratio,
        out_path=out_path,
    )
    prompt_path.write_text(prompt, encoding="utf-8")

    codex_bin = os.environ.get("CODEX_BIN", "").strip() or "codex"
    repo_root = Path(__file__).resolve().parents[3]
    command = [
        codex_bin,
        "exec",
        "-m",
        _codex_model(),
        "-c",
        f'model_reasoning_effort="{_codex_reasoning_effort()}"',
        "--sandbox",
        "workspace-write",
        "-C",
        str(repo_root),
        "--add-dir",
        str(out_path.parent),
        "--add-dir",
        str(content_file.expanduser().resolve().parent),
        "-o",
        str(transcript_path),
        prompt,
    ]
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n")
        process = subprocess.run(
            command,
            cwd=str(repo_root),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            timeout=_codex_timeout_seconds(),
            check=False,
        )
    if process.returncode != 0:
        print(
            f"ERROR: Codex image handoff failed with exit code {process.returncode}. "
            f"See {log_path}",
            file=sys.stderr,
        )
        return 1
    if not out_path.exists():
        print(
            f"ERROR: Codex image handoff completed but did not create {out_path}. "
            f"See {log_path}",
            file=sys.stderr,
        )
        return 1
    if out_path.stat().st_size < 1024:
        print(
            f"ERROR: Codex image handoff created a suspiciously small PNG at {out_path}. "
            f"See {log_path}",
            file=sys.stderr,
        )
        return 1
    if out_path.suffix.lower() == ".png" and out_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        print(
            f"ERROR: Codex image handoff output is not a valid PNG: {out_path}. "
            f"See {log_path}",
            file=sys.stderr,
        )
        return 1
    print(
        f"Saved via Codex image handoff: {out_path} "
        f"(model={_codex_model()}, reasoning={_codex_reasoning_effort()})",
        file=sys.stderr,
    )
    return 0


def check_backend() -> None:
    pb = _paperbanana_path()
    if pb is None:
        env_val = os.environ.get("PAPERBANANA_PATH", "")
        if env_val:
            print(
                f"PAPERBANANA_PATH={env_val!r} is set but does not point to a valid "
                "PaperBanana clone (utils/paperviz_processor.py not found).\n"
                "Clone PaperBanana and set PAPERBANANA_PATH to its root directory."
            )
        else:
            print(
                "PAPERBANANA_PATH is NOT set.  PaperBanana backbone is unavailable.\n"
                "The plotting-agent will use the matplotlib fallback (render_matplotlib.py\n"
                "/ render_diagram.py).\n\n"
                "To enable PaperBanana:\n"
                "  1. git clone https://github.com/dwzhu-pku/PaperBanana\n"
                "  2. cd PaperBanana && uv pip install -r requirements.txt\n"
                "  3. cp configs/model_config.template.yaml configs/model_config.yaml\n"
                "     # fill in google_api_key or openrouter_api_key\n"
                "  4. export PAPERBANANA_PATH=/path/to/PaperBanana"
            )
        sys.exit(2)

    print(f"PaperBanana found at: {pb}")
    print(f"  Python                  = {sys.executable}")
    main_model = os.environ.get("PAPERBANANA_MAIN_MODEL", "(from model_config.yaml)")
    img_model = os.environ.get("PAPERBANANA_IMAGE_MODEL", "(from model_config.yaml)")
    print(f"  PAPERBANANA_MAIN_MODEL  = {main_model}")
    print(f"  PAPERBANANA_IMAGE_MODEL = {img_model}")
    config_path = pb / "configs" / "model_config.yaml"
    print(f"  model_config.yaml       = {config_path.exists()}")
    has_key = _model_api_key_configured(pb)
    print(f"  model_api_key_configured = {has_key}")
    print(f"  codex_image_handoff    = {_codex_handoff_enabled()}")
    print(f"  codex_handoff_model    = {_codex_model()}")
    print(f"  codex_handoff_reasoning = {_codex_reasoning_effort()}")
    missing = [(module, detail) for module, ok, detail in _dependency_status(pb) if not ok]
    if missing:
        print("Backend dependencies are incomplete:")
        for module, detail in missing:
            print(f"  {module}: {detail}")
        sys.exit(1)
    if has_key:
        print("Backend is ready for generation.")
    elif _codex_handoff_enabled():
        print("Backend imports are ready. Generation will hand off to Codex when no model API key is configured.")
    else:
        print("Backend imports are ready. Generation requires GOOGLE_API_KEY or OPENROUTER_API_KEY.")
    sys.exit(0)


# ---------------------------------------------------------------------------
# PaperBanana invocation
# ---------------------------------------------------------------------------

async def _run_pipeline(
    pb_path: Path,
    input_data: dict,
    task_name: str,
    max_critic_rounds: int,
    main_model: str,
    image_gen_model: str,
) -> dict | None:
    """Import PaperBanana from pb_path and run the full pipeline on a single item."""
    sys.path.insert(0, str(pb_path))
    try:
        from utils import config as pb_config  # type: ignore
        from utils import paperviz_processor    # type: ignore
        from agents.vanilla_agent import VanillaAgent      # type: ignore
        from agents.planner_agent import PlannerAgent      # type: ignore
        from agents.visualizer_agent import VisualizerAgent  # type: ignore
        from agents.stylist_agent import StylistAgent      # type: ignore
        from agents.critic_agent import CriticAgent        # type: ignore
        from agents.retriever_agent import RetrieverAgent  # type: ignore
        from agents.polish_agent import PolishAgent        # type: ignore
    except ImportError as exc:
        print(
            f"ERROR: Could not import PaperBanana from {pb_path}: {exc}\n"
            "Make sure you have run: uv pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    exp_config = pb_config.ExpConfig(
        dataset_name="paper-orchestra",
        task_name=task_name,
        split_name="single",
        exp_mode="demo_full",          # Retriever → Planner → Stylist → Visualizer → Critic
        retrieval_setting="auto",
        max_critic_rounds=max_critic_rounds,
        main_model_name=main_model,
        image_gen_model_name=image_gen_model,
        work_dir=pb_path,
    )

    processor = paperviz_processor.PaperVizProcessor(
        exp_config=exp_config,
        vanilla_agent=VanillaAgent(exp_config=exp_config),
        planner_agent=PlannerAgent(exp_config=exp_config),
        visualizer_agent=VisualizerAgent(exp_config=exp_config),
        stylist_agent=StylistAgent(exp_config=exp_config),
        critic_agent=CriticAgent(exp_config=exp_config),
        retriever_agent=RetrieverAgent(exp_config=exp_config),
        polish_agent=PolishAgent(exp_config=exp_config),
    )

    results = []
    async for result in processor.process_queries_batch(
        [input_data], max_concurrent=1, do_eval=False
    ):
        results.append(result)

    return results[0] if results else None


def _extract_best_image_b64(result: dict, task_name: str) -> str | None:
    """
    Find the best (latest critic round) base64 JPEG image in the result dict.

    PaperBanana stores images as base64 JPEG strings keyed by:
        target_{task_name}_critic_descN_base64_jpg   (critic rounds, latest wins)
        target_{task_name}_stylist_desc0_base64_jpg  (stylist fallback)
        target_{task_name}_desc0_base64_jpg          (planner fallback)
        vanilla_{task_name}_base64_jpg               (last resort)
    """
    # Try critic rounds from high to low
    for round_idx in range(9, -1, -1):
        key = f"target_{task_name}_critic_desc{round_idx}_base64_jpg"
        if result.get(key):
            return result[key]

    # Try eval_image_field pointer
    eval_key = result.get("eval_image_field")
    if eval_key and result.get(eval_key):
        return result[eval_key]

    for key in [
        f"target_{task_name}_stylist_desc0_base64_jpg",
        f"target_{task_name}_desc0_base64_jpg",
        f"vanilla_{task_name}_base64_jpg",
    ]:
        if result.get(key):
            return result[key]

    return None


def _save_png(b64_jpeg: str, out_path: Path, dpi: int = 300) -> None:
    """Decode a base64 JPEG and save as a 300-DPI PNG."""
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        print(
            "ERROR: Pillow is not installed. Run: pip install pillow",
            file=sys.stderr,
        )
        sys.exit(1)

    img_bytes = base64.b64decode(b64_jpeg)
    img = Image.open(BytesIO(img_bytes))

    # Preserve pixel dimensions; embed 300 DPI metadata so LaTeX sees it
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), format="PNG", dpi=(dpi, dpi))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    _load_runtime_env()
    _maybe_reexec_with_paperbanana_python()

    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--check-backend", action="store_true",
        help="Print PaperBanana availability and exit (no figure generated)",
    )
    p.add_argument("--figure-id", help="Figure ID from the plotting plan (e.g. fig_overview)")
    p.add_argument(
        "--caption", required=False,
        help="Figure caption / objective from the figure spec (used as visual intent)",
    )
    p.add_argument(
        "--content-file", type=Path, required=False,
        help="Path to idea.md or experimental_log.md — used as method context",
    )
    p.add_argument(
        "--task", choices=["diagram", "plot"], default="diagram",
        help="Figure task type (default: diagram)",
    )
    p.add_argument(
        "--aspect-ratio", default="16:9",
        help=f"Aspect ratio string (default: 16:9). "
             f"Allowed: {', '.join(sorted(_VALID_ASPECT_RATIOS))}",
    )
    p.add_argument(
        "--max-critic-rounds", type=int, default=3,
        help="Number of Critic refinement rounds (default: 3, range: 0–5)",
    )
    p.add_argument(
        "--out", type=Path, required=False,
        help="Output PNG path (e.g. workspace/figures/fig_overview.png)",
    )
    args = p.parse_args()

    if args.check_backend:
        check_backend()   # exits internally

    # --- validate required args for actual rendering ---
    missing = [f for f, v in [("--caption", args.caption), ("--out", args.out)] if v is None]
    if missing:
        p.error(f"The following arguments are required for rendering: {', '.join(missing)}")

    if args.content_file is None or not args.content_file.exists():
        p.error(
            f"--content-file is required and must exist. "
            f"Got: {args.content_file}"
        )

    aspect_ratio = args.aspect_ratio
    if aspect_ratio not in _VALID_ASPECT_RATIOS:
        print(
            f"WARN: aspect ratio {aspect_ratio!r} is not in the standard set "
            f"({', '.join(sorted(_VALID_ASPECT_RATIOS))}). Passing as-is to PaperBanana.",
            file=sys.stderr,
        )

    # --- check backend availability ---
    pb_path = _paperbanana_path()
    if pb_path is None:
        print(
            "INFO: PAPERBANANA_PATH not set or invalid. "
            "Falling back to matplotlib renderer.",
            file=sys.stderr,
        )
        sys.exit(2)   # caller uses exit code 2 to trigger fallback

    content = args.content_file.read_text(encoding="utf-8")
    figure_id = args.figure_id or args.out.stem

    if not _model_api_key_configured(pb_path):
        if _codex_handoff_enabled():
            print(
                "PaperBanana has no model API key configured; handing image generation to Codex "
                f"(model={_codex_model()}, reasoning={_codex_reasoning_effort()}).",
                file=sys.stderr,
            )
            return _run_codex_image_handoff(
                figure_id=figure_id,
                caption=args.caption,
                content=content,
                content_file=args.content_file,
                task=args.task,
                aspect_ratio=aspect_ratio,
                out_path=args.out,
            )
        print(
            "ERROR: PaperBanana is installed, but no model API key is configured. "
            "Set GOOGLE_API_KEY or OPENROUTER_API_KEY in the environment, "
            "~/.paperorchestra/config, or PaperBanana/configs/model_config.yaml.",
            file=sys.stderr,
        )
        return 1

    input_data = {
        "filename":        f"{figure_id}_candidate_0",
        "candidate_id":    0,
        "caption":         args.caption,
        "content":         content,
        "visual_intent":   args.caption,
        "additional_info": {"rounded_ratio": aspect_ratio},
        "max_critic_rounds": max(0, min(5, args.max_critic_rounds)),
    }

    main_model = os.environ.get("PAPERBANANA_MAIN_MODEL", "")
    image_gen_model = os.environ.get("PAPERBANANA_IMAGE_MODEL", "")

    print(
        f"PaperBanana: generating {args.task} figure '{figure_id}' "
        f"({aspect_ratio}, {args.max_critic_rounds} critic rounds) …",
        file=sys.stderr,
    )

    result = asyncio.run(
        _run_pipeline(
            pb_path=pb_path,
            input_data=input_data,
            task_name=args.task,
            max_critic_rounds=args.max_critic_rounds,
            main_model=main_model,
            image_gen_model=image_gen_model,
        )
    )

    if result is None:
        print("ERROR: PaperBanana returned no result.", file=sys.stderr)
        return 1

    b64 = _extract_best_image_b64(result, args.task)
    if not b64:
        print(
            f"ERROR: No image found in PaperBanana result. "
            f"Available keys: {[k for k in result if 'base64' in k]}",
            file=sys.stderr,
        )
        return 1

    _save_png(b64, args.out)
    print(f"Saved: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
