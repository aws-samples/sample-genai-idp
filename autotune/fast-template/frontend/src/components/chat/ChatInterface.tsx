"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { ChatHeader } from "./ChatHeader"
import { ChatInput } from "./ChatInput"
import { ChatMessages } from "./ChatMessages"
import { ChatSidebar } from "./ChatSidebar"
import { ChatSession, Message, MessageSegment, ToolCall } from "./types"

import { useGlobal } from "@/app/context/GlobalContext"
import { AgentCoreClient } from "@/lib/agentcore-client"
import type { AgentPattern } from "@/lib/agentcore-client"
import { submitFeedback } from "@/services/feedbackService"
import { useAuth } from "react-oidc-context"
import { useDefaultTool } from "@/hooks/useToolRenderer"
import { ToolCallDisplay } from "./ToolCallDisplay"
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar"

const SESSIONS_KEY = "idpautotune-sessions"

function loadSessions(): ChatSession[] {
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) || "[]")
  } catch {
    return []
  }
}

function saveSessions(sessions: ChatSession[]) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions))
}

function makeSessionName(messages: Message[]): string {
  const first = messages.find(m => m.role === "user")
  if (!first) return "New Chat"
  return first.content.slice(0, 50) + (first.content.length > 50 ? "…" : "")
}

function newSession(): ChatSession {
  const now = new Date().toISOString()
  return { id: crypto.randomUUID(), name: "New Chat", history: [], startDate: now, endDate: now }
}

