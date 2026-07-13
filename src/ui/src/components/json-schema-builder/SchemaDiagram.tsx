// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useMemo, useState } from 'react';
import { Box, Alert, SpaceBetween, Badge } from '@cloudscape-design/components';
import { X_AWS_IDP_DOCUMENT_TYPE } from '../../constants/schemaConstants';

// A dependency-free entity-relationship diagram of the schema: each class is a
// node listing its attributes; $ref / items.$ref relationships are drawn as
// labelled edges (single object vs array-of). Layout is a simple layered
// (Sugiyama-lite) placement — document types on the left, referenced shared
// classes in subsequent columns by reference depth. Rendered as inline SVG so
// no charting/graph library is required.

interface DiagramAttribute {
  type?: string;
  $ref?: string;
  items?: { $ref?: string; type?: string };
  [key: string]: unknown;
}

interface DiagramClass {
  id: string;
  name: string;
  [X_AWS_IDP_DOCUMENT_TYPE]?: unknown;
  attributes?: {
    properties?: Record<string, DiagramAttribute>;
    required?: string[];
  };
  [key: string]: unknown;
}

interface SchemaDiagramProps {
  classes: DiagramClass[];
  selectedClassId?: string | null;
  onSelectClass?: ((classId: string) => void) | null;
}

// Resolve a "#/$defs/Name" ref to just "Name".
const refToName = (ref: string | undefined): string | null => {
  if (!ref) return null;
  const parts = ref.split('/');
  return parts[parts.length - 1] || null;
};

interface Edge {
  fromId: string;
  toName: string;
  attribute: string;
  kind: 'object' | 'array';
}

// Layout constants.
const NODE_WIDTH = 220;
const HEADER_HEIGHT = 34;
const ROW_HEIGHT = 20;
const NODE_VGAP = 28;
const COL_HGAP = 90;
const PADDING = 24;
const MAX_ATTR_ROWS = 12; // cap visible attribute rows per node to keep it readable

