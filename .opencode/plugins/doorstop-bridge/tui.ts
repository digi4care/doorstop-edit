import { Plugin } from "@opencode/plugin/tui"
import { ADAPTER_ID, bootstrapPreview, parseDoorstopCommand, sessionCwd, USAGE } from "./commands.ts"
import { doorstopInitRpc } from "./rpc.ts"

type Policy = "enabled" | "disabled" | "unenforced" | "blocked"
type Status = { policy: Policy; ready: boolean; reason: string }
type Toast = { message: string; variant: "success" | "info" | "warning" | "error" }
type ConfirmationRequest = {
  requestID: string
  sessionID: string
  action: "disable" | "bootstrap"
  directory: string
  expiresAt: number
  taskID?: string
  header?: string
  text?: string
}

function confirmationRequest(value: unknown): ConfirmationRequest | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return
  const data = value as Record<string, unknown>
  if (Object.keys(data).some(key => !["requestID", "sessionID", "action", "directory", "expiresAt", "taskID", "header", "text"].includes(key))) return
  if (typeof data.requestID !== "string" || !data.requestID || typeof data.sessionID !== "string" || !data.sessionID
    || (data.action !== "disable" && data.action !== "bootstrap")
    || typeof data.directory !== "string" || !data.directory
    || typeof data.expiresAt !== "number" || !Number.isFinite(data.expiresAt) || data.expiresAt <= Date.now()) return
  if (data.action === "disable" && ["taskID", "header", "text"].some(key => Object.hasOwn(data, key))) return
  if (data.action === "bootstrap" && (typeof data.taskID !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(data.taskID)
    || typeof data.header !== "string" || !data.header.trim() || data.header.length > 200
    || typeof data.text !== "string" || !data.text.trim() || data.text.length > 4000)) return
  return data as ConfirmationRequest
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === "string") return error
  if (typeof error === "object" && error !== null) {
    const message = (error as { message?: unknown }).message
    if (typeof message === "string") return message
    try { return JSON.stringify(error) } catch {}
  }
  return String(error)
}

export function versionMessage(value: unknown): string {
  const result = value as { bridgeVersion?: unknown; pluginVersion?: unknown } | null
  const semver = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/
  if (!result || typeof result.bridgeVersion !== "string" || typeof result.pluginVersion !== "string"
    || !semver.test(result.bridgeVersion) || !semver.test(result.pluginVersion)) {
    throw new Error("Bridge or OpenCode plugin version is unavailable or invalid")
  }
  return `Bridge ${result.bridgeVersion}; OpenCode plugin ${result.pluginVersion}`
}

function taskErrorMessage(error: unknown): string {
  const value = error as { message?: unknown; stderr?: unknown }
  const stderr = value && typeof value.stderr === "string" ? value.stderr
    : value?.stderr instanceof Uint8Array ? new TextDecoder().decode(value.stderr) : ""
  if (stderr.trim()) {
    try {
      const parsed: unknown = JSON.parse(stderr)
      if (typeof parsed === "object" && parsed !== null) {
        const payload = parsed as { message?: unknown; error?: unknown }
        if (typeof payload.message === "string") return payload.message
        if (typeof payload.error === "string") return payload.error
        if (typeof payload.error === "object" && payload.error !== null && typeof (payload.error as { message?: unknown }).message === "string") {
          return (payload.error as { message: string }).message
        }
      }
    } catch {}
    return stderr.trim()
  }
  return error instanceof Error ? error.message : String(error)
}

function statusFrom(value: unknown): Status | undefined {
  if (typeof value !== "object" || value === null) return
  const data = value as Record<string, unknown>
  if (
    (data.policy !== "enabled" && data.policy !== "disabled" && data.policy !== "unenforced" && data.policy !== "blocked") ||
    typeof data.ready !== "boolean"
  ) return
  return { policy: data.policy, ready: data.ready, reason: typeof data.reason === "string" ? data.reason : "" }
}

function throwRpcFailure(response: unknown): void {
  if (typeof response !== "object" || response === null || (response as { ok?: unknown }).ok !== false) return
  const error = (response as { error?: unknown }).error
  const message = typeof error === "object" && error !== null ? (error as { message?: unknown }).message : undefined
  throw new Error(typeof message === "string" && message.trim() ? message : "Doorstop bridge operation failed. Check the project and try again.")
}

function statusToast(status: Status, recovered: boolean): Toast {
  const prefix = recovered ? "Recovered. " : ""
  if (status.policy === "enabled" && status.ready) {
    return { message: `${prefix}Policy: enabled; adapter ready.`, variant: "success" }
  }
  if (status.policy === "blocked") {
    const detail = status.reason === "conflicting policy markers" ? " Conflicting policy markers." : ""
    return { message: `${prefix}Policy: blocked; not ready.${detail}`, variant: "error" }
  }
  return {
    message: `${prefix}Policy: ${status.policy}; not ready.`,
    variant: status.policy === "enabled" ? "warning" : "info",
  }
}

