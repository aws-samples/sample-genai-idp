// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { Button, Icon, Hotspot } from '@cloudscape-design/components';
import { AgentChatProvider } from '../../contexts/agentChat';
import AgentChatLayout from './AgentChatLayout';
import { WELCOME_PATH } from '../../routes/constants';
import './QuickStartWidget.css';

const isWidgetEnabled = (): boolean => {
  const flag = import.meta.env.VITE_ENABLE_QUICK_START_WIDGET;
  return flag === undefined || flag === 'true' || flag === true;
};

const POSITION_KEY = 'idp-quick-start-widget-pos';
const DRAG_THRESHOLD = 4;

interface Position {
  x: number;
  y: number;
}

const loadPosition = (): Position | null => {
  try {
    const raw = localStorage.getItem(POSITION_KEY);
    return raw ? (JSON.parse(raw) as Position) : null;
  } catch {
    return null;
  }
};

const PANEL_MAX_W = 550;
const PANEL_MAX_H = 680;

const computePanelPosition = (rect: DOMRect): Position => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const panelW = Math.min(PANEL_MAX_W, vw - 48);
  const panelH = Math.min(PANEL_MAX_H, vh - 100);
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  let left = cx > vw / 2 ? rect.right - panelW : rect.left;
  let top = cy > vh / 2 ? rect.bottom - panelH : rect.top;
  left = Math.max(8, Math.min(left, vw - panelW - 8));
  top = Math.max(8, Math.min(top, vh - panelH - 8));
  return { x: left, y: top };
};

const OPENED_KEY = 'idp-qs-widget-opened';

const hasOpenedBefore = (): boolean => {
  try {
    return localStorage.getItem(OPENED_KEY) === 'true';
  } catch {
    return false;
  }
};

const QuickStartWidget = (): React.JSX.Element | null => {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<Position | null>(loadPosition);
  const [panelPos, setPanelPos] = useState<Position | null>(null);
  const [mounted, setMounted] = useState(false);
  const [initialMode, setInitialMode] = useState<'chat' | 'quick_start'>('quick_start');
  const dragState = useRef<{ startX: number; startY: number; originX: number; originY: number; moved: boolean } | null>(null);
  const suppressNextClick = useRef(false);
  const launcherRef = useRef<HTMLDivElement>(null);

  const doOpen = useCallback(
    (mode: 'chat' | 'quick_start') => {
      const rect = launcherRef.current?.getBoundingClientRect();
      if (rect) {
        setPanelPos(computePanelPosition(rect));
      }
      if (!mounted) {
        setInitialMode(hasOpenedBefore() ? mode : 'quick_start');
        try {
          localStorage.setItem(OPENED_KEY, 'true');
        } catch {
          /* ignore */
        }
        setMounted(true);
      }
      setOpen(true);
    },
    [mounted],
  );

  const openFromLauncher = useCallback(() => doOpen('chat'), [doOpen]);

  useEffect(() => {
    const handleOpen = () => doOpen('quick_start');
    window.addEventListener('openQuickStart', handleOpen);
    return () => window.removeEventListener('openQuickStart', handleOpen);
  }, [doOpen]);

  const clampLauncher = useCallback((x: number, y: number): Position => {
    const el = launcherRef.current;
    const w = el?.offsetWidth ?? 56;
    const h = el?.offsetHeight ?? 56;
    return { x: Math.max(8, Math.min(x, window.innerWidth - w - 8)), y: Math.max(8, Math.min(y, window.innerHeight - h - 8)) };
  }, []);

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      const ds = dragState.current;
      if (!ds) return;
      const dx = e.clientX - ds.startX;
      const dy = e.clientY - ds.startY;
      if (!ds.moved && Math.abs(dx) + Math.abs(dy) < DRAG_THRESHOLD) return;
      ds.moved = true;
      setPosition(clampLauncher(ds.originX + dx, ds.originY + dy));
    },
    [clampLauncher],
  );

  const onPointerUp = useCallback(() => {
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    const ds = dragState.current;
    dragState.current = null;
    if (ds?.moved) {
      suppressNextClick.current = true;
      setPosition((prev) => {
        if (prev) {
          try {
            localStorage.setItem(POSITION_KEY, JSON.stringify(prev));
          } catch {
            /* ignore */
          }
        }
        return prev;
      });
    }
  }, [onPointerMove]);

  const startDrag = useCallback(
    (e: React.PointerEvent) => {
      const rect = launcherRef.current?.getBoundingClientRect();
      dragState.current = {
        startX: e.clientX,
        startY: e.clientY,
        originX: rect?.left ?? 0,
        originY: rect?.top ?? 0,
        moved: false,
      };
      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp);
    },
    [onPointerMove, onPointerUp],
  );

  const handleLauncherClick = useCallback(() => {
    if (suppressNextClick.current) {
      suppressNextClick.current = false;
      return;
    }
    openFromLauncher();
  }, [openFromLauncher]);

  if (!isWidgetEnabled() || location.pathname === WELCOME_PATH) {
    return null;
  }

  const launcherWrapStyle: React.CSSProperties = position
    ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto', display: open ? 'none' : undefined }
    : { display: open ? 'none' : undefined };

  const panelStyle: React.CSSProperties = {
    position: 'fixed',
    display: open ? undefined : 'none',
    ...(panelPos ? { left: panelPos.x, top: panelPos.y, right: 'auto', bottom: 'auto' } : {}),
  };

  const headerTitle = initialMode === 'quick_start' ? 'Quick Start' : 'Agent Companion Chat';

  return (
    <div className="quick-start-widget">
      <div ref={launcherRef} className="quick-start-widget-launcher-wrap" style={launcherWrapStyle}>
        <Hotspot hotspotId="quick-start-launcher" side="left">
          <button
            type="button"
            className="quick-start-widget-launcher"
            aria-label="Open Quick Start"
            onPointerDown={startDrag}
            onClick={handleLauncherClick}
          >
            <Icon name="gen-ai" size="medium" />
          </button>
        </Hotspot>
      </div>
      <div className="quick-start-widget-panel" role="dialog" aria-label="Assistant" style={panelStyle}>
        <div className="quick-start-widget-header">
          <span className="quick-start-widget-title">{headerTitle}</span>
          <Button variant="icon" iconName="treeview-collapse" ariaLabel="Minimize" onClick={() => setOpen(false)} />
        </div>
        <div className="quick-start-widget-chat">
          {mounted && (
            <AgentChatProvider initialMode={initialMode}>
              <AgentChatLayout showHeader={false} brand={initialMode} />
            </AgentChatProvider>
          )}
        </div>
      </div>
    </div>
  );
};

export default QuickStartWidget;
