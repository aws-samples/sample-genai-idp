// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: LicenseRef-AWS-Proprietary

import { RefObject } from "react"
import { Message } from "./types"
import { ChatMessage } from "./ChatMessage"

interface ChatMessagesProps {
  messages: Message[]
  messagesEndRef: RefObject<HTMLDivElement | null>
}

export function ChatMessages({ messages, messagesEndRef }: ChatMessagesProps) {
  return (
    <div
      className={`h-full p-4 space-y-4 w-full ${
        messages.length > 0 ? "overflow-y-auto" : "overflow-hidden"
      }`}
    >
      {messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-400">
          Start a new conversation
        </div>
      ) : (
        messages.map((message, index) => (
          <ChatMessage key={index} message={message} />
        ))
      )}
      <div ref={messagesEndRef} />
    </div>
  )
}
