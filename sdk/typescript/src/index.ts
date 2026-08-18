export type Response = { text: string; parse_mode?: string };
export type CommandContext = { args: string[]; sender_id?: number; chat_id?: number; platform: string; text: string };
export type PluginContext = {
  command(name: string, handler: (ctx: CommandContext) => Promise<Response | string> | Response | string): void;
  on(event: string, handler: (payload: unknown) => void | Promise<void>): void;
  reply(text: string): Response;
  log(message: string): void;
};
export type Plugin = {
  manifest: { id: string; name: string; version: string; runtime: "typescript"; commands: Array<{ name: string; description?: string; usage?: string; access?: "owner" | "sudo" }>; events?: string[] };
  setup(context: PluginContext): void | Promise<void>;
  shutdown?(): void | Promise<void>;
};
export const definePlugin = (plugin: Plugin): Plugin => plugin;
