"""
Entry point for ``python -m nibbler``.

When Python executes a package with ``python -m nibbler``, it runs this
``__main__.py`` module.  All it does is import and invoke the CLI entry
point defined in :mod:`nibbler.cli`.

Usage::

    python -m nibbler <command> <woz_file> [options]

Example::

    python -m nibbler info  game.woz
    python -m nibbler scan  game.woz
    python -m nibbler flux  game.woz -o disk_surface.png
    python -m nibbler boot  game.woz --stop 0x4000 --dump 0x4000-0xA7FF
"""
from .cli import main

main()
