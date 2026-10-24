"use client";

import "@xyflow/react/dist/style.css";

import {
  useState,
  useCallback,
  useRef,
  useEffect,
  type DragEvent,
} from "react";
import { useSearchParams } from "next/navigation";
import { useLocalAuth } from "@/lib/local-auth";
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  addEdge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeTypes,
  BackgroundVariant,
  SelectionMode,
} from "@xyflow/react";

import { NodePalette } from "./NodePalette";
import { PropertiesPanel } from "./PropertiesPanel";
import TriggerNode from "./nodes/TriggerNode";
import ActionNode from "./nodes/ActionNode";
import ConditionalNode from "./nodes/ConditionalNode";
import EndpointNode from "./nodes/EndpointNode";
import { type CatalogueNode } from "./types";
import {
  createWorkflow,
  createWorkflowFromTemplate,
  updateWorkflow,
  listWorkflows,
  listWorkflowTemplates,
  getWorkflow,
  generateWorkflowFromPrompt,
  executeWorkflowWithContext,
  checkCallStatus,
  listPatientReports,
  listPatients,
  createPatient,
  transcribeAudioWithDeepgram,
  type ReportItem,
  type CallStatusResult,
  type ExecuteWorkflowResult,
  type WorkflowTemplateItem,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import Image from "next/image";
import {
  Undo2,
  Redo2,
  MousePointer2,
  Hand,
  Mic,
  FileText,
  Phone,
  Sparkles,
  LayoutTemplate,
} from "lucide-react";
import dagre from "dagre";
import { CmdHoverContext } from "./CmdHoverContext";

// ─── Auto-layout helper (dagre) ─────────────────────────────────────────────

function getLayoutedElements(nodes: Node[], edges: Edge[], direction = "TB") {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 80 });

  nodes.forEach((node) => {
    g.setNode(node.id, { width: 200, height: 100 });
  });
  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target);
  });

  dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    return { ...node, position: { x: pos.x - 100, y: pos.y - 50 } };
  });

  return { nodes: layoutedNodes, edges };
}

// ─── Register custom node types ─────────────────────────────────────────────

const nodeTypes: NodeTypes = {
  trigger: TriggerNode,
  action: ActionNode,
  conditional: ConditionalNode,
  endpoint: EndpointNode,
};

// ─── Edge defaults ───────────────────────────────────────────────────────────

const defaultEdgeOptions = {
  animated: true,
  style: { stroke: "#C43B3B", strokeWidth: 2 },
};

// ─── Node ID generator ───────────────────────────────────────────────────────

let _idCounter = 0;
const newId = () => `node_${Date.now()}_${++_idCounter}`;

type WorkflowListEntry = {
  id: string;
  name?: string;
  description?: string;
  status?: string;
  nodes?: unknown[];
  edges?: unknown[];
  created_at?: string;
};

type PatientListItem = {
  id: string;
  name: string;
  phone: string;
};

type ExecutionStep = {
  label?: string;
  node_type?: string;
  status?: string;
  message?: string;
};

// ─── Example workflow ────────────────────────────────────────────────────────

const EXAMPLE_NODES: Node[] = [
  {
    id: "ex_1",
    type: "trigger",
    position: { x: 280, y: 40 },
    data: {
      label: "Lab Results Received",
      nodeType: "lab_results_received",
      description: "Lab result arrives for patient",
      params: {},
    },
  },
  {
    id: "ex_2",
    type: "conditional",
    position: { x: 280, y: 180 },
    data: {
      label: "Check Result Values",
      nodeType: "check_result_values",
      description: "Are results abnormal?",
      params: { result: "" },
    },
  },
  {
    id: "ex_3",
    type: "action",
    position: { x: 100, y: 340 },
    data: {
      label: "Call Patient",
      nodeType: "call_patient",
      description: "Place outbound Twilio call",
      params: { message: "" },
    },
  },
  {
    id: "ex_4",
    type: "action",
    position: { x: 100, y: 490 },
    data: {
      label: "Schedule Appointment",
      nodeType: "schedule_appointment",
      description: "Schedule follow-up",
      params: {},
    },
  },
  {
    id: "ex_5",
    type: "endpoint",
    position: { x: 100, y: 640 },
    data: {
      label: "Send Summary to Doctor",
      nodeType: "send_summary_to_doctor",
      description: "Notify the doctor",
      params: {},
    },
  },
  {
    id: "ex_6",
    type: "action",
    position: { x: 460, y: 340 },
    data: {
      label: "Send SMS",
      nodeType: "send_sms",
      description: "SMS with normal results",
      params: { message: "Your results are normal." },
    },
  },
  {
    id: "ex_7",
    type: "endpoint",
    position: { x: 460, y: 490 },
    data: {
      label: "Log Completion",
      nodeType: "log_completion",
      description: "Workflow complete",
      params: {},
    },
  },
];

const EXAMPLE_EDGES: Edge[] = [
  {
    id: "ee_1",
    source: "ex_1",
    target: "ex_2",
    animated: true,
    style: { stroke: "#C43B3B", strokeWidth: 2 },
  },
  {
    id: "ee_2",
    source: "ex_2",
    sourceHandle: "true",
    target: "ex_3",
    animated: true,
    style: { stroke: "#10b981", strokeWidth: 2 },
  },
  {
    id: "ee_3",
    source: "ex_2",
    sourceHandle: "false",
    target: "ex_6",
    animated: true,
    style: { stroke: "#ef4444", strokeWidth: 2 },
  },
  {
    id: "ee_4",
    source: "ex_3",
    target: "ex_4",
    animated: true,
    style: { stroke: "#C43B3B", strokeWidth: 2 },
  },
  {
    id: "ee_5",
    source: "ex_4",
    target: "ex_5",
    animated: true,
    style: { stroke: "#C43B3B", strokeWidth: 2 },
  },
  {
    id: "ee_6",
    source: "ex_6",
    target: "ex_7",
    animated: true,
    style: { stroke: "#C43B3B", strokeWidth: 2 },
  },
];

// ─── Inner component — uses useReactFlow, must be inside ReactFlowProvider ──

