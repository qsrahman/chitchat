// Types for the JavaScript modules, checked by `tsc` (jsconfig.json; run by scripts/check.py). Nothing in the page loads
// this file. The shapes are what the server sends, so a change to a response in app/routes.py or an event in
// app/llm.py is changed here too, and the compiler then points at every module that reads it.

// The vendored libraries are classic scripts that define globals; they are not typed.
declare const marked: any
declare const hljs: any
declare const katex: any
declare const DOMPurify: any

interface ConversationSettings {
  model: string | null
  system_prompt: string
  reasoning_effort: string | null
  temperature: number | null
  tools: string[]
}

interface Conversation {
  id: string
  title: string
  settings: ConversationSettings
  pinned: number
  archived: number
  created_at: string
  updated_at: string
}

interface Attachment {
  id: string
  name: string
  kind: 'image' | 'file' | 'text'
}

interface ToolCall {
  id: string
  name: string
  status: string
  [field: string]: unknown
}

// Token counts of a reply (all the rounds of its tool calls added up); output includes the reasoning tokens.
interface Usage {
  input_tokens: number
  output_tokens: number
  reasoning_tokens: number
}

// What the server keeps in a message's `meta`.
interface MessageMeta {
  attachments?: Attachment[]
  tools?: ToolCall[]
  reasoning?: string
  model?: string
  usage?: Usage
  incomplete?: string
  stopped?: boolean
  compaction?: boolean
  trimmed?: number
}

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  meta: MessageMeta
  siblings: number[] // the ids of its versions, oldest first, itself included
}

interface ConversationWithMessages extends Conversation {
  messages: Message[]
}

interface Versions {
  id: number
  siblings: number[]
}

// The events of a turn (POST .../chat, /edit, /regenerate), as app/llm.py normalizes them and routes.py extends "done".
type StreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'reasoning_delta'; text: string }
  | ({ type: 'tool_call' } & ToolCall)
  | { type: 'compaction' }
  | { type: 'context_trimmed'; count: number }
  | { type: 'title'; title: string }
  | { type: 'error'; message: string }
  | {
      type: 'done'
      model: string
      usage?: Usage
      incomplete?: string
      branch?: { user: Versions; assistant: Versions }
    }

interface ModelInfo {
  default: string | null // the model a chat uses when it picks none: the one chosen in Settings, else the server's
  server_default?: string
  efforts?: string[]
  models: { id: string; reasoning: boolean }[]
}

// GET/PUT /api/defaults: chosen in Settings, for chats that don't pick their own (the tools: for new chats).
interface Defaults {
  model: string | null
  reasoning_effort: string | null
  tools: string[]
}

interface ToolInfo {
  name: string
  label: string
  hint: string
}

// A message element: the DOM node plus the raw texts and ids the modules keep on it (messages.js builds it).
interface MessageEl extends HTMLDivElement {
  _text?: string
  _reasoning?: string | null
  _model?: string
  _usage?: Usage
  _siblings?: number[]
  _attachments?: Attachment[]
  _frame?: number | null
  _timer?: ReturnType<typeof setTimeout> | null
  _resumeAt?: number
}

// GET /api/storage: what is kept, for Settings, Data controls.
interface StorageOverview {
  database_bytes: number
  attachment_files: number
  attachment_bytes: number
  unused_files: number
  unused_bytes: number
  chats: number
  archived_chats: number
}

// GET /api/config: what the server is set up with (Settings, Server tab).
interface ServerConfig {
  endpoint: string
  custom_endpoint: boolean
  model: string
  chosen_model: string | null
  title_model: string
  web_search: boolean
  tools: string[]
  compaction: boolean
  compact_threshold: number
  history_tokens: number
  max_tool_calls: number
  max_output_tokens: number | null
  pdf_input: string
  reasoning_summaries: boolean
  log_level: string
  database: string
  attachments: string
  default_instructions: string
}
