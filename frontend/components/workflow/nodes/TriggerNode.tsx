'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { type WorkflowNodeData } from '../types';
import { CustomTag, isCustomNodeType } from './CustomTag';

export default function TriggerNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNodeData;
  const isCustom = isCustomNodeType(d.nodeType);

  return (
    <div
      className={`
        min-w-[192px] rounded-xl border-2 px-4 py-3 ${isCustom ? "border-dashed" : ""}
        bg-card
        transition-all duration-150
        ${selected
          ? 'border-blue-500 shadow-lg shadow-blue-100'
          : 'border-blue-200 hover:border-blue-300'
        }
      `}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] text-blue-600 uppercase tracking-widest font-bold">Trigger</span>
        {isCustom && <CustomTag />}
      </div>

      {/* Label */}
      <p className="text-sm font-semibold text-foreground leading-tight">{d.label}</p>

      {/* Node type */}
      <p className="text-[11px] text-blue-400 font-mono mt-1 truncate">{isCustom ? "Not automated · skipped on run" : d.nodeType}</p>

      {/* Source handle — bottom center */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-blue-500 !border-2 !border-blue-300 !w-3 !h-3"
      />
    </div>
  );
}
