"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { ChatHeader } from "./ChatHeader"
import { ChatInput } from "./ChatInput"
import { ChatSidebar } from "./ChatSidebar"
import { Message, RunSummary } from "./types"

import { useGlobal } from "@/app/context/GlobalContext"
import { AgentCoreClient } from "@/lib/agentcore-client"
import type { AgentPattern } from "@/lib/agentcore-client"
import { useAuth } from "react-oidc-context"
import { useDefaultTool } from "@/hooks/useToolRenderer"
import { ToolCallDisplay } from "./ToolCallDisplay"
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar"

const MESSAGES_KEY = "idpautotune-messages"

function loadMessages(sessionId: string): Message[] {
  try {
    const all = JSON.parse(localStorage.getItem(MESSAGES_KEY) || "{}")
    return all[sessionId] ?? []
  } catch { return [] }
}

function saveMessages(sessionId: string, messages: Message[]) {
  try {
    const all = JSON.parse(localStorage.getItem(MESSAGES_KEY) || "{}")
    all[sessionId] = messages
    localStorage.setItem(MESSAGES_KEY, JSON.stringify(all))
  } catch { /* ignore */ }
}

// Parsed stream event types matching the consolidated JSONL from the backend
type StreamItem =
  | { type: "text"; content: string; ts?: string }
  | { type: "tool_use"; toolUseId: string; name: string; input: string; ts?: string }
  | { type: "tool_result"; toolUseId: string; result: string; ts?: string }

function parseStreamLine(line: string): StreamItem | null {
  try {
    const evt = JSON.parse(line)
    if (evt.type === "text" && evt.content) return evt
    if (evt.type === "tool_use") return evt
    if (evt.type === "tool_result") return evt
    return null
  } catch { return null }
}

