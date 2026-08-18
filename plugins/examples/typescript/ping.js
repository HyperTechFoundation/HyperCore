module.exports = {
  manifest: {
    id: "typescript-ping", name: "TypeScript Ping", version: "1.0.0", runtime: "typescript",
    commands: [{ name: "tsping", description: "Reply from a TypeScript plugin", access: "sudo" }], events: ["startup_complete"]
  },
  async setup(context) {
    context.command("tsping", () => "pong from TypeScript");
    context.on("startup_complete", () => context.log("TypeScript ping received startup"));
  },
  async shutdown() { console.error("TypeScript ping stopped"); }
};
