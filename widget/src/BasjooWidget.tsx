/**
 * Basjoo AI Chat Widget
 * 可嵌入的智能聊天组件
 */

import {
  DEFAULT_LOCALE,
  SUPPORTED_LOCALES,
  WIDGET_LOCALE_STORAGE_KEY,
  WidgetLocale,
  isWidgetLocale,
  t,
} from './locales';

interface WidgetConfig {
  agentId: string;
  apiBase?: string;
  themeColor?: string;
  logoUrl?: string;
  title?: string;
  welcomeMessage?: string;
  language?: 'auto' | string;
  position?: 'left' | 'right';
  theme?: 'light' | 'dark' | 'auto';
}

interface PublicWidgetConfig {
  widget_title?: string | null;
  welcome_message?: string | null;
  widget_color?: string | null;
  default_agent_id?: string | null;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  timestamp: Date;
  // PR14: attachments surfaced in the user message bubble. Server returns
  // the canonical post-process values via SSE `done.attachments`; the widget
  // also patches `preview_url` for local blob: previews before upload completes.
  attachments?: Attachment[];
}

interface Source {
  type: 'url' | 'qa';
  title?: string;
  url?: string;
  snippet?: string;
  question?: string;
  id?: string;
}

type AttachmentKind = 'image' | 'audio';

interface Attachment {
  id: string;                       // '' for pre-upload local-only
  kind: AttachmentKind;
  mime_type: string;
  filename: string;
  size_bytes: number;
  url: string;                      // '' pre-upload; server URL after
  status: 'pending' | 'uploaded';
  preview_url: string;              // blob: URL (image only)
  duration_ms?: number;              // audio only
}

interface StreamDoneMeta {
  message_id?: number | null;
  session_id?: string;
  taken_over?: boolean;
  // PR14: server-side echo of resolved attachment metadata.
  attachments?: Attachment[];
}

interface StreamErrorPayload {
  error?: string;
  code?: string;
}

interface StreamEventPayload {
  sources?: Source[];
  content?: string;
  elapsed?: number;
}

interface PendingAttachment {
  clientId: string;                 // local-only UUID for DOM keying
  kind: AttachmentKind;
  mimeType: string;
  filename: string;
  size: number;
  file?: File;                      // image
  chunks?: Blob[];                  // audio
  previewUrl: string;               // blob: URL (image only)
  status: 'pending' | 'uploading' | 'uploaded' | 'error';
  attachmentId: string;             // '' until upload returns
  serverUrl: string;                // '' until upload returns
  errorMessage: string;
  durationMs?: number;              // audio only
}

interface ChatHistoryMessage {
  id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources?: Source[];
  // PR14: backend /api/v1/chat/messages response shape (PR13 already returns this).
  attachments?: Array<{
    id: string;
    kind: AttachmentKind;
    mime_type: string;
    filename: string;
    size_bytes: number;
    url: string;
    status: string;
    transcript: string | null;
    description: string | null;
    duration_ms: number | null;
    error_message: string | null;
    created_at: string;
  }>;
}

