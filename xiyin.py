"""Entry executable from any cwd; the Windows machine policy still applies."""
from xiyin_runtime.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
