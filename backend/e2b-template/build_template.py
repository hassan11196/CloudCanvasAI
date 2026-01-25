#!/usr/bin/env python3
"""Build E2B template for Zephior docs.

Usage:
    # Using E2B CLI (recommended):
    cd e2b-template && e2b template build --name zephior-docs

    # Or using this script:
    python build_template.py --name zephior-docs
"""
import argparse
import subprocess
import sys
from pathlib import Path


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

    # Use E2B CLI for building templates
    cmd = ["e2b", "template", "build", "--name", args.name, "--path", str(template_dir)]

    print(f"Building template '{args.name}' from {template_dir}")
    print(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, cwd=template_dir)
        print(f"Template '{args.name}' built successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Error building template: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: E2B CLI not found. Install it with: npm install -g @e2b/cli", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
