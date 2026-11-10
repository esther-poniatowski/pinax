# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Without `--config`, every command reads `config/tools/pinax.yml` below the current directory,
  then `pinax.yml`. A given `--config` is read as before, and a missing configuration names both
  places.
