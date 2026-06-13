import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

// 兼容性更好的 UUID 生成函数
function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  // 降级方案
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0
    const v = c === 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

// 将 AudioBuffer 转换为 WAV 格式
function bufferToWav(buffer: AudioBuffer): Blob {
  const numOfChan = buffer.numberOfChannels
  const length = buffer.length * numOfChan * 2 + 44
  const arrayBuffer = new ArrayBuffer(length)
  const view = new DataView(arrayBuffer)
  const channels: Float32Array[] = []
  let offset = 0
  let pos = 0

  // 写入 WAV 头部
  writeString('RIFF')
  setUint32(length - 8)
  writeString('WAVE')
  writeString('fmt ')
  setUint32(16)
  setUint16(1)
  setUint16(numOfChan)
  setUint32(buffer.sampleRate)
  setUint32(buffer.sampleRate * numOfChan * 2)
  setUint16(numOfChan * 2)
  setUint16(16)
  writeString('data')
  setUint32(length - pos - 4)

  // 写入音频数据
  for (let i = 0; i < buffer.numberOfChannels; i++) {
    channels.push(buffer.getChannelData(i))
  }

  while (offset < buffer.length) {
    for (let i = 0; i < numOfChan; i++) {
      let sample = Math.max(-1, Math.min(1, channels[i][offset]))
      sample = sample < 0 ? sample * 0x8000 : sample * 0x7FFF
      view.setInt16(pos, sample, true)
      pos += 2
    }
    offset++
  }

  return new Blob([arrayBuffer], { type: 'audio/wav' })

  function writeString(str: string) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(pos++, str.charCodeAt(i))
    }
  }
  function setUint16(data: number) {
    view.setUint16(pos, data, true)
    pos += 2
  }
  function setUint32(data: number) {
    view.setUint32(pos, data, true)
    pos += 4
  }
}

// 将 Blob (WEBM) 转换为 WAV
async function convertToWav(blob: Blob): Promise<Blob> {
  const audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)()
  const arrayBuffer = await blob.arrayBuffer()
  const audioBuffer = await audioContext.decodeAudioData(arrayBuffer)
  return bufferToWav(audioBuffer)
}

type ChatRole = 'user' | 'assistant'
type Language = 'zh' | 'en' | 'vi'

type ChatMessage = {
  id: string
  role: ChatRole
  text?: string
  imagePreviewUrl?: string
  audioUrl?: string
}

const translations = {
  zh: {
    title: '智能客服',
    clear: '清空',
    welcome: '欢迎',
    subtitle: '输入文字、语音或拍照/上传图片开始对话',
    placeholder: '请输入问题…',
    send: '发送',
    photo: '拍照/图片',
    audio: '按住说话',
    recording: '录音中…',
    remove: '移除',
    removeAudio: '删除语音',
    thinking: '正在思考…',
    emptyResponse: '(空响应)',
    requestFailed: '请求失败',
    networkError: '网络错误',
    audioNotSupported: '您的浏览器不支持录音功能',
  },
  en: {
    title: 'Smart Assistant',
    clear: 'Clear',
    welcome: 'Welcome',
    subtitle: 'Type, record audio or upload an image to start chatting',
    placeholder: 'Type your question…',
    send: 'Send',
    photo: 'Photo/Image',
    audio: 'Hold to Talk',
    recording: 'Recording…',
    remove: 'Remove',
    removeAudio: 'Delete Audio',
    thinking: 'Thinking…',
    emptyResponse: '(Empty response)',
    requestFailed: 'Request failed',
    networkError: 'Network error',
    audioNotSupported: 'Your browser does not support audio recording',
  },
  vi: {
    title: 'Trợ lý Thông minh',
    clear: 'Xóa',
    welcome: 'Chào mừng',
    subtitle: 'Nhập văn bản, ghi âm hoặc tải ảnh lên để bắt đầu trò chuyện',
    placeholder: 'Nhập câu hỏi của bạn…',
    send: 'Gửi',
    photo: 'Chụp ảnh/Tải ảnh',
    audio: 'Giữ để nói',
    recording: 'Đang ghi âm…',
    remove: 'Xóa',
    removeAudio: 'Xóa âm thanh',
    thinking: 'Đang suy nghĩ…',
    emptyResponse: '(Phản hồi trống)',
    requestFailed: 'Yêu cầu thất bại',
    networkError: 'Lỗi mạng',
    audioNotSupported: 'Trình duyệt của bạn không hỗ trợ ghi âm',
  },
}

