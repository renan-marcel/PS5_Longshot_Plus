"""Generate a64-kit runtime headers (a64_suyu.h, a64_fpx.h, etc.) into a target directory."""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="Generate a64-kit runtime headers.")
    parser.add_argument(
        "--out",
        default=os.path.join(ROOT, "work", "kit-gen"),
        help="Output directory for generated headers (default: work/kit-gen)",
    )
    args = parser.parse_args()

    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "lift"))
    sys.path.insert(0, os.path.join(ROOT, "nx2"))
    import a64_lift
    import a64_rtgen

    os.makedirs(args.out, exist_ok=True)
    a64_rtgen.write(args.out)
    with open(os.path.join(args.out, "a64_fpx.h"), "w", newline="\n", encoding="utf-8") as f:
        f.write(a64_lift.fpx_header(set()))
    print("SUCCESS: kit-gen headers generated in", args.out)


if __name__ == "__main__":
    main()