export default function ChatInterface() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [, setMessagesState] = useState<Message[]>([])

  const [input, setInput] = useState("")
  const [testSetId, setTestSetId] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [client, setClient] = useState<AgentCoreClient | null>(null)
  const [stateApiUrl, setStateApiUrl] = useState<string>("")
  const [agentState, setAgentState] = useState<Record<string, string | number | null> | null>(null)
  const [now, setNow] = useState(Date.now())

  // Stream polling state
  const [streamItems, setStreamItems] = useState<StreamItem[]>([])
  // Use ref for offset so polling closure always sees current value
  const streamOffsetRef = useRef(0)  // Optimization log polling state
  const [optimizationLog, setOptimizationLog] = useState("")
  // Tab: "stream" or "log"
  const [activeTab, setActiveTab] = useState<"stream" | "log">("stream")

  const { isLoading, setIsLoading } = useGlobal()
  const auth = useAuth()
  const streamEndRef = useRef<HTMLDivElement>(null)

  useDefaultTool(({ name, args, status, result }) => (
    <ToolCallDisplay name={name} args={args} status={status} result={result} />
  ))

  // Load messages from localStorage when session changes
  useEffect(() => {
    if (currentSessionId) {
      setMessagesState(loadMessages(currentSessionId))
    } else {
      setMessagesState([])
    }
  }, [currentSessionId])

  const setMessages = useCallback(
    (updater: Message[] | ((prev: Message[]) => Message[])) => {
      setMessagesState(prev => {
        const next = typeof updater === "function" ? updater(prev) : updater
        if (currentSessionId) saveMessages(currentSessionId, next)
        return next
      })
    },
    [currentSessionId]
  )

  // Load config
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
        if (config.optimizationStateApiUrl) setStateApiUrl(config.optimizationStateApiUrl)
      } catch (err) {
        setError(`Configuration error: ${err instanceof Error ? err.message : "Unknown error"}`)
      }
    }
    loadConfig()
  }, [])

  // Poll /runs for sidebar
  useEffect(() => {
    if (!stateApiUrl) return
    const idToken = auth.user?.id_token
    if (!idToken) return

    let active = true
    const poll = async () => {
      try {
        const resp = await fetch(`${stateApiUrl}runs`, {
          headers: { Authorization: `Bearer ${idToken}` },
        })
        if (resp.ok && active) {
          const data = await resp.json()
          if (data.runs) setRuns(data.runs)
        }
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 10000)
    return () => { active = false; clearInterval(interval) }
  }, [stateApiUrl, auth.user?.id_token])

  // Auto-scroll stream view
  useEffect(() => {
    streamEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [streamItems, activeTab])

  // 1s tick for heartbeat age display
  useEffect(() => {
    if (agentState?.status !== "running") return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [agentState?.status])

  // Poll DynamoDB state while viewing a session
  useEffect(() => {
    if (!stateApiUrl || !currentSessionId) return
    const idToken = auth.user?.id_token
    if (!idToken) return

    let active = true
    const poll = async () => {
      try {
        const resp = await fetch(`${stateApiUrl}state?sessionId=${currentSessionId}`, {
          headers: { Authorization: `Bearer ${idToken}` },
        })
        if (resp.ok && active) {
          const data = await resp.json()
          if (data.state) setAgentState(data.state)
        }
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => { active = false; clearInterval(interval) }
  }, [stateApiUrl, currentSessionId, auth.user?.id_token])

  // Poll agent stream (JSONL)
  useEffect(() => {
    if (!stateApiUrl || !currentSessionId || !agentState || !["running", "complete", "failed", "cancelled"].includes(String(agentState.status))) return
    const idToken = auth.user?.id_token
    if (!idToken) return

    let active = true
    const poll = async () => {
      try {
        const resp = await fetch(`${stateApiUrl}stream?sessionId=${currentSessionId}&offset=${streamOffsetRef.current}`, {
          headers: { Authorization: `Bearer ${idToken}` },
        })
        if (resp.ok && active) {
          const data = await resp.json()
          if (data.lines && data.lines.length > 0) {
            const newItems = data.lines.map(parseStreamLine).filter(Boolean) as StreamItem[]
            if (newItems.length > 0) setStreamItems(prev => [...prev, ...newItems])
            streamOffsetRef.current = data.nextOffset
          }
        }
      } catch { /* ignore */ }
    }
    poll()
    const isRunning = agentState.status === "running"
    const interval = setInterval(poll, isRunning ? 3000 : 10000)
    if (!isRunning) {
      setTimeout(() => { if (active) clearInterval(interval) }, 5000)
    }
    return () => { active = false; clearInterval(interval) }
  }, [stateApiUrl, currentSessionId, agentState?.status, auth.user?.id_token])

  // Poll optimization log
  useEffect(() => {
    if (!stateApiUrl || !currentSessionId || !agentState || !["running", "complete", "failed", "cancelled"].includes(String(agentState.status))) return
    const idToken = auth.user?.id_token
    if (!idToken) return

    let active = true
    const poll = async () => {
      try {
        const resp = await fetch(`${stateApiUrl}log?sessionId=${currentSessionId}`, {
          headers: { Authorization: `Bearer ${idToken}` },
        })
        if (resp.ok && active) {
          const data = await resp.json()
          if (data.content) setOptimizationLog(data.content)
        }
      } catch { /* ignore */ }
    }
    poll()
    const isRunning = agentState.status === "running"
    const interval = setInterval(poll, isRunning ? 5000 : 15000)
    if (!isRunning) {
      setTimeout(() => { if (active) clearInterval(interval) }, 10000)
    }
    return () => { active = false; clearInterval(interval) }
  }, [stateApiUrl, currentSessionId, agentState?.status, auth.user?.id_token])

  const invokeAgent = async (sessionId: string, testSet: string, guidance: string, isResume: boolean) => {
    if (!client) return
    setError(null)
    setIsLoading(true)

    try {
      const accessToken = auth.user?.access_token
      if (!accessToken) throw new Error("Authentication required. Please log in again.")

      const extra: Record<string, string> = {
        test_set_id: testSet,
        optimization_guidance: guidance,
      }
      if (isResume) extra.resume = "true"

      await client.invoke(
        isResume ? "Resume optimization" : "Begin optimization",
        sessionId,
        accessToken,
        () => {},
        extra
      )

      const msg: Message = {
        role: "assistant",
        content: isResume ? "Resuming optimization..." : "Optimization started. Monitoring progress below...",
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, msg])
    } catch (err) {
      setError(`Failed to ${isResume ? "resume" : "start"} optimization: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setIsLoading(false)
    }
  }

  const sendMessage = async (userMessage: string) => {
    if (!testSetId.trim()) {
      setError("Test Set ID is required to start an optimization run")
      return
    }

    const sessionId = crypto.randomUUID()
    setCurrentSessionId(sessionId)
    streamOffsetRef.current = 0
    setStreamItems([])
    setOptimizationLog("")
    setAgentState(null)

    const userMsg: Message = { role: "user", content: userMessage || "(no guidance)", timestamp: new Date().toISOString() }
    // Save immediately since setMessages depends on currentSessionId which just changed
    saveMessages(sessionId, [userMsg])
    setMessagesState([userMsg])

    await invokeAgent(sessionId, testSetId.trim(), userMessage, false)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
    setInput("")
  }

  const handleResume = async () => {
    if (!currentSessionId || !agentState) return
    streamOffsetRef.current = 0
    setStreamItems([])
    setOptimizationLog("")
    await invokeAgent(
      currentSessionId,
      String(agentState.test_set_id ?? ""),
      String(agentState.optimization_guidance ?? ""),
      true
    )
  }

  const startNewChat = () => {
    setCurrentSessionId(null)
    setInput("")
    setError(null)
    setAgentState(null)
    streamOffsetRef.current = 0
    setStreamItems([])
    setOptimizationLog("")
  }

  const handleCancelOptimization = async () => {
    if (!stateApiUrl || !currentSessionId) return
    try {
      const idToken = auth.user?.id_token
      if (!idToken) throw new Error("Authentication required")
      const resp = await fetch(`${stateApiUrl}cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
        body: JSON.stringify({ sessionId: currentSessionId }),
      })
      if (!resp.ok) throw new Error(`Cancel failed: ${resp.status}`)
    } catch (err) {
      setError(`Failed to cancel: ${err instanceof Error ? err.message : "Unknown error"}`)
    }
  }

  const handleRunSelect = (run: RunSummary) => {
    setCurrentSessionId(run.session_id)
    setError(null)
    setAgentState(null)
    streamOffsetRef.current = 0
    setStreamItems([])
    setOptimizationLog("")
  }

  const isInitialState = currentSessionId === null
  const isResumable = agentState && ["failed", "cancelled"].includes(String(agentState.status))

  // Merge tool_use + tool_result by toolUseId for display
  const toolResults = new Map<string, string>()
  for (const item of streamItems) {
    if (item.type === "tool_result") toolResults.set(item.toolUseId, item.result)
  }

  const renderedStream = streamItems.map((item, i) => {
    if (item.type === "text") {
      return (
        <div key={i} className="whitespace-pre-wrap text-gray-800 my-2">
          {item.ts && <span className="text-xs text-gray-400 mr-2">[{item.ts}]</span>}
          {item.content}
        </div>
      )
    }
    if (item.type === "tool_use") {
      const result = toolResults.get(item.toolUseId)
      return (
        <div key={i} className="flex items-start gap-2">
          {item.ts && <span className="text-xs text-gray-400 mt-1.5 shrink-0">[{item.ts}]</span>}
          <div className="grow">
            <ToolCallDisplay name={item.name} args={item.input} status="complete" result={result} />
          </div>
        </div>
      )
    }
    return null
  }).filter(Boolean)

  return (
    <SidebarProvider>
      <ChatSidebar
        runs={runs}
        currentSessionId={currentSessionId ?? undefined}
        onRunSelect={handleRunSelect}
        onNewChat={startNewChat}
      />
      <SidebarInset>
        <div className="flex flex-col h-screen w-full" style={{ backgroundColor: "rgba(66, 194, 245, 0.15)" }}>
          <div className="flex-none">
            <ChatHeader onNewChat={startNewChat} canStartNewChat={!isInitialState} />
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
                <h2 className="text-2xl font-bold text-gray-800">IDPAutoTune</h2>
                <p className="text-gray-600 mt-2">Enter a test set ID and optional guidance to start an optimization run</p>
              </div>
              <div className="px-4 mb-16 max-w-4xl mx-auto w-full space-y-3">
                <input
                  type="text"
                  value={testSetId}
                  onChange={e => setTestSetId(e.target.value)}
                  placeholder="Test Set ID (required)"
                  className="w-full px-3 py-2 border rounded-md text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <ChatInput input={input} setInput={setInput} handleSubmit={handleSubmit} isLoading={isLoading} placeholder="Optimization guidance (optional)" allowEmpty />
              </div>
              <div className="grow" />
            </>
          ) : (
            <>
              {/* Status bar */}
              {stateApiUrl && (
                <div className="flex-none px-4 py-2 border-b bg-white/80">
                  <div className="max-w-4xl mx-auto flex items-center gap-3">
                    {agentState && (
                      <div className="text-xs text-gray-500 flex items-center gap-2 flex-wrap">
                        <span className={`font-medium ${
                          agentState.status === "running"
                            ? (agentState.last_heartbeat_at && (Date.now() - new Date(String(agentState.last_heartbeat_at)).getTime()) > 120000)
                              ? "text-yellow-600"
                              : "text-green-600"
                            : agentState.status === "failed" ? "text-red-600"
                            : agentState.status === "complete" ? "text-blue-600"
                            : "text-yellow-600"
                        }`}>
                          {agentState.status === "running" && agentState.last_heartbeat_at && (Date.now() - new Date(String(agentState.last_heartbeat_at)).getTime()) > 120000
                            ? "POSSIBLY STALLED"
                            : String(agentState.status ?? "unknown").toUpperCase()}
                        </span>
                        {agentState.phase && <span>· {String(agentState.phase)}</span>}
                        {agentState.phase_detail && <span>— {String(agentState.phase_detail)}</span>}
                        {agentState.iteration != null && <span>· Iteration {String(agentState.iteration)}/{String(agentState.max_iterations ?? "?")}</span>}
                        {agentState.best_accuracy != null && Number(agentState.best_accuracy) > 0 && (
                          <span>· Best: {String(agentState.best_accuracy)}%</span>
                        )}
                        {agentState.status === "running" && agentState.last_heartbeat_at && (() => {
                          const ago = Math.floor((now - new Date(String(agentState.last_heartbeat_at)).getTime()) / 1000)
                          return <span>· ♥ {ago}s ago</span>
                        })()}
                      </div>
                    )}
                    <div className="ml-auto flex gap-2">
                      {isResumable && (
                        <button
                          onClick={handleResume}
                          disabled={isLoading}
                          className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 transition-colors disabled:opacity-50"
                        >
                          Resume
                        </button>
                      )}
                      {agentState?.status === "running" && (
                        <button
                          onClick={handleCancelOptimization}
                          className="px-3 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Tab bar */}
              <div className="flex-none border-b bg-white/60">
                <div className="max-w-4xl mx-auto flex">
                  <button
                    onClick={() => setActiveTab("stream")}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === "stream"
                        ? "border-blue-500 text-blue-700"
                        : "border-transparent text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Agent Stream {streamItems.length > 0 && `(${streamItems.length})`}
                  </button>
                  <button
                    onClick={() => setActiveTab("log")}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === "log"
                        ? "border-blue-500 text-blue-700"
                        : "border-transparent text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Optimization Log
                  </button>
                </div>
              </div>

              {/* Content area */}
              <div className="grow overflow-hidden">
                <div className="max-w-4xl mx-auto w-full h-full overflow-y-auto p-4">
                  {activeTab === "stream" ? (
                    <div className="space-y-1">
                      {renderedStream.length > 0 ? renderedStream : (
                        <p className="text-gray-400 text-center mt-8">
                          {agentState?.status === "running" ? "Waiting for agent events..." : "No stream data available"}
                        </p>
                      )}
                      <div ref={streamEndRef} />
                    </div>
                  ) : (
                    <div className="prose prose-sm max-w-none bg-white p-6 rounded border">
                      {optimizationLog ? (
                        <pre className="whitespace-pre-wrap text-sm text-gray-800">{optimizationLog}</pre>
                      ) : (
                        <p className="text-gray-400 text-center mt-8">
                          {agentState?.status === "running" ? "Waiting for optimization log..." : "No optimization log available"}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
