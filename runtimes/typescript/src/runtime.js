#!/usr/bin/env node
// Minimal JSON-lines host. stdout is protocol only; plugin diagnostics use stderr.
const readline = require("node:readline");
const path = require("node:path");
const pluginPath = process.argv[2];
let plugin;
const commands = new Map();
const events = new Map();
const send = (type, payload, request_id) => {
  process.stdout.write(JSON.stringify({ protocol_version: 1, type, payload, ...(request_id ? { request_id } : {}) }) + "\n");
};
const invoke = async (message) => {
  try {
    if (message.type === "runtime.initialize") {
      plugin = require(path.resolve(pluginPath));
      plugin = plugin.default || plugin;
      const manifest = plugin.manifest || { id: path.basename(pluginPath), name: path.basename(pluginPath), version: "0.0.0", runtime: "typescript", commands: [] };
      if (typeof plugin.setup === "function") await plugin.setup({
        command: (name, handler) => commands.set(name, handler),
        on: (name, handler) => events.set(name, handler),
        reply: (text) => ({ text }), log: (value) => console.error(value)
      });
      send("runtime.ready", { manifest }, message.request_id);
    } else if (message.type === "command.execute") {
      const handler = commands.get(message.payload.name);
      if (!handler) throw new Error(`Command is not registered: ${message.payload.name}`);
      const result = await handler(message.payload);
      const response = typeof result === "string" ? { text: result } : (result || { text: "" });
      send("command.response", response, message.request_id);
    } else if (message.type === "event.emit") {
      const handler = events.get(message.payload.name);
      if (handler) await handler(message.payload.payload);
      send("event.ack", {}, message.request_id);
    } else if (message.type === "runtime.shutdown") {
      if (plugin && typeof plugin.shutdown === "function") await plugin.shutdown();
      send("runtime.stopped", {}, message.request_id);
      process.exit(0);
    } else {
      send("runtime.error", { message: `Unknown message type: ${message.type}` }, message.request_id);
    }
  } catch (error) {
    send(message.type === "command.execute" ? "command.error" : "runtime.error", { message: error.message || String(error), code: error.code || "RUNTIME_ERROR" }, message.request_id);
  }
};
readline.createInterface({ input: process.stdin }).on("line", (line) => {
  try {
    const message = JSON.parse(line);
    if (message.protocol_version !== 1 || typeof message.type !== "string" || typeof message.payload !== "object") throw new Error("Invalid protocol message");
    invoke(message);
  } catch (error) { send("runtime.error", { message: error.message, code: "INVALID_MESSAGE" }); }
});
