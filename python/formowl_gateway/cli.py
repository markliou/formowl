from __future__ import annotations


def main() -> None:
    from .jsonrpc import main as jsonrpc_main

    jsonrpc_main()


if __name__ == "__main__":
    main()
