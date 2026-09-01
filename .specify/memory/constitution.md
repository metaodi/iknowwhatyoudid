# Project Constitution: iknowwhatyoudid

This document defines the project-wide principles, constraints, and values
that anchor every specification written under `specs/`. It is written once
and should rarely change. Any spec, plan, or implementation that conflicts
with this constitution should be revisited.

## Purpose

`iknowwhatyoudid` is a local tool to get information about how you spend
your days.

## Principles

- **Local-first**: the tool runs entirely on the user's machine.
- **Privacy by default**: user data never leaves the machine unless the
  user explicitly exports it.
- **Simplicity**: prefer straightforward, readable solutions over clever
  or heavyweight ones.
- **Transparency**: how data is collected and processed should be easy for
  the user to inspect and understand.

## Constraints

- No cloud dependency: the tool must not require a network connection or
  external service to function.
- No telemetry: the tool must not send usage data anywhere.

## Non-Goals

- This tool is not a hosted or multi-user service.
- This tool does not aim to replace dedicated time-tracking or analytics
  platforms.

## Tech Stack Preferences

_To be filled in as decisions are made (e.g., language, storage format)._