function formatAssistantMessage(content: string, sources: Source[] = []): { content: string; references: Array<{ title: string; url: string }> } {
  if (!content) {
    return { content, references: [] };
  }

  const references: Array<{ title: string; url: string }> = [];
  const seenUrls = new Set<string>();
  const sourceByUrl = new Map<string, Source & { type: 'url'; url: string }>();

  for (const source of sources) {
    if (source.type !== 'url' || typeof source.url !== 'string' || !/^https?:\/\//.test(source.url) || sourceByUrl.has(source.url)) {
      continue;
    }
    sourceByUrl.set(source.url, source as Source & { type: 'url'; url: string });
  }

  const addReference = (url: string) => {
    if (seenUrls.has(url)) {
      return;
    }
    seenUrls.add(url);
    const source = sourceByUrl.get(url);
    references.push({
      title: source?.title?.trim() || url,
      url,
    });
  };

  const formattedContent = content.replace(
    /\[([^\]]+)\]\((#source-(\d+)|https?:\/\/[^\s)]+)\)/g,
    (_match, label: string, target: string, sourceIndexText?: string) => {
      if (sourceIndexText) {
        const sourceIndex = Number(sourceIndexText) - 1;
        const source = sources[sourceIndex];
        if (source && source.type === 'url' && source.url && /^https?:\/\//.test(source.url)) {
          addReference(source.url);
        }
        return label;
      }

      if (sourceByUrl.has(target)) {
        addReference(target);
        return label;
      }

      return _match;
    },
  );

  return {
    content: formattedContent,
    references,
  };
}

const AUTO_INIT_SCRIPT_PARAM_MAP = {
  agentId: ['agentId', 'agent_id'],
  apiBase: ['apiBase', 'api_base'],
  themeColor: ['themeColor', 'theme_color'],
  welcomeMessage: ['welcomeMessage', 'welcome_message'],
  language: ['language', 'locale'],
  position: ['position'],
  theme: ['theme'],
  // PR12: explicit widget-locale preset on the script tag, written straight to
  // localStorage by the bootstrap so the first paint shows the right option.
  widgetLocale: ['widget_locale', 'widgetLocale'],
} as const

function buildDefaultLogoUrl(apiBase: string): string {
  if (!apiBase) {
    return '/basjoo-logo.png'
  }

  try {
    return new URL('/basjoo-logo.png', `${apiBase}/`).toString()
  } catch {
    return '/basjoo-logo.png'
  }
}

// Storage adapter that safely wraps localStorage with try/catch and memory fallback
class StorageAdapter {
  private memoryStore = new Map<string, string>();
  private storageAvailable: boolean | null = null;

  private isAvailable(): boolean {
    if (this.storageAvailable !== null) {
      return this.storageAvailable;
    }
    try {
      const testKey = '__storage_test__';
      window.localStorage.setItem(testKey, 'test');
      window.localStorage.removeItem(testKey);
      this.storageAvailable = true;
      return true;
    } catch {
      this.storageAvailable = false;
      return false;
    }
  }

  getItem(key: string): string | null {
    if (this.isAvailable()) {
      try {
        return window.localStorage.getItem(key);
      } catch {
        // Fall through to memory store
      }
    }
    return this.memoryStore.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (this.isAvailable()) {
      try {
        window.localStorage.setItem(key, value);
        return;
      } catch {
        // Fall through to memory store
      }
    }
    this.memoryStore.set(key, value);
  }

  removeItem(key: string): void {
    if (this.isAvailable()) {
      try {
        window.localStorage.removeItem(key);
        return;
      } catch {
        // Fall through to memory store
      }
    }
    this.memoryStore.delete(key);
  }
}

class BasjooWidget {
  private config: Required<WidgetConfig>;
  private readonly hasTitleOverride: boolean;
  private readonly hasWelcomeMessageOverride: boolean;
  private container: HTMLElement | null = null;
  private button: HTMLElement | null = null;
  private unreadBadge: HTMLSpanElement | null = null;
  private chatWindow: HTMLElement | null = null;
  private messages: ChatMessage[] = [];
  private sessionId: string | null = null;
  private isOpen = false;
  private readonly STORAGE_KEY: string;
  private readonly VISITOR_STORAGE_KEY = 'basjoo_visitor_id';
  private visitorId: string;
  private storage: StorageAdapter;
  private effectiveTheme: 'light' | 'dark' = 'light';
  private originalTitle: string = '';
  private titleBlinkInterval: number | null = null;
  private hasUnread = false;
  private pollIntervalId: number | null = null;
  private lastMessageId: number = 0;
  private isSending = false;
  private streamAbortController: AbortController | null = null;
  private streamingMessage: HTMLDivElement | null = null;
  private streamingMessageContent: HTMLDivElement | null = null;
  private thinkingIndicator: HTMLDivElement | null = null;
  private thinkingIndicatorText: HTMLSpanElement | null = null;
  private thinkingElapsed = 0;
  private thinkingTimerId: number | null = null;
  private currentStreamContent = '';
  private currentStreamSources: Source[] = [];
  // Track imperative event listeners for cleanup
  private _buttonClickListener: (() => void) | null = null;
  private _closeBtnClickListener: (() => void) | null = null;
  private _sendBtnClickListener: (() => void) | null = null;
  private _inputKeypressListener: ((e: KeyboardEvent) => void) | null = null;
  // PR12: visitor's chosen widget language (independent from admin's basjoo_locale).
  private widgetLocale: WidgetLocale = DEFAULT_LOCALE;
  private _localeChangeListener: (() => void) | null = null;

  // PR14: visitor-side attachment state (two-phase upload → SSE stream).
  private pendingAttachments: PendingAttachment[] = [];
  private attachmentsStripEl: HTMLDivElement | null = null;
  private attachBtnEl: HTMLButtonElement | null = null;
  private micBtnEl: HTMLButtonElement | null = null;
  private fileInputEl: HTMLInputElement | null = null;
  private _attachBtnClickListener: (() => void) | null = null;
  private _micBtnPressListener: ((e: PointerEvent) => void) | null = null;
  private _micBtnReleaseListener: ((e: PointerEvent) => void) | null = null;
  private _fileInputChangeListener: ((e: Event) => void) | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private recordingStartedAt: number = 0;
  private recordingMaxTimerId: number | null = null;
  private recordingState: 'idle' | 'recording' = 'idle';

  constructor(config: WidgetConfig) {
    const apiBase = this.detectApiBase(config.apiBase);
    this.hasTitleOverride = typeof config.title === 'string' && config.title.trim().length > 0;
    this.hasWelcomeMessageOverride = typeof config.welcomeMessage === 'string' && config.welcomeMessage.trim().length > 0;

    this.config = {
      agentId: config.agentId,
      apiBase,
      themeColor: config.themeColor || '',
      logoUrl: config.logoUrl || buildDefaultLogoUrl(apiBase),
      title: config.title || 'AI助手',
      welcomeMessage: config.welcomeMessage || '你好！有什么可以帮助您的吗？',
      language: config.language || 'auto',
      position: config.position || 'right',
      theme: config.theme || 'auto',
    };

    this.STORAGE_KEY = `basjoo_session_${this.config.agentId}`;
    this.storage = new StorageAdapter();
    this.sessionId = this.storage.getItem(this.STORAGE_KEY);
    this.visitorId = this.storage.getItem(this.VISITOR_STORAGE_KEY) || this.generateVisitorId();

    this.effectiveTheme = this.getEffectiveTheme();

    // PR12: restore the visitor's language choice from localStorage. StorageAdapter
    // falls back to in-memory storage on localStorage denial (cross-origin /
    // sandboxed embeds), so this works even when localStorage is blocked.
    const storedWidgetLocale = this.storage.getItem(WIDGET_LOCALE_STORAGE_KEY);
    this.widgetLocale = isWidgetLocale(storedWidgetLocale)
      ? storedWidgetLocale
      : DEFAULT_LOCALE;
  }

  private generateVisitorId(): string {
    const visitorId = `visitor_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 11)}`;
    this.storage.setItem(this.VISITOR_STORAGE_KEY, visitorId);
    return visitorId;
  }

  private detectApiBase(configuredApiBase?: string): string {
    if (configuredApiBase) {
      try {
        const url = new URL(configuredApiBase, window.location.href)
        if ((url.protocol === 'http:' || url.protocol === 'https:') && url.port === '3000') {
          const directBase = `${url.protocol}//${url.hostname}:8000`
          console.info('[Basjoo Widget] Rewriting configured dev apiBase to direct backend:', directBase)
          return directBase
        }
        return url.toString().replace(/\/$/, '')
      } catch {
        return configuredApiBase;
      }
    }

    const currentScript = document.currentScript;
    if (currentScript instanceof HTMLScriptElement && currentScript.src) {
      try {
        const scriptUrl = new URL(currentScript.src, window.location.href);
        console.info('[Basjoo Widget] Detected API base from current script:', scriptUrl.origin);
        return scriptUrl.origin;
      } catch {
        // Ignore and continue fallback detection.
      }
    }

    const scripts = document.querySelectorAll('script[src]');
    for (const script of scripts) {
      const src = script.getAttribute('src') || '';
      if (!src.includes('sdk.js') && !src.includes('basjoo')) {
        continue;
      }

      try {
        const scriptUrl = new URL(src, window.location.href);
        console.info('[Basjoo Widget] Detected API base from script src:', scriptUrl.origin);
        return scriptUrl.origin;
      } catch {
        // Ignore invalid script URLs and continue scanning.
      }
    }

    const port = window.location.port;
    if (port === '3000' || port === '5173') {
      const devBase = `${window.location.protocol}//${window.location.hostname}:8000`;
      console.info('[Basjoo Widget] Development mode detected, using:', devBase);
      return devBase;
    }

    if (window.location.protocol === 'file:') {
      console.error('[Basjoo Widget] Cannot determine API base from a local file. Please set apiBase explicitly.');
      return '';
    }

    console.warn('[Basjoo Widget] Falling back to window.location.origin. Set apiBase explicitly if the API is hosted elsewhere.');
    return window.location.origin;
  }

  private getEffectiveTheme(): 'light' | 'dark' {
    if (this.config.theme === 'light' || this.config.theme === 'dark') {
      return this.config.theme;
    }
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return 'light';
  }

  private async loadPublicConfig() {
    if (!this.config.apiBase) {
      console.warn('[Basjoo Widget] Skipping public config fetch because apiBase could not be determined.');
      return;
    }

    try {
      const publicConfigUrl = new URL(`${this.config.apiBase}/api/v1/config:public`)
      if (this.config.agentId) {
        publicConfigUrl.searchParams.set('agent_id', this.config.agentId)
      }
      const response = await fetch(publicConfigUrl.toString())
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const data = await response.json() as PublicWidgetConfig
      if (!this.config.agentId && data.default_agent_id) {
        this.config.agentId = data.default_agent_id
      }
      this.config.themeColor = this.config.themeColor || data.widget_color || '#3B82F6'
      if (!this.hasTitleOverride) {
        this.config.title = data.widget_title || 'AI助手'
      }
      if (!this.hasWelcomeMessageOverride) {
        this.config.welcomeMessage = data.welcome_message || '你好！有什么可以帮助您的吗？'
      }
      this.effectiveTheme = this.getEffectiveTheme()
    } catch (error) {
      console.warn('[Basjoo Widget] Failed to load public config, using defaults.', error)
      if (error instanceof TypeError) {
        console.warn('[Basjoo Widget] Public config request may be blocked by CORS, network issues, or an incorrect apiBase:', this.config.apiBase)
      }
    }
  }

  /**
   * 初始化Widget
   */
  async init() {
    if (!document.body) {
      console.warn('[Basjoo Widget] document.body is not available yet. Call init() after DOMContentLoaded or place the embed code near the end of <body>.')
      return
    }

    if (document.getElementById('basjoo-widget-container')) {
      console.warn('[Basjoo Widget] Initialization skipped because #basjoo-widget-container already exists. Avoid loading or initializing the widget twice on the same page.')
      return
    }

    await this.loadPublicConfig()

    // 保存原始标题用于闪烁
    this.originalTitle = document.title;

    this.createStyles();
    this.createContainer();
    this.createButton();
    this.createChatWindow();

    // 显示打招呼气泡
    this.showGreetingBubble();

    // 页面加载时立即启动标题闪烁提醒，吸引用户打开聊天窗口
    this.startTitleBlink();

    if (this.sessionId) {
      void this.loadHistory();
      return;
    }

    // 欢迎消息
    if (this.config.welcomeMessage) {
      this.addMessage({
        role: 'assistant',
        content: this.config.welcomeMessage,
        timestamp: new Date(),
      });
    }
  }

  /**
   * 显示打招呼气泡
   */
  private showGreetingBubble() {
    if (!this.button) return;

    const bubble = document.createElement('div');
    bubble.className = 'basjoo-greeting-bubble';
    bubble.textContent = this.getText('greetingBubble');

    // 定位到按钮左上方
    const position = this.config.position;
    bubble.style.position = 'fixed';
    bubble.style.bottom = '100px';
    bubble.style[position] = '24px';
    bubble.style.zIndex = '9999';

    document.body.appendChild(bubble);

    // 5秒后自动消失
    setTimeout(() => {
      bubble.remove();
    }, 5000);
  }

  private async loadHistory() {
    if (!this.sessionId) return;

    try {
      const response = await fetch(
        `${this.config.apiBase}/api/v1/chat/messages?session_id=${encodeURIComponent(this.sessionId)}`
      );
      if (!response.ok) {
        throw new Error('Failed to load history');
      }

      const messages = await response.json() as ChatHistoryMessage[];
      if (messages && messages.length > 0) {
        for (const message of messages) {
          this.addMessage({
            role: message.role === 'user' ? 'user' : 'assistant',
            content: message.content,
            sources: message.sources,
            timestamp: new Date(),
            attachments: (message.attachments || []).map((a) => ({
              id: a.id,
              kind: a.kind,
              mime_type: a.mime_type,
              filename: a.filename,
              size_bytes: a.size_bytes,
              url: a.url,
              status: 'uploaded',
              preview_url: '',
              duration_ms: a.duration_ms ?? undefined,
            })),
          });
          if (message.id > this.lastMessageId) {
            this.lastMessageId = message.id;
          }
        }
        this.startPolling();
        return;
      }
    } catch {
      // Fall through to reset invalid or expired sessions.
    }

    this.sessionId = null;
    this.storage.removeItem(this.STORAGE_KEY);
    if (this.config.welcomeMessage) {
      this.addMessage({
        role: 'assistant',
        content: this.config.welcomeMessage,
        timestamp: new Date(),
      });
    }
  }

  /**
   * 开始标题闪烁提醒
   */
  private startTitleBlink() {
    if (this.titleBlinkInterval) return;

    this.hasUnread = true;
    this.updateUnreadBadge();
    let showOriginal = true;

    this.titleBlinkInterval = window.setInterval(() => {
      document.title = showOriginal ? this.originalTitle : '❗ ' + this.getText('newMessage');
      showOriginal = !showOriginal;
    }, 1000);
  }

  /**
   * 停止标题闪烁
   */
  private stopTitleBlink() {
    if (this.titleBlinkInterval) {
      clearInterval(this.titleBlinkInterval);
      this.titleBlinkInterval = null;
    }
    document.title = this.originalTitle;
    this.hasUnread = false;
    this.updateUnreadBadge();
  }

  /**
   * 创建样式
   */
  private createStyles() {
    const style = document.createElement('style');
    style.id = 'basjoo-widget-styles';
    const isDark = this.effectiveTheme === 'dark';
    const bgColor = isDark ? '#1a1a2e' : 'white';
    const textColor = isDark ? '#e2e8f0' : '#1f2937';
    const mutedColor = isDark ? '#94a3b8' : '#6b7280';
    const borderColor = isDark ? 'rgba(148, 163, 184, 0.2)' : '#e5e7eb';
    const inputBg = isDark ? '#0f0f1a' : 'white';
    const messageBg = isDark ? '#2d2d44' : '#f3f4f6';
    const errorBg = isDark ? 'rgba(239, 68, 68, 0.2)' : '#fef2f2';

    style.textContent = `
      #basjoo-widget-container, #basjoo-widget-container * {
        box-sizing: border-box;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      }

      #basjoo-widget-button {
        position: fixed;
        bottom: 24px;
        ${this.config.position === 'left' ? 'left' : 'right'}: 24px;
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background-color: ${this.config.themeColor};
        cursor: pointer;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s, box-shadow 0.2s;
        z-index: 9999;
      }

      #basjoo-widget-button:hover {
        transform: scale(1.05);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
      }

      #basjoo-widget-button svg {
        width: 30px;
        height: 30px;
        fill: white;
      }

      .basjoo-unread-badge {
        position: absolute;
        top: -4px;
        right: -4px;
        min-width: 20px;
        height: 20px;
        padding: 0 6px;
        border-radius: 10px;
        background: #ef4444;
        color: white;
        font-size: 11px;
        font-weight: 600;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid white;
      }

      .basjoo-greeting-bubble {
        background: white;
        color: ${textColor};
        padding: 10px 14px;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        font-size: 13px;
        line-height: 1.4;
        animation: basjoo-bubble-fadein 0.3s ease-out;
        max-width: 200px;
      }

      .basjoo-greeting-bubble::after {
        content: '';
        position: absolute;
        bottom: -6px;
        ${this.config.position === 'left' ? 'left' : 'right'}: 30px;
        width: 12px;
        height: 12px;
        background: white;
        transform: rotate(45deg);
        border-bottom: 1px solid ${borderColor};
        border-right: 1px solid ${borderColor};
      }

      @keyframes basjoo-bubble-fadein {
        from {
          opacity: 0;
          transform: translateY(10px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      #basjoo-chat-window {
        position: fixed;
        bottom: 96px;
        ${this.config.position === 'left' ? 'left' : 'right'}: 24px;
        width: 380px;
        height: 600px;
        max-height: calc(100vh - 120px);
        background: ${bgColor};
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transform: scale(0);
        transform-origin: ${this.config.position === 'left' ? 'bottom left' : 'bottom right'};
        transition: transform 0.3s ease;
        z-index: 9998;
      }

      #basjoo-chat-window.open {
        transform: scale(1);
      }

      #basjoo-chat-window.closing {
        transform: scale(0);
      }

      .basjoo-header {
        background: linear-gradient(135deg, ${this.config.themeColor} 0%, ${this.adjustColor(this.config.themeColor, -20)} 100%);
        color: white;
        padding: 20px 24px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-shrink: 0;
      }

      .basjoo-header-title {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 18px;
        font-weight: 600;
      }

      .basjoo-header-logo {
        width: 32px;
        height: 32px;
        object-fit: contain;
        border-radius: 8px;
        background: rgba(255,255,255,0.2);
        padding: 4px;
        flex-shrink: 0;
      }

      .basjoo-close {
        width: 32px;
        height: 32px;
        border: none;
        background: rgba(255,255,255,0.15);
        border-radius: 8px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
        color: white;
      }

      .basjoo-close:hover {
        background: rgba(255,255,255,0.25);
      }

      .basjoo-messages {
        flex: 1;
        overflow-y: auto;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        background: ${inputBg};
      }

      #basjoo-widget-container .basjoo-message {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        max-width: 85%;
        min-width: 0;
        width: fit-content;
        animation: basjoo-message-fadein 0.3s ease-out;
      }

      #basjoo-widget-container .basjoo-message-user {
        align-self: flex-end;
        align-items: flex-end;
      }

      #basjoo-widget-container .basjoo-message-assistant {
        align-self: flex-start;
        align-items: flex-start;
      }

      #basjoo-widget-container .basjoo-message-content {
        display: block;
        align-self: flex-start;
        width: fit-content;
        max-width: 100%;
        min-width: 0;
        padding: 12px 16px;
        border-radius: 16px;
        font-size: 14px;
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-wrap: anywhere;
      }

      #basjoo-widget-container .basjoo-message-user .basjoo-message-content {
        align-self: flex-end;
      }

      #basjoo-widget-container .basjoo-message-content > * {
        display: block;
        max-width: 100%;
      }

      #basjoo-widget-container .basjoo-message-content p,
      #basjoo-widget-container .basjoo-message-content ul,
      #basjoo-widget-container .basjoo-message-content ol,
      #basjoo-widget-container .basjoo-message-content pre,
      #basjoo-widget-container .basjoo-message-content blockquote {
        margin: 0 0 10px;
      }

      #basjoo-widget-container .basjoo-message-content p:last-child,
      #basjoo-widget-container .basjoo-message-content ul:last-child,
      #basjoo-widget-container .basjoo-message-content ol:last-child,
      #basjoo-widget-container .basjoo-message-content pre:last-child,
      #basjoo-widget-container .basjoo-message-content blockquote:last-child {
        margin-bottom: 0;
      }

      #basjoo-widget-container .basjoo-message-content ul,
      #basjoo-widget-container .basjoo-message-content ol {
        padding-left: 18px;
      }

      #basjoo-widget-container .basjoo-message-content code {
        font-family: SFMono-Regular, Consolas, Liberation Mono, Menlo, monospace;
        font-size: 12px;
        background: rgba(15, 23, 42, 0.08);
        padding: 1px 4px;
        border-radius: 4px;
      }

      #basjoo-widget-container .basjoo-message-content pre {
        background: #0f172a;
        color: #e2e8f0;
        padding: 10px 12px;
        border-radius: 10px;
        overflow-x: auto;
      }

      #basjoo-widget-container .basjoo-message-content pre code {
        background: transparent;
        padding: 0;
        color: inherit;
      }

      #basjoo-widget-container .basjoo-message-content a {
        color: ${this.adjustColor(this.config.themeColor, -10)};
        text-decoration: underline;
      }

      #basjoo-widget-container .basjoo-message-content blockquote {
        padding-left: 12px;
        border-left: 3px solid rgba(148, 163, 184, 0.4);
        color: ${mutedColor};
      }

      #basjoo-widget-container .basjoo-message-user .basjoo-message-content {
        background: ${this.config.themeColor};
        color: white;
        border-bottom-right-radius: 4px;
      }

      #basjoo-widget-container .basjoo-message-user .basjoo-message-content a {
        color: white;
      }

      #basjoo-widget-container .basjoo-message-user .basjoo-message-content code {
        background: rgba(255, 255, 255, 0.18);
        color: white;
      }

      #basjoo-widget-container .basjoo-message-assistant .basjoo-message-content {
        background: ${messageBg};
        color: ${textColor};
        border-bottom-left-radius: 4px;
      }

      #basjoo-widget-container .basjoo-message-error .basjoo-message-content {
        background: ${errorBg};
        color: ${isDark ? '#fca5a5' : '#dc2626'};
        border: 1px solid ${isDark ? 'rgba(239,68,68,0.35)' : '#fecaca'};
      }

      .basjoo-stream-cursor {
        display: inline-block;
        width: 0.5rem;
        height: 1em;
        margin-left: 0.12rem;
        vertical-align: text-bottom;
        background: ${this.config.themeColor};
        animation: basjoo-cursor-blink 1s steps(1) infinite;
      }

      @keyframes basjoo-cursor-blink {
        0%, 50% { opacity: 1; }
        50.01%, 100% { opacity: 0; }
      }

      .basjoo-loading {
        display: flex;
        gap: 4px;
        padding: 12px 16px !important;
        align-self: flex-start;
        margin-top: 4px !important;
      }

      .basjoo-loading-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: ${mutedColor};
        animation: basjoo-bounce 1.4s infinite ease-in-out both;
      }

      .basjoo-loading-dot:nth-child(1) { animation-delay: -0.32s; }
      .basjoo-loading-dot:nth-child(2) { animation-delay: -0.16s; }

      @keyframes basjoo-bounce {
        0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
        40% { transform: scale(1); opacity: 1; }
      }

      .basjoo-input-area {
        padding: 16px 20px 24px 20px !important;
        border-top: 1px solid ${borderColor};
        display: flex;
        gap: 12px;
        background: ${bgColor};
        flex-shrink: 0;
      }

      .basjoo-input {
        flex: 1;
        height: 48px;
        padding: 0 20px 0 20px !important;
        border: 1px solid ${borderColor};
        border-radius: 24px;
        font-size: 14px;
        outline: none;
        transition: all 0.2s;
        background: ${inputBg};
        color: ${textColor};
        margin-bottom: 8px !important;
        margin-left: 4px !important;
      }

      .basjoo-input::placeholder {
        color: ${mutedColor};
      }

      .basjoo-input:focus {
        border-color: ${this.config.themeColor};
        box-shadow: 0 0 0 3px ${this.hexToRgba(this.config.themeColor, 0.1)};
      }

      .basjoo-send {
        width: 48px;
        height: 48px;
        border: none;
        border-radius: 50%;
        background: ${this.config.themeColor};
        color: white;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
        flex-shrink: 0;
      }

      .basjoo-send:hover:not(:disabled) {
        transform: scale(1.05);
        box-shadow: 0 4px 12px ${this.hexToRgba(this.config.themeColor, 0.3)};
      }

      .basjoo-send:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .basjoo-send svg {
        width: 20px;
        height: 20px;
        stroke: currentColor;
      }

      .basjoo-error {
        padding: 12px 16px;
        background: ${errorBg};
        color: ${isDark ? '#fca5a5' : '#dc2626'};
        font-size: 13px;
        text-align: center;
        border-top: 1px solid ${isDark ? 'rgba(239,68,68,0.35)' : '#fecaca'};
      }

      #basjoo-widget-container .basjoo-message-time {
        font-size: 11px;
        color: ${mutedColor};
        margin-top: 4px;
        padding: 0 4px;
      }

      #basjoo-widget-container .basjoo-message-user .basjoo-message-time {
        text-align: right;
      }

      .basjoo-thinking {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: ${mutedColor};
        font-size: 12px;
        margin-top: 8px;
      }

      .basjoo-thinking-spinner {
        width: 12px;
        height: 12px;
        border: 2px solid ${this.hexToRgba(this.config.themeColor, 0.2)};
        border-top-color: ${this.config.themeColor};
        border-radius: 50%;
        animation: basjoo-spin 0.8s linear infinite;
      }

      @keyframes basjoo-spin {
        to { transform: rotate(360deg); }
      }

      @keyframes basjoo-message-fadein {
        from {
          opacity: 0;
          transform: translateY(10px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      /* PR12: language selector (header) */
      .basjoo-sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }
      .basjoo-language-selector-wrap {
        display: inline-flex;
        align-items: center;
        margin: 0 8px;
        flex-shrink: 0;
      }
      .basjoo-language-selector {
        appearance: none;
        -webkit-appearance: none;
        background-color: rgba(255, 255, 255, 0.15);
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none' stroke='white' stroke-width='1.5'><polyline points='3,5 6,8 9,5'/></svg>");
        background-repeat: no-repeat;
        background-position: right 8px center;
        background-size: 10px 10px;
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 6px;
        padding: 4px 24px 4px 10px;
        font-size: 12px;
        font-weight: 500;
        font-family: inherit;
        line-height: 1.4;
        cursor: pointer;
        outline: none;
        transition: background-color 0.2s, border-color 0.2s;
      }
      .basjoo-language-selector:hover {
        background-color: rgba(255, 255, 255, 0.25);
        border-color: rgba(255, 255, 255, 0.35);
      }
      .basjoo-language-selector:focus-visible {
        background-color: rgba(255, 255, 255, 0.25);
        border-color: rgba(255, 255, 255, 0.6);
        box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.4);
      }
      .basjoo-language-selector option {
        background: ${bgColor};
        color: ${textColor};
      }

      /* PR14: input bar wrapper */
      .basjoo-input-bar { display: flex; flex-direction: column; flex-shrink: 0; background: ${bgColor}; }
      .basjoo-attachments-strip {
        display: flex; flex-wrap: wrap; gap: 8px;
        padding: 10px 20px 0 20px;
        border-top: 1px solid ${borderColor}; background: ${inputBg};
        max-height: 140px; overflow-y: auto;
      }
      .basjoo-attachment-chip {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 4px 8px 4px 4px; background: ${messageBg};
        border: 1px solid ${borderColor}; border-radius: 18px;
        font-size: 12px; color: ${textColor}; max-width: 220px;
      }
      .basjoo-attachment-chip .basjoo-attachment-thumb { width: 28px; height: 28px; object-fit: cover; border-radius: 14px; flex-shrink: 0; }
      .basjoo-attachment-chip audio { height: 28px; max-width: 140px; }
      .basjoo-attachment-chip .basjoo-attachment-chip-meta { display: flex; flex-direction: column; min-width: 0; }
      .basjoo-attachment-chip .basjoo-attachment-chip-filename { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 130px; }
      .basjoo-attachment-chip .basjoo-attachment-chip-status { font-size: 10px; color: ${mutedColor}; }
      .basjoo-attachment-chip .basjoo-attachment-chip-status[data-status="error"] { color: #ef4444; }
      .basjoo-attachment-chip .basjoo-attachment-chip-remove { border: 0; background: transparent; color: ${mutedColor}; cursor: pointer; padding: 0 4px; font-size: 14px; line-height: 1; }
      .basjoo-attachment-chip .basjoo-attachment-chip-remove:hover { color: #ef4444; }
      .basjoo-attach, .basjoo-mic {
        width: 40px; height: 40px; border: 1px solid ${borderColor}; border-radius: 50%;
        background: transparent; color: ${mutedColor}; cursor: pointer;
        display: flex; align-items: center; justify-content: center; flex-shrink: 0;
        transition: all 0.2s;
      }
      .basjoo-attach:hover, .basjoo-mic:hover { border-color: ${this.config.themeColor}; color: ${this.config.themeColor}; }
      .basjoo-mic.basjoo-mic--recording { background: #ef4444; color: white; border-color: #ef4444; animation: basjoo-mic-pulse 1s ease-in-out infinite; }
      @keyframes basjoo-mic-pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.5); }
        50%      { box-shadow: 0 0 0 6px rgba(239,68,68,0); }
      }
      .basjoo-message-attachments { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; align-self: flex-end; }
      .basjoo-message-attachment-thumb { width: 120px; height: 120px; object-fit: cover; border-radius: 8px; }
      .basjoo-message-attachment-audio { width: 220px; height: 36px; }

      @media (max-width: 480px) {
        #basjoo-chat-window {
          width: calc(100vw - 32px);
          height: calc(100vh - 120px);
          max-height: 640px;
          bottom: 88px;
          left: 16px !important;
          right: 16px !important;
        }

        #basjoo-widget-button {
          bottom: 16px;
          ${this.config.position === 'left' ? 'left' : 'right'}: 16px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  private adjustColor(hex: string, amount: number): string {
    let useHash = false;
    let color = hex;
    if (color[0] === '#') {
      color = color.slice(1);
      useHash = true;
    }

    const num = parseInt(color, 16);
    let r = (num >> 16) + amount;
    let g = ((num >> 8) & 255) + amount;
    let b = (num & 255) + amount;

    r = Math.max(0, Math.min(255, r));
    g = Math.max(0, Math.min(255, g));
    b = Math.max(0, Math.min(255, b));

    return `${useHash ? '#' : ''}${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
  }

  private hexToRgba(hex: string, alpha: number): string {
    let color = hex.replace('#', '');
    if (color.length === 3) {
      const [r, g, b] = color.split('');
      color = `${r}${r}${g}${g}${b}${b}`;
    }

    const num = parseInt(color, 16);
    const r = (num >> 16) & 255;
    const g = (num >> 8) & 255;
    const b = num & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  private updateUnreadBadge() {
    if (!this.button) {
      return;
    }

    if (this.hasUnread) {
      if (!this.unreadBadge) {
        const badge = document.createElement('span');
        badge.className = 'basjoo-unread-badge';
        badge.textContent = '1';
        this.button.appendChild(badge);
        this.unreadBadge = badge;
      }
      return;
    }

    this.unreadBadge?.remove();
    this.unreadBadge = null;
  }

  /**
   * 创建容器
   */
  private createContainer() {
    this.container = document.createElement('div');
    this.container.id = 'basjoo-widget-container';
    document.body.appendChild(this.container);
  }

  /**
   * 创建浮动按钮
   */
  private createButton() {
    this.button = document.createElement('div');
    this.button.id = 'basjoo-widget-button';
    this.button.innerHTML = `
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
      </svg>
    `;
    this._buttonClickListener = () => this.toggle();
    this.button.addEventListener('click', this._buttonClickListener);
    this.container!.appendChild(this.button);
    this.updateUnreadBadge();
  }

  /**
   * 创建聊天窗口
   */
  private createChatWindow() {
    this.chatWindow = document.createElement('div');
    this.chatWindow.id = 'basjoo-chat-window';

    const safeLogoUrl = this.config.logoUrl ? this.sanitizeUrlAttribute(this.config.logoUrl) : '';
    const safeTitle = this.escapeHtml(this.config.title);
    const safePlaceholder = this.escapeHtml(this.getText('inputPlaceholder'));

    this.chatWindow.innerHTML = `
      <div class="basjoo-header">
        <div class="basjoo-header-title">
          ${safeLogoUrl ? `<img src="${safeLogoUrl}" class="basjoo-header-logo" alt="">` : ''}
          <span>${safeTitle}</span>
        </div>
        <button class="basjoo-close">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
      <div class="basjoo-messages"></div>
      <div class="basjoo-input-bar">
        <div class="basjoo-attachments-strip" hidden></div>
        <div class="basjoo-input-area">
          <button type="button" class="basjoo-attach" aria-label="${t(this.widgetLocale,'attachImage')}" title="${t(this.widgetLocale,'attachImageTitle')}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </button>
          <button type="button" class="basjoo-mic" aria-label="${t(this.widgetLocale,'recordAudio')}" title="${t(this.widgetLocale,'recordAudioTitle')}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="3" width="6" height="12" rx="3" />
              <path d="M5 11a7 7 0 0 0 14 0" />
              <line x1="12" y1="18" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </svg>
          </button>
          <input type="text" class="basjoo-input" placeholder="${safePlaceholder}" maxlength="2000">
          <button class="basjoo-send">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
      <input type="file" class="basjoo-hidden-file-input" accept="image/jpeg,image/png,image/webp" hidden>
    `;

    const closeBtn = this.chatWindow.querySelector('.basjoo-close') as HTMLElement;
    this._closeBtnClickListener = () => this.close();
    closeBtn.addEventListener('click', this._closeBtnClickListener);

    const input = this.chatWindow.querySelector('.basjoo-input') as HTMLInputElement;
    const sendBtn = this.chatWindow.querySelector('.basjoo-send') as HTMLButtonElement;

    this._sendBtnClickListener = () => {
      if (this.isSending) {
        return;
      }
      const message = input.value.trim();
      if (message) {
        if (message.length > 2000) {
          this.showError(this.getText('messageTooLong'));
          return;
        }
        this.sendMessage(message);
        input.value = '';
      }
    };

    sendBtn.addEventListener('click', this._sendBtnClickListener);
    this._inputKeypressListener = (e: KeyboardEvent) => {
      if (e.key === 'Enter') this._sendBtnClickListener?.();
    };
    input.addEventListener('keypress', this._inputKeypressListener);

    // PR14: image picker + voice recorder.
    this.attachmentsStripEl = this.chatWindow.querySelector('.basjoo-attachments-strip') as HTMLDivElement;
    this.attachBtnEl = this.chatWindow.querySelector('.basjoo-attach') as HTMLButtonElement;
    this.micBtnEl = this.chatWindow.querySelector('.basjoo-mic') as HTMLButtonElement;
    this.fileInputEl = this.chatWindow.querySelector('.basjoo-hidden-file-input') as HTMLInputElement;

    this._attachBtnClickListener = () => this.fileInputEl?.click();
    this.attachBtnEl.addEventListener('click', this._attachBtnClickListener);

    this._fileInputChangeListener = (e: Event) => {
      const input = e.target as HTMLInputElement;
      if (!input.files) return;
      for (const file of Array.from(input.files)) {
        void this._addPendingAttachment(file);
      }
      input.value = ''; // reset so the same file can be re-picked
    };
    this.fileInputEl.addEventListener('change', this._fileInputChangeListener);

    this._micBtnPressListener = (e) => { e.preventDefault(); void this._startRecording(); };
    this._micBtnReleaseListener = (e) => {
      e.preventDefault();
      if (this.recordingState === 'recording') {
        void this._stopRecording();
      }
      // pointercancel / pointerleave while not yet recording → no-op
    };
    this.micBtnEl.addEventListener('pointerdown', this._micBtnPressListener);
    this.micBtnEl.addEventListener('pointerup', this._micBtnReleaseListener);
    this.micBtnEl.addEventListener('pointercancel', this._micBtnReleaseListener);
    this.micBtnEl.addEventListener('pointerleave', this._micBtnReleaseListener);

    // PR12: language selector — sits in the header, between title and close (D15).
    const header = this.chatWindow.querySelector('.basjoo-header') as HTMLElement;
    const closeBtnForLocale = header.querySelector('.basjoo-close') as HTMLElement;

    const localeSelect = document.createElement('select');
    localeSelect.className = 'basjoo-language-selector';
    localeSelect.setAttribute('data-basjoo-locale-select', '');
    localeSelect.setAttribute('aria-label', t(this.widgetLocale, 'languageSelectorLabel'));
    for (const code of SUPPORTED_LOCALES) {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = t(
        this.widgetLocale,
        code === 'zh-CN' ? 'optionZh' : code === 'en-US' ? 'optionEn' : 'optionVi'
      );
      if (code === this.widgetLocale) {
        opt.selected = true;
      }
      localeSelect.appendChild(opt);
    }
    this._localeChangeListener = () => this.setWidgetLocale(localeSelect.value);
    localeSelect.addEventListener('change', this._localeChangeListener);

    const localeWrap = document.createElement('label');
    localeWrap.className = 'basjoo-language-selector-wrap';
    const srOnly = document.createElement('span');
    srOnly.className = 'basjoo-sr-only';
    srOnly.textContent = t(this.widgetLocale, 'languageSelectorLabel');
    localeWrap.appendChild(srOnly);
    localeWrap.appendChild(localeSelect);
    header.insertBefore(localeWrap, closeBtnForLocale);

    this.container!.appendChild(this.chatWindow);
  }

  /**
   * 切换聊天窗口
   */
  private toggle() {
    if (this.isOpen) {
      this.close();
      return;
    }
    this.open();
  }

  private open() {
    this.isOpen = true;
    this.chatWindow?.classList.remove('closing');
    this.chatWindow?.classList.add('open');
    this.stopTitleBlink();
    this.updateUnreadBadge();
    const input = this.chatWindow?.querySelector('.basjoo-input') as HTMLInputElement | null;
    setTimeout(() => {
      input?.focus();
    }, 300);
  }

  private close() {
    this.isOpen = false;
    this.chatWindow?.classList.remove('open');
    this.chatWindow?.classList.add('closing');
  }

  private getRequestLocale(): string {
    if (this.config.language && this.config.language !== 'auto') {
      return this.config.language
    }

    return navigator.language || 'en-US'
  }

  /**
   * Get localized text based on the visitor's widget language choice
   * (PR12 — driven by `this.widgetLocale`, NOT by `getRequestLocale()` so the
   * selector value wins over the auto-detected `config.language`).
   */
  private getText(
    key:
      | 'sendFailed' | 'networkError' | 'quotaExceeded' | 'takenOverNotice'
      | 'inputPlaceholder' | 'messageTooLong' | 'greetingBubble' | 'newMessage'
      | 'thinking' | 'references' | 'languageSelectorLabel'
      | 'optionZh' | 'optionEn' | 'optionVi'
      | 'attachImage' | 'attachImageTitle' | 'recordAudio' | 'recordAudioTitle'
      | 'attachmentUnsupported' | 'attachmentTooLarge'
      | 'recordingUnsupported' | 'micPermissionDenied' | 'recordingCapReached'
      | 'attachmentStatusUploading' | 'attachmentStatusReady' | 'attachmentStatusError'
      | 'attachmentRemove'
  ): string {
    return t(this.widgetLocale, key)
  }

  /**
   * PR12: set the visitor's widget language and persist to localStorage.
   * Silently ignores unknown values; no-op when value matches the current one.
   */
  private setWidgetLocale(next: string): void {
    if (!isWidgetLocale(next) || next === this.widgetLocale) {
      return
    }
    this.widgetLocale = next
    try {
      this.storage.setItem(WIDGET_LOCALE_STORAGE_KEY, next)
    } catch {
      // StorageAdapter.setItem already handles denial; the try/catch is for the
      // extremely unlikely case where even the in-memory map is unreachable.
    }
    this.applyWidgetLocale()
  }

  /**
   * PR12: re-render widget UI strings that were captured at construction time
   * (input placeholder, selector a11y label, greeting bubble text). Strings
   * that are read live by `getText()` (e.g. thinking, error toasts) do not
   * need manual re-rendering.
   */
  private applyWidgetLocale(): void {
    if (!this.chatWindow) return
    const input = this.chatWindow.querySelector('.basjoo-input') as HTMLInputElement | null
    if (input) {
      input.placeholder = t(this.widgetLocale, 'inputPlaceholder')
    }
    const select = this.chatWindow.querySelector('[data-basjoo-locale-select]') as HTMLSelectElement | null
    if (select) {
      select.setAttribute('aria-label', t(this.widgetLocale, 'languageSelectorLabel'))
    }
    const srOnly = this.chatWindow.querySelector(
      '.basjoo-language-selector-wrap .basjoo-sr-only'
    ) as HTMLElement | null
    if (srOnly) {
      srOnly.textContent = t(this.widgetLocale, 'languageSelectorLabel')
    }
    // Re-text the greeting bubble if it's still on screen (5-second auto-hide).
    const bubble = document.querySelector('.basjoo-greeting-bubble') as HTMLElement | null
    if (bubble) {
      bubble.textContent = t(this.widgetLocale, 'greetingBubble')
    }
    // PR14: re-render the pending-attachments strip so localized strings refresh.
    if (this.attachmentsStripEl) {
      this.renderPendingStrip()
    }
  }

  /**
   * 将纯文本安全转义为HTML
   */
  // ---- PR14: image picker + voice recorder (helper methods) ----

  private _addPendingAttachment(file: File): void {
    const allowedImage = new Set(['image/jpeg', 'image/png', 'image/webp']);
    if (!allowedImage.has(file.type)) {
      this.showError(this.getText('attachmentUnsupported'));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      this.showError(this.getText('attachmentTooLarge'));
      return;
    }
    const clientId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : 'c_' + Math.random().toString(36).slice(2);
    const previewUrl = URL.createObjectURL(file);
    this.pendingAttachments.push({
      clientId,
      kind: 'image',
      mimeType: file.type,
      filename: file.name || 'image',
      size: file.size,
      file,
      previewUrl,
      status: 'pending',
      attachmentId: '',
      serverUrl: '',
      errorMessage: '',
    });
    this.renderPendingStrip();
  }

  private _removePendingAttachment(clientId: string): void {
    const idx = this.pendingAttachments.findIndex((a) => a.clientId === clientId);
    if (idx === -1) return;
    const row = this.pendingAttachments[idx];
    if (row.previewUrl) URL.revokeObjectURL(row.previewUrl);
    this.pendingAttachments.splice(idx, 1);
    this.renderPendingStrip();
  }

  private renderPendingStrip(): void {
    if (!this.attachmentsStripEl) return;
    this.attachmentsStripEl.innerHTML = '';
    if (this.pendingAttachments.length === 0) {
      this.attachmentsStripEl.hidden = true;
      return;
    }
    this.attachmentsStripEl.hidden = false;
    for (const row of this.pendingAttachments) {
      const chip = document.createElement('div');
      chip.className = 'basjoo-attachment-chip basjoo-attachment-chip--' + row.status;
      chip.setAttribute('data-client-id', row.clientId);
      const safeUrl = this.sanitizeUrlAttribute(row.previewUrl || row.serverUrl);
      if (row.kind === 'image' && safeUrl) {
        const img = document.createElement('img');
        img.className = 'basjoo-attachment-thumb';
        img.src = safeUrl;
        img.alt = row.filename;
        chip.appendChild(img);
      } else {
        const dot = document.createElement('span');
        dot.className = 'basjoo-attachment-kind-dot';
        dot.textContent = '♪';
        chip.appendChild(dot);
      }
      const meta = document.createElement('span');
      meta.className = 'basjoo-attachment-chip-meta';
      const fname = document.createElement('span');
      fname.className = 'basjoo-attachment-chip-filename';
      fname.textContent = row.filename;
      meta.appendChild(fname);
      const status = document.createElement('span');
      status.className = 'basjoo-attachment-chip-status';
      status.setAttribute('data-status', row.status);
      status.textContent =
        row.status === 'uploading'
          ? this.getText('attachmentStatusUploading')
          : row.status === 'uploaded'
          ? this.getText('attachmentStatusReady')
          : row.status === 'error'
          ? (row.errorMessage || this.getText('attachmentStatusError'))
          : '';
      meta.appendChild(status);
      chip.appendChild(meta);
      if (row.status === 'uploaded' && row.serverUrl) {
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'metadata';
        audio.src = this.sanitizeUrlAttribute(row.serverUrl);
        audio.className = 'basjoo-attachment-audio';
        chip.appendChild(audio);
      }
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'basjoo-attachment-chip-remove';
      remove.setAttribute('aria-label', this.getText('attachmentRemove'));
      remove.textContent = '×';
      remove.addEventListener('click', () => this._removePendingAttachment(row.clientId));
      chip.appendChild(remove);
      this.attachmentsStripEl.appendChild(chip);
    }
  }

  private async uploadPendingAttachments(): Promise<string[]> {
    const ids: string[] = [];
    for (const row of this.pendingAttachments) {
      if (row.status === 'uploaded' && row.attachmentId) {
        ids.push(row.attachmentId);
        continue;
      }
      row.status = 'uploading';
      row.errorMessage = '';
      this.renderPendingStrip();
      const fd = new FormData();
      if (row.file) {
        fd.append('file', row.file, row.filename);
      } else if (row.chunks && row.chunks.length) {
        const blob = new Blob(row.chunks, { type: row.mimeType });
        fd.append('file', blob, row.filename);
      }
      fd.append('agent_id', this.config.agentId);
      fd.append('session_id', this.sessionId || '');
      fd.append('visitor_id', this.visitorId);
      if (row.durationMs) fd.append('duration_ms', String(row.durationMs));
      try {
        const res = await fetch(`${this.config.apiBase}/api/v1/chat/attachments`, {
          method: 'POST',
          body: fd,
          signal: this.streamAbortController?.signal,
        });
        if (!res.ok) {
          row.status = 'error';
          row.errorMessage = `HTTP ${res.status}`;
          ids.push('');
        } else {
          const data = await res.json();
          const att = data && data.attachment;
          if (att && typeof att.id === 'string') {
            row.attachmentId = att.id;
            row.serverUrl = att.url || '';
            row.status = 'uploaded';
            ids.push(att.id);
          } else {
            row.status = 'error';
            row.errorMessage = 'malformed response';
            ids.push('');
          }
        }
      } catch (err) {
        row.status = 'error';
        row.errorMessage = (err as Error)?.message || 'upload failed';
        ids.push('');
      }
      this.renderPendingStrip();
    }
    return ids;
  }

  private _clearSuccessfulPending(): void {
    this.pendingAttachments = this.pendingAttachments.filter((row) => {
      if (row.status === 'uploaded') {
        if (row.previewUrl) URL.revokeObjectURL(row.previewUrl);
        return false;
      }
      return true;
    });
    this.renderPendingStrip();
  }

  private async _startRecording(): Promise<void> {
    if (this.recordingState === 'recording') return;
    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== 'function' ||
      typeof window === 'undefined' ||
      typeof (window as any).MediaRecorder === 'undefined'
    ) {
      this.showError(this.getText('recordingUnsupported'));
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.showError(this.getText('micPermissionDenied'));
      return;
    }
    this.mediaStream = stream;
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
    ];
    const supported = candidates.find(
      (m) => (window as any).MediaRecorder.isTypeSupported(m)
    ) || '';
    const chunks: Blob[] = [];
    const recorder = supported
      ? new (window as any).MediaRecorder(stream, { mimeType: supported })
      : new (window as any).MediaRecorder(stream);
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    const stopWaiter = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    this.mediaRecorder = recorder;
    this.recordingStartedAt = Date.now();
    this.recordingState = 'recording';
    this.micBtnEl?.classList.add('basjoo-mic--recording');
    this.recordingMaxTimerId = window.setTimeout(
      () => void this._stopRecording(true),
      60_000
    );
    try {
      recorder.start(250);
    } catch {
      this.mediaStream?.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
      this.mediaRecorder = null;
      this.recordingState = 'idle';
      this.micBtnEl?.classList.remove('basjoo-mic--recording');
      this.showError(this.getText('micPermissionDenied'));
      return;
    }
    (recorder as any)._chunks = chunks;
    (recorder as any)._stopWaiter = stopWaiter;
  }

  private async _stopRecording(capReached = false): Promise<void> {
    if (this.recordingState !== 'recording') return;
    const recorder = this.mediaRecorder;
    const stream = this.mediaStream;
    if (this.recordingMaxTimerId !== null) {
      window.clearTimeout(this.recordingMaxTimerId);
      this.recordingMaxTimerId = null;
    }
    this.recordingState = 'idle';
    this.micBtnEl?.classList.remove('basjoo-mic--recording');
    if (!recorder) return;
    try {
      try { recorder.requestData(); } catch { /* ignore */ }
      const stopWaiter: Promise<void> | undefined = (recorder as any)._stopWaiter;
      try { recorder.stop(); } catch { /* ignore */ }
      if (stopWaiter) await stopWaiter;
    } finally {
      stream?.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
      this.mediaRecorder = null;
    }
    const chunks: Blob[] = ((recorder as any)._chunks) || [];
    if (chunks.length === 0) {
      if (capReached) this.showError(this.getText('recordingCapReached'));
      return;
    }
    const mimeType = (recorder as any).mimeType || 'audio/webm';
    const ts = this.recordingStartedAt || Date.now();
    const ext = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
    const filename = `recording-${ts}.${ext}`;
    const clientId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : 'c_' + Math.random().toString(36).slice(2);
    this.pendingAttachments.push({
      clientId,
      kind: 'audio',
      mimeType,
      filename,
      size: chunks.reduce((n, b) => n + b.size, 0),
      chunks,
      previewUrl: '',
      status: 'pending',
      attachmentId: '',
      serverUrl: '',
      errorMessage: '',
      durationMs: Date.now() - ts,
    });
    this.renderPendingStrip();
    if (capReached) this.showError(this.getText('recordingCapReached'));
  }

  // ---- end PR14 helpers ----

  private _rerenderLastUserMessage(): void {
    const messagesEl = this.chatWindow?.querySelector('.basjoo-messages');
    if (!messagesEl) return;
    // The last appended user-message DOM element is the second-to-last child
    // (the most-recent child is the streamingMessage placeholder if any). Find
    // the user-role .basjoo-message containing the most recent timestamp.
    const lastUserEl = Array.from(messagesEl.querySelectorAll('.basjoo-message-user'))
      .pop() as HTMLElement | undefined;
    if (!lastUserEl) return;
    // Re-render by removing + re-creating. Cheap: at most a few chips.
    const idx = this.messages.length - 1;
    const last = this.messages[idx];
    if (!last) return;
    const replacement = this.createMessageElement(last);
    lastUserEl.replaceWith(replacement);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Sanitise a URL to be safe for use in an HTML attribute (e.g. src/href).
   * Allows http/https for server-served attachments and blob: for local
   * previews produced by URL.createObjectURL. Anything else is stripped.
   */
  private sanitizeUrlAttribute(url: string): string {
    try {
      const parsed = new URL(url);
      if (
        parsed.protocol === 'http:' ||
        parsed.protocol === 'https:' ||
        parsed.protocol === 'blob:'
      ) {
        return this.escapeHtml(url);
      }
    } catch { /* invalid URL */ }
    return '';
  }

  /**
   * 安全渲染基础 Markdown
   */
  private renderMarkdown(markdown: string): string {
    if (!markdown) {
      return '';
    }

    const blocks = markdown
      .replace(/\r\n/g, '\n')
      .split(/\n{2,}/)
      .map((block) => block.trim())
      .filter(Boolean);

    const renderInline = (text: string): string => {
      let html = this.escapeHtml(text);
      html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
      html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
      html = html.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>');
      html = html.replace(/(^|[^_])_([^_]+)_(?!_)/g, '$1<em>$2</em>');
      html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_match, label, url) => {
        const safeLabel = label;
        const safeUrl = this.sanitizeUrlAttribute(url);
        if (!safeUrl) {
          return safeLabel;
        }
        return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeLabel}</a>`;
      });
      return html;
    };

    const renderedBlocks = blocks.map((block) => {
      if (/^```/.test(block) && /```$/.test(block)) {
        const code = block.replace(/^```\w*\n?/, '').replace(/```$/, '');
        return `<pre><code>${this.escapeHtml(code)}</code></pre>`;
      }

      if (/^(?:[-*]\s.+\n?)+$/.test(block)) {
        const items = block
          .split('\n')
          .map((line) => line.replace(/^[-*]\s+/, '').trim())
          .filter(Boolean)
          .map((line) => `<li>${renderInline(line)}</li>`)
          .join('');
        return `<ul>${items}</ul>`;
      }

      if (/^(?:\d+\.\s.+\n?)+$/.test(block)) {
        const items = block
          .split('\n')
          .map((line) => line.replace(/^\d+\.\s+/, '').trim())
          .filter(Boolean)
          .map((line) => `<li>${renderInline(line)}</li>`)
          .join('');
        return `<ol>${items}</ol>`;
      }

      if (/^>\s?/.test(block)) {
        const quote = block
          .split('\n')
          .map((line) => line.replace(/^>\s?/, ''))
          .join('<br>');
        return `<blockquote>${renderInline(quote)}</blockquote>`;
      }

      if (/^#{1,6}\s/.test(block)) {
        const headingText = block.replace(/^#{1,6}\s+/, '');
        return `<p><strong>${renderInline(headingText)}</strong></p>`;
      }

      return `<p>${renderInline(block).replace(/\n/g, '<br>')}</p>`;
    });

    return renderedBlocks.join('');
  }

  private updateMessageContent(element: HTMLElement, content: string, includeCursor = false): void {
    element.innerHTML = this.renderMarkdown(content) + (includeCursor ? '<span class="basjoo-stream-cursor"></span>' : '');
  }

  private createMessageElement(message: ChatMessage): HTMLDivElement {
    const messageDiv = document.createElement('div');
    messageDiv.className = `basjoo-message basjoo-message-${message.role}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'basjoo-message-content';

    if (message.role === 'assistant') {
      const formattedMessage = formatAssistantMessage(message.content, message.sources);
      const referenceMarkdown = formattedMessage.references.length > 0
        ? `\n\n**${this.getText('references')}**\n${formattedMessage.references.map((reference) => `- [${reference.title}](${reference.url})`).join('\n')}`
        : '';
      this.updateMessageContent(contentDiv, formattedMessage.content + referenceMarkdown);
    } else {
      this.updateMessageContent(contentDiv, message.content);
    }

    messageDiv.appendChild(contentDiv);

    // PR14: render attachments (user bubble only). Assistant bubble skips
    // this block because the assistant turn never sends inbound attachments.
    if (message.attachments && message.attachments.length > 0 && message.role === 'user') {
      const row = document.createElement('div');
      row.className = 'basjoo-message-attachments';
      for (const att of message.attachments) {
        const safeUrl = this.sanitizeUrlAttribute(att.preview_url || att.url);
        if (!safeUrl) continue;
        if (att.kind === 'image') {
          const img = document.createElement('img');
          img.className = 'basjoo-message-attachment-thumb';
          img.src = safeUrl;
          img.alt = att.filename;
          row.appendChild(img);
        } else if (att.kind === 'audio') {
          const audio = document.createElement('audio');
          audio.className = 'basjoo-message-attachment-audio';
          audio.controls = true;
          audio.preload = 'metadata';
          audio.src = safeUrl;
          row.appendChild(audio);
        }
      }
      if (row.children.length > 0) {
        messageDiv.appendChild(row);
      }
    }

    const timeDiv = document.createElement('div');
    timeDiv.className = 'basjoo-message-time';
    timeDiv.textContent = message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    messageDiv.appendChild(timeDiv);

    return messageDiv;
  }

  private formatThinkingText(): string {
    return `${this.getText('thinking')} ${this.thinkingElapsed}s`;
  }

  private showThinkingIndicator(elapsed = 0): void {
    this.hideLoading();
    if (!this.currentStreamContent.trim()) {
      this.streamingMessage?.remove();
      this.streamingMessage = null;
      this.streamingMessageContent = null;
    }
    this.thinkingElapsed = elapsed;
    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement | null;
    if (!messagesContainer) {
      return;
    }

    if (!this.thinkingIndicator) {
      const indicator = document.createElement('div');
      indicator.className = 'basjoo-thinking';
      indicator.innerHTML = `
        <span class="basjoo-thinking-spinner"></span>
        <span>${this.getText('thinking')}</span>
      `;
      messagesContainer.appendChild(indicator);
      this.thinkingIndicator = indicator;
      this.thinkingIndicatorText = indicator.querySelector('span:last-child') as HTMLSpanElement | null;
    }

    if (this.thinkingIndicatorText) {
      this.thinkingIndicatorText.textContent = this.formatThinkingText();
    }
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    if (this.thinkingTimerId === null) {
      this.thinkingTimerId = window.setInterval(() => {
        this.thinkingElapsed += 1;
        if (this.thinkingIndicatorText) {
          this.thinkingIndicatorText.textContent = this.formatThinkingText();
        }
      }, 1000);
    }
  }

  private hideThinkingIndicator(): void {
    if (this.thinkingTimerId !== null) {
      window.clearInterval(this.thinkingTimerId);
      this.thinkingTimerId = null;
    }
    this.thinkingIndicator?.remove();
    this.thinkingIndicator = null;
    this.thinkingIndicatorText = null;
    this.thinkingElapsed = 0;
  }

  private removeStreamingMessage(): void {
    this.streamingMessage?.remove();
    this.streamingMessage = null;
    this.streamingMessageContent = null;
    this.currentStreamContent = '';
    this.currentStreamSources = [];
  }

  private createStreamingMessage(includeCursor = false): HTMLDivElement {
    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement | null;
    const messageDiv = document.createElement('div');
    messageDiv.className = 'basjoo-message basjoo-message-assistant';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'basjoo-message-content';
    this.updateMessageContent(contentDiv, this.currentStreamContent, includeCursor);
    messageDiv.appendChild(contentDiv);

    if (!messagesContainer) {
      this.streamingMessage = messageDiv;
      this.streamingMessageContent = contentDiv;
      this.currentStreamContent = '';
      return messageDiv;
    }

    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    this.streamingMessage = messageDiv;
    this.streamingMessageContent = contentDiv;
    this.currentStreamContent = '';
    return messageDiv;
  }

  private appendToStreamingMessage(chunk: string): void {
    if (!this.streamingMessage || !this.streamingMessageContent) {
      this.hideThinkingIndicator();
      this.createStreamingMessage();
    }

    this.currentStreamContent += chunk;
    if (this.streamingMessageContent) {
      this.updateMessageContent(this.streamingMessageContent, this.currentStreamContent, true);
    }

    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement | null;
    if (!messagesContainer) {
      return;
    }
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  private finalizeStreamingMessage(sources: Source[] = []): void {
    if (!this.streamingMessage || !this.streamingMessageContent) {
      return;
    }

    if (!this.currentStreamContent.trim()) {
      this.removeStreamingMessage();
      return;
    }

    const cursor = this.streamingMessage.querySelector('.basjoo-stream-cursor');
    cursor?.remove();
    this.currentStreamSources = sources;
    const formattedMessage = formatAssistantMessage(this.currentStreamContent, sources);
    const referenceMarkdown = formattedMessage.references.length > 0
      ? `\n\n**${this.getText('references')}**\n${formattedMessage.references.map((reference) => `- [${reference.title}](${reference.url})`).join('\n')}`
      : '';
    const finalContent = formattedMessage.content + referenceMarkdown;
    this.updateMessageContent(this.streamingMessageContent, finalContent);

    this.messages.push({
      role: 'assistant',
      content: finalContent,
      sources,
      timestamp: new Date(),
    });

    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement;
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    this.streamingMessage = null;
    this.streamingMessageContent = null;
    this.currentStreamContent = '';
    this.currentStreamSources = [];
  }

  /**
   * 添加消息到界面
   */
  private addMessage(message: ChatMessage) {
    this.messages.push(message);
    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement | null;

    if (!message.content) {
      console.error('Message content is null or undefined:', message);
      return;
    }

    if (!messagesContainer) {
      return;
    }

    const messageDiv = this.createMessageElement(message);
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    if (message.role === 'assistant' && !this.isOpen) {
      this.hasUnread = true;
      this.updateUnreadBadge();
    }
  }

  /**
   * 显示加载动画
   */
  private showLoading() {
    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement | null;
    if (!messagesContainer) {
      return;
    }

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'basjoo-loading';
    loadingDiv.id = 'basjoo-loading';
    loadingDiv.innerHTML = `
      <div class="basjoo-loading-dot"></div>
      <div class="basjoo-loading-dot"></div>
      <div class="basjoo-loading-dot"></div>
    `;
    messagesContainer.appendChild(loadingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  /**
   * 移除加载动画
   */
  private hideLoading() {
    const loading = this.chatWindow?.querySelector('#basjoo-loading');
    loading?.remove();
  }

  /**
   * 显示错误
   */
  private showError(message: string) {
    const messagesContainer = this.chatWindow?.querySelector('.basjoo-messages') as HTMLElement | null;
    if (!messagesContainer) {
      return;
    }

    const errorDiv = document.createElement('div');
    errorDiv.className = 'basjoo-error';
    errorDiv.textContent = message;
    messagesContainer.appendChild(errorDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    setTimeout(() => errorDiv.remove(), 5000);
  }

  /**
   * 开始轮询新消息（人工接管后管理员发送的消息）
   */
  private startPolling() {
    if (this.pollIntervalId) return;
    this.pollIntervalId = window.setInterval(() => this.pollMessages(), 3000);
  }

  /**
   * 停止轮询
   */
  private stopPolling() {
    if (this.pollIntervalId) {
      clearInterval(this.pollIntervalId);
      this.pollIntervalId = null;
    }
  }

  /**
   * 轮询拉取新消息
   */
  private async pollMessages() {
    if (!this.sessionId) return;

    try {
      const response = await fetch(
        `${this.config.apiBase}/api/v1/chat/messages?session_id=${encodeURIComponent(this.sessionId)}&after_id=${this.lastMessageId}&role=assistant`
      );
      if (!response.ok) return;

      const messages = await response.json() as ChatHistoryMessage[];
      for (const msg of messages) {
        if (msg.content) {
          this.addMessage({
            role: msg.role === 'user' ? 'user' : 'assistant',
            content: msg.content,
            sources: msg.sources,
            timestamp: new Date(),
            attachments: (msg.attachments || []).map((a) => ({
              id: a.id,
              kind: a.kind,
              mime_type: a.mime_type,
              filename: a.filename,
              size_bytes: a.size_bytes,
              url: a.url,
              status: 'uploaded',
              preview_url: '',
              duration_ms: a.duration_ms ?? undefined,
            })),
          });
          if (!this.isOpen) {
            this.startTitleBlink();
          }
        }
        if (msg.id > this.lastMessageId) {
          this.lastMessageId = msg.id;
        }
      }
    } catch {
      // 轮询失败静默忽略
    }
  }

  /**
   * Unified cleanup after any stream termination path.
   * Hides transient UI states and removes incomplete streaming content.
   */
  private cleanupAfterStreamError() {
    this.hideLoading();
    this.hideThinkingIndicator();
    this.removeStreamingMessage();
  }

  private async consumeStream(response: Response): Promise<void> {
    if (!response.body) {
      throw new Error('Streaming response body is unavailable');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamCompleted = false;

    const processEvent = (rawEvent: string) => {
      if (!rawEvent.trim()) {
        return;
      }

      let eventName = 'message';
      const dataLines: string[] = [];

      for (const line of rawEvent.split('\n')) {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart());
        }
      }

      if (!dataLines.length) {
        return;
      }

      const payload = JSON.parse(dataLines.join('\n')) as StreamEventPayload | StreamDoneMeta | StreamErrorPayload;

      switch (eventName) {
        case 'sources':
          this.currentStreamSources = Array.isArray((payload as StreamEventPayload).sources)
            ? (payload as StreamEventPayload).sources!
            : [];
          break;
        case 'thinking':
          this.showThinkingIndicator(typeof (payload as StreamEventPayload).elapsed === 'number'
            ? (payload as StreamEventPayload).elapsed!
            : 0);
          break;
        case 'thinking_done':
          this.hideThinkingIndicator();
          break;
        case 'content': {
          const contentChunk = (payload as StreamEventPayload).content || '';
          this.appendToStreamingMessage(contentChunk);
          break;
        }
        case 'done': {
          const donePayload = payload as StreamDoneMeta;
          if (donePayload.session_id) {
            this.sessionId = donePayload.session_id;
            this.storage.setItem(this.STORAGE_KEY, donePayload.session_id);
            this.startPolling();
          }
          if (typeof donePayload.message_id === 'number' && donePayload.message_id > this.lastMessageId) {
            this.lastMessageId = donePayload.message_id;
          }
          // PR14: server-side echo of resolved attachment metadata.
          if (Array.isArray(donePayload.attachments) && donePayload.attachments.length) {
            for (const att of donePayload.attachments) {
              const row = this.pendingAttachments.find((p) => p.attachmentId === att.id);
              if (row) {
                row.serverUrl = att.url || row.serverUrl;
                row.status = 'uploaded';
              }
            }
            this.renderPendingStrip();
          }
          if (donePayload.taken_over) {
            this.removeStreamingMessage();
            this.addMessage({
              role: 'assistant',
              content: this.getText('takenOverNotice'),
              timestamp: new Date(),
            });
          } else {
            this.finalizeStreamingMessage(this.currentStreamSources);
            if (!this.isOpen) {
              this.startTitleBlink();
            }
          }
          streamCompleted = true;
          break;
        }
        case 'error': {
          const streamErrorPayload = payload as StreamErrorPayload;
          const streamError = new Error(streamErrorPayload.error || 'Stream failed');
          if (streamErrorPayload.code) {
            streamError.name = streamErrorPayload.code;
          }
          throw streamError;
        }
        default:
          break;
      }
    };

    const findEventDelimiter = (): { index: number; length: number } | null => {
      const crlfIndex = buffer.indexOf('\r\n\r\n');
      const lfIndex = buffer.indexOf('\n\n');

      if (crlfIndex === -1 && lfIndex === -1) {
        return null;
      }
      if (crlfIndex === -1) {
        return { index: lfIndex, length: 2 };
      }
      if (lfIndex === -1) {
        return { index: crlfIndex, length: 4 };
      }
      return crlfIndex < lfIndex
        ? { index: crlfIndex, length: 4 }
        : { index: lfIndex, length: 2 };
    };

    const streamReadTimeout = 90_000;

    while (!streamCompleted) {
      // Check if the stream was aborted externally (e.g. new message, widget destroy).
      if (this.streamAbortController?.signal.aborted) {
        reader.cancel();
        return;
      }

      let timeoutId: number | null = null;
      try {
        const { done, value } = await Promise.race([
          reader.read(),
          new Promise<ReadableStreamReadResult<Uint8Array>>((_, reject) => {
            timeoutId = window.setTimeout(() => reject(new Error('Stream read timeout')), streamReadTimeout);
          }),
        ]);
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        let delimiter = findEventDelimiter();
        while (delimiter) {
          const rawEvent = buffer.slice(0, delimiter.index);
          buffer = buffer.slice(delimiter.index + delimiter.length);
          processEvent(rawEvent.replace(/\r\n/g, '\n'));
          if (streamCompleted) {
            break;
          }
          delimiter = findEventDelimiter();
        }

        if (done) {
          break;
        }
      } finally {
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
        }
      }
    }

    if (!streamCompleted) {
      if (buffer.trim()) {
        processEvent(buffer);
      }
      if (!streamCompleted) {
        throw new Error('Stream ended unexpectedly');
      }
    }
  }

  /**
   * Abort the active stream and release the reader lock.
   */
  private abortStream() {
    this.streamAbortController?.abort();
    this.streamAbortController = null;
  }

  /**
   * 发送消息
   */
  private async sendMessageWithRetry(
    message: string,
    attachmentIds: string[] = []
  ): Promise<void> {
    let lastError: unknown = null;

    for (let attempt = 0; attempt <= 1; attempt++) {
      // Abort any prior stream before starting a new attempt.
      this.abortStream();
      this.streamAbortController = new AbortController();

      try {
        const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

        const response = await fetch(`${this.config.apiBase}/api/v1/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
          },
          signal: this.streamAbortController.signal,
          body: JSON.stringify({
            agent_id: this.config.agentId,
            message,
            locale: this.getRequestLocale(),
            widget_locale: this.widgetLocale,
            attachment_ids: attachmentIds.filter(Boolean),
            session_id: this.sessionId || undefined,
            visitor_id: this.visitorId,
            timezone: userTimezone,
          }),
        });

        if (!response.ok) {
          let detail = `HTTP ${response.status}: ${response.statusText}`;
          try {
            const errorPayload = await response.json();
            detail = errorPayload.message || errorPayload.detail || detail;
          } catch {
            // ignore non-JSON error bodies
          }
          throw new Error(detail);
        }

        this.hideLoading();
        await this.consumeStream(response);
        return;
      } catch (error: any) {
        lastError = error;
        const errorText = String(error?.message || '');
        const hasPartialContent = this.currentStreamContent.trim().length > 0;
        const isRetryable = !hasPartialContent && (
          error instanceof TypeError
          || errorText.includes('fetch')
          || errorText.includes('Failed to fetch')
          || errorText.includes('Stream ended unexpectedly')
        );

        if (!isRetryable || attempt >= 1) {
          this.cleanupAfterStreamError();
          throw error;
        }

        this.cleanupAfterStreamError();
        console.warn(`[Basjoo Widget] Stream attempt ${attempt + 1} failed, retrying...`);
        await new Promise(resolve => window.setTimeout(resolve, 1000));
        this.showLoading();
      }
    }

    throw lastError;
  }

  private async sendMessage(message: string) {
    if (this.isSending) {
      return;
    }

    this.isSending = true;

    this.addMessage({
      role: 'user',
      content: message,
      timestamp: new Date(),
      // PR14: snapshot the local previews so the user bubble renders chips
      // immediately; the resolve-to-server-url re-render happens after upload.
      attachments: this.pendingAttachments.map((p) => ({
        id: p.attachmentId,
        kind: p.kind,
        mime_type: p.mimeType,
        filename: p.filename,
        size_bytes: p.size,
        url: p.serverUrl,
        status: p.status === 'uploaded' ? 'uploaded' : 'pending',
        preview_url: p.previewUrl,
        duration_ms: p.durationMs,
      })),
    });

    this.hideLoading();
    this.hideThinkingIndicator();
    this.removeStreamingMessage();
    this.createStreamingMessage(true);

    let attachmentIds: string[] = [];
    try {
      if (this.pendingAttachments.length > 0) {
        attachmentIds = await this.uploadPendingAttachments();
        // Patch the just-added user message with the now-resolved server URLs.
        const last = this.messages[this.messages.length - 1];
        if (last) {
          last.attachments = this.pendingAttachments
            .filter((p) => p.status === 'uploaded')
            .map((p) => ({
              id: p.attachmentId,
              kind: p.kind,
              mime_type: p.mimeType,
              filename: p.filename,
              size_bytes: p.size,
              url: p.serverUrl,
              status: 'uploaded',
              preview_url: '',
              duration_ms: p.durationMs,
            }));
          this._rerenderLastUserMessage();
        }
      }
      await this.sendMessageWithRetry(message, attachmentIds);
    } catch (error: any) {
      console.error('[Basjoo Widget] Error sending message:', error);

      let errorMessage = this.getText('sendFailed');
      let consoleHint = '';
      const errorText = String(error?.message || '');

      if (error instanceof TypeError || errorText.includes('fetch')) {
        errorMessage = this.getText('networkError');
        consoleHint = `Request may be blocked by CORS, network connectivity, or an incorrect apiBase. Current apiBase: ${this.config.apiBase || '(not set)'}`;
      } else if (errorText.includes('429') || errorText.toLowerCase().includes('quota')) {
        errorMessage = this.getText('quotaExceeded');
      } else if (error?.name === 'ORIGIN_NOT_ALLOWED' || errorText.toLowerCase().includes('widget origin not allowed')) {
        errorMessage = this.getText('sendFailed');
        consoleHint = 'Widget request was blocked because the current page origin is not on the allowed domain list.';
      } else if (errorText.includes('401')) {
        consoleHint = 'Authentication failed. Please check the agent configuration and public API access.';
      }

      if (!this.config.apiBase) {
        consoleHint = 'apiBase could not be determined. When embedding the widget from a local file, set apiBase explicitly or load the SDK from the target server.';
      }

      if (consoleHint) {
        console.error('[Basjoo Widget]', consoleHint);
      }

      this.showError(errorMessage);
    } finally {
      this.isSending = false;
    }
  }

  /**
   * 销毁Widget
   */
  destroy() {
    // 停止轮询和标题闪烁
    this.stopPolling();
    this.stopTitleBlink();
    this.hideThinkingIndicator();
    this.removeStreamingMessage();

    // Abort any active stream request.
    this.abortStream();

    // Remove tracked event listeners.
    if (this.button && this._buttonClickListener) {
      this.button.removeEventListener('click', this._buttonClickListener);
    }
    const closeBtn = this.chatWindow?.querySelector('.basjoo-close') as HTMLElement | null;
    if (closeBtn && this._closeBtnClickListener) {
      closeBtn.removeEventListener('click', this._closeBtnClickListener);
    }
    const sendBtn = this.chatWindow?.querySelector('.basjoo-send') as HTMLButtonElement | null;
    if (sendBtn && this._sendBtnClickListener) {
      sendBtn.removeEventListener('click', this._sendBtnClickListener);
    }
    const input = this.chatWindow?.querySelector('.basjoo-input') as HTMLInputElement | null;
    if (input && this._inputKeypressListener) {
      input.removeEventListener('keypress', this._inputKeypressListener);
    }

    // PR14: cancel any active recording, then drop the 4 new listeners.
    if (this.recordingState === 'recording') {
      try { this.mediaRecorder?.stop(); } catch { /* ignore */ }
      this.mediaStream?.getTracks().forEach((t) => t.stop());
      if (this.recordingMaxTimerId !== null) {
        window.clearTimeout(this.recordingMaxTimerId);
        this.recordingMaxTimerId = null;
      }
      this.recordingState = 'idle';
      this.mediaRecorder = null;
      this.mediaStream = null;
    }
    for (const row of this.pendingAttachments) {
      if (row.previewUrl) URL.revokeObjectURL(row.previewUrl);
    }
    this.pendingAttachments = [];
    if (this.attachBtnEl && this._attachBtnClickListener) {
      this.attachBtnEl.removeEventListener('click', this._attachBtnClickListener);
    }
    if (this.micBtnEl && this._micBtnPressListener) {
      this.micBtnEl.removeEventListener('pointerdown', this._micBtnPressListener);
      if (this._micBtnReleaseListener) {
        this.micBtnEl.removeEventListener('pointerup', this._micBtnReleaseListener);
        this.micBtnEl.removeEventListener('pointercancel', this._micBtnReleaseListener);
        this.micBtnEl.removeEventListener('pointerleave', this._micBtnReleaseListener);
      }
    }
    if (this.fileInputEl && this._fileInputChangeListener) {
      this.fileInputEl.removeEventListener('change', this._fileInputChangeListener);
    }
    this._attachBtnClickListener = null;
    this._micBtnPressListener = null;
    this._micBtnReleaseListener = null;
    this._fileInputChangeListener = null;
    // PR12: drop the language-selector listener tracked separately.
    const localeSelect = this.chatWindow?.querySelector(
      '[data-basjoo-locale-select]'
    ) as HTMLSelectElement | null;
    if (localeSelect && this._localeChangeListener) {
      localeSelect.removeEventListener('change', this._localeChangeListener);
    }
    this._localeChangeListener = null;

    this.container?.remove();
    const styles = document.getElementById('basjoo-widget-styles');
    styles?.remove();
  }
}

// 导出到全局（不使用 export default，避免 ES Module 格式）
(window as any).BasjooWidget = BasjooWidget;

function getSearchParamValue(searchParams: URLSearchParams, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = searchParams.get(key)
    if (value && value.trim()) {
      return value.trim()
    }
  }
  return null
}

function findAutoInitScript(): HTMLScriptElement | null {
  if (document.currentScript instanceof HTMLScriptElement) {
    return document.currentScript
  }

  const scripts = Array.from(document.querySelectorAll('script[src]')) as HTMLScriptElement[]
  for (let index = scripts.length - 1; index >= 0; index -= 1) {
    const script = scripts[index]
    const src = script.getAttribute('src') || ''
    if (!src.includes('sdk.js')) {
      continue
    }
    try {
      const url = new URL(src, window.location.href)
      if (getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.agentId)) {
        return script
      }
    } catch {
      continue
    }
  }

  return null
}

function getAutoInitConfig(script: HTMLScriptElement): WidgetConfig | null {
  const src = script.getAttribute('src') || script.src
  if (!src) {
    return null
  }

  let url: URL
  try {
    url = new URL(src, window.location.href)
  } catch {
    return null
  }

  const agentId = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.agentId)
  if (!agentId) {
    return null
  }

  const config: WidgetConfig = { agentId }

  const apiBase = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.apiBase)
  if (apiBase) {
    config.apiBase = apiBase
  }

  const themeColor = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.themeColor)
  if (themeColor) {
    config.themeColor = themeColor
  }

  const welcomeMessage = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.welcomeMessage)
  if (welcomeMessage) {
    config.welcomeMessage = welcomeMessage
  }

  const language = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.language)
  if (language) {
    config.language = language
  }

  const position = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.position)
  if (position === 'left' || position === 'right') {
    config.position = position
  }

  const theme = getSearchParamValue(url.searchParams, AUTO_INIT_SCRIPT_PARAM_MAP.theme)
  if (theme === 'light' || theme === 'dark' || theme === 'auto') {
    config.theme = theme
  }

  return config
}

(function bootstrapBasjooWidget() {
  const globalWindow = window as Window & typeof globalThis & {
    __basjooWidgetAutoInitScheduled?: boolean
  }

  const script = findAutoInitScript()
  if (!script) {
    return
  }

  const config = getAutoInitConfig(script)
  if (!config) {
    return
  }

  if (globalWindow.__basjooWidgetAutoInitScheduled) {
    return
  }
  globalWindow.__basjooWidgetAutoInitScheduled = true

  // PR12: honor ?widget_locale=... on the script src by priming localStorage
  // before the widget constructs, so the first paint shows the correct option
  // (no flash). Unknown values are silently dropped.
  try {
    const presetRaw = getSearchParamValue(
      new URL(script.src).searchParams,
      AUTO_INIT_SCRIPT_PARAM_MAP.widgetLocale
    )
    if (presetRaw && isWidgetLocale(presetRaw)) {
      window.localStorage.setItem(WIDGET_LOCALE_STORAGE_KEY, presetRaw)
    }
  } catch {
    // localStorage may be denied (cross-origin / sandboxed); StorageAdapter
    // will still keep an in-memory copy. No-op is fine.
  }

  const start = () => {
    void new BasjooWidget(config).init()
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true })
    return
  }

  start()
})()