const SchemaDiagram = ({ classes, selectedClassId = null, onSelectClass = null }: SchemaDiagramProps): React.JSX.Element => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const { nodes, edges, width, height, unreferenced } = useMemo(() => {
    const byName = new Map<string, DiagramClass>();
    classes.forEach((c) => byName.set(c.name, c));

    // Collect edges from every class's attributes.
    const allEdges: Edge[] = [];
    classes.forEach((cls) => {
      const props = cls.attributes?.properties || {};
      Object.entries(props).forEach(([attrName, attr]) => {
        const objRef = refToName(attr.$ref);
        const arrRef = refToName(attr.items?.$ref);
        if (objRef && byName.has(objRef)) {
          allEdges.push({ fromId: cls.id, toName: objRef, attribute: attrName, kind: 'object' });
        } else if (arrRef && byName.has(arrRef)) {
          allEdges.push({ fromId: cls.id, toName: arrRef, attribute: attrName, kind: 'array' });
        }
      });
    });

    // Assign columns by reference depth from document types (BFS). Document
    // types start at column 0; a class referenced by a column-N class sits at
    // column N+1 (max, so it's to the right of everything that references it).
    const colByName = new Map<string, number>();
    const docTypes = classes.filter((c) => c[X_AWS_IDP_DOCUMENT_TYPE]);
    const roots = docTypes.length > 0 ? docTypes : classes.slice(0, 1);
    roots.forEach((r) => colByName.set(r.name, 0));

    // Iteratively push referenced classes to the right of their referrers.
    // Bounded iterations guard against cycles.
    for (let iter = 0; iter < classes.length + 2; iter += 1) {
      let changed = false;
      allEdges.forEach((e) => {
        const from = classes.find((c) => c.id === e.fromId);
        if (!from) return;
        const fromCol = colByName.get(from.name) ?? 0;
        const want = fromCol + 1;
        const cur = colByName.get(e.toName);
        if (cur === undefined || want > cur) {
          colByName.set(e.toName, want);
          changed = true;
        }
      });
      if (!changed) break;
    }

    // Any class never placed (orphan shared class) goes in its own far column.
    const maxCol = Math.max(0, ...Array.from(colByName.values()));
    const unreferencedNames: string[] = [];
    classes.forEach((c) => {
      if (!colByName.has(c.name)) {
        colByName.set(c.name, maxCol + 1);
        if (!c[X_AWS_IDP_DOCUMENT_TYPE]) unreferencedNames.push(c.name);
      }
    });

    // Group classes by column, then stack vertically within each column.
    const columns = new Map<number, DiagramClass[]>();
    classes.forEach((c) => {
      const col = colByName.get(c.name) ?? 0;
      if (!columns.has(col)) columns.set(col, []);
      columns.get(col)!.push(c);
    });

    const nodeLayout = new Map<
      string,
      { cls: DiagramClass; x: number; y: number; w: number; h: number; attrRows: { name: string; badge: string }[] }
    >();

    const sortedCols = Array.from(columns.keys()).sort((a, b) => a - b);
    let maxColHeight = 0;
    sortedCols.forEach((col) => {
      const colClasses = columns.get(col)!;
      let y = PADDING;
      colClasses.forEach((cls) => {
        const props = cls.attributes?.properties || {};
        const entries = Object.entries(props).slice(0, MAX_ATTR_ROWS);
        const attrRows = entries.map(([name, attr]) => {
          let badge = attr.type || 'string';
          const objRef = refToName(attr.$ref);
          const arrRef = refToName(attr.items?.$ref);
          if (objRef) badge = objRef;
          else if (arrRef) badge = `array[${arrRef}]`;
          else if (attr.type === 'array') badge = `array[${attr.items?.type || 'item'}]`;
          return { name, badge };
        });
        const hiddenCount = Object.keys(props).length - entries.length;
        if (hiddenCount > 0) {
          attrRows.push({ name: `… +${hiddenCount} more`, badge: '' });
        }
        const h = HEADER_HEIGHT + Math.max(1, attrRows.length) * ROW_HEIGHT + 8;
        const x = PADDING + col * (NODE_WIDTH + COL_HGAP);
        nodeLayout.set(cls.id, { cls, x, y, w: NODE_WIDTH, h, attrRows });
        y += h + NODE_VGAP;
      });
      maxColHeight = Math.max(maxColHeight, y);
    });

    const totalWidth = PADDING * 2 + (sortedCols.length > 0 ? sortedCols[sortedCols.length - 1] : 0) * (NODE_WIDTH + COL_HGAP) + NODE_WIDTH;

    return {
      nodes: Array.from(nodeLayout.values()),
      edges: allEdges.map((e) => {
        const from = nodeLayout.get(e.fromId);
        const toCls = classes.find((c) => c.name === e.toName);
        const to = toCls ? nodeLayout.get(toCls.id) : undefined;
        return { edge: e, from, to };
      }),
      width: Math.max(totalWidth, 400),
      height: Math.max(maxColHeight + PADDING, 200),
      unreferenced: unreferencedNames,
    };
  }, [classes]);

  if (classes.length === 0) {
    return (
      <Box textAlign="center" padding="xxl">
        <Alert type="info">Add classes and attributes to see the entity-relationship diagram.</Alert>
      </Box>
    );
  }

  const hasEdges = edges.some((e) => e.from && e.to);

  return (
    <SpaceBetween size="s">
      <Box color="text-body-secondary" fontSize="body-s">
        Document types and the classes they reference via <code>$ref</code>. Solid arrow = single object, dashed arrow = array/list. Click a
        class to open it.
      </Box>
      {!hasEdges && (
        <Alert type="info">
          No relationships between classes yet. Reference a shared class from an attribute (object or array) to see connections here.
        </Alert>
      )}
      <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 360px)', border: '1px solid #e9ebed', borderRadius: 8 }}>
        <svg width={width} height={height} role="img" aria-label="Schema entity-relationship diagram" style={{ display: 'block' }}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#5f6b7a" />
            </marker>
          </defs>

          {/* Edges (drawn first so nodes paint on top) */}
          {edges.map(({ edge, from, to }, i) => {
            if (!from || !to) return null;
            const x1 = from.x + from.w;
            const y1 = from.y + HEADER_HEIGHT / 2;
            const x2 = to.x;
            const y2 = to.y + HEADER_HEIGHT / 2;
            const midX = (x1 + x2) / 2;
            const path = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
            const active = hoveredId === from.cls.id || hoveredId === to.cls.id;
            return (
              // eslint-disable-next-line react/no-array-index-key
              <g key={`edge-${i}`}>
                <path
                  d={path}
                  fill="none"
                  stroke={active ? '#0972d3' : '#5f6b7a'}
                  strokeWidth={active ? 2 : 1.25}
                  strokeDasharray={edge.kind === 'array' ? '5 4' : undefined}
                  markerEnd="url(#arrow)"
                />
                <text x={midX} y={(y1 + y2) / 2 - 4} fontSize="10" fill="#5f6b7a" textAnchor="middle">
                  {edge.attribute}
                </text>
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map(({ cls, x, y, w, h, attrRows }) => {
            const isDocType = Boolean(cls[X_AWS_IDP_DOCUMENT_TYPE]);
            const isSelected = cls.id === selectedClassId;
            const headerFill = isDocType ? '#0972d3' : '#414d5c';
            return (
              <g
                key={cls.id}
                transform={`translate(${x}, ${y})`}
                style={{ cursor: onSelectClass ? 'pointer' : 'default' }}
                onClick={() => onSelectClass?.(cls.id)}
                onMouseEnter={() => setHoveredId(cls.id)}
                onMouseLeave={() => setHoveredId(null)}
              >
                <rect
                  width={w}
                  height={h}
                  rx={6}
                  fill="#ffffff"
                  stroke={isSelected ? '#0972d3' : '#c6c6cd'}
                  strokeWidth={isSelected ? 2.5 : 1}
                />
                <rect width={w} height={HEADER_HEIGHT} rx={6} fill={headerFill} />
                <rect y={HEADER_HEIGHT - 6} width={w} height={6} fill={headerFill} />
                <text x={10} y={HEADER_HEIGHT / 2 + 4} fontSize="13" fontWeight="bold" fill="#ffffff">
                  {cls.name.length > 26 ? `${cls.name.slice(0, 25)}…` : cls.name}
                </text>
                {attrRows.map((row, ri) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <g key={`${cls.id}-row-${ri}`} transform={`translate(0, ${HEADER_HEIGHT + ri * ROW_HEIGHT})`}>
                    <text x={10} y={ROW_HEIGHT / 2 + 8} fontSize="11" fill="#16191f">
                      {row.name.length > 20 ? `${row.name.slice(0, 19)}…` : row.name}
                    </text>
                    {row.badge && (
                      <text x={w - 10} y={ROW_HEIGHT / 2 + 8} fontSize="10" fill="#5f6b7a" textAnchor="end">
                        {row.badge.length > 16 ? `${row.badge.slice(0, 15)}…` : row.badge}
                      </text>
                    )}
                  </g>
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <Box fontSize="body-s" color="text-body-secondary">
        <SpaceBetween direction="horizontal" size="xs">
          <Badge color="blue">Document type</Badge>
          <Badge color="grey">Shared class</Badge>
          {unreferenced.length > 0 && <span>Unreferenced shared classes: {unreferenced.join(', ')}</span>}
        </SpaceBetween>
      </Box>
    </SpaceBetween>
  );
};

export default React.memo(SchemaDiagram);
