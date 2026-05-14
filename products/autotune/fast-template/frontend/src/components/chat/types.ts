// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: LicenseRef-AWS-Proprietary

// Define message types
export type MessageRole = "user" | "assistant"

export type ToolCallStatus = "streaming" | "executing" | "complete"

export interface ToolCall {
  toolUseId: string
  name: string
  input: string
  result?: string
  status: ToolCallStatus
}

export type MessageSegment =
  | { type: "text"; content: string }
  | { type: "tool"; toolCall: ToolCall }

export interface Message {
  role: MessageRole
  content: string
  timestamp: string
  segments?: MessageSegment[]
}

// Define chat session types
export interface ChatSession {
  id: string
  name: string
  history: Message[]
  startDate: string
  endDate: string
}

// Run summary from DynamoDB (GET /runs endpoint)
export interface RunSummary {
  session_id: string
  status: string
  test_set_id?: string
  best_accuracy_within_budget?: number | string
  iteration?: number | string
  started_at?: string
  updated_at?: string
  phase?: string
  phase_detail?: string
  optimization_guidance?: string
}
