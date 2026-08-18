# HyperCore

HyperCore is a small Python-first Telegram core for userbot deployments with optional bot polling. Version 0.5.0 adds TypeScript as another way to build plugins without creating a second core.

## Architecture

The Python kernel remains the source of truth for commands, authorization, events, lifecycle, storage, and platform adapters. An optional Node process hosts TypeScript plugins and talks to the kernel through versioned JSON messages over stdin/stdout. The external process receives capabilities through messages, not internal Python objects.

## Plugins

Python plugins live in `hypercore/plugins/`, expose `PLUGIN_MANIFEST`, and define `setup(core)`. If no module list is supplied, the loader discovers package modules and validates stable IDs, versions, dependencies, commands, events, capabilities, and runtime.

The event bus keeps a bounded history and supports `on()`/`off()` subscriptions. Lifecycle hooks remain simple sync-or-async callbacks and retain the existing error policy.

## TypeScript plugins

The Node host is `runtimes/typescript/src/runtime.js`; the SDK source is under `sdk/typescript/src`. A plugin has one contract: exported `manifest`, `setup(context)`, and optional `shutdown()`. Commands and event subscriptions are registered from `setup`; there is no second `execute()` API. Build the SDK with TypeScript, then point `.env` at a plugin entry point:

```text
TYPESCRIPT_PLUGIN=plugins/examples/typescript/ping.js
```

The example plugin exposes `tsping`, handles `startup_complete`, and has a clean shutdown hook. The included `.js` file is directly runnable for tests; `ping.ts` demonstrates the SDK authoring API.

## Protocol

Each line is one JSON object with `protocol_version`, `type`, optional `request_id`, and an object `payload`. V0.5.0 uses `runtime.initialize`, `runtime.ready`, `command.execute`, `command.response`, `event.emit`, `event.ack`, and `runtime.shutdown`. stdout is reserved for protocol traffic; runtime diagnostics go to stderr.

## Configuration and development

Python 3.11+ and the Telegram libraries are required. Edit the root `.env` with `API_ID` and `API_HASH`; `BOT_TOKEN`, `DATABASE_URL`, `LOG_CHANNEL`, and `TYPESCRIPT_PLUGIN` are optional. Run with `bash startup` or `python -m hypercore`.

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```

Run the credential-free health check with:

```bash
python -m hypercore --health
```

It validates the Python core, plugins, protocol, process runtime, storage, and clean startup/shutdown. Node.js and TypeScript are optional; when unavailable they are reported as a warning rather than a core failure.

Node is only required when a TypeScript plugin is enabled. The TypeScript SDK can be compiled with the local project’s TypeScript toolchain and is intentionally dependency-light.

## Migration

Existing Python plugins continue to work. Their old `name`, `version`, `description`, `commands`, and `platforms` manifest fields remain valid; new fields are optional. V0.5.0 changes the core version and adds discovery, but does not require a Python plugin rewrite.
