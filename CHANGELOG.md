# Changelog

All notable changes to this project are documented in this file.

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Migrated Python packaging, dependency management, and CI/release workflows from Poetry to uv.
- Support Python 3.11–3.14 with refreshed dependencies. PySide6 6.12 sets runtime floors of macOS 14+, Linux glibc 2.34+ (x86-64), and glibc 2.39+ (ARM64).

### Added

- Coalesced external file changes and refresh Doorstop Edit's item tree after project files change.
- Added project validation feedback with item-level findings, status counts, and a complete findings view.
- Added actions to create and remove Doorstop documents, with safeguards for child documents.