function FlowContent() {
  const { screenToFlowPosition, fitView } = useReactFlow();
  const { user } = useLocalAuth();
  const searchParams = useSearchParams();

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [selectMode, setSelectMode] = useState(true);
  const [rightPanelWidth, setRightPanelWidth] = useState(352);
  const [agentPanelHeight, setAgentPanelHeight] = useState(320);
  const [activeResize, setActiveResize] = useState<
    "column" | "split" | null
  >(null);

  // ── Cmd+hover connection state ──────────────────────────────────────
  const [cmdHeld, setCmdHeld] = useState(false);
  const workspaceBodyRef = useRef<HTMLDivElement | null>(null);
  const rightPanelRef = useRef<HTMLElement | null>(null);
  const resizeDragRef = useRef<{
    type: "column" | "split";
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
  } | null>(null);
  const lastHoveredRef = useRef<string | null>(null);
  const cmdHandleRef = useRef<string | undefined>(undefined);
  const setHandle = useCallback((h: string | undefined) => {
    cmdHandleRef.current = h;
  }, []);

  // ── Undo / Redo history ──────────────────────────────────────────────
  const historyRef = useRef<{ nodes: Node[]; edges: Edge[] }[]>([]);
  const historyIndexRef = useRef(-1);
  const isUndoRedoRef = useRef(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  // ── Save-to-DB state ──────────────────────────────────────────────────
  const [savedWorkflowId, setSavedWorkflowId] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [showNameModal, setShowNameModal] = useState(false);
  const [workflowName, setWorkflowName] = useState("");
  const [workflowDescription, setWorkflowDescription] = useState("");

  // ── AI Builder panel state ───────────────────────────────────────────
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiWarnings, setAiWarnings] = useState<string[]>([]);
  const [aiNotes, setAiNotes] = useState<string[]>([]);
  const [isSpeechRecording, setIsSpeechRecording] = useState(false);
  const [isSpeechTranscribing, setIsSpeechTranscribing] = useState(false);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const speechChunksRef = useRef<Blob[]>([]);

  // ── Load Workflow modal state ─────────────────────────────────────────
  const [showLoadModal, setShowLoadModal] = useState(false);
  const [availableWorkflows, setAvailableWorkflows] = useState<
    WorkflowListEntry[]
  >([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(false);
  const [loadWorkflowError, setLoadWorkflowError] = useState<string | null>(
    null,
  );

  // ── Ready templates modal state ───────────────────────────────────────
  const [showTemplatesModal, setShowTemplatesModal] = useState(false);
  const [workflowTemplates, setWorkflowTemplates] = useState<
    WorkflowTemplateItem[]
  >([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [applyingTemplateId, setApplyingTemplateId] = useState<string | null>(
    null,
  );
  const [creatingTemplateId, setCreatingTemplateId] = useState<string | null>(
    null,
  );

  // ── Run Workflow modal state ──────────────────────────────────────────
  const [showRunModal, setShowRunModal] = useState(false);
  const [patients, setPatients] = useState<PatientListItem[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(false);
  const [patientsFallbackUsed, setPatientsFallbackUsed] = useState(false);
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(
    null,
  );
  const [runStatus, setRunStatus] = useState<
    "idle" | "running" | "success" | "error"
  >("idle");
  const [runResult, setRunResult] = useState<ExecuteWorkflowResult | null>(
    null,
  );
  const [showAddPatient, setShowAddPatient] = useState(false);
  const [newPatientName, setNewPatientName] = useState("");
  const [newPatientPhone, setNewPatientPhone] = useState("");
  const [addingPatient, setAddingPatient] = useState(false);

  // ── Report / Call state ───────────────────────────────────────────────
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [patientReports, setPatientReports] = useState<ReportItem[]>([]);
  const [loadingReports, setLoadingReports] = useState(false);
  const [callLogId, setCallLogId] = useState<string | null>(null);
  const [callStatus, setCallStatus] = useState<CallStatusResult | null>(null);
  const [pollingActive, setPollingActive] = useState(false);

  // ── Auto-load workflow from URL query param ─────────────────────────
  useEffect(() => {
    const workflowId = searchParams.get("id");
    if (!workflowId) return;
    (async () => {
      try {
        const wf = await getWorkflow(workflowId);
        if (wf && wf.id) {
          const loadedNodes: Node[] = Array.isArray(wf.nodes) ? wf.nodes : [];
          const loadedEdges: Edge[] = Array.isArray(wf.edges) ? wf.edges : [];
          setNodes(loadedNodes);
          setEdges(loadedEdges);
          setSavedWorkflowId(wf.id);
          setWorkflowName(wf.name ?? "");
          setWorkflowDescription(wf.description ?? "");
          setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 100);
        }
      } catch {
        // silently fail — user can load manually
      }
    })();
  }, [searchParams, setNodes, setEdges, fitView]);

  // ── Connections ───────────────────────────────────────────────────────

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            animated: true,
            style: { stroke: "#C43B3B", strokeWidth: 2 },
          },
          eds,
        ),
      );
    },
    [setEdges],
  );

  // ── Selection ─────────────────────────────────────────────────────────

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // ── Cmd+hover to connect nodes ───────────────────────────────────────

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        setCmdHeld(true);
        lastHoveredRef.current = null;
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (!e.metaKey && !e.ctrlKey) {
        setCmdHeld(false);
        lastHoveredRef.current = null;
        cmdHandleRef.current = undefined;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  // ── Resizable side panels ───────────────────────────────────────────

  useEffect(() => {
    if (!activeResize) return;

    const onMouseMove = (event: MouseEvent) => {
      const drag = resizeDragRef.current;
      if (!drag) return;

      if (drag.type === "column") {
        const containerWidth =
          workspaceBodyRef.current?.clientWidth ?? window.innerWidth;
        const minWidth = 300;
        const maxWidth = Math.max(minWidth, containerWidth - 360);
        const deltaX = event.clientX - drag.startX;
        const nextWidth = Math.max(
          minWidth,
          Math.min(maxWidth, drag.startWidth - deltaX),
        );
        setRightPanelWidth(nextWidth);
      } else {
        const panelHeight = rightPanelRef.current?.clientHeight ?? 0;
        const minHeight = 220;
        const maxHeight = Math.max(minHeight, panelHeight - 220);
        const deltaY = event.clientY - drag.startY;
        const nextHeight = Math.max(
          minHeight,
          Math.min(maxHeight, drag.startHeight - deltaY),
        );
        setAgentPanelHeight(nextHeight);
      }
    };

    const onMouseUp = () => {
      setActiveResize(null);
      resizeDragRef.current = null;
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    document.body.style.userSelect = "none";
    document.body.style.cursor =
      activeResize === "column" ? "col-resize" : "row-resize";

    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
  }, [activeResize]);

  useEffect(() => {
    const clampPanelSizes = () => {
      const containerWidth =
        workspaceBodyRef.current?.clientWidth ?? window.innerWidth;
      const minWidth = 300;
      const maxWidth = Math.max(minWidth, containerWidth - 360);
      setRightPanelWidth((prev) => Math.max(minWidth, Math.min(maxWidth, prev)));

      const panelHeight = rightPanelRef.current?.clientHeight ?? 0;
      if (panelHeight > 0) {
        const minHeight = 220;
        const maxHeight = Math.max(minHeight, panelHeight - 220);
        setAgentPanelHeight((prev) =>
          Math.max(minHeight, Math.min(maxHeight, prev)),
        );
      }
    };

    clampPanelSizes();
    window.addEventListener("resize", clampPanelSizes);
    return () => window.removeEventListener("resize", clampPanelSizes);
  }, []);

  const stopSpeechStream = useCallback(() => {
    if (!mediaStreamRef.current) return;
    mediaStreamRef.current.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  }, []);

  const stopSpeechCapture = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder) {
      stopSpeechStream();
      setIsSpeechRecording(false);
      return;
    }
    if (recorder.state !== "inactive") {
      recorder.stop();
      return;
    }
    stopSpeechStream();
    setIsSpeechRecording(false);
  }, [stopSpeechStream]);

  const startSpeechCapture = useCallback(async () => {
    if (typeof window === "undefined") return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setSpeechError("Microphone recording is not supported in this browser.");
      return;
    }

    setSpeechError(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      const supportedMimeType = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
      ].find((type) => MediaRecorder.isTypeSupported(type));

      const recorder = supportedMimeType
        ? new MediaRecorder(stream, { mimeType: supportedMimeType })
        : new MediaRecorder(stream);

      speechChunksRef.current = [];
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          speechChunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        setSpeechError("Microphone recording failed. Please retry.");
        setIsSpeechRecording(false);
        stopSpeechStream();
      };

      recorder.onstop = async () => {
        setIsSpeechRecording(false);
        stopSpeechStream();

        const chunks = speechChunksRef.current;
        speechChunksRef.current = [];
        mediaRecorderRef.current = null;

        if (chunks.length === 0) return;

        const audioBlob = new Blob(chunks, {
          type: recorder.mimeType || "audio/webm",
        });
        if (audioBlob.size === 0) return;

        setIsSpeechTranscribing(true);
        setSpeechError(null);

        try {
          const { transcript } = await transcribeAudioWithDeepgram(audioBlob);
          const text = transcript.trim();
          if (!text) {
            setSpeechError("No speech detected. Please try again.");
            return;
          }

          setAiPrompt((prev) => {
            const base = prev.trimEnd();
            return base ? `${base} ${text}` : text;
          });
        } catch (err: unknown) {
          setSpeechError(
            err instanceof Error
              ? err.message
              : "Deepgram transcription failed. Please retry.",
          );
        } finally {
          setIsSpeechTranscribing(false);
        }
      };

      recorder.start(250);
      setIsSpeechRecording(true);
    } catch (err: unknown) {
      setSpeechError(
        err instanceof Error
          ? err.message
          : "Unable to access microphone. Check browser permissions.",
      );
      stopSpeechStream();
      setIsSpeechRecording(false);
    }
  }, [stopSpeechStream]);

  const toggleSpeechCapture = useCallback(async () => {
    if (isSpeechTranscribing) return;

    if (isSpeechRecording) {
      stopSpeechCapture();
      return;
    }

    await startSpeechCapture();
  }, [isSpeechRecording, isSpeechTranscribing, startSpeechCapture, stopSpeechCapture]);

  useEffect(() => {
    return () => {
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.stop();
      }
      stopSpeechStream();
    };
  }, [stopSpeechStream]);

  // ── Undo / Redo ─────────────────────────────────────────────────────

  const pushHistory = useCallback((n: Node[], e: Edge[]) => {
    const history = historyRef.current;
    const idx = historyIndexRef.current;
    // Trim any future entries if we branched
    historyRef.current = history.slice(0, idx + 1);
    historyRef.current.push({
      nodes: JSON.parse(JSON.stringify(n)),
      edges: JSON.parse(JSON.stringify(e)),
    });
    historyIndexRef.current = historyRef.current.length - 1;
    setCanUndo(historyIndexRef.current > 0);
    setCanRedo(false);
  }, []);

  // Debounced history recording — only structural changes (not position/selection moves)
  useEffect(() => {
    if (isUndoRedoRef.current) {
      isUndoRedoRef.current = false;
      return;
    }
    const timer = setTimeout(() => {
      const last = historyRef.current[historyIndexRef.current];
      const stripNode = (n: Node) => ({ id: n.id, type: n.type, data: n.data });
      const stripEdge = (e: Edge) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
        data: e.data,
      });
      const nodesKey = JSON.stringify(nodes.map(stripNode));
      const edgesKey = JSON.stringify(edges.map(stripEdge));
      if (last) {
        const lastNodesKey = JSON.stringify(last.nodes.map(stripNode));
        const lastEdgesKey = JSON.stringify(last.edges.map(stripEdge));
        if (nodesKey === lastNodesKey && edgesKey === lastEdgesKey) return;
      }
      pushHistory(nodes, edges);
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  const undo = useCallback(() => {
    const idx = historyIndexRef.current;
    if (idx <= 0) return;
    const newIdx = idx - 1;
    historyIndexRef.current = newIdx;
    const snap = historyRef.current[newIdx];
    isUndoRedoRef.current = true;
    setNodes(JSON.parse(JSON.stringify(snap.nodes)));
    isUndoRedoRef.current = true;
    setEdges(JSON.parse(JSON.stringify(snap.edges)));
    setCanUndo(newIdx > 0);
    setCanRedo(true);
  }, [setNodes, setEdges]);

  const redo = useCallback(() => {
    const idx = historyIndexRef.current;
    if (idx >= historyRef.current.length - 1) return;
    const newIdx = idx + 1;
    historyIndexRef.current = newIdx;
    const snap = historyRef.current[newIdx];
    isUndoRedoRef.current = true;
    setNodes(JSON.parse(JSON.stringify(snap.nodes)));
    isUndoRedoRef.current = true;
    setEdges(JSON.parse(JSON.stringify(snap.edges)));
    setCanUndo(true);
    setCanRedo(newIdx < historyRef.current.length - 1);
  }, [setNodes, setEdges]);

  // Keyboard shortcuts for undo/redo + select/pan mode
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Skip if user is typing in an input/textarea
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && e.shiftKey) {
        e.preventDefault();
        redo();
      }
      if (e.key === "v" && !e.metaKey && !e.ctrlKey) setSelectMode(true);
      if (e.key === "h" && !e.metaKey && !e.ctrlKey) setSelectMode(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [undo, redo]);

  const onNodeMouseEnter = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (!cmdHeld) return;
      const prev = lastHoveredRef.current;
      if (prev && prev !== node.id) {
        // Detect sourceHandle for conditional nodes via ref set by ConditionalNode
        let sourceHandle: string | undefined;
        const prevNode = nodes.find((n) => n.id === prev);
        if (prevNode?.type === "conditional") {
          sourceHandle = cmdHandleRef.current ?? "true";
        }
        setEdges((eds) =>
          addEdge(
            {
              id: `e_${prev}_${node.id}_${Date.now()}`,
              source: prev,
              target: node.id,
              sourceHandle,
              animated: true,
              style: {
                stroke:
                  sourceHandle === "false"
                    ? "#ef4444"
                    : sourceHandle === "true"
                      ? "#10b981"
                      : "#C43B3B",
                strokeWidth: 2,
              },
            },
            eds,
          ),
        );
      }
      lastHoveredRef.current = node.id;
    },
    [cmdHeld, setEdges, nodes],
  );

  // ── Drag and drop from palette ────────────────────────────────────────

  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();

      const raw = event.dataTransfer.getData("application/reactflow");
      if (!raw) return;

      const dropped = JSON.parse(raw) as CatalogueNode & {
        reactFlowType: string;
      };
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode: Node = {
        id: newId(),
        type: dropped.reactFlowType,
        position,
        data: {
          label: dropped.label,
          nodeType: dropped.nodeType,
          description: dropped.description,
          params: { ...dropped.params },
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [screenToFlowPosition, setNodes],
  );

  // ── Properties panel updates ──────────────────────────────────────────

  const updateNodeParams = useCallback(
    (nodeId: string, params: Record<string, string>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, params } } : n,
        ),
      );
      setSelectedNode((prev) =>
        prev?.id === nodeId
          ? { ...prev, data: { ...prev.data, params } }
          : prev,
      );
    },
    [setNodes],
  );

  const deleteNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) =>
        eds.filter((e) => e.source !== nodeId && e.target !== nodeId),
      );
      setSelectedNode((prev) => (prev?.id === nodeId ? null : prev));
    },
    [setNodes, setEdges],
  );

  // ── Toolbar actions ───────────────────────────────────────────────────

  const clearCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSelectedNode(null);
    setSavedWorkflowId(null);
    setWorkflowName("");
    setWorkflowDescription("");
  }, [setNodes, setEdges]);

  const loadExample = useCallback(() => {
    setNodes(EXAMPLE_NODES);
    setEdges(EXAMPLE_EDGES);
    setSelectedNode(null);
    setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 50);
  }, [setNodes, setEdges, fitView]);

  const cleanLayout = useCallback(() => {
    const { nodes: layouted } = getLayoutedElements(nodes, edges);
    setNodes(layouted);
    setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 50);
  }, [nodes, edges, setNodes, fitView]);

  const exportWorkflow = useCallback(() => {
    const workflow = { nodes, edges };
    const blob = new Blob([JSON.stringify(workflow, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `workflow-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [nodes, edges]);

  const startColumnResize = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      resizeDragRef.current = {
        type: "column",
        startX: event.clientX,
        startY: event.clientY,
        startWidth: rightPanelWidth,
        startHeight: agentPanelHeight,
      };
      setActiveResize("column");
    },
    [rightPanelWidth, agentPanelHeight],
  );

  const startSplitResize = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      resizeDragRef.current = {
        type: "split",
        startX: event.clientX,
        startY: event.clientY,
        startWidth: rightPanelWidth,
        startHeight: agentPanelHeight,
      };
      setActiveResize("split");
    },
    [rightPanelWidth, agentPanelHeight],
  );

  // ── Save to Supabase via backend API ──────────────────────────────────

  const doSave = useCallback(
    async (name: string, description: string) => {
      setSaveStatus("saving");
      setShowNameModal(false);
      setWorkflowName(name);
      setWorkflowDescription(description);

      const doctorId = user?.doctor_id ?? user?.sub ?? "anonymous";

      try {
        if (savedWorkflowId) {
          await updateWorkflow(savedWorkflowId, {
            name,
            description,
            nodes: nodes as unknown[],
            edges: edges as unknown[],
          });
        } else {
          const result = await createWorkflow({
            doctor_id: doctorId,
            name,
            description,
            nodes: nodes as unknown[],
            edges: edges as unknown[],
          });
          setSavedWorkflowId(result.id);
        }
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2500);
      } catch {
        setSaveStatus("error");
        setTimeout(() => setSaveStatus("idle"), 3000);
      }
    },
    [savedWorkflowId, nodes, edges, user],
  );

  const handleSaveClick = useCallback(() => {
    if (savedWorkflowId) {
      doSave(workflowName, workflowDescription);
    } else {
      setShowNameModal(true);
    }
  }, [savedWorkflowId, workflowName, workflowDescription, doSave]);

  const handleGenerateWorkflowWithAi = useCallback(async () => {
    const prompt = aiPrompt.trim();
    if (!prompt) {
      setAiError("Please describe the workflow you want to build.");
      return;
    }

    setAiGenerating(true);
    setAiError(null);
    setAiWarnings([]);
    setAiNotes([]);

    try {
      const doctorId = user?.doctor_id ?? user?.sub ?? null;
      const generated = await generateWorkflowFromPrompt({
        prompt,
        doctor_id: doctorId,
      });

      const generatedNodes = Array.isArray(generated.nodes)
        ? (generated.nodes as Node[])
        : [];
      const generatedEdges = Array.isArray(generated.edges)
        ? (generated.edges as Edge[])
        : [];

      setNodes(generatedNodes);
      setEdges(generatedEdges);
      setSelectedNode(null);

      const nextName = (generated.workflow_name || "AI Generated Workflow").trim();
      const nextDescription = (generated.workflow_description || "").trim();
      setWorkflowName(nextName);
      setWorkflowDescription(nextDescription);

      setAiWarnings(Array.isArray(generated.warnings) ? generated.warnings : []);
      setAiNotes(Array.isArray(generated.notes) ? generated.notes : []);

      const currentWorkflowId = savedWorkflowId;
      setSaveStatus("saving");
      if (currentWorkflowId) {
        await updateWorkflow(currentWorkflowId, {
          name: nextName,
          description: nextDescription,
          nodes: generatedNodes as unknown[],
          edges: generatedEdges as unknown[],
        });
      } else {
        const created = await createWorkflow({
          doctor_id: doctorId ?? "anonymous",
          name: nextName,
          description: nextDescription,
          nodes: generatedNodes as unknown[],
          edges: generatedEdges as unknown[],
        });
        if (created?.id) {
          setSavedWorkflowId(created.id);
        }
      }

      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2500);
      setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 120);
    } catch (err: unknown) {
      setAiError(
        err instanceof Error
          ? err.message
          : "Failed to generate workflow from prompt.",
      );
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("idle"), 2500);
    } finally {
      setAiGenerating(false);
    }
  }, [aiPrompt, user, savedWorkflowId, setNodes, setEdges, fitView]);

  // ── Load Workflow ─────────────────────────────────────────────────────

  const openLoadModal = useCallback(async () => {
    setShowLoadModal(true);
    setLoadingWorkflows(true);
    setLoadWorkflowError(null);
    try {
      const workflows = await listWorkflows();
      setAvailableWorkflows(Array.isArray(workflows) ? workflows : []);
    } catch (err: unknown) {
      setAvailableWorkflows([]);
      setLoadWorkflowError(
        err instanceof Error
          ? err.message
          : "Failed to load workflows. Is the backend running?",
      );
    } finally {
      setLoadingWorkflows(false);
    }
  }, []);

  const openTemplatesModal = useCallback(async () => {
    setShowTemplatesModal(true);
    setLoadingTemplates(true);
    setTemplateError(null);
    try {
      const templates = await listWorkflowTemplates();
      setWorkflowTemplates(Array.isArray(templates) ? templates : []);
    } catch (err: unknown) {
      setWorkflowTemplates([]);
      setTemplateError(
        err instanceof Error
          ? err.message
          : "Failed to load workflow templates.",
      );
    } finally {
      setLoadingTemplates(false);
    }
  }, []);

  const applyTemplateToCanvas = useCallback(
    async (template: WorkflowTemplateItem) => {
      setApplyingTemplateId(template.id);
      try {
        const nextNodes: Node[] = Array.isArray(template.nodes)
          ? (template.nodes as Node[])
          : [];
        const nextEdges: Edge[] = Array.isArray(template.edges)
          ? (template.edges as Edge[])
          : [];
        setNodes(JSON.parse(JSON.stringify(nextNodes)));
        setEdges(JSON.parse(JSON.stringify(nextEdges)));
        setWorkflowName(template.name);
        setWorkflowDescription(template.description ?? "");
        setSavedWorkflowId(null);
        setSelectedNode(null);
        setShowTemplatesModal(false);
        setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 70);
      } finally {
        setApplyingTemplateId(null);
      }
    },
    [setNodes, setEdges, fitView],
  );

  const createFromTemplate = useCallback(
    async (template: WorkflowTemplateItem) => {
      setCreatingTemplateId(template.id);
      setSaveStatus("saving");
      try {
        const doctorId = user?.doctor_id ?? user?.sub ?? "anonymous";
        const created = await createWorkflowFromTemplate(template.id, {
          doctor_id: doctorId,
          name: template.name,
          description: template.description,
          status: "DRAFT",
        });

        const nextNodes: Node[] = Array.isArray(created?.nodes)
          ? (created.nodes as Node[])
          : ((template.nodes as Node[]) ?? []);
        const nextEdges: Edge[] = Array.isArray(created?.edges)
          ? (created.edges as Edge[])
          : ((template.edges as Edge[]) ?? []);

        setNodes(JSON.parse(JSON.stringify(nextNodes)));
        setEdges(JSON.parse(JSON.stringify(nextEdges)));
        setWorkflowName(created?.name ?? template.name);
        setWorkflowDescription(
          created?.description ?? template.description ?? "",
        );
        setSavedWorkflowId(created?.id ?? null);
        setSelectedNode(null);
        setShowTemplatesModal(false);
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2500);
        setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 70);
      } catch {
        setSaveStatus("error");
        setTimeout(() => setSaveStatus("idle"), 2500);
      } finally {
        setCreatingTemplateId(null);
      }
    },
    [user, setNodes, setEdges, fitView],
  );

  const loadWorkflow = useCallback(
    (wf: WorkflowListEntry) => {
      const loadedNodes: Node[] = Array.isArray(wf.nodes)
        ? (wf.nodes as Node[])
        : [];
      const loadedEdges: Edge[] = Array.isArray(wf.edges)
        ? (wf.edges as Edge[])
        : [];
      setNodes(loadedNodes);
      setEdges(loadedEdges);
      setSavedWorkflowId(wf.id);
      setWorkflowName(wf.name ?? "");
      setWorkflowDescription(wf.description ?? "");
      setSelectedNode(null);
      setShowLoadModal(false);
      setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 50);
    },
    [setNodes, setEdges, fitView],
  );

  // ── Run Workflow ──────────────────────────────────────────────────────

  const openRunModal = useCallback(async () => {
    if (!savedWorkflowId) return;
    setShowRunModal(true);
    setRunStatus("idle");
    setRunResult(null);
    setSelectedPatientId(null);
    setPatientsFallbackUsed(false);
    setShowAddPatient(false);
    setNewPatientName("");
    setNewPatientPhone("");
    setLoadingPatients(true);
    try {
      const doctorId = user?.doctor_id ?? user?.sub ?? undefined;
      const scopedData = await listPatients(doctorId);
      const scopedPatients = Array.isArray(scopedData) ? scopedData : [];

      if (doctorId && scopedPatients.length === 0) {
        const allData = await listPatients();
        const allPatients = Array.isArray(allData) ? allData : [];
        setPatients(allPatients);
        setPatientsFallbackUsed(allPatients.length > 0);
      } else {
        setPatients(scopedPatients);
      }
    } catch {
      setPatients([]);
    } finally {
      setLoadingPatients(false);
    }
  }, [savedWorkflowId, user]);

  const handleAddPatient = useCallback(async () => {
    if (!newPatientName.trim() || !newPatientPhone.trim()) return;
    setAddingPatient(true);
    try {
      const doctorId = user?.doctor_id ?? user?.sub ?? "anonymous";
      const created = await createPatient({
        name: newPatientName.trim(),
        phone: newPatientPhone.trim(),
        doctor_id: doctorId,
      });
      setPatients((prev) => [created, ...prev]);
      setSelectedPatientId(created.id);
      setShowAddPatient(false);
      setNewPatientName("");
      setNewPatientPhone("");
    } catch {
      // ignore — patient still won't show
    } finally {
      setAddingPatient(false);
    }
  }, [newPatientName, newPatientPhone, user]);

  // ── Load reports when patient changes ────────────────────────────────
  useEffect(() => {
    if (!selectedPatientId) {
      setPatientReports([]);
      setSelectedReportId(null);
      return;
    }
    setLoadingReports(true);
    listPatientReports(selectedPatientId)
      .then((data) => setPatientReports(Array.isArray(data) ? data : []))
      .catch(() => setPatientReports([]))
      .finally(() => setLoadingReports(false));
  }, [selectedPatientId]);

  const handleRun = useCallback(async () => {
    if (!savedWorkflowId || !selectedPatientId) return;
    setRunStatus("running");
    setRunResult(null);
    setCallStatus(null);
    setCallLogId(null);
    try {
      const doctorId = user?.doctor_id ?? user?.sub ?? null;
      const result = await executeWorkflowWithContext(savedWorkflowId, {
        patient_id: selectedPatientId,
        report_id: selectedReportId || null,
        doctor_id: doctorId,
      });
      setRunResult(result);
      setCallLogId(result.call_log_id || null);
      setRunStatus(result.status === "failed" ? "error" : "success");
      if (result.call_log_id && result.status === "running") {
        setPollingActive(true);
      }
    } catch {
      setRunStatus("error");
      setRunResult({ execution_log: [], status: "failed", call_log_id: null });
    }
  }, [savedWorkflowId, selectedPatientId, selectedReportId, user]);

  // ── Poll call status ──────────────────────────────────────────────────
  useEffect(() => {
    if (!pollingActive || !callLogId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const status = await checkCallStatus(callLogId);
        if (!stopped) {
          setCallStatus(status);
          if (status.status === "completed") {
            setPollingActive(false);
            setRunStatus("success");
          }
        }
      } catch {
        /* ignore polling errors */
      }
    };
    const interval = setInterval(poll, 5000);
    poll();
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [pollingActive, callLogId]);

  // ── Helpers ───────────────────────────────────────────────────────────

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return iso;
    }
  };

  const stepColor = (s: string) => {
    if (s === "ok") return "#10b981";
    if (s === "error") return "#ef4444";
    return "#6b7280";
  };

  // ────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <header className="h-12 shrink-0 flex items-center justify-between px-4 border-b border-border bg-card">
        <div className="flex items-center gap-2">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 font-serif text-2xl tracking-tight text-foreground"
          >
            <Image
              src="/assets/Clarus.png"
              alt="Clarus"
              width={32}
              height={32}
            />
            CareSync AI
          </Link>
          <span className="text-muted-foreground text-sm">/</span>
          <span className="text-muted-foreground text-sm">
            {workflowName ? workflowName : "Workflow Builder"}
          </span>

          {/* Node / edge counters */}
          {(nodes.length > 0 || edges.length > 0) && (
            <div className="flex items-center gap-1.5 ml-2">
              <span className="text-[10px] bg-muted border border-border text-muted-foreground px-2 py-0.5 rounded-full">
                {nodes.length} nodes
              </span>
              <span className="text-[10px] bg-muted border border-border text-muted-foreground px-2 py-0.5 rounded-full">
                {edges.length} edges
              </span>
            </div>
          )}

          {/* Undo / Redo */}
          <div className="flex items-center gap-0.5 ml-1">
            <button
              onClick={undo}
              disabled={!canUndo}
              title="Undo (⌘Z)"
              className="p-1 rounded hover:bg-muted text-muted-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Undo2 className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={redo}
              disabled={!canRedo}
              title="Redo (⌘⇧Z)"
              className="p-1 rounded hover:bg-muted text-muted-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Redo2 className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Select / Pan mode toggle */}
          <div className="flex items-center gap-0.5 ml-1 border-l border-border pl-2">
            <button
              onClick={() => setSelectMode(true)}
              title="Select mode (V)"
              className={`p-1 rounded transition-colors ${selectMode ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted"}`}
            >
              <MousePointer2 className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setSelectMode(false)}
              title="Pan mode (H)"
              className={`p-1 rounded transition-colors ${!selectMode ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted"}`}
            >
              <Hand className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="xs" onClick={openTemplatesModal}>
            <LayoutTemplate className="size-3.5 mr-1" />
            Ready Workflows
          </Button>
          <Button variant="outline" size="xs" onClick={openLoadModal}>
            Load Workflow
          </Button>
          <Button variant="outline" size="xs" onClick={loadExample}>
            Load Example
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={clearCanvas}
            disabled={nodes.length === 0}
          >
            Clear
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={exportWorkflow}
            disabled={nodes.length === 0}
          >
            Export JSON
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={cleanLayout}
            disabled={nodes.length === 0}
          >
            Clean
          </Button>
          <Button
            size="xs"
            onClick={handleSaveClick}
            disabled={nodes.length === 0 || saveStatus === "saving"}
            className={
              saveStatus === "saved"
                ? "bg-emerald-600 hover:bg-emerald-600 text-white"
                : saveStatus === "error"
                  ? "bg-red-600 hover:bg-red-600 text-white"
                  : ""
            }
          >
            {saveStatus === "saving"
              ? "Saving…"
              : saveStatus === "saved"
                ? "✓ Saved"
                : saveStatus === "error"
                  ? "✕ Error"
                  : savedWorkflowId
                    ? "Update Workflow"
                    : "Save Workflow"}
          </Button>
          <Button
            size="xs"
            onClick={openRunModal}
            disabled={!savedWorkflowId}
            title={
              !savedWorkflowId ? "Save the workflow first" : "Run this workflow"
            }
            className="bg-emerald-600 hover:bg-emerald-500 text-white"
          >
            ▶&nbsp;Run
          </Button>
        </div>
      </header>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <CmdHoverContext.Provider value={{ cmdHeld, setHandle }}>
        <div ref={workspaceBodyRef} className="flex flex-1 overflow-hidden">
          {/* Left: Node palette */}
          <NodePalette />

          {/* Centre: React Flow canvas */}
          <div
            className="flex-1 relative"
            onDrop={onDrop}
            onDragOver={onDragOver}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onPaneClick={onPaneClick}
              onNodeMouseEnter={onNodeMouseEnter}
              nodeTypes={nodeTypes}
              defaultEdgeOptions={defaultEdgeOptions}
              fitView
              selectionOnDrag={selectMode}
              panOnDrag={selectMode ? [1, 2] : true}
              selectionMode={SelectionMode.Partial}
              proOptions={{ hideAttribution: true }}
              deleteKeyCode="Delete"
            >
              <Background
                variant={BackgroundVariant.Dots}
                color="#EDE6E8"
                gap={20}
                size={1.5}
              />
              <Controls />
              <MiniMap
                nodeColor={(node) => {
                  switch (node.type) {
                    case "trigger":
                      return "#3b82f6";
                    case "action":
                      return "#8b5cf6";
                    case "conditional":
                      return "#f59e0b";
                    case "endpoint":
                      return "#10b981";
                    default:
                      return "#6b7280";
                  }
                }}
                maskColor="rgba(250,250,248,0.7)"
              />
            </ReactFlow>

            {/* Empty-state hint */}
            {nodes.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-center space-y-2">
                  <p className="text-muted-foreground text-sm">
                    Drag nodes from the palette, or
                  </p>
                  <p className="text-muted-foreground text-xs">
                    click{" "}
                    <span className="text-foreground bg-muted px-1.5 py-0.5 rounded font-mono">
                      Ready Workflows
                    </span>{" "}
                    to load a prebuilt template, or{" "}
                    click{" "}
                    <span className="text-foreground bg-muted px-1.5 py-0.5 rounded font-mono">
                      Load Workflow
                    </span>{" "}
                    to reload a saved workflow, or click{" "}
                    <span className="text-foreground bg-muted px-1.5 py-0.5 rounded font-mono">
                      Load Example
                    </span>{" "}
                    to see a pre-built one
                  </p>
                </div>
              </div>
            )}
          </div>

          <div
            className={`w-1.5 shrink-0 cursor-col-resize transition-colors ${
              activeResize === "column"
                ? "bg-primary/60"
                : "bg-border/70 hover:bg-primary/40"
            }`}
            onMouseDown={startColumnResize}
            title="Resize panel"
          />

          {/* Right: Stacked side panels */}
          <aside
            ref={rightPanelRef}
            style={{ width: rightPanelWidth }}
            className="shrink-0 bg-card flex flex-col"
          >
            <div className="min-h-0 flex-1">
              <PropertiesPanel
                selectedNode={selectedNode}
                onUpdateParams={updateNodeParams}
                onDeleteNode={deleteNode}
                mode="embedded"
                className="border-b border-border"
              />
            </div>

            <div
              className={`h-1.5 shrink-0 cursor-row-resize transition-colors ${
                activeResize === "split"
                  ? "bg-primary/60"
                  : "bg-border/70 hover:bg-primary/40"
              }`}
              onMouseDown={startSplitResize}
              title="Resize split"
            />

            <section style={{ height: agentPanelHeight }} className="min-h-[220px] flex flex-col">
              <div className="px-4 py-3 border-b border-border">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-1.5">
                  <Sparkles className="size-3 text-amber-500" />
                  Agent Builder
                </p>
              </div>

              <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Describe trigger, conditions, actions, and outputs. The agent
                  will generate a workflow graph and save it.
                </p>

                <div className="relative">
                  <textarea
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                    placeholder="Example: When lab results are received, check if HbA1c is greater than 8.0. If abnormal, call patient and schedule follow-up, then send summary to doctor. If normal, send SMS and log completion."
                    rows={5}
                    className="w-full px-3 py-2 pr-12 pb-10 rounded-lg bg-muted border border-input text-foreground text-xs placeholder-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-y"
                  />

                  <button
                    type="button"
                    onClick={() => {
                      void toggleSpeechCapture();
                    }}
                    disabled={isSpeechTranscribing}
                    aria-label={isSpeechRecording ? "Stop microphone" : "Start microphone"}
                    aria-pressed={isSpeechRecording}
                    className={`absolute right-2 bottom-2 h-7 w-7 rounded-full border flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                      isSpeechRecording
                        ? "bg-red-600 border-red-600 text-white"
                        : "bg-background border-border text-muted-foreground hover:text-foreground"
                    }`}
                    title={
                      isSpeechRecording ? "Stop recording" : "Start recording"
                    }
                  >
                    <Mic
                      className={`size-4 ${isSpeechRecording ? "fill-current" : ""}`}
                    />
                  </button>
                </div>

                {isSpeechRecording && (
                  <p className="text-[11px] text-red-600">
                    Listening... click the mic again to stop.
                  </p>
                )}

                {isSpeechTranscribing && (
                  <p className="text-[11px] text-muted-foreground">
                    Transcribing with Deepgram...
                  </p>
                )}

                {speechError && <p className="text-xs text-destructive">{speechError}</p>}

                {aiError && <p className="text-xs text-destructive">{aiError}</p>}

                {aiWarnings.length > 0 && (
                  <div className="rounded-lg border border-amber-300/60 bg-amber-50/70 px-3 py-2">
                    <p className="text-[11px] font-medium text-amber-800 mb-1">
                      Validation notes
                    </p>
                    <div className="space-y-1">
                      {aiWarnings.map((warning, idx) => (
                        <p
                          key={`${warning}-${idx}`}
                          className="text-[11px] text-amber-700"
                        >
                          • {warning}
                        </p>
                      ))}
                    </div>
                  </div>
                )}

                {aiNotes.length > 0 && (
                  <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                    <p className="text-[11px] font-medium text-foreground mb-1">
                      AI reasoning highlights
                    </p>
                    <div className="space-y-1">
                      {aiNotes.map((note, idx) => (
                        <p
                          key={`${note}-${idx}`}
                          className="text-[11px] text-muted-foreground"
                        >
                          • {note}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="px-4 py-3 border-t border-border flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={aiGenerating}
                  onClick={() => {
                    setAiPrompt("");
                    setAiError(null);
                    setAiWarnings([]);
                    setAiNotes([]);
                    setSpeechError(null);
                  }}
                >
                  Clear
                </Button>
                <Button
                  size="sm"
                  disabled={aiGenerating || aiPrompt.trim().length < 10}
                  onClick={handleGenerateWorkflowWithAi}
                  className="bg-amber-600 hover:bg-amber-500 text-white"
                >
                  {aiGenerating ? "Generating…" : "Generate"}
                </Button>
              </div>
            </section>
          </aside>
        </div>
      </CmdHoverContext.Provider>

      {/* ── Save workflow name modal ───────────────────────────────────── */}
      {showNameModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-lg font-semibold text-foreground mb-4">
              Save Workflow
            </h2>
            <label className="block text-sm text-muted-foreground mb-1">
              Name *
            </label>
            <input
              autoFocus
              type="text"
              value={workflowName}
              onChange={(e) => setWorkflowName(e.target.value)}
              placeholder="e.g. Lab Results Follow-Up"
              className="w-full px-3 py-2 rounded-lg bg-muted border border-input text-foreground text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring mb-3"
            />
            <label className="block text-sm text-muted-foreground mb-1">
              Description
            </label>
            <textarea
              value={workflowDescription}
              onChange={(e) => setWorkflowDescription(e.target.value)}
              placeholder="Optional description…"
              rows={2}
              className="w-full px-3 py-2 rounded-lg bg-muted border border-input text-foreground text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring mb-4 resize-none"
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowNameModal(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={!workflowName.trim()}
                onClick={() =>
                  doSave(workflowName.trim(), workflowDescription.trim())
                }
              >
                Save
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Load Workflow modal ────────────────────────────────────────── */}
      {showLoadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-card border border-border rounded-xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-foreground">
                Load Workflow
              </h2>
              <button
                onClick={() => setShowLoadModal(false)}
                className="text-muted-foreground hover:text-foreground text-xl leading-none"
              >
                ×
              </button>
            </div>

            {loadingWorkflows ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                Loading workflows…
              </p>
            ) : loadWorkflowError ? (
              <p className="text-sm text-destructive text-center py-8">
                {loadWorkflowError}
              </p>
            ) : availableWorkflows.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No saved workflows found.
              </p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {availableWorkflows.map((wf) => (
                  <button
                    key={wf.id}
                    onClick={() => loadWorkflow(wf)}
                    className="w-full text-left rounded-lg border border-border bg-background hover:bg-muted hover:border-primary/50 px-4 py-3 transition-colors group"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-foreground group-hover:text-primary truncate">
                          {wf.name}
                        </p>
                        {wf.description && (
                          <p className="text-xs text-muted-foreground mt-0.5 truncate">
                            {wf.description}
                          </p>
                        )}
                        <div className="flex items-center gap-3 mt-1.5">
                          <span className="text-[10px] text-muted-foreground">
                            {Array.isArray(wf.nodes) ? wf.nodes.length : 0}{" "}
                            nodes
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {Array.isArray(wf.edges) ? wf.edges.length : 0}{" "}
                            edges
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {formatDate(wf.created_at)}
                          </span>
                        </div>
                      </div>
                      <span
                        className={`flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full font-medium ${
                          wf.status === "ENABLED"
                            ? "bg-success/10 text-success"
                            : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {wf.status}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Ready workflow templates modal ─────────────────────────────── */}
      {showTemplatesModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-card border border-border rounded-xl p-6 w-full max-w-3xl shadow-2xl">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold text-foreground">
                Ready Workflows
              </h2>
              <button
                onClick={() => setShowTemplatesModal(false)}
                className="text-muted-foreground hover:text-foreground text-xl leading-none"
              >
                ×
              </button>
            </div>

            <p className="text-xs text-muted-foreground mb-4">
              Top 5 most-used automation flows. Load one instantly, or create
              and save it in one click.
            </p>

            {loadingTemplates ? (
              <p className="text-sm text-muted-foreground text-center py-10">
                Loading templates…
              </p>
            ) : templateError ? (
              <p className="text-sm text-destructive text-center py-10">
                {templateError}
              </p>
            ) : workflowTemplates.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-10">
                No templates are currently available.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
                {workflowTemplates.map((template) => (
                  <div
                    key={template.id}
                    className="rounded-xl border border-border bg-background p-4"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-foreground">
                          {template.name}
                        </p>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {template.description}
                        </p>
                      </div>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                        {template.category}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 mt-3 text-[10px] text-muted-foreground">
                      <span>{template.use_case}</span>
                      <span>
                        {Array.isArray(template.nodes) ? template.nodes.length : 0} nodes
                      </span>
                      <span>
                        {Array.isArray(template.edges) ? template.edges.length : 0} edges
                      </span>
                    </div>

                    <div className="flex items-center gap-2 mt-4">
                      <Button
                        variant="outline"
                        size="xs"
                        disabled={
                          applyingTemplateId === template.id ||
                          creatingTemplateId === template.id
                        }
                        onClick={() => {
                          void applyTemplateToCanvas(template);
                        }}
                      >
                        {applyingTemplateId === template.id
                          ? "Loading…"
                          : "Load to Canvas"}
                      </Button>
                      <Button
                        size="xs"
                        disabled={
                          applyingTemplateId === template.id ||
                          creatingTemplateId === template.id
                        }
                        onClick={() => {
                          void createFromTemplate(template);
                        }}
                      >
                        {creatingTemplateId === template.id
                          ? "Creating…"
                          : "Create & Save"}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Run Workflow modal ─────────────────────────────────────────── */}
      {showRunModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-card border border-border rounded-xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-lg font-semibold text-foreground">
                Run Workflow
              </h2>
              <button
                onClick={() => {
                  setShowRunModal(false);
                  setRunResult(null);
                  setRunStatus("idle");
                  setCallStatus(null);
                  setCallLogId(null);
                  setPollingActive(false);
                  setSelectedReportId(null);
                  setPatientReports([]);
                }}
                className="text-muted-foreground hover:text-foreground text-xl leading-none"
              >
                ×
              </button>
            </div>
            <p className="text-xs text-muted-foreground mb-4">
              Workflow:{" "}
              <span className="text-primary font-medium">{workflowName}</span>
            </p>

            {/* Patient picker */}
            {runStatus === "idle" && (
              <>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm text-muted-foreground font-medium">
                    Select Patient
                  </label>
                  <button
                    onClick={() => setShowAddPatient((v) => !v)}
                    className="text-xs text-primary hover:text-primary/80 transition-colors"
                  >
                    {showAddPatient ? "− Cancel" : "+ Add Patient"}
                  </button>
                </div>

                {showAddPatient && (
                  <div className="mb-3 rounded-lg border border-border bg-muted p-3 space-y-2">
                    <input
                      type="text"
                      value={newPatientName}
                      onChange={(e) => setNewPatientName(e.target.value)}
                      placeholder="Full Name"
                      className="w-full px-3 py-1.5 rounded-lg bg-background border border-input text-foreground text-xs placeholder-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <input
                      type="tel"
                      value={newPatientPhone}
                      onChange={(e) => setNewPatientPhone(e.target.value)}
                      placeholder="Phone (e.g. +1 555 000 0000)"
                      className="w-full px-3 py-1.5 rounded-lg bg-background border border-input text-foreground text-xs placeholder-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <Button
                      size="xs"
                      onClick={handleAddPatient}
                      disabled={
                        addingPatient ||
                        !newPatientName.trim() ||
                        !newPatientPhone.trim()
                      }
                    >
                      {addingPatient ? "Saving…" : "Create Patient"}
                    </Button>
                  </div>
                )}

                {loadingPatients ? (
                  <p className="text-xs text-muted-foreground mb-4">
                    Loading patients…
                  </p>
                ) : patients.length === 0 && !showAddPatient ? (
                  <p className="text-xs text-muted-foreground mb-4">
                    No patients yet — add one above.
                  </p>
                ) : (
                  <>
                    {patientsFallbackUsed && (
                      <p className="text-[11px] text-amber-600 mb-2">
                        No patients were found for your doctor ID, so showing
                        all patients.
                      </p>
                    )}
                    <div className="space-y-1.5 max-h-48 overflow-y-auto mb-4 pr-1">
                      {patients.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => setSelectedPatientId(p.id)}
                          className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                            selectedPatientId === p.id
                              ? "border-primary bg-primary/10 text-foreground"
                              : "border-border bg-background text-foreground hover:border-border hover:bg-muted"
                          }`}
                        >
                          <span className="font-medium">{p.name}</span>
                          <span className="text-xs text-muted-foreground ml-2">
                            {p.phone}
                          </span>
                        </button>
                      ))}
                    </div>
                  </>
                )}

                {/* Report selection */}
                {selectedPatientId && (
                  <div className="mb-4">
                    <label className="text-sm text-muted-foreground font-medium block mb-2">
                      Link Report (optional)
                    </label>
                    {loadingReports ? (
                      <p className="text-xs text-muted-foreground">
                        Loading reports…
                      </p>
                    ) : patientReports.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        No reports available for this patient.
                      </p>
                    ) : (
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        <button
                          onClick={() => setSelectedReportId(null)}
                          className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition-colors ${
                            !selectedReportId
                              ? "border-primary bg-primary/10"
                              : "border-border bg-background hover:bg-muted"
                          }`}
                        >
                          No report link
                        </button>
                        {patientReports.map((r) => {
                          const rd = r.report_data || {};
                          const title =
                            (rd.title as string | undefined) ||
                            (rd.report_type as string | undefined) ||
                            `Report ${r.id.slice(0, 8)}`;
                          const date =
                            (rd.report_date as string | undefined) ||
                            r.created_at?.slice(0, 10);
                          return (
                            <button
                              key={r.id}
                              onClick={() => setSelectedReportId(r.id)}
                              className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition-colors ${
                                selectedReportId === r.id
                                  ? "border-primary bg-primary/10"
                                  : "border-border bg-background hover:bg-muted"
                              }`}
                            >
                              <span className="font-medium">{title}</span>
                              {date && (
                                <span className="text-muted-foreground ml-2">
                                  {date}
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setShowRunModal(false);
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    disabled={!selectedPatientId}
                    onClick={handleRun}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white"
                  >
                    ▶ Execute
                  </Button>
                </div>
              </>
            )}

            {/* Running state */}
            {runStatus === "running" && (
              <div className="flex flex-col items-center justify-center py-10 gap-3">
                <svg
                  className="animate-spin size-8 text-emerald-500"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
                <p className="text-sm text-muted-foreground">
                  Executing workflow…
                </p>
              </div>
            )}

            {/* Result state */}
            {(runStatus === "success" || runStatus === "error") &&
              runResult && (
                <>
                  <div
                    className={`flex items-center gap-2 mb-4 rounded-lg px-3 py-2 ${
                      runStatus === "success"
                        ? "bg-success/10 border border-success/30"
                        : "bg-destructive/10 border border-destructive/30"
                    }`}
                  >
                    <span className="text-sm font-semibold">
                      {runStatus === "success" ? "✓ Completed" : "✕ Failed"}
                    </span>
                    {runResult.call_log_id && (
                      <span className="text-[10px] text-muted-foreground ml-auto">
                        Log&nbsp;ID:&nbsp;{runResult.call_log_id.slice(0, 8)}…
                      </span>
                    )}
                  </div>

                  {/* Context summary banner */}
                  {runResult?.context_summary && (
                    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs mb-3">
                      {runResult.context_summary.report_title && (
                        <div className="flex items-center gap-2">
                          <FileText className="size-3 text-muted-foreground" />
                          <span className="text-muted-foreground">Report:</span>
                          <span className="font-medium">
                            {runResult.context_summary.report_title}
                          </span>
                          {runResult.context_summary.report_date && (
                            <span className="text-muted-foreground">
                              ({runResult.context_summary.report_date})
                            </span>
                          )}
                        </div>
                      )}
                      {runResult.context_summary.doctor_name && (
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-muted-foreground">Doctor:</span>
                          <span className="font-medium">
                            {runResult.context_summary.doctor_name}
                          </span>
                          {runResult.context_summary.doctor_specialty && (
                            <span className="text-muted-foreground">
                              ({runResult.context_summary.doctor_specialty})
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1 mb-4">
                    {(runResult.execution_log ?? []).map((rawStep, i: number) => {
                      const step = (rawStep as ExecutionStep) ?? {};
                      return (
                        <div
                          key={i}
                          className="rounded-lg bg-muted border border-border px-3 py-2"
                        >
                          <div className="flex items-center gap-2">
                            <span
                              className="size-2 rounded-full flex-shrink-0"
                              style={{
                                backgroundColor: stepColor(step.status),
                              }}
                            />
                            <span className="text-xs font-medium text-foreground">
                              {step.label || step.node_type}
                            </span>
                            <span className="ml-auto text-[10px] text-muted-foreground capitalize">
                              {step.status}
                            </span>
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-0.5 pl-4">
                            {step.message}
                          </p>
                        </div>
                      );
                    })}
                  </div>

                  {/* Live call status / polling */}
                  {callLogId && runStatus === "success" && (
                    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs mb-3">
                      <div className="flex items-center gap-2 mb-1">
                        <Phone className="size-3 text-primary" />
                        <span className="font-medium">Call Status</span>
                        {pollingActive && (
                          <span className="text-[10px] text-muted-foreground animate-pulse">
                            polling…
                          </span>
                        )}
                      </div>
                      {callStatus ? (
                        <div>
                          <div className="flex gap-2">
                            <span className="text-muted-foreground">
                              Outcome:
                            </span>
                            <span className="capitalize">
                              {callStatus.call_outcome || callStatus.status}
                            </span>
                          </div>
                          {callStatus.patient_confirmed !== undefined && (
                            <div className="flex gap-2">
                              <span className="text-muted-foreground">
                                Confirmed:
                              </span>
                              <span>
                                {callStatus.patient_confirmed
                                  ? "✓ Yes"
                                  : "✗ No"}
                              </span>
                            </div>
                          )}
                          {callStatus.confirmed_date && (
                            <div className="flex gap-2">
                              <span className="text-muted-foreground">
                                Slot:
                              </span>
                              <span>
                                {callStatus.confirmed_date}{" "}
                                {callStatus.confirmed_time}
                              </span>
                            </div>
                          )}
                          {callStatus.appointment_id && (
                            <div className="flex gap-2 mt-1">
                              <span className="text-success font-medium">
                                ✓ Appointment booked!
                              </span>
                              <code className="text-[10px] text-muted-foreground">
                                {callStatus.appointment_id.slice(0, 8)}…
                              </code>
                            </div>
                          )}
                          {callStatus.transcript && (
                            <details className="mt-2">
                              <summary className="cursor-pointer text-muted-foreground text-[10px]">
                                View transcript
                              </summary>
                              <pre className="mt-1 text-[10px] whitespace-pre-wrap bg-background rounded p-2 max-h-32 overflow-y-auto">
                                {callStatus.transcript}
                              </pre>
                            </details>
                          )}
                        </div>
                      ) : (
                        <p className="text-muted-foreground">
                          Waiting for call result…
                        </p>
                      )}
                    </div>
                  )}

                  <div className="flex justify-end gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setRunStatus("idle");
                        setRunResult(null);
                        setSelectedPatientId(null);
                        setCallStatus(null);
                        setCallLogId(null);
                        setPollingActive(false);
                        setSelectedReportId(null);
                        setPatientReports([]);
                      }}
                    >
                      Run Again
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => {
                        setShowRunModal(false);
                        setRunResult(null);
                        setRunStatus("idle");
                        setCallStatus(null);
                        setCallLogId(null);
                        setPollingActive(false);
                        setSelectedReportId(null);
                        setPatientReports([]);
                      }}
                    >
                      Close
                    </Button>
                  </div>
                </>
              )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Public export — wraps inner component in provider ──────────────────────

export default function WorkflowBuilder() {
  return (
    <ReactFlowProvider>
      <FlowContent />
    </ReactFlowProvider>
  );
}
