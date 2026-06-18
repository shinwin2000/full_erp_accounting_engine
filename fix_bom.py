from __future__ import annotations

import os


def remove_bom_from_file(filepath: str) -> None:
    """Remove UTF-8 BOM (U+FEFF) from a file if present."""
    with open(filepath, "rb") as f:
        content = f.read()

    # Check if file starts with BOM bytes (EF BB BF)
    if content.startswith(b"\xef\xbb\xbf"):
        # Write back without the first 3 bytes
        with open(filepath, "wb") as f:
            f.write(content[3:])
        print(f"✅ Fixed: {filepath}")


def main() -> None:
    """Walk through all Python files and remove BOM."""
    print("Scanning and fixing files with BOM (U+FEFF)...")
    for root, _dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                remove_bom_from_file(filepath)
    print("Done!")


if __name__ == "__main__":
    main()
