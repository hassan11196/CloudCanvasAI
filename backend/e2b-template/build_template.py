#!/usr/bin/env python3
"""Build E2B template for Zephior docs.

Usage:
    python build_template.py --name zephior-docs
"""
import argparse
import inspect
import sys
from pathlib import Path


def _find_builder():
    try:
        from e2b import Template  # type: ignore
    except Exception:
        Template = None

    if Template and hasattr(Template, "build"):
        return Template.build

    try:
        import e2b  # type: ignore
    except Exception:
        return None

    if hasattr(e2b, "Template") and hasattr(e2b.Template, "build"):
        return e2b.Template.build

    for module_name in ("template", "templates"):
        module = getattr(e2b, module_name, None)
        if module and hasattr(module, "build"):
            return module.build

    if hasattr(e2b, "build_template"):
        return e2b.build_template

    return None


def _build_kwargs(builder, name: str, template_dir: Path, skip_cache: bool) -> dict:
    sig = inspect.signature(builder)
    kwargs = {}

    if "name" in sig.parameters:
        kwargs["name"] = name
    elif "alias" in sig.parameters:
        kwargs["alias"] = name

    if "path" in sig.parameters:
        kwargs["path"] = str(template_dir)
    elif "template_dir" in sig.parameters:
        kwargs["template_dir"] = str(template_dir)

    if "skip_cache" in sig.parameters:
        kwargs["skip_cache"] = skip_cache
    elif "no_cache" in sig.parameters:
        kwargs["no_cache"] = skip_cache

    return kwargs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build E2B template for Zephior docs")
    parser.add_argument("--name", "--alias", required=True, help="Template name")
    parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Force rebuild without cache",
    )
    args = parser.parse_args()

    template_dir = Path(__file__).parent

    builder = _find_builder()
    if not builder:
        print(
            "Error: E2B Python SDK not found or missing template builder. "
            "Install it with: pip install e2b",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Building template '{args.name}' from {template_dir}")
    print("Running: E2B Python SDK template build")

    try:
        kwargs = _build_kwargs(builder, args.name, template_dir, args.skip_cache)
        builder(**kwargs)
        print(f"Template '{args.name}' built successfully!")
    except Exception as e:
        print(f"Error building template: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