// 前端显示的语言名称
const languageNames: Record<Language, string> = {
  zh: '普通话',
  en: 'English',
  vi: 'Tiếng Việt',
}

// 传给 Coze 的语言参数
const languageParams: Record<Language, string> = {
  zh: '普通话',
  en: '英文',
  vi: '越南语',
}

const languageShort: Record<Language, string> = {
  zh: '中',
  en: 'EN',
  vi: 'VI',
}

function Avatar({ role }: { role: ChatRole }) {
  if (role === 'user') {
    return (
      <div className="avatar avatar-user">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="8" r="5"></circle>
          <path d="M20 21a8 8 0 1 0-16 0"></path>
        </svg>
      </div>
    )
  }
  return (
    <div className="avatar avatar-assistant">
      <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect>
        <circle cx="8" cy="10" r="1.5" fill="#fff"></circle>
        <circle cx="16" cy="10" r="1.5" fill="#fff"></circle>
        <path d="M9 16q3 3 6 0"></path>
      </svg>
    </div>
  )
}

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [recordingDuration, setRecordingDuration] = useState(0)
  const [lang, setLang] = useState<Language>('zh')
  const [isLangMenuOpen, setIsLangMenuOpen] = useState(false)
  const [isVoiceMode, setIsVoiceMode] = useState(false)
  const [isMorePanelOpen, setIsMorePanelOpen] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const recordingStartTimeRef = useRef<number>(0)
  const recordingTimerRef = useRef<number | null>(null)
  const isRecordingRef = useRef<boolean>(false)
  // const apiBase = (import.meta.env.VITE_API_BASE as string | undefined) || 'https://zcf.h5.qumall.qushiyun.com'
  const apiBase = (import.meta.env.VITE_API_BASE as string | undefined) || ''
  
  const t = translations[lang]

  const imagePreviewUrl = useMemo(() => {
    if (!file) return null
    return URL.createObjectURL(file)
  }, [file])

  const audioUrl = useMemo(() => {
    if (!audioBlob) return null
    return URL.createObjectURL(audioBlob)
  }, [audioBlob])

  useEffect(() => {
    return () => {
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl)
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    }
  }, [imagePreviewUrl, audioUrl])

  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current)
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
        mediaRecorderRef.current.stop()
      }
    }
  }, [])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, isSending, isMorePanelOpen])

  useEffect(() => {
    if (audioBlob && isVoiceMode && !isSending) {
      void handleSend()
    }
  }, [audioBlob, isVoiceMode, isSending])

  async function startRecording() {
    try {
      if (isRecordingRef.current) {
        console.log('Already recording, ignoring start request')
        return
      }
      isRecordingRef.current = true
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('您的浏览器不支持录音功能，请使用 Chrome、Edge 或 Firefox 浏览器')
        return
      }
      console.log('Starting recording...')
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      
      // MediaRecorder 主要支持 webm，Coze 可能不支持
      // 尝试 mp4 如果浏览器支持
      const mimeType = MediaRecorder.isTypeSupported('audio/mp4') ? 'audio/mp4' : 'audio/webm'
      console.log('Using mimeType:', mimeType)
      const mediaRecorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        console.log('Data available, size:', event.data.size)
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = async () => {
        console.log('Recording stopped, chunks count:', audioChunksRef.current.length)
        isRecordingRef.current = false
        setIsRecording(false)  // 确保录音状态被重置
        
        if (audioChunksRef.current.length === 0) {
          console.warn('No audio data collected')
          stream.getTracks().forEach(track => track.stop())
          return
        }
        const webmBlob = new Blob(audioChunksRef.current, { type: mimeType })
        console.log('Recording stopped, webm blob size:', webmBlob.size, 'type:', mimeType)
        
        // 转换为 WAV 格式（Coze 支持）
        try {
          console.log('Converting to WAV...')
          const wavBlob = await convertToWav(webmBlob)
          console.log('Converted to WAV, size:', wavBlob.size, 'type:', wavBlob.type)
          // 验证 WAV 文件大小是否合理（至少 44 字节的头部）
          if (wavBlob.size < 100) {
            console.warn('WAV file too small, using original webm')
            setAudioBlob(webmBlob)
          } else {
            setAudioBlob(wavBlob)
          }
        } catch (err) {
          console.error('Failed to convert to WAV:', err)
          // 如果转换失败，使用原始格式
          setAudioBlob(webmBlob)
        }
        stream.getTracks().forEach(track => track.stop())
      }

      mediaRecorder.onerror = (event) => {
        console.error('MediaRecorder error:', event)
        isRecordingRef.current = false
        setIsRecording(false)
        stream.getTracks().forEach(track => track.stop())
      }

      mediaRecorder.start(100)
      setIsRecording(true)
      setRecordingDuration(0)
      recordingStartTimeRef.current = Date.now()
      recordingTimerRef.current = setInterval(() => {
        setRecordingDuration(Math.floor((Date.now() - recordingStartTimeRef.current) / 1000))
      }, 1000)
      console.log('Recording started at:', recordingStartTimeRef.current)
    } catch (err) {
      const errorMsg = String(err)
      if (errorMsg.includes('NotAllowedError') || errorMsg.includes('Permission denied')) {
        alert('麦克风权限被拒绝，请在浏览器设置中允许访问麦克风')
      } else if (errorMsg.includes('NotFoundError') || errorMsg.includes('DevicesNotFoundError')) {
        alert('未找到麦克风设备，请检查麦克风是否连接')
      } else if (errorMsg.includes('NotReadableError') || errorMsg.includes('TrackStartError')) {
        alert('麦克风被其他应用占用，请关闭其他使用麦克风的应用')
      } else if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost') {
        alert('录音功能需要在 HTTPS 或 localhost 环境下使用，请使用 https 访问或 localhost')
      } else {
        alert(t.audioNotSupported)
      }
      console.error('Failed to start recording:', err)
    }
  }

  function stopRecording() {
    const duration = Date.now() - recordingStartTimeRef.current
    console.log('Recording duration:', duration, 'ms')
    
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current)
      recordingTimerRef.current = null
    }
    
    if (duration < 500) {
      console.warn('Recording too short, ignoring')
      isRecordingRef.current = false
      setIsRecording(false)
      return
    }
    
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop()
      console.log('Recording stop requested')
    }
  }

  async function handleSend() {
    if (isSending) return
    const trimmed = text.trim()
    if (!trimmed && !file && !audioBlob) return

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      text: trimmed || undefined,
      imagePreviewUrl: imagePreviewUrl || undefined,
      audioUrl: audioUrl || undefined,
    }

    setMessages((prev) => [...prev, userMsg])
    setIsSending(true)

    try {
      const fd = new FormData()
      fd.append('text', trimmed)
      fd.append('language', languageParams[lang])
      if (file) fd.append('image', file)
      if (audioBlob) {
        // 根据 MIME 类型选择合适的扩展名（Coze 支持 wav, mp3, m4a 等）
        const ext = audioBlob.type.includes('wav') ? 'wav' : 'webm'
        fd.append('audio', audioBlob, `recording.${ext}`)
        console.log('Uploading audio:', audioBlob.type, audioBlob.size, 'ext:', ext)
      }

      const resp = await fetch(`${apiBase}/api/chat`, { method: 'POST', body: fd })
      const data = await resp.json().catch(() => null)

      if (!resp.ok) {
        const msg = (data && (data.detail || data.message)) || `${t.requestFailed}: HTTP ${resp.status}`
        setMessages((prev) => [
          ...prev,
          { id: generateId(), role: 'assistant', text: String(msg) },
        ])
        return
      }

      const assistantText = (data && data.assistant_text) || ''
      setMessages((prev) => [
        ...prev,
        { id: generateId(), role: 'assistant', text: String(assistantText) || t.emptyResponse },
      ])
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { id: generateId(), role: 'assistant', text: `${t.networkError}: ${String(e)}` },
      ])
    } finally {
      setIsSending(false)
      setText('')
      setFile(null)
      setAudioBlob(null)
    }
  }

  return (
    <div className="appContainer">
      {isLangMenuOpen ? <div className="overlay" onClick={() => setIsLangMenuOpen(false)}></div> : null}
      <header className="topbar">
        <div className="topbarSide">
          <div className="langSelectorWrap">
            <button
              className="langSelector"
              type="button"
              onClick={() => setIsLangMenuOpen((v) => !v)}
              disabled={isSending}
            >
              <span>{languageShort[lang]}</span>
              <span className={`chevron ${isLangMenuOpen ? 'rotate' : ''}`}>⌄</span>
            </button>
            {isLangMenuOpen ? (
              <div className="langDropdown">
                {(Object.keys(languageNames) as Language[]).map((l) => (
                  <button
                    key={l}
                    className={`langItem ${lang === l ? 'active' : ''}`}
                    type="button"
                    onClick={() => {
                      setLang(l)
                      setIsLangMenuOpen(false)
                    }}
                  >
                    {languageNames[l]}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div className="title">{t.title}</div>
        <div className="topbarSide topbarRight">
          <button
            className="iconBtn"
            type="button"
            onClick={() => {
              setMessages([])
              setFile(null)
              setAudioBlob(null)
            }}
            disabled={isSending || messages.length === 0}
            aria-label={t.clear}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </div>
      </header>

      <main className="chat" ref={listRef} onClick={() => setIsMorePanelOpen(false)}>
        <div className="systemMessage">
          <span className="systemText">{t.subtitle}</span>
        </div>
        {messages.map((m) => (
          <div key={m.id} className={`row ${m.role === 'user' ? 'user' : 'assistant'}`}>
            {m.role === 'assistant' ? <Avatar role="assistant" /> : null}
            <div className={`bubble ${m.imagePreviewUrl ? 'imageBubble' : ''}`}>
              {m.imagePreviewUrl ? <img className="img" src={m.imagePreviewUrl} alt="User" /> : null}
              {m.audioUrl ? (
                <div className="voiceBubble">
                  <audio className="audioMessage" src={m.audioUrl} controls />
                </div>
              ) : null}
              {m.text ? <div className="text">{m.text}</div> : null}
            </div>
            {m.role === 'user' ? <Avatar role="user" /> : null}
          </div>
        ))}
        {isSending ? (
          <div className="row assistant">
            <Avatar role="assistant" />
            <div className="bubble">
              <div className="text typing">{t.thinking}</div>
            </div>
          </div>
        ) : null}
      </main>

      <div className="bottomContainer">
        <footer className="composer">
          <button
            className="actionBtn"
            type="button"
            onClick={() => {
              setIsVoiceMode((v) => !v)
              setIsMorePanelOpen(false)
            }}
            disabled={isSending}
          >
            {isVoiceMode ? (
              <svg viewBox="0 0 24 24" width="28" height="28" stroke="#111" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="4" width="20" height="16" rx="2" ry="2"></rect>
                <line x1="6" y1="8" x2="6.01" y2="8"></line>
                <line x1="10" y1="8" x2="10.01" y2="8"></line>
                <line x1="14" y1="8" x2="14.01" y2="8"></line>
                <line x1="18" y1="8" x2="18.01" y2="8"></line>
                <line x1="8" y1="12" x2="8.01" y2="12"></line>
                <line x1="12" y1="12" x2="12.01" y2="12"></line>
                <line x1="16" y1="12" x2="16.01" y2="12"></line>
                <line x1="7" y1="16" x2="17" y2="16"></line>
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="28" height="28" stroke="#111" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                <line x1="12" y1="19" x2="12" y2="22"></line>
              </svg>
            )}
          </button>

          <div className="inputWrap">
            {isVoiceMode ? (
              <button
                className={`voiceBtn ${isRecording ? 'recording' : ''}`}
                type="button"
                onPointerDown={(e) => {
                  e.preventDefault()
                  void startRecording()
                }}
                onPointerUp={(e) => {
                  e.preventDefault()
                  stopRecording()
                }}
                onPointerLeave={(e) => {
                  e.preventDefault()
                  if (isRecordingRef.current) stopRecording()
                }}
                disabled={isSending}
              >
                {isRecording ? `${t.recording} ${recordingDuration}s` : t.audio}
              </button>
            ) : (
              <textarea
                className="input"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t.placeholder}
                rows={1}
                disabled={isSending}
                onFocus={() => setIsMorePanelOpen(false)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void handleSend()
                  }
                }}
              />
            )}
          </div>

          <div className="rightAction">
            {((text.trim().length > 0 || file || audioBlob) && !isVoiceMode) ? (
              <button className="send" type="button" onClick={() => void handleSend()} disabled={isSending}>
                {t.send}
              </button>
            ) : (
              <button
                className={`actionBtn addBtn ${isMorePanelOpen ? 'open' : ''}`}
                type="button"
                onClick={() => setIsMorePanelOpen((v) => !v)}
                disabled={isSending}
              >
                <svg viewBox="0 0 24 24" width="28" height="28" stroke="#111" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="12" y1="8" x2="12" y2="16"></line>
                  <line x1="8" y1="12" x2="16" y2="12"></line>
                </svg>
              </button>
            )}
          </div>
        </footer>

        {file ? (
          <div className="selectedHint">
            <span>{t.photo}</span>
            <button className="danger" type="button" onClick={() => setFile(null)}>
              {t.remove}
            </button>
          </div>
        ) : null}
        {audioUrl && !isVoiceMode ? (
          <div className="selectedHint">
            <audio className="audioPreview" src={audioUrl} controls />
            <button className="danger" type="button" onClick={() => setAudioBlob(null)}>
              {t.removeAudio}
            </button>
          </div>
        ) : null}

        <input
          type="file"
          ref={fileInputRef}
          accept="image/*"
          capture="environment"
          style={{ display: 'none' }}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            e.currentTarget.value = ''
            setIsMorePanelOpen(false)
          }}
          disabled={isSending}
        />

        <div className={`morePanel ${isMorePanelOpen ? 'open' : ''}`}>
          <button
            type="button"
            className="panelItem"
            onClick={() => fileInputRef.current?.click()}
            disabled={isSending}
          >
            <div className="panelIconBg">
              <svg viewBox="0 0 24 24" width="28" height="28" stroke="#111" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <circle cx="8.5" cy="8.5" r="1.5"></circle>
                <polyline points="21 15 16 10 5 21"></polyline>
              </svg>
            </div>
            <span className="panelText">{t.photo}</span>
          </button>
          <button type="button" className="panelItem" onClick={() => setIsMorePanelOpen(false)}>
            <div className="panelIconBg">
              <svg viewBox="0 0 24 24" width="28" height="28" stroke="#111" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                <circle cx="12" cy="13" r="4"></circle>
              </svg>
            </div>
            <span className="panelText">拍摄</span>
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