export function createTuiPlugin(runBootstrap = async (cwd: string, args: string[]) => {
  const result = await Bun.$`doorstop-bridge ${args}`.cwd(cwd).quiet()
  return result.stdout.toString().trim()
}) { return Plugin.define({
  id: "doorstop-bridge-tui",
  setup(context) {
    // The subscription is live-only. No TUI listener means the server's pending request expires safely.
    const seen = new Set<string>()
    const active = new Set<string>()
    let disposed = false
    const rpc = context.client?.rpc?.(doorstopInitRpc)
    const unsubscribe = rpc?.events?.on?.("confirmationRequested", async (event) => {
      if (disposed) return
      const request = confirmationRequest(event.data)
      if (!request || seen.has(request.requestID) || active.has(request.requestID) || active.size >= 8) return
      const session = context.data.session.get(request.sessionID)
      if (!session?.location?.directory) return
      let root: string
      try { root = sessionCwd(session) } catch { return }
      if (root !== request.directory) return
      const sessionDirectory = session.location.directory
      const subpath = session.subpath
      if (event.location !== undefined && event.location?.directory !== root && event.location?.directory !== sessionDirectory) return
      const current = () => {
        const route = context.ui.router.current()
        if (route.type !== "session" || route.sessionID !== request.sessionID) return false
        const latest = context.data.session.get(request.sessionID)
        if (!latest || latest.location?.directory !== sessionDirectory || latest.subpath !== subpath) return false
        try { return sessionCwd(latest) === request.directory } catch { return false }
      }
      if (!current()) return

      active.add(request.requestID)
      try {
        let confirmed = false
        try {
          confirmed = await context.ui.dialog.confirm(request.action === "bootstrap" ? {
            title: "Create Doorstop requirement?",
            message: `${bootstrapPreview({ taskID: request.taskID!, header: request.header!, text: request.text! })}\n\nProject: ${request.directory}`,
            label: { confirm: "Create requirement", cancel: "Cancel" },
          } : {
            title: "Disable Doorstop bridge?",
            message: `This changes project policy.\n\nProject: ${request.directory}`,
            label: { confirm: "Disable", cancel: "Cancel" },
          }) === true
        } catch {
          // Closed/failed dialogs cannot authorize the server operation.
        }
        await rpc?.confirmationReply({ requestID: request.requestID, sessionID: request.sessionID,
          confirmed: confirmed && !disposed && request.expiresAt > Date.now() && current(),
        }, { location: event.location ?? session.location })
      } catch {
        // Server disconnection or an expired request is not a successful operation.
      } finally {
        active.delete(request.requestID)
        seen.add(request.requestID)
        if (seen.size > 128) seen.delete(seen.values().next().value!)
      }
    })
    context.keymap.layer(() => ({
      commands: [{
        id: "doorstop-bridge-tui.doorstop_init",
        slash: { name: "doorstop_init", arguments: true },
        async run(input) {
          const action = input?.trim()
          const route = context.ui.router.current()
          if (route.type !== "session") {
            context.ui.toast.show({ message: "Open a session to run Doorstop.", variant: "warning" })
            return
          }

          const sessionID = route.sessionID
          const location = context.data.session.get(sessionID)?.location
            ?? context.location
            ?? context.data.location.default()

          const parsed = parseDoorstopCommand(action ?? "")
          if (typeof parsed === "object" && "bootstrap" in parsed) {
            const confirmed = await context.ui.dialog.confirm({
              title: "Create Doorstop requirement?",
              message: bootstrapPreview(parsed.bootstrap),
              label: { confirm: "Create requirement", cancel: "Cancel" },
            })
            if (confirmed !== true) {
              context.ui.toast.show({ message: "Doorstop bootstrap cancelled; no requirement created.", variant: "info" })
              return
            }
            try {
              const session = context.data.session.get(sessionID)
              if (!session) throw new Error("Session is unavailable")
              const cwd = sessionCwd(session)
              const { taskID, header, text } = parsed.bootstrap
              const args = ["bootstrap", "--json", "--cwd", cwd, "--adapter-id", ADAPTER_ID, "--session-id", sessionID, "--confirm", "--task-id", taskID, "--header", header, "--text", text]
              const result = await runBootstrap(cwd, args)
              context.ui.toast.show({ message: `Requirement created. ${result}`, variant: "success" })
            } catch (error) {
              context.ui.toast.show({ message: `Doorstop bootstrap failed: ${taskErrorMessage(error)}`, variant: "error" })
            }
            return
          }
          if (parsed === "enable" || parsed === "disable") {
            if (parsed === "disable") {
              const confirmed = await context.ui.dialog.confirm({ title: "Disable Doorstop bridge?", message: "This changes project policy.", label: { confirm: "Disable", cancel: "Cancel" } })
              if (confirmed !== true) {
                context.ui.toast.show({ message: "Doorstop disable cancelled; policy unchanged.", variant: "info" })
                return
              }
            }
            try {
              const response = await context.client.rpc(doorstopInitRpc).execute(
                parsed === "disable" ? { sessionID, action: parsed, confirmed: true } : { sessionID, action: parsed },
                { location },
              )
              throwRpcFailure(response)
              if (!response || response.action !== parsed || response.result == null) throw new Error("Incomplete Doorstop command result")
              if (parsed === "enable" && (typeof response.ready !== "object" || response.ready === null
                || (response.ready as { ready?: unknown }).ready !== true)) {
                const candidate = (response.ready as { reason?: unknown } | null)?.reason
                const reason = typeof candidate === "string" && candidate.trim() ? candidate : "Adapter is not ready."
                throw new Error(reason)
              }
              context.ui.toast.show({ message: parsed === "enable" ? "Doorstop bridge enabled." : "Doorstop bridge disabled.", variant: "success" })
            } catch (error) {
              context.ui.toast.show({ message: `Doorstop ${parsed} failed: ${errorMessage(error)}`, variant: "error" })
            }
            return
          }

          if (parsed === "tasks" || (typeof parsed === "object" && "select" in parsed)) {
            try {
              const cwd = location.directory
              const args = [action === "tasks" ? "selectable-tasks" : "select-task", "--json", "--cwd", cwd, "--adapter-id", "opencode-v2", "--session-id", sessionID]
              if (typeof parsed === "object") args.push("--task-id", parsed.select)
              const result = await Bun.$`doorstop-bridge ${args}`.cwd(cwd).quiet()
              context.ui.toast.show({ message: action === "tasks" ? result.stdout.toString() : "Task selected for this session.", variant: "success" })
            } catch (error) {
              context.ui.toast.show({ message: `Doorstop task command failed: ${taskErrorMessage(error)}`, variant: "error" })
            }
            return
          }

          if (action === "version") {
            try {
              const response = await context.client.rpc(doorstopInitRpc).execute({ sessionID, action }, { location })
              throwRpcFailure(response)
              if (!response || response.action !== "version") throw new Error("Incomplete version response")
              context.ui.toast.show({ message: versionMessage(response.result), variant: "info" })
            } catch (error) {
              context.ui.toast.show({ message: `Doorstop version failed: ${errorMessage(error)}`, variant: "error" })
            }
            return
          }

          if (action !== "status" && action !== "recover") {
            context.ui.toast.show({ message: USAGE, variant: "info" })
            return
          }

          try {
            const rpc = context.client.rpc(doorstopInitRpc)
            if (action === "recover") {
              const recovery = await rpc.execute({ sessionID, action }, { location })
              throwRpcFailure(recovery)
              const result = recovery.result
              const status = statusFrom(recovery.status)
              const readiness = recovery.ready
              const checksPassed = typeof result === "object" && result !== null
                && (result as { project_ready?: unknown }).project_ready === true
              if (!checksPassed || !status) {
                context.ui.toast.show({ message: "Recovery incomplete; policy unchanged. Check status.", variant: "warning" })
                return
              }
              if (status.policy === "enabled" && typeof readiness === "object" && readiness !== null
                && (readiness as { ready?: unknown }).ready === true) {
                context.ui.toast.show(statusToast({ ...status, ready: true }, true))
                return
              }
              context.ui.toast.show({
                message: `Recovery checks passed; policy: ${status.policy}; adapter not ready.`,
                variant: status.policy === "enabled" || status.policy === "blocked" ? "warning" : "info",
              })
              return
            }

            const response = await rpc.execute({ sessionID, action }, { location })
            throwRpcFailure(response)
            const status = statusFrom(response.result)
            if (!status) {
              context.ui.toast.show({ message: "Doorstop status unavailable; response incomplete.", variant: "error" })
              return
            }
            context.ui.toast.show(statusToast(status, false))
          } catch (error) {
            context.ui.toast.show({
              message: action === "recover"
                ? `Recovery failed; policy unchanged. ${errorMessage(error)}`
                : `Doorstop status check failed: ${errorMessage(error)}`,
              variant: "error",
            })
          }
        },
      }],
    }))
    return () => { disposed = true; unsubscribe?.(); active.clear(); seen.clear() }
  },
})
}

export default createTuiPlugin()
