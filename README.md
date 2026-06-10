# LogicDaemon-py3-win32-symlink-resolve

### resolve_win32_symlink

Resolve Windows symlink targets using the Windows API.
Unlike os.readlink(), this can resolve both absolute and relative symlinks
correctly on Windows, including those that point to UNC paths.

## Installation

```sh
pip install LogicDaemon-win32-symlink-resolve
```

## Usage

```python
from pathlib import Path
from resolve_win32_symlink import resolve_symlink

# Returns the target Path if it's a symlink, or None if the path is not a valid IO_REPARSE_TAG_SYMLINK.
target_path: Path | None = resolve_symlink(Path(r'C:\path\to\symlink'))

if target_path:
    print(f"Symlink points to: {target_path}")
```

### Important Notes and Limitations

- **Windows Only:** This package relies on `ctypes` bindings for `kernel32.dll` and Windows-specific `DeviceIoControl` codes. It is exclusively for Windows environments.
- **Supported Reparse Points:** This module specifically resolves symlinks (`IO_REPARSE_TAG_SYMLINK`). Other types of reparse points, such as directory junctions (`IO_REPARSE_TAG_MOUNT_POINT`), are not supported and will resolve to None.
- **Path Prefixes:** Windows symlink targets often use the NT device prefix `\??\` in the raw substitution name. To preserve idiomatic paths, `resolve_symlink` extracts the cleaner `PrintName` when available, falling back to the target's `SubstituteName` only if `PrintName` is empty.

## Build and publish to PyPI

```bash
# Ensure you have the build tool and twine installed
pip install build twine

# Build the distribution packages
python -m build

# Upload to PyPI (this will ask for credentials)
twine upload dist/*
```

See [Uploading the distribution archives](https://packaging.python.org/en/latest/tutorials/packaging-projects/#uploading-the-distribution-archives) for more details.
