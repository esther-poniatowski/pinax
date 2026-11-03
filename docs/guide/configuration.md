# Configuration

<!--
TODO: Replace this template with project-specific configuration documentation.

Document each configuration source the package supports: config files, environment
variables, and CLI flags. Specify the precedence order if multiple sources overlap.
-->

## Config Directory

The `config/` directory holds tool and linter configurations, not application
settings.

### `config/tools/`

External tool settings, each in its native format:

| File | Tool |
| ---- | ---- |
| `black.toml` | Black (formatter) |
| `mypy.ini` | Mypy (type checker) |
| `pylintrc.ini` | Pylint (linter, production code) |
| `pylintrc_tests.ini` | Pylint (linter, test code) |
| `pyrightconfig.json` | Pyright (type checker) |
| `releaserc.toml` | Semantic Release |

### `config/dictionaries/`

Word lists for the CSpell spell-checker extension:

| File | Scope |
| ---- | ----- |
| `project.txt` | Project-specific names and concepts. |
| `python.txt` | Python names (functions, modules) and programming concepts. |
| `tools.txt` | Tool-specific names and project management concepts. |

## Application Settings

<!--
TODO: Document runtime configuration once the package defines it.

### Configuration File

Describe the config file format, location, and schema.

```yaml
# Example configuration
key: value
```

### Environment Variables

| Variable | Description | Default | Required |
| -------- | ----------- | ------- | -------- |
| `EXAMPLE_VAR` | Description. | None | Yes |

### Precedence

Configuration values resolve in this order (highest priority first):

1. Command-line arguments
2. Environment variables
3. Configuration file
4. Built-in defaults
-->
