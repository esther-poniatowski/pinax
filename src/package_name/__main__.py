"""
Entry point for the `pinax` package, invoked as a module.

Usage
-----
To launch the command-line interface, execute::

    python -m pinax


See Also
--------
pinax.cli: Module implementing the application's command-line interface.
"""
from .cli import app

app()
