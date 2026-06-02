# Changelog

All notable changes to LavronOS HA Bridge will be documented in this file.

## [Unreleased]

## [0.1.3] - 2026-06-02

### Changed
- Added periodic snapshot refresh so LavronOS receives Home Assistant area, device and entity registry changes without disconnecting and re-pairing the bridge.

### Fixed
- Fixed Home Assistant registry serialization so dict-backed area, device and entity registry entries keep their stable ids and names.
- Fixed snapshot startup failures caused by mutating Home Assistant read-only state dictionaries.
