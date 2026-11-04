import path from "node:path"

export const ADAPTER_ID = "opencode-v2"
export const PLUGIN_VERSION = "0.1.0"
export const USAGE = "Usage: /doorstop_init status | enable | recover | disable | tasks | version | select <task-id> | bootstrap <task-id> | <header> | <text> (bootstrap: task-id max 128, header max 200, text max 4000 characters)"
export type BootstrapAction = { bootstrap: { taskID: string; header: string; text: string } }
export type Action = "status" | "enable" | "recover" | "disable" | "tasks" | "version" | { select: string } | BootstrapAction

export function bootstrapPreview({ taskID, header, text }: BootstrapAction["bootstrap"]): string {
  return `Create a Doorstop requirement for task ${taskID}?\n\nTarget: doc/requirements/vision\nRoot document/prefix: VSN\nItem identifier: VSN001\n\nHeader: ${header}\nText:\n${text}`
}

export function parseDoorstopCommand(text: string): Action | undefined {
  const value = text.trim()
  if (value.length > 4500) return
  if (value === "status" || value === "enable" || value === "recover") return value
  if (value === "disable") return "disable"
  if (value === "tasks") return "tasks"
  if (value === "version") return "version"
  const select = /^select ([A-Za-z0-9][A-Za-z0-9._-]*)$/.exec(value)
  if (select) return { select: select[1] }
  const bootstrap = /^bootstrap ([A-Za-z0-9][A-Za-z0-9._-]{0,127})\s*\|\s*([^|\r\n]+?)\s*\|\s*([\s\S]+)$/.exec(value)
  if (bootstrap) {
    const header = bootstrap[2].trim(), text = bootstrap[3].trim()
    if (header && header.length <= 200 && text && text.length <= 4000) return { bootstrap: { taskID: bootstrap[1], header, text } }
  }
}

export function sessionCwd(
  session: { location: { directory: string }; subpath?: string },
  paths: Pick<typeof path, "isAbsolute" | "normalize" | "dirname" | "relative" | "sep"> = path,
): string {
  const location = session.location.directory
  if (!paths.isAbsolute(location) || paths.normalize(location) !== location) throw new Error("Invalid session location")
  const subpath = session.subpath ?? ""
  const components = subpath === "" ? [] : subpath.split("/")
  if (components.join("/") !== subpath) throw new Error("Invalid session subpath")
  if (components.some(part => part === "" || part === "." || part === ".." || part.includes("\\"))) {
    throw new Error("Invalid session subpath")
  }
  let root = location
  for (const _component of components) {
    const parent = paths.dirname(root)
    if (parent === root) throw new Error("Session subpath is outside project location")
    root = parent
  }
  const actualSubpath = paths.relative(root, location).replaceAll(paths.sep, "/")
  if (actualSubpath !== subpath) throw new Error("Session location does not match subpath")
  return root
}
