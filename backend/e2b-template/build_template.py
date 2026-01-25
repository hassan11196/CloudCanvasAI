import argparse
from pathlib import Path

from e2b import Template


def main() -> None:
    parser = argparse.ArgumentParser(description="Build E2B template for Zephior docs")
    parser.add_argument("--alias", required=True, help="Template alias name")
    parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Force rebuild without cache",
    )
    args = parser.parse_args()

    dockerfile_path = Path(__file__).parent / "Dockerfile"
    template = Template().from_dockerfile(str(dockerfile_path))
    if args.skip_cache:
        template.skip_cache()

    Template.build(template, alias=args.alias)
    print(f"Template build submitted for alias: {args.alias}")


if __name__ == "__main__":
    main()
