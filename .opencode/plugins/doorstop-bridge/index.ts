import { spawn } from "node:child_process"
import { randomUUID } from "node:crypto"
import { Plugin } from "@opencode/plugin"
import { ADAPTER_ID, bootstrapPreview, parseDoorstopCommand, PLUGIN_VERSION, sessionCwd, USAGE } from "./commands.ts"
import { doorstopInitRpc } from "./rpc.ts"

export async function invokeBridge(cwd: string, verb: string, sessionID?: string, tool?: string, input?: unknown, options?: { confirmed?: boolean; taskID?: string; header?: string; text?: string }): Promise<any> {
  if (verb === "bootstrap" && (options?.confirmed !== true || !options.taskID || !options.header || !options.text)) {
    throw new Error("Bootstrap requires a confirmed task, header and text")
  }
  const args = [verb, "--json"]
  if (verb !== "version") args.push("--cwd", cwd, "--adapter-id", ADAPTER_ID)
  if (sessionID) args.push("--session-id", sessionID)
  if (tool !== undefined) args.push("--tool", tool, "--input-json", JSON.stringify(input))
  if ((verb === "disable" || verb === "bootstrap") && options?.confirmed) args.push("--confirm")
  if (options?.taskID) args.push("--task-id", options.taskID)
  if (verb === "bootstrap") args.push("--header", options!.header!, "--text", options!.text!)
  return await new Promise((resolve, reject) => {
    const child = spawn("doorstop-bridge", args, { cwd, shell: false, stdio: ["ignore", "pipe", "pipe"] })
    let stdout = "", stderr = "", settled = false
    const finish = (fn: (value: any) => void, value: any) => { if (!settled) { settled = true; clearTimeout(timer); fn(value) } }
    const timer = setTimeout(() => { child.kill("SIGKILL"); finish(reject, new Error("doorstop-bridge timed out")) }, 15_000)
    child.stdout.setEncoding("utf8").on("data", chunk => stdout += chunk)
    child.stderr.setEncoding("utf8").on("data", chunk => stderr += chunk)
    child.on("error", error => finish(reject, new Error(`doorstop-bridge failed: ${error.message}`)))
    child.on("close", code => {
      let result: any
      try { result = JSON.parse(stdout) } catch { finish(reject, new Error(stderr.trim() || "doorstop-bridge returned invalid JSON")); return }
      if (code !== 0) {
        if (verb !== "authorize" || result?.allowed !== false || (typeof result?.error !== "string" && typeof result?.reason !== "string")) {
          finish(reject, new Error(result?.error ?? result?.reason ?? (stderr.trim() || `doorstop-bridge exited ${code}`))); return
        }
      }
      resolve(result)
    })
  })
}

const nativeActions = ["status", "recover", "tasks", "select", "enable", "disable", "version", "bootstrap", "session"] as const
function validateNativeInput(input: unknown): { ok: true; action: typeof nativeActions[number] } | { ok: false; action?: string; message: string } {
  if (!input || typeof input !== "object" || Array.isArray(input)) return { ok: false, message: "Input must be an object" }
  const value = input as Record<string, unknown>, action = value.action
  if (typeof action !== "string" || !nativeActions.includes(action as any)) return { ok: false, message: "Invalid action" }
  const keys = action === "select" ? ["action", "task_id", "details"] : action === "bootstrap" ? ["action", "task_id", "header", "text", "details"] : ["action", "details"]
  if (Object.keys(value).some(key => !keys.includes(key))) return { ok: false, action, message: "Unexpected input property" }
  if ((action === "select" || action === "bootstrap") && (typeof value.task_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value.task_id))) return { ok: false, action, message: "Invalid or missing task_id" }
  if (action !== "select" && action !== "bootstrap" && "task_id" in value) return { ok: false, action, message: "Unexpected task_id" }
  if (action === "bootstrap" && (typeof value.header !== "string" || !value.header.trim() || value.header.length > 200 || typeof value.text !== "string" || !value.text.trim() || value.text.length > 4000)) return { ok: false, action, message: "Bootstrap requires bounded header and text" }
  if (action !== "bootstrap" && ("header" in value || "text" in value)) return { ok: false, action, message: "Unexpected bootstrap fields" }
  if (value.details !== undefined && typeof value.details !== "boolean") return { ok: false, action, message: "details must be boolean" }
  return { ok: true, action: action as typeof nativeActions[number] }
}
function compactResult(action: string, result: any): any {
  if (!result || typeof result !== "object" || Array.isArray(result)) return result
  const keys = new Set(["allowed", "task", "tasks", "shortlist", "list_scope", "exhaustive", "selection_hint", "policy", "ready", "project_ready", "reason", "error", "scope", "bridgeVersion", "pluginVersion"])
  const compact = Object.fromEntries(Object.entries(result).filter(([key]) => keys.has(key)))
  return action === "version" && typeof result.version === "string" ? { bridgeVersion: result.version, pluginVersion: PLUGIN_VERSION } : compact
}

