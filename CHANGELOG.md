# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The option `-r`, `--root` names the root of the reconciliation. Without it, the root is read
  from the new environment variable `PINAX_ROOT`, and otherwise is the nearest folder, from the
  current one upwards, holding `config/tools/pinax.yml` or `pinax.yml`, and otherwise the current
  folder.
- Without `--config`, every command reads `config/tools/pinax.yml` or `pinax.yml` below the root.
  When both files exist, the command stops with status 2 and names both; when neither exists, the
  message names both places. A given `--config` is read from the current folder, as before.

### Changed

- A relative path written in the configuration file, such as `workspace`, `sources.root`,
  `library.storage`, `resolutions`, `corrections` or `staging`, resolves against the root, no
  longer against the folder of the file. A file at the root of its reconciliation, run from that
  root, reads the same paths; a file in `config/tools/` drops its `../../`; a file named by
  `--config` from another folder needs `--root` set to its own folder to keep its paths.
- An absent file given to `pinax export --header` is a usage error with status 2, no longer an
  uncaught exception.
