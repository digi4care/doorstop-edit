import { Rpc } from "@opencode/plugin/rpc"

export type DoorstopInitAction = "status" | "recover" | "enable" | "disable" | "version"

export const doorstopInitRpc = Rpc.define({
  id: "doorstop-bridge.init",
  methods: {
    execute: {
      input: {
        type: "object",
        properties: {
          sessionID: { type: "string" },
          action: { type: "string", enum: ["status", "recover", "enable", "disable", "version"] },
          confirmed: { type: "boolean" },
        },
        required: ["sessionID", "action"],
        additionalProperties: false,
      },
      output: { type: "object", additionalProperties: true },
    },
    confirmationReply: {
      input: {
        type: "object",
        properties: {
          requestID: { type: "string" },
          sessionID: { type: "string" },
          confirmed: { type: "boolean" },
        },
        required: ["requestID", "sessionID", "confirmed"],
        additionalProperties: false,
      },
      output: {
        type: "object",
        properties: { accepted: { type: "boolean" } },
        required: ["accepted"],
        additionalProperties: false,
      },
    },
  },
  events: {
    confirmationRequested: {
      schema: {
        type: "object",
        properties: {
          requestID: { type: "string" },
          sessionID: { type: "string" },
          action: { type: "string", enum: ["disable", "bootstrap"] },
          directory: { type: "string" },
          expiresAt: { type: "number" },
          taskID: { type: "string" },
          header: { type: "string" },
          text: { type: "string" },
        },
        required: ["requestID", "sessionID", "action", "directory", "expiresAt"],
        additionalProperties: false,
      },
    },
  },
})

export type DoorstopInitResult = {
  action: DoorstopInitAction
  result: unknown
  ready?: unknown
}

export type DoorstopInitFailure = {
  action: DoorstopInitAction
  ok: false
  error: { message: string; code: "BRIDGE_OPERATION_FAILED" }
}