export default function ChatInterface() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    const saved = loadSessions()
    return saved.length > 0 ? saved : [newSession()]
  })
  const [currentSessionId, setCurrentSessionId] = useState<string>(
    () => sessions[0]?.id ?? newSession().id
  )

  const currentSession = sessions.find(s => s.id === currentSessionId)!
  const messages = currentSession?.history ?? []

  const [input, setInput] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [client, setClient] = useState<AgentCoreClient | null>(null)

  const { isLoading, setIsLoading } = useGlobal()
  const auth = useAuth()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useDefaultTool(({ name, args, status, result }) => (
    <ToolCallDisplay name={name} args={args} status={status} result={result} />
  ))

  // Persist sessions to localStorage whenever they change
  useEffect(() => {
    saveSessions(sessions)
  }, [sessions])

  // Helper to update messages for the current session
  const setMessages = useCallback(
    (updater: Message[] | ((prev: Message[]) => Message[])) => {
      setSessions(prev =>
        prev.map(s => {
          if (s.id !== currentSessionId) return s
          const newHistory = typeof updater === "function" ? updater(s.history) : updater
          return {
            ...s,
            history: newHistory,
            name: makeSessionName(newHistory) || s.name,
            endDate: new Date().toISOString(),
          }
        })
      )
    },
    [currentSessionId]
  )

  // Load agent configuration and create client on mount
  useEffect(() => {
    async function loadConfig() {
      try {
        const response = await fetch("/aws-exports.json")
        if (!response.ok) throw new Error("Failed to load configuration")
        const config = await response.json()
        if (!config.agentRuntimeArn) throw new Error("Agent Runtime ARN not found in configuration")

        setClient(
          new AgentCoreClient({
            runtimeArn: config.agentRuntimeArn,
            region: config.awsRegion || "us-east-1",
            pattern: (config.agentPattern || "strands-single-agent") as AgentPattern,
          })
        )
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Unknown error"
        setError(`Configuration error: ${errorMessage}`)
      }
    }
    loadConfig()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const sendMessage = async (userMessage: string) => {
    if (!userMessage.trim() || !client) return
    setError(null)

    const newUserMessage: Message = {
      role: "user",
      content: userMessage,
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, newUserMessage])
    setInput("")
    setIsLoading(true)

    const assistantResponse: Message = {
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, assistantResponse])

    try {
      const accessToken = auth.user?.access_token
      if (!accessToken) throw new Error("Authentication required. Please log in again.")

      const segments: MessageSegment[] = []
      const toolCallMap = new Map<string, ToolCall>()

      const updateMessage = () => {
        const content = segments
          .filter((s): s is Extract<MessageSegment, { type: "text" }> => s.type === "text")
          .map(s => s.content)
          .join("")

        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content,
            segments: [...segments],
          }
          return updated
        })
      }

      await client.invoke(userMessage, currentSessionId, accessToken, event => {
        switch (event.type) {
          case "text": {
            const prev = segments[segments.length - 1]
            if (prev && prev.type === "tool") {
              for (const tc of toolCallMap.values()) {
                if (tc.status === "streaming" || tc.status === "executing") {
                  tc.status = "complete"
                }
              }
            }
            const last = segments[segments.length - 1]
            if (last && last.type === "text") {
              last.content += event.content
            } else {
              segments.push({ type: "text", content: event.content })
            }
            updateMessage()
            break
          }
          case "tool_use_start": {
            const tc: ToolCall = {
              toolUseId: event.toolUseId,
              name: event.name,
              input: "",
              status: "streaming",
            }
            toolCallMap.set(event.toolUseId, tc)
            segments.push({ type: "tool", toolCall: tc })
            updateMessage()
            break
          }
          case "tool_use_delta": {
            const tc = toolCallMap.get(event.toolUseId)
            if (tc) tc.input += event.input
            updateMessage()
            break
          }
          case "tool_result": {
            const tc = toolCallMap.get(event.toolUseId)
            if (tc) {
              tc.result = event.result
              tc.status = "complete"
            }
            updateMessage()
            break
          }
          case "message": {
            if (event.role === "assistant") {
              for (const tc of toolCallMap.values()) {
                if (tc.status === "streaming") tc.status = "executing"
              }
              updateMessage()
            }
            break
          }
        }
      })
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error"
      setError(`Failed to get response: ${errorMessage}`)
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: "I apologize, but I encountered an error processing your request. Please try again.",
        }
        return updated
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  const handleFeedbackSubmit = async (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => {
    try {
      const idToken = auth.user?.id_token
      if (!idToken) throw new Error("Authentication required. Please log in again.")

      await submitFeedback(
        { sessionId: currentSessionId, message: messageContent, feedbackType, comment: comment || undefined },
        idToken
      )
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error"
      setError(`Failed to submit feedback: ${errorMessage}`)
    }
  }

  const startNewChat = () => {
    const session = newSession()
    setSessions(prev => [session, ...prev])
    setCurrentSessionId(session.id)
    setInput("")
    setError(null)
  }

  const handleSessionSelect = (session: ChatSession) => {
    setCurrentSessionId(session.id)
    setInput("")
    setError(null)
  }

  const isInitialState = messages.length === 0
  const hasAssistantMessages = messages.some(m => m.role === "assistant")

  return (
    <SidebarProvider>
      <ChatSidebar
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSessionSelect={handleSessionSelect}
        onNewChat={startNewChat}
      />
      <SidebarInset>
        <div className="flex flex-col h-screen w-full" style={{ backgroundColor: "rgba(66, 194, 245, 0.15)" }}>
          <div className="flex-none">
            <ChatHeader onNewChat={startNewChat} canStartNewChat={hasAssistantMessages} />
            {error && (
              <div className="bg-red-50 border-l-4 border-red-500 p-4 mx-4 mt-2">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}
          </div>

          {isInitialState ? (
            <>
              <div className="grow" />
              <div className="text-center mb-6">
                <h2 className="text-2xl font-bold text-gray-800">Welcome to IDPAutoTune Temporary Developer Chat</h2>
                <p className="text-gray-600 mt-2">Ask me anything to get started</p>
              </div>
              <div className="px-4 mb-16 max-w-4xl mx-auto w-full">
                <ChatInput input={input} setInput={setInput} handleSubmit={handleSubmit} isLoading={isLoading} />
              </div>
              <div className="grow" />
            </>
          ) : (
            <>
              <div className="grow overflow-hidden">
                <div className="max-w-4xl mx-auto w-full h-full">
                  <ChatMessages
                    messages={messages}
                    messagesEndRef={messagesEndRef}
                    sessionId={currentSessionId}
                    onFeedbackSubmit={handleFeedbackSubmit}
                  />
                </div>
              </div>
              <div className="flex-none">
                <div className="max-w-4xl mx-auto w-full">
                  <ChatInput input={input} setInput={setInput} handleSubmit={handleSubmit} isLoading={isLoading} />
                </div>
              </div>
            </>
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