export function createPlugin(run = invokeBridge, options: { confirmationTimeoutMs?: number } = {}) { return Plugin.define({
  id: "doorstop-bridge",
  async setup(ctx) {
    const pending = new Map<string, { sessionID: string; expiresAt: number; resolve: (confirmed: boolean) => void; timer: ReturnType<typeof setTimeout>; signal?: AbortSignal; abort?: () => void }>()
    let disposed = false
    const settlePending = (requestID: string, confirmed: boolean) => {
      const request = pending.get(requestID)
      if (!request) return false
      pending.delete(requestID)
      clearTimeout(request.timer)
      if (request.signal && request.abort) request.signal.removeEventListener("abort", request.abort)
      request.resolve(confirmed)
      return true
    }
    const registration = await ctx.rpc.register(doorstopInitRpc, {
      async confirmationReply(input: any) {
        if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).length !== 3 || typeof input.requestID !== "string" || typeof input.sessionID !== "string" || typeof input.confirmed !== "boolean") return { accepted: false }
        const request = pending.get(input.requestID)
        if (!request || request.sessionID !== input.sessionID || request.expiresAt <= Date.now()) return { accepted: false }
        return { accepted: settlePending(input.requestID, input.confirmed) }
      },
      async execute({ sessionID, action, confirmed }) {
        try {
          const session = await ctx.session.get({ sessionID })
          const cwd = sessionCwd(session)
          if (action === "disable" && confirmed !== true) throw new Error("Disable requires interactive confirmation")
          const result = await run(cwd, action, undefined, undefined, undefined, action === "disable" ? { confirmed: true } : undefined)
          if (action === "version") {
            if (typeof result?.version !== "string") throw new Error("Bridge version unavailable")
            return { action, result: { bridgeVersion: result.version, pluginVersion: PLUGIN_VERSION } }
          }
          if (action === "enable") {
            const readiness = await run(cwd, "adapter-ready")
            const ready = readiness?.ready === true
              ? readiness
              : { ready: false, reason: typeof readiness?.reason === "string" && readiness.reason.trim() ? readiness.reason : "Adapter is not ready." }
            return { action, result, ready }
          }
          if (action === "recover") {
            const status = await run(cwd, "status")
            let ready: any = { ready: false, reason: status?.reason ?? "Project policy is not enabled." }
            if (status?.policy === "enabled") {
              const readiness = await run(cwd, "adapter-ready")
              ready = readiness?.ready === true
                ? readiness
                : { ready: false, reason: typeof readiness?.reason === "string" && readiness.reason.trim() ? readiness.reason : "Adapter is not ready." }
            }
            return { action, result, status, ready }
          }
          return { action, result }
        } catch (error) {
          const message = error instanceof Error ? error.message
            : typeof error === "string" ? error
              : typeof error === "object" && error !== null && typeof (error as { message?: unknown }).message === "string"
                ? (error as { message: string }).message : String(error)
          return { action, ok: false, error: { message: message || "Doorstop bridge operation failed.", code: "BRIDGE_OPERATION_FAILED" } }
        }
      },
    })
    const requestConfirmation = async (data: Record<string, unknown>, sessionID: string, signal?: AbortSignal): Promise<boolean> => {
      const events = (registration as any)?.events
      if (typeof events?.emit !== "function" || !sessionID || signal?.aborted || disposed) throw new Error("CONFIRMATION_UNAVAILABLE")
      const requestID = randomUUID(), expiresAt = Date.now() + (options.confirmationTimeoutMs ?? 120_000)
      return await new Promise<boolean>((resolve, reject) => {
        const timeoutMs = Math.max(0, expiresAt - Date.now())
        const timer = setTimeout(() => { settlePending(requestID, false) }, timeoutMs)
        const abort = () => { settlePending(requestID, false) }
        const request = { sessionID, expiresAt, resolve, timer, signal, abort }
        pending.set(requestID, request)
        signal?.addEventListener("abort", abort, { once: true })
        try {
          const emitted = events.emit("confirmationRequested", { ...data, requestID, sessionID, expiresAt })
          Promise.resolve(emitted).catch(cause => {
            const current = pending.get(requestID)
            if (current) { pending.delete(requestID); clearTimeout(current.timer); signal?.removeEventListener("abort", abort) }
            reject(cause)
          })
        } catch (cause) {
          const current = pending.get(requestID)
          if (current) { pending.delete(requestID); clearTimeout(current.timer); signal?.removeEventListener("abort", abort) }
          reject(cause)
        }
      })
    }
    await ctx.command.transform(editor => editor.add({
      name: "doorstop_init",
      description: USAGE,
      async execute({ sessionID, prompt }) {
        const session = await ctx.session.get({ sessionID })
        const cwd = sessionCwd(session)
        const action = parseDoorstopCommand(prompt.text)
        let message: string
        let toast: { message: string; variant: "success" | "error" } | undefined
        try {
          if (!action) { message = USAGE; toast = { message: USAGE, variant: "error" } }
          else if (action === "tasks") message = JSON.stringify(await dispatch("tasks", cwd, sessionID))
          else if (typeof action === "object" && "bootstrap" in action) {
            const confirmed = await ctx.ui.dialog.confirm({ title: "Create Doorstop requirement?", message: bootstrapPreview(action.bootstrap), label: { confirm: "Create requirement", cancel: "Cancel" } })
            if (confirmed !== true) {
              ctx.ui.toast.show({ message: "Doorstop bootstrap cancelled; no requirement created.", variant: "info" })
              return
            }
            message = JSON.stringify(await run(cwd, "bootstrap", sessionID, undefined, undefined, { confirmed: true, ...action.bootstrap }))
          }
          else if (typeof action === "object") message = JSON.stringify(await dispatch("select", cwd, sessionID, action.select))
          else if (action === "version") {
            const result = await run(cwd, "version")
            if (typeof result?.version !== "string") throw new Error("Bridge version unavailable")
            message = `Bridge ${result.version}; OpenCode plugin ${PLUGIN_VERSION}`
          }
          else if (action === "enable") {
            await run(cwd, "enable")
            const ready = await run(cwd, "adapter-ready")
            if (ready?.ready !== true) throw new Error(typeof ready?.reason === "string" && ready.reason.trim() ? ready.reason : "Adapter is not ready.")
            message = `Doorstop bridge enabled. ${JSON.stringify(ready)}`
          } else if (action === "recover") {
            const recovered = await run(cwd, "recover")
            const status = await run(cwd, "status")
            const projectReady = recovered?.project_ready === true
            if (!projectReady) {
              message = `Doorstop recovery project checks did not pass. ${JSON.stringify({ recovered, status })}`
              toast = { message, variant: "error" }
            } else if (status?.policy === "enabled" && typeof status.ready === "boolean") {
              const ready = await run(cwd, "adapter-ready")
              if (ready?.ready === true) {
                message = `Doorstop bridge recovered. ${JSON.stringify({ recovered, status, ready })}`
              } else {
                const reason = typeof ready?.reason === "string" && ready.reason.trim() ? ready.reason : "Adapter is not ready."
                message = `Doorstop recovery checks passed; policy: enabled; adapter not ready. ${reason}`
                toast = { message, variant: "error" }
              }
            } else if (status?.policy === "disabled" || status?.policy === "unenforced") {
              message = `Doorstop recovery checks passed; policy: ${typeof status?.policy === "string" ? status.policy : "unknown"}; adapter attestation not required.`
              toast = { message, variant: "info" }
            } else {
              const policy = status?.policy === "blocked" ? "blocked" : "unavailable or malformed"
              const reason = typeof status?.reason === "string" && status.reason.trim() ? ` ${status.reason}` : ""
              message = `Doorstop recovery cannot be confirmed; policy status ${policy}.${reason}`
              toast = { message, variant: "error" }
            }
          } else if (action === "disable") {
            const confirmed = await ctx.ui.dialog.confirm({ title: "Disable Doorstop bridge?", message: "This changes project policy.", label: { confirm: "Disable", cancel: "Cancel" } })
            if (confirmed !== true) {
              ctx.ui.toast.show({ message: "Doorstop disable cancelled; policy unchanged.", variant: "info" })
              return
            }
            message = JSON.stringify(await run(cwd, "disable", undefined, undefined, undefined, { confirmed: true }))
          } else message = JSON.stringify(await dispatch(action, cwd, sessionID))
          if (action && !toast) toast = { message: `${typeof action === "object" ? "bootstrap" in action ? "Requirement created" : "Task selected" : action} completed.`, variant: "success" }
        } catch (error) { message = `Doorstop bridge error: ${error instanceof Error ? error.message : String(error)}`; toast = { message, variant: "error" } }
        await ctx.session.synthetic({ sessionID, text: message, resume: false })
        if (toast) {
          try { ctx.ui?.toast?.show?.(toast) } catch { /* Notifications are best effort; preserve command output. */ }
        }
      },
    }))
    const dispatch = async (action: string, cwd: string, sessionID: string, taskID?: string) => {
      if (action === "tasks") return run(cwd, "selectable-tasks", sessionID)
      if (action === "select") return run(cwd, "select-task", sessionID, undefined, undefined, { taskID })
      if (action === "recover") {
        const result = await run(cwd, "recover")
        const ready = await run(cwd, "status")
        return { result, status: ready }
      }
      return run(cwd, action)
    }
    await ctx.tool.transform(editor => editor.add({
      name: "doorstop", description: "Doorstop bridge actions for this session",
      input: { type: "object", properties: { action: { type: "string", enum: ["status", "recover", "tasks", "select", "enable", "disable", "version", "bootstrap", "session"] }, task_id: { type: "string" }, header: { type: "string", maxLength: 200 }, text: { type: "string", maxLength: 4000 }, details: { type: "boolean" } }, required: ["action"], additionalProperties: false },
      async execute(input: any, context: any) {
        const validation = validateNativeInput(input), action = validation.ok ? validation.action : validation.action ?? input?.action
        const error = (message: string, code = "INVALID_INPUT") => ({ content: JSON.stringify({ action, ok: false, error: { message, code } }) })
        if (!validation.ok) return error(validation.message)
        const args = Object.freeze({ taskID: input.task_id as string | undefined, header: input.header as string | undefined, text: input.text as string | undefined, details: input.details === true })
        if (typeof context?.sessionID !== "string" || !context.sessionID) return error("Session context is unavailable", "SESSION_UNAVAILABLE")
        const sessionID = context.sessionID
        const session = await ctx.session.get({ sessionID }), cwd = sessionCwd(session)
        if (["enable", "recover", "select", "disable", "bootstrap"].includes(action)) {
          if (typeof context.agent !== "string" || typeof context.messageID !== "string" || typeof context.id !== "string") return error("Host permission context is incomplete", "PERMISSION_CONTEXT_UNAVAILABLE")
          if (typeof ctx.permission?.assert !== "function") return error("Host permission API unavailable", "PERMISSION_UNAVAILABLE")
          await ctx.permission.assert({ sessionID, agent: context.agent, source: { type: "tool", messageID: context.messageID, id: context.id }, action: `doorstop.${action}`, resources: [cwd], save: [] })
        }
        const captured = action === "bootstrap" ? { taskID: args.taskID!, header: args.header!, text: args.text! } : undefined
        if (action === "disable" || action === "bootstrap") {
          let confirmed: boolean
          try { confirmed = await requestConfirmation({ action, directory: cwd, ...(captured ?? {}) }, sessionID, context.signal) }
          catch (cause) { return error(cause instanceof Error ? cause.message : String(cause), "CONFIRMATION_UNAVAILABLE") }
          if (!confirmed) return { content: JSON.stringify({ action, ok: false, error: { message: "Confirmation cancelled or expired", code: "CONFIRMATION_CANCELLED" } }) }
          const latestSession = await ctx.session.get({ sessionID })
          if (sessionCwd(latestSession) !== cwd) return error("Session project root changed during confirmation", "SESSION_ROOT_CHANGED")
          if (disposed || context.signal?.aborted) return error("Operation aborted", "ABORTED")
          try {
            const result = action === "disable"
              ? await run(cwd, "disable", sessionID, undefined, undefined, { confirmed: true })
              : await run(cwd, "bootstrap", sessionID, undefined, undefined, { confirmed: true, ...captured })
            return { content: JSON.stringify({ action, ok: result?.allowed !== false, result: args.details ? result : compactResult(action, result) }) }
          } catch (cause) { return error(cause instanceof Error ? cause.message : String(cause), "BRIDGE_OPERATION_FAILED") }
        }
        try {
          let result = action === "recover" ? undefined : action === "session" ? await run(cwd, "session-task", sessionID) : action === "select" ? await run(cwd, "select-task", sessionID, undefined, undefined, { taskID: args.taskID }) : action === "tasks" ? await run(cwd, "selectable-tasks", sessionID) : await dispatch(action, cwd, sessionID)
          if (action === "version") {
            if (typeof result?.version !== "string") return error("Bridge version unavailable", "VERSION_UNAVAILABLE")
            result = { bridgeVersion: result.version, pluginVersion: PLUGIN_VERSION }
          }
          if (action === "status" && (!result || !["enabled", "disabled", "unenforced", "blocked"].includes(result.policy) || typeof result.ready !== "boolean")) return error("Bridge status is malformed", "STATUS_UNAVAILABLE")
          if (action === "enable") { const ready = await run(cwd, "adapter-ready"); if (ready?.ready !== true) return error(ready?.reason || "Adapter is not ready", "NOT_READY"); result = { ...(result && typeof result === "object" ? result : {}), ...ready } }
          if (action === "recover") {
            const recovered = await run(cwd, "recover")
            const status = await run(cwd, "status")
            if (recovered?.project_ready !== true) return error("Recovery project checks did not pass", "RECOVERY_FAILED")
            if (!status || !["enabled", "disabled", "unenforced", "blocked"].includes(status.policy) || typeof status.ready !== "boolean") return error("Recovery policy status is malformed", "POLICY_UNAVAILABLE")
            let ready = false
            if (status?.policy === "enabled") {
              const attestation = await run(cwd, "adapter-ready")
              if (attestation?.ready !== true) return error(attestation?.reason || "Adapter is not ready", "NOT_READY")
              ready = true
            } else if (status.policy !== "disabled" && status.policy !== "unenforced") return error(status.reason || "Recovery policy status is unavailable", "POLICY_UNAVAILABLE")
            result = { project_ready: true, policy: status.policy, ready, scope: status.scope, ...(status.reason ? { reason: status.reason } : {}) }
          }
          if (!args.details) result = compactResult(action, result)
          return { content: JSON.stringify({ action, ok: result?.allowed !== false, ...(result?.allowed === false ? { error: { message: result.reason ?? result.error ?? "Doorstop action denied", code: "ACTION_DENIED" } } : { result }) }) }
        } catch (cause) { return error(cause instanceof Error ? cause.message : String(cause), "BRIDGE_OPERATION_FAILED") }
      },
    }))
    const bridgeManagedTools = new Set([
      "read", "read_file", "list_files", "search", "grep", "find", "glob",
      "br", "doorstop", "write", "write_file", "edit", "edit_file", "apply_patch", "patch",
    ])
    await ctx.tool.hook("execute.before", async event => {
      if (event.tool === "doorstop") {
        const input = event.input
        if (input && typeof input === "object" && !Array.isArray(input) && "action" in input) {
          if (validateNativeInput(input).ok) return
          throw new Error("Doorstop native action input is invalid")
        }
        if (input && typeof input === "object" && !Array.isArray(input) && "command" in input) {
          const command = input.command
          if (["list", "show", "search", "validate"].includes(command)) { /* authorize through CLI below */ }
          else throw new Error("Doorstop legacy command input is invalid")
        } else if (input && typeof input === "object" && !Array.isArray(input)) throw new Error("Doorstop tool input is invalid")
      }
      // OpenCode invokes this hook again for each tool called inside Code Mode's execute wrapper.
      // Keep the wrapper transparent; managed project tools are checked below. MCP tools receive
      // host permission checks, while custom plugin tools must call ctx.permission.assert themselves.
      if (!bridgeManagedTools.has(event.tool)) return
      try {
        const session = await ctx.session.get({ sessionID: event.sessionID })
        const result = await run(sessionCwd(session), "authorize", event.sessionID, event.tool, event.input)
        if (result?.allowed !== true) throw new Error(result?.reason ?? result?.error ?? "Doorstop bridge denied tool")
      } catch (error) {
        throw new Error(error instanceof Error ? error.message : String(error))
      }
    })
    return () => {
      disposed = true
      for (const [requestID, request] of pending) {
        settlePending(requestID, false)
      }
    }
  },
}) }
export default createPlugin()
