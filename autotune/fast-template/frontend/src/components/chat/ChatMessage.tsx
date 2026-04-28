import { Message } from "./types"
import { getToolRenderer } from "@/hooks/useToolRenderer"
import { MarkdownRenderer } from "./MarkdownRenderer"

interface ChatMessageProps {
  message: Message
}

export function ChatMessage({ message }: ChatMessageProps) {
  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const renderAssistantContent = () => {
    // If segments exist, render them in order (interleaved text + tools)
    if (message.segments && message.segments.length > 0) {
      return message.segments.map((seg, i) => {
        if (seg.type === "text") {
          return <MarkdownRenderer key={i} content={seg.content} />
        }
        const render = getToolRenderer(seg.toolCall.name)
        if (!render) return null
        return (
          <div key={seg.toolCall.toolUseId} className="my-1">
            {render({
              name: seg.toolCall.name,
              args: seg.toolCall.input,
              status: seg.toolCall.status,
              result: seg.toolCall.result,
            })}
          </div>
        )
      })
    }
    // Fallback: just render content as markdown
    return <MarkdownRenderer content={message.content} />
  }

  return (
    <div className={`flex flex-col ${message.role === "user" ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[80%] break-words ${
          message.role === "user"
            ? "p-3 rounded-lg bg-gray-800 text-white rounded-br-none whitespace-pre-wrap"
            : "text-gray-800"
        }`}
      >
        {message.role === "assistant" ? renderAssistantContent() : message.content}
      </div>

      <div className="flex items-center gap-2 mt-1 px-1">
        <div className="text-xs text-gray-500">{formatTime(message.timestamp)}</div>
      </div>
    </div>
  )
}
