"use client"

import { Activity, CheckCircle, XCircle, AlertTriangle, Plus } from "lucide-react"
import { RunSummary } from "./types"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"

type ChatSidebarProps = {
  runs: RunSummary[]
  currentSessionId?: string
  onRunSelect: (run: RunSummary) => void
  onNewChat: () => void
}

const STATUS_CONFIG: Record<string, { icon: typeof Activity; color: string }> = {
  complete: { icon: CheckCircle, color: "text-blue-600" },
  failed: { icon: XCircle, color: "text-red-600" },
  cancelled: { icon: AlertTriangle, color: "text-yellow-600" },
}

export function ChatSidebar({ runs, currentSessionId, onRunSelect, onNewChat }: ChatSidebarProps) {
  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader className="p-4 space-y-2">
        <Button onClick={onNewChat} className="w-full justify-start gap-2">
          <Plus className="h-4 w-4" />
          New Optimization Run
        </Button>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Optimization Runs</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {runs.map(run => {
                const cfg = STATUS_CONFIG[run.status] ?? { icon: Activity, color: "text-green-600" }
                const Icon = cfg.icon
                const shortId = run.session_id.slice(0, 8)
                const accuracy = run.best_accuracy != null && Number(run.best_accuracy) > 0
                  ? `${run.best_accuracy}%`
                  : null
                return (
                  <SidebarMenuItem key={run.session_id}>
                    <SidebarMenuButton
                      onClick={() => onRunSelect(run)}
                      isActive={currentSessionId === run.session_id}
                      className="w-full justify-start gap-2 h-auto py-2"
                    >
                      <Icon className={`h-4 w-4 shrink-0 ${cfg.color}`} />
                      <div className="flex flex-col items-start min-w-0">
                        <span className="text-xs font-mono truncate w-full">
                          {shortId} · {run.test_set_id ?? "unknown"}
                        </span>
                        <span className="text-xs text-gray-400 truncate w-full">
                          {accuracy && <span className="font-medium text-gray-600">{accuracy} </span>}
                          {run.iteration != null && `iter ${run.iteration}`}
                          {run.started_at && ` · ${new Date(run.started_at).toLocaleDateString()}`}
                        </span>
                      </div>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
              {runs.length === 0 && (
                <p className="text-xs text-gray-400 px-3 py-2">No runs yet</p>
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
