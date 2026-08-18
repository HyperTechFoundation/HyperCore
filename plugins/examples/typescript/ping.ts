import { definePlugin } from "../../../../sdk/typescript/src/index";

export default definePlugin({
  manifest: {
    id: "typescript-ping", name: "TypeScript Ping", version: "1.0.0", runtime: "typescript",
    commands: [{ name: "tsping", description: "Reply from a TypeScript plugin", access: "sudo" }], events: ["startup_complete"],
  },
  setup(context) {
    context.command("tsping", () => context.reply("pong from TypeScript"));
    context.on("startup_complete", () => context.log("TypeScript ping received startup"));
  },
  shutdown() { console.error("TypeScript ping stopped"); },
});
