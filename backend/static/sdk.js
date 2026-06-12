"use strict";(()=>{var j=["zh-CN","en-US","vi-VN"],S="zh-CN",v="basjoo_widget_locale",T={"zh-CN":{languageSelectorLabel:"\u8BED\u8A00",optionZh:"\u4E2D\u6587",optionEn:"English",optionVi:"Ti\u1EBFng Vi\u1EC7t",sendFailed:"\u53D1\u9001\u5931\u8D25\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5",networkError:"\u7F51\u7EDC\u8FDE\u63A5\u5931\u8D25\uFF0C\u8BF7\u68C0\u67E5\u7F51\u7EDC",quotaExceeded:"\u4ECA\u65E5\u6D88\u606F\u5DF2\u8FBE\u4E0A\u9650",takenOverNotice:"\u5DF2\u8F6C\u63A5\u4EBA\u5DE5\u5BA2\u670D\uFF0C\u8BF7\u7B49\u5F85\u56DE\u590D\u3002",inputPlaceholder:"\u8F93\u5165\u60A8\u7684\u95EE\u9898...",messageTooLong:"\u6D88\u606F\u8FC7\u957F\uFF08\u6700\u591A2000\u5B57\u7B26\uFF09",greetingBubble:"\u4F60\u597D\uFF01\u6709\u4EC0\u4E48\u53EF\u4EE5\u5E2E\u60A8\uFF1F",newMessage:"\u65B0\u6D88\u606F",thinking:"\u601D\u8003\u4E2D...",references:"\u53C2\u8003\u6765\u6E90",attachImage:"\u6DFB\u52A0\u56FE\u7247",attachImageTitle:"\u6DFB\u52A0\u56FE\u7247\uFF08\u6700\u591A 5MB\uFF09",recordAudio:"\u5F55\u97F3",recordAudioTitle:"\u6309\u4F4F\u5F55\u97F3\uFF08\u6700\u957F 60 \u79D2\uFF09",attachmentUnsupported:"\u4E0D\u652F\u6301\u7684\u6587\u4EF6\u683C\u5F0F",attachmentTooLarge:"\u6587\u4EF6\u8FC7\u5927",recordingUnsupported:"\u5F53\u524D\u6D4F\u89C8\u5668\u4E0D\u652F\u6301\u5F55\u97F3",micPermissionDenied:"\u65E0\u6CD5\u8BBF\u95EE\u9EA6\u514B\u98CE\uFF0C\u8BF7\u68C0\u67E5\u6743\u9650",recordingCapReached:"\u5F55\u97F3\u5DF2\u8FBE 60 \u79D2\u4E0A\u9650",attachmentStatusUploading:"\u4E0A\u4F20\u4E2D\u2026",attachmentStatusReady:"\u5DF2\u5C31\u7EEA",attachmentStatusError:"\u4E0A\u4F20\u5931\u8D25",attachmentRemove:"\u79FB\u9664"},"en-US":{languageSelectorLabel:"Language",optionZh:"Chinese",optionEn:"English",optionVi:"Vietnamese",sendFailed:"Send failed, please try again later",networkError:"Network connection failed, please check your connection",quotaExceeded:"Daily message limit reached",takenOverNotice:"Your conversation has been transferred to a human agent. Please wait for their reply.",inputPlaceholder:"Type your question...",messageTooLong:"Message too long (max 2000 characters)",greetingBubble:"Hi! How can I help you?",newMessage:"New message",thinking:"Thinking...",references:"References",attachImage:"Attach image",attachImageTitle:"Attach image (max 5 MB)",recordAudio:"Record audio",recordAudioTitle:"Press and hold to record (max 60 s)",attachmentUnsupported:"Unsupported file format",attachmentTooLarge:"File too large",recordingUnsupported:"Recording not supported in this browser",micPermissionDenied:"Microphone access denied",recordingCapReached:"Recording reached 60 s limit",attachmentStatusUploading:"Uploading\u2026",attachmentStatusReady:"Ready",attachmentStatusError:"Upload failed",attachmentRemove:"Remove"},"vi-VN":{languageSelectorLabel:"Ng\xF4n ng\u1EEF",optionZh:"Ti\u1EBFng Trung",optionEn:"Ti\u1EBFng Anh",optionVi:"Ti\u1EBFng Vi\u1EC7t",sendFailed:"G\u1EEDi th\u1EA5t b\u1EA1i, vui l\xF2ng th\u1EED l\u1EA1i sau",networkError:"K\u1EBFt n\u1ED1i m\u1EA1ng th\u1EA5t b\u1EA1i, vui l\xF2ng ki\u1EC3m tra m\u1EA1ng",quotaExceeded:"\u0110\xE3 \u0111\u1EA1t gi\u1EDBi h\u1EA1n tin nh\u1EAFn h\xF4m nay",takenOverNotice:"\u0110\xE3 chuy\u1EC3n ti\u1EBFp cho nh\xE2n vi\xEAn h\u1ED7 tr\u1EE3, vui l\xF2ng \u0111\u1EE3i ph\u1EA3n h\u1ED3i.",inputPlaceholder:"Nh\u1EADp c\xE2u h\u1ECFi c\u1EE7a b\u1EA1n...",messageTooLong:"Tin nh\u1EAFn qu\xE1 d\xE0i (t\u1ED1i \u0111a 2000 k\xFD t\u1EF1)",greetingBubble:"Xin ch\xE0o! T\xF4i c\xF3 th\u1EC3 gi\xFAp g\xEC cho b\u1EA1n?",newMessage:"Tin nh\u1EAFn m\u1EDBi",thinking:"\u0110ang suy ngh\u0129...",references:"Ngu\u1ED3n tham kh\u1EA3o",attachImage:"\u0110\xEDnh k\xE8m h\xECnh \u1EA3nh",attachImageTitle:"\u0110\xEDnh k\xE8m \u1EA3nh (t\u1ED1i \u0111a 5 MB)",recordAudio:"Ghi \xE2m",recordAudioTitle:"Nh\u1EA5n gi\u1EEF \u0111\u1EC3 ghi \xE2m (t\u1ED1i \u0111a 60 gi\xE2y)",attachmentUnsupported:"\u0110\u1ECBnh d\u1EA1ng t\u1EC7p kh\xF4ng \u0111\u01B0\u1EE3c h\u1ED7 tr\u1EE3",attachmentTooLarge:"T\u1EC7p qu\xE1 l\u1EDBn",recordingUnsupported:"Tr\xECnh duy\u1EC7t kh\xF4ng h\u1ED7 tr\u1EE3 ghi \xE2m",micPermissionDenied:"Kh\xF4ng th\u1EC3 truy c\u1EADp micro",recordingCapReached:"\u0110\xE3 \u0111\u1EA1t gi\u1EDBi h\u1EA1n 60 gi\xE2y",attachmentStatusUploading:"\u0110ang t\u1EA3i l\xEAn\u2026",attachmentStatusReady:"S\u1EB5n s\xE0ng",attachmentStatusError:"T\u1EA3i l\xEAn th\u1EA5t b\u1EA1i",attachmentRemove:"X\xF3a"}};function x(g){return typeof g=="string"&&j.indexOf(g)!==-1}function p(g,e){return T[g][e]}function L(g,e=[]){if(!g)return{content:g,references:[]};let t=[],i=new Set,n=new Map;for(let a of e)a.type!=="url"||typeof a.url!="string"||!/^https?:\/\//.test(a.url)||n.has(a.url)||n.set(a.url,a);let s=a=>{if(i.has(a))return;i.add(a);let r=n.get(a);t.push({title:r?.title?.trim()||a,url:a})};return{content:g.replace(/\[([^\]]+)\]\((#source-(\d+)|https?:\/\/[^\s)]+)\)/g,(a,r,l,c)=>{if(c){let m=Number(c)-1,d=e[m];return d&&d.type==="url"&&d.url&&/^https?:\/\//.test(d.url)&&s(d.url),r}return n.has(l)?(s(l),r):a}),references:t}}var f={agentId:["agentId","agent_id"],apiBase:["apiBase","api_base"],themeColor:["themeColor","theme_color"],welcomeMessage:["welcomeMessage","welcome_message"],language:["language","locale"],position:["position"],theme:["theme"],widgetLocale:["widget_locale","widgetLocale"]};function M(g){if(!g)return"/basjoo-logo.png";try{return new URL("/basjoo-logo.png",`${g}/`).toString()}catch{return"/basjoo-logo.png"}}var k=class{constructor(){this.memoryStore=new Map;this.storageAvailable=null}isAvailable(){if(this.storageAvailable!==null)return this.storageAvailable;try{let e="__storage_test__";return window.localStorage.setItem(e,"test"),window.localStorage.removeItem(e),this.storageAvailable=!0,!0}catch{return this.storageAvailable=!1,!1}}getItem(e){if(this.isAvailable())try{return window.localStorage.getItem(e)}catch{}return this.memoryStore.get(e)??null}setItem(e,t){if(this.isAvailable())try{window.localStorage.setItem(e,t);return}catch{}this.memoryStore.set(e,t)}removeItem(e){if(this.isAvailable())try{window.localStorage.removeItem(e);return}catch{}this.memoryStore.delete(e)}},y=class{constructor(e){this.container=null;this.button=null;this.unreadBadge=null;this.chatWindow=null;this.messages=[];this.sessionId=null;this.isOpen=!1;this.VISITOR_STORAGE_KEY="basjoo_visitor_id";this.effectiveTheme="light";this.originalTitle="";this.titleBlinkInterval=null;this.hasUnread=!1;this.pollIntervalId=null;this.lastMessageId=0;this.isSending=!1;this.streamAbortController=null;this.streamingMessage=null;this.streamingMessageContent=null;this.thinkingIndicator=null;this.thinkingIndicatorText=null;this.thinkingElapsed=0;this.thinkingTimerId=null;this.currentStreamContent="";this.currentStreamSources=[];this._buttonClickListener=null;this._closeBtnClickListener=null;this._sendBtnClickListener=null;this._inputKeypressListener=null;this.widgetLocale=S;this._localeChangeListener=null;this.pendingAttachments=[];this.attachmentsStripEl=null;this.attachBtnEl=null;this.micBtnEl=null;this.fileInputEl=null;this._attachBtnClickListener=null;this._micBtnPressListener=null;this._micBtnReleaseListener=null;this._fileInputChangeListener=null;this.mediaRecorder=null;this.mediaStream=null;this.recordingStartedAt=0;this.recordingMaxTimerId=null;this.recordingState="idle";let t=this.detectApiBase(e.apiBase);this.hasTitleOverride=typeof e.title=="string"&&e.title.trim().length>0,this.hasWelcomeMessageOverride=typeof e.welcomeMessage=="string"&&e.welcomeMessage.trim().length>0,this.config={agentId:e.agentId,apiBase:t,themeColor:e.themeColor||"",logoUrl:e.logoUrl||M(t),title:e.title||"AI\u52A9\u624B",welcomeMessage:e.welcomeMessage||"\u4F60\u597D\uFF01\u6709\u4EC0\u4E48\u53EF\u4EE5\u5E2E\u52A9\u60A8\u7684\u5417\uFF1F",language:e.language||"auto",position:e.position||"right",theme:e.theme||"auto"},this.STORAGE_KEY=`basjoo_session_${this.config.agentId}`,this.storage=new k,this.sessionId=this.storage.getItem(this.STORAGE_KEY),this.visitorId=this.storage.getItem(this.VISITOR_STORAGE_KEY)||this.generateVisitorId(),this.effectiveTheme=this.getEffectiveTheme();let i=this.storage.getItem(v);this.widgetLocale=x(i)?i:S}generateVisitorId(){let e=`visitor_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,11)}`;return this.storage.setItem(this.VISITOR_STORAGE_KEY,e),e}detectApiBase(e){if(e)try{let s=new URL(e,window.location.href);if((s.protocol==="http:"||s.protocol==="https:")&&s.port==="3000"){let o=`${s.protocol}//${s.hostname}:8000`;return console.info("[Basjoo Widget] Rewriting configured dev apiBase to direct backend:",o),o}return s.toString().replace(/\/$/,"")}catch{return e}let t=document.currentScript;if(t instanceof HTMLScriptElement&&t.src)try{let s=new URL(t.src,window.location.href);return console.info("[Basjoo Widget] Detected API base from current script:",s.origin),s.origin}catch{}let i=document.querySelectorAll("script[src]");for(let s of i){let o=s.getAttribute("src")||"";if(!(!o.includes("sdk.js")&&!o.includes("basjoo")))try{let a=new URL(o,window.location.href);return console.info("[Basjoo Widget] Detected API base from script src:",a.origin),a.origin}catch{}}let n=window.location.port;if(n==="3000"||n==="5173"){let s=`${window.location.protocol}//${window.location.hostname}:8000`;return console.info("[Basjoo Widget] Development mode detected, using:",s),s}return window.location.protocol==="file:"?(console.error("[Basjoo Widget] Cannot determine API base from a local file. Please set apiBase explicitly."),""):(console.warn("[Basjoo Widget] Falling back to window.location.origin. Set apiBase explicitly if the API is hosted elsewhere."),window.location.origin)}getEffectiveTheme(){return this.config.theme==="light"||this.config.theme==="dark"?this.config.theme:typeof window<"u"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}async loadPublicConfig(){if(!this.config.apiBase){console.warn("[Basjoo Widget] Skipping public config fetch because apiBase could not be determined.");return}try{let e=new URL(`${this.config.apiBase}/api/v1/config:public`);this.config.agentId&&e.searchParams.set("agent_id",this.config.agentId);let t=await fetch(e.toString());if(!t.ok)throw new Error(`HTTP ${t.status}: ${t.statusText}`);let i=await t.json();!this.config.agentId&&i.default_agent_id&&(this.config.agentId=i.default_agent_id),this.config.themeColor=this.config.themeColor||i.widget_color||"#3B82F6",this.hasTitleOverride||(this.config.title=i.widget_title||"AI\u52A9\u624B"),this.hasWelcomeMessageOverride||(this.config.welcomeMessage=i.welcome_message||"\u4F60\u597D\uFF01\u6709\u4EC0\u4E48\u53EF\u4EE5\u5E2E\u52A9\u60A8\u7684\u5417\uFF1F"),this.effectiveTheme=this.getEffectiveTheme()}catch(e){console.warn("[Basjoo Widget] Failed to load public config, using defaults.",e),e instanceof TypeError&&console.warn("[Basjoo Widget] Public config request may be blocked by CORS, network issues, or an incorrect apiBase:",this.config.apiBase)}}async init(){if(!document.body){console.warn("[Basjoo Widget] document.body is not available yet. Call init() after DOMContentLoaded or place the embed code near the end of <body>.");return}if(document.getElementById("basjoo-widget-container")){console.warn("[Basjoo Widget] Initialization skipped because #basjoo-widget-container already exists. Avoid loading or initializing the widget twice on the same page.");return}if(await this.loadPublicConfig(),this.originalTitle=document.title,this.createStyles(),this.createContainer(),this.createButton(),this.createChatWindow(),this.showGreetingBubble(),this.startTitleBlink(),this.sessionId){this.loadHistory();return}this.config.welcomeMessage&&this.addMessage({role:"assistant",content:this.config.welcomeMessage,timestamp:new Date})}showGreetingBubble(){if(!this.button)return;let e=document.createElement("div");e.className="basjoo-greeting-bubble",e.textContent=this.getText("greetingBubble");let t=this.config.position;e.style.position="fixed",e.style.bottom="100px",e.style[t]="24px",e.style.zIndex="9999",document.body.appendChild(e),setTimeout(()=>{e.remove()},5e3)}async loadHistory(){if(this.sessionId){try{let e=await fetch(`${this.config.apiBase}/api/v1/chat/messages?session_id=${encodeURIComponent(this.sessionId)}`);if(!e.ok)throw new Error("Failed to load history");let t=await e.json();if(t&&t.length>0){for(let i of t)this.addMessage({role:i.role==="user"?"user":"assistant",content:i.content,sources:i.sources,timestamp:new Date,attachments:(i.attachments||[]).map(n=>({id:n.id,kind:n.kind,mime_type:n.mime_type,filename:n.filename,size_bytes:n.size_bytes,url:n.url,status:"uploaded",preview_url:"",duration_ms:n.duration_ms??void 0}))}),i.id>this.lastMessageId&&(this.lastMessageId=i.id);this.startPolling();return}}catch{}this.sessionId=null,this.storage.removeItem(this.STORAGE_KEY),this.config.welcomeMessage&&this.addMessage({role:"assistant",content:this.config.welcomeMessage,timestamp:new Date})}}startTitleBlink(){if(this.titleBlinkInterval)return;this.hasUnread=!0,this.updateUnreadBadge();let e=!0;this.titleBlinkInterval=window.setInterval(()=>{document.title=e?this.originalTitle:"\u2757 "+this.getText("newMessage"),e=!e},1e3)}stopTitleBlink(){this.titleBlinkInterval&&(clearInterval(this.titleBlinkInterval),this.titleBlinkInterval=null),document.title=this.originalTitle,this.hasUnread=!1,this.updateUnreadBadge()}createStyles(){let e=document.createElement("style");e.id="basjoo-widget-styles";let t=this.effectiveTheme==="dark",i=t?"#1a1a2e":"white",n=t?"#e2e8f0":"#1f2937",s=t?"#94a3b8":"#6b7280",o=t?"rgba(148, 163, 184, 0.2)":"#e5e7eb",a=t?"#0f0f1a":"white",r=t?"#2d2d44":"#f3f4f6",l=t?"rgba(239, 68, 68, 0.2)":"#fef2f2";e.textContent=`
      #basjoo-widget-container, #basjoo-widget-container * {
        box-sizing: border-box;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      }

      #basjoo-widget-button {
        position: fixed;
        bottom: 24px;
        ${this.config.position==="left"?"left":"right"}: 24px;
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
        color: ${n};
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
        ${this.config.position==="left"?"left":"right"}: 30px;
        width: 12px;
        height: 12px;
        background: white;
        transform: rotate(45deg);
        border-bottom: 1px solid ${o};
        border-right: 1px solid ${o};
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
        ${this.config.position==="left"?"left":"right"}: 24px;
        width: 380px;
        height: 600px;
        max-height: calc(100vh - 120px);
        background: ${i};
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transform: scale(0);
        transform-origin: ${this.config.position==="left"?"bottom left":"bottom right"};
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
        background: linear-gradient(135deg, ${this.config.themeColor} 0%, ${this.adjustColor(this.config.themeColor,-20)} 100%);
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
        background: ${a};
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
        color: ${this.adjustColor(this.config.themeColor,-10)};
        text-decoration: underline;
      }

      #basjoo-widget-container .basjoo-message-content blockquote {
        padding-left: 12px;
        border-left: 3px solid rgba(148, 163, 184, 0.4);
        color: ${s};
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
        background: ${r};
        color: ${n};
        border-bottom-left-radius: 4px;
      }

      #basjoo-widget-container .basjoo-message-error .basjoo-message-content {
        background: ${l};
        color: ${t?"#fca5a5":"#dc2626"};
        border: 1px solid ${t?"rgba(239,68,68,0.35)":"#fecaca"};
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
        background: ${s};
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
        border-top: 1px solid ${o};
        display: flex;
        gap: 12px;
        background: ${i};
        flex-shrink: 0;
      }

      .basjoo-input {
        flex: 1;
        height: 48px;
        padding: 0 20px 0 20px !important;
        border: 1px solid ${o};
        border-radius: 24px;
        font-size: 14px;
        outline: none;
        transition: all 0.2s;
        background: ${a};
        color: ${n};
        margin-bottom: 8px !important;
        margin-left: 4px !important;
      }

      .basjoo-input::placeholder {
        color: ${s};
      }

      .basjoo-input:focus {
        border-color: ${this.config.themeColor};
        box-shadow: 0 0 0 3px ${this.hexToRgba(this.config.themeColor,.1)};
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
        box-shadow: 0 4px 12px ${this.hexToRgba(this.config.themeColor,.3)};
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
        background: ${l};
        color: ${t?"#fca5a5":"#dc2626"};
        font-size: 13px;
        text-align: center;
        border-top: 1px solid ${t?"rgba(239,68,68,0.35)":"#fecaca"};
      }

      #basjoo-widget-container .basjoo-message-time {
        font-size: 11px;
        color: ${s};
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
        color: ${s};
        font-size: 12px;
        margin-top: 8px;
      }

      .basjoo-thinking-spinner {
        width: 12px;
        height: 12px;
        border: 2px solid ${this.hexToRgba(this.config.themeColor,.2)};
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
        background: ${i};
        color: ${n};
      }

      /* PR14: input bar wrapper */
      .basjoo-input-bar { display: flex; flex-direction: column; flex-shrink: 0; background: ${i}; }
      .basjoo-attachments-strip {
        display: flex; flex-wrap: wrap; gap: 8px;
        padding: 10px 20px 0 20px;
        border-top: 1px solid ${o}; background: ${a};
        max-height: 140px; overflow-y: auto;
      }
      .basjoo-attachment-chip {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 4px 8px 4px 4px; background: ${r};
        border: 1px solid ${o}; border-radius: 18px;
        font-size: 12px; color: ${n}; max-width: 220px;
      }
      .basjoo-attachment-chip .basjoo-attachment-thumb { width: 28px; height: 28px; object-fit: cover; border-radius: 14px; flex-shrink: 0; }
      .basjoo-attachment-chip audio { height: 28px; max-width: 140px; }
      .basjoo-attachment-chip .basjoo-attachment-chip-meta { display: flex; flex-direction: column; min-width: 0; }
      .basjoo-attachment-chip .basjoo-attachment-chip-filename { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 130px; }
      .basjoo-attachment-chip .basjoo-attachment-chip-status { font-size: 10px; color: ${s}; }
      .basjoo-attachment-chip .basjoo-attachment-chip-status[data-status="error"] { color: #ef4444; }
      .basjoo-attachment-chip .basjoo-attachment-chip-remove { border: 0; background: transparent; color: ${s}; cursor: pointer; padding: 0 4px; font-size: 14px; line-height: 1; }
      .basjoo-attachment-chip .basjoo-attachment-chip-remove:hover { color: #ef4444; }
      .basjoo-attach, .basjoo-mic {
        width: 40px; height: 40px; border: 1px solid ${o}; border-radius: 50%;
        background: transparent; color: ${s}; cursor: pointer;
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
          ${this.config.position==="left"?"left":"right"}: 16px;
        }
      }
    `,document.head.appendChild(e)}adjustColor(e,t){let i=!1,n=e;n[0]==="#"&&(n=n.slice(1),i=!0);let s=parseInt(n,16),o=(s>>16)+t,a=(s>>8&255)+t,r=(s&255)+t;return o=Math.max(0,Math.min(255,o)),a=Math.max(0,Math.min(255,a)),r=Math.max(0,Math.min(255,r)),`${i?"#":""}${(o<<16|a<<8|r).toString(16).padStart(6,"0")}`}hexToRgba(e,t){let i=e.replace("#","");if(i.length===3){let[r,l,c]=i.split("");i=`${r}${r}${l}${l}${c}${c}`}let n=parseInt(i,16),s=n>>16&255,o=n>>8&255,a=n&255;return`rgba(${s}, ${o}, ${a}, ${t})`}updateUnreadBadge(){if(this.button){if(this.hasUnread){if(!this.unreadBadge){let e=document.createElement("span");e.className="basjoo-unread-badge",e.textContent="1",this.button.appendChild(e),this.unreadBadge=e}return}this.unreadBadge?.remove(),this.unreadBadge=null}}createContainer(){this.container=document.createElement("div"),this.container.id="basjoo-widget-container",document.body.appendChild(this.container)}createButton(){this.button=document.createElement("div"),this.button.id="basjoo-widget-button",this.button.innerHTML=`
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
      </svg>
    `,this._buttonClickListener=()=>this.toggle(),this.button.addEventListener("click",this._buttonClickListener),this.container.appendChild(this.button),this.updateUnreadBadge()}createChatWindow(){this.chatWindow=document.createElement("div"),this.chatWindow.id="basjoo-chat-window";let e=this.config.logoUrl?this.sanitizeUrlAttribute(this.config.logoUrl):"",t=this.escapeHtml(this.config.title),i=this.escapeHtml(this.getText("inputPlaceholder"));this.chatWindow.innerHTML=`
      <div class="basjoo-header">
        <div class="basjoo-header-title">
          ${e?`<img src="${e}" class="basjoo-header-logo" alt="">`:""}
          <span>${t}</span>
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
          <button type="button" class="basjoo-attach" aria-label="${p(this.widgetLocale,"attachImage")}" title="${p(this.widgetLocale,"attachImageTitle")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </button>
          <button type="button" class="basjoo-mic" aria-label="${p(this.widgetLocale,"recordAudio")}" title="${p(this.widgetLocale,"recordAudioTitle")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="3" width="6" height="12" rx="3" />
              <path d="M5 11a7 7 0 0 0 14 0" />
              <line x1="12" y1="18" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </svg>
          </button>
          <input type="text" class="basjoo-input" placeholder="${i}" maxlength="2000">
          <button class="basjoo-send">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
      <input type="file" class="basjoo-hidden-file-input" accept="image/jpeg,image/png,image/webp" hidden>
    `;let n=this.chatWindow.querySelector(".basjoo-close");this._closeBtnClickListener=()=>this.close(),n.addEventListener("click",this._closeBtnClickListener);let s=this.chatWindow.querySelector(".basjoo-input"),o=this.chatWindow.querySelector(".basjoo-send");this._sendBtnClickListener=()=>{if(this.isSending)return;let d=s.value.trim();if(d){if(d.length>2e3){this.showError(this.getText("messageTooLong"));return}this.sendMessage(d),s.value=""}},o.addEventListener("click",this._sendBtnClickListener),this._inputKeypressListener=d=>{d.key==="Enter"&&this._sendBtnClickListener?.()},s.addEventListener("keypress",this._inputKeypressListener),this.attachmentsStripEl=this.chatWindow.querySelector(".basjoo-attachments-strip"),this.attachBtnEl=this.chatWindow.querySelector(".basjoo-attach"),this.micBtnEl=this.chatWindow.querySelector(".basjoo-mic"),this.fileInputEl=this.chatWindow.querySelector(".basjoo-hidden-file-input"),this._attachBtnClickListener=()=>this.fileInputEl?.click(),this.attachBtnEl.addEventListener("click",this._attachBtnClickListener),this._fileInputChangeListener=d=>{let h=d.target;if(h.files){for(let u of Array.from(h.files))this._addPendingAttachment(u);h.value=""}},this.fileInputEl.addEventListener("change",this._fileInputChangeListener),this._micBtnPressListener=d=>{d.preventDefault(),this._startRecording()},this._micBtnReleaseListener=d=>{d.preventDefault(),this.recordingState==="recording"&&this._stopRecording()},this.micBtnEl.addEventListener("pointerdown",this._micBtnPressListener),this.micBtnEl.addEventListener("pointerup",this._micBtnReleaseListener),this.micBtnEl.addEventListener("pointercancel",this._micBtnReleaseListener),this.micBtnEl.addEventListener("pointerleave",this._micBtnReleaseListener);let a=this.chatWindow.querySelector(".basjoo-header"),r=a.querySelector(".basjoo-close"),l=document.createElement("select");l.className="basjoo-language-selector",l.setAttribute("data-basjoo-locale-select",""),l.setAttribute("aria-label",p(this.widgetLocale,"languageSelectorLabel"));for(let d of j){let h=document.createElement("option");h.value=d,h.textContent=p(this.widgetLocale,d==="zh-CN"?"optionZh":d==="en-US"?"optionEn":"optionVi"),d===this.widgetLocale&&(h.selected=!0),l.appendChild(h)}this._localeChangeListener=()=>this.setWidgetLocale(l.value),l.addEventListener("change",this._localeChangeListener);let c=document.createElement("label");c.className="basjoo-language-selector-wrap";let m=document.createElement("span");m.className="basjoo-sr-only",m.textContent=p(this.widgetLocale,"languageSelectorLabel"),c.appendChild(m),c.appendChild(l),a.insertBefore(c,r),this.container.appendChild(this.chatWindow)}toggle(){if(this.isOpen){this.close();return}this.open()}open(){this.isOpen=!0,this.chatWindow?.classList.remove("closing"),this.chatWindow?.classList.add("open"),this.stopTitleBlink(),this.updateUnreadBadge();let e=this.chatWindow?.querySelector(".basjoo-input");setTimeout(()=>{e?.focus()},300)}close(){this.isOpen=!1,this.chatWindow?.classList.remove("open"),this.chatWindow?.classList.add("closing")}getRequestLocale(){return this.config.language&&this.config.language!=="auto"?this.config.language:navigator.language||"en-US"}getText(e){return p(this.widgetLocale,e)}setWidgetLocale(e){if(!(!x(e)||e===this.widgetLocale)){this.widgetLocale=e;try{this.storage.setItem(v,e)}catch{}this.applyWidgetLocale()}}applyWidgetLocale(){if(!this.chatWindow)return;let e=this.chatWindow.querySelector(".basjoo-input");e&&(e.placeholder=p(this.widgetLocale,"inputPlaceholder"));let t=this.chatWindow.querySelector("[data-basjoo-locale-select]");t&&t.setAttribute("aria-label",p(this.widgetLocale,"languageSelectorLabel"));let i=this.chatWindow.querySelector(".basjoo-language-selector-wrap .basjoo-sr-only");i&&(i.textContent=p(this.widgetLocale,"languageSelectorLabel"));let n=document.querySelector(".basjoo-greeting-bubble");n&&(n.textContent=p(this.widgetLocale,"greetingBubble")),this.attachmentsStripEl&&this.renderPendingStrip()}_addPendingAttachment(e){if(!new Set(["image/jpeg","image/png","image/webp"]).has(e.type)){this.showError(this.getText("attachmentUnsupported"));return}if(e.size>5*1024*1024){this.showError(this.getText("attachmentTooLarge"));return}let i=typeof crypto<"u"&&typeof crypto.randomUUID=="function"?crypto.randomUUID():"c_"+Math.random().toString(36).slice(2),n=URL.createObjectURL(e);this.pendingAttachments.push({clientId:i,kind:"image",mimeType:e.type,filename:e.name||"image",size:e.size,file:e,previewUrl:n,status:"pending",attachmentId:"",serverUrl:"",errorMessage:""}),this.renderPendingStrip()}_removePendingAttachment(e){let t=this.pendingAttachments.findIndex(n=>n.clientId===e);if(t===-1)return;let i=this.pendingAttachments[t];i.previewUrl&&URL.revokeObjectURL(i.previewUrl),this.pendingAttachments.splice(t,1),this.renderPendingStrip()}renderPendingStrip(){if(this.attachmentsStripEl){if(this.attachmentsStripEl.innerHTML="",this.pendingAttachments.length===0){this.attachmentsStripEl.hidden=!0;return}this.attachmentsStripEl.hidden=!1;for(let e of this.pendingAttachments){let t=document.createElement("div");t.className="basjoo-attachment-chip basjoo-attachment-chip--"+e.status,t.setAttribute("data-client-id",e.clientId);let i=this.sanitizeUrlAttribute(e.previewUrl||e.serverUrl);if(e.kind==="image"&&i){let r=document.createElement("img");r.className="basjoo-attachment-thumb",r.src=i,r.alt=e.filename,t.appendChild(r)}else{let r=document.createElement("span");r.className="basjoo-attachment-kind-dot",r.textContent="\u266A",t.appendChild(r)}let n=document.createElement("span");n.className="basjoo-attachment-chip-meta";let s=document.createElement("span");s.className="basjoo-attachment-chip-filename",s.textContent=e.filename,n.appendChild(s);let o=document.createElement("span");if(o.className="basjoo-attachment-chip-status",o.setAttribute("data-status",e.status),o.textContent=e.status==="uploading"?this.getText("attachmentStatusUploading"):e.status==="uploaded"?this.getText("attachmentStatusReady"):e.status==="error"?e.errorMessage||this.getText("attachmentStatusError"):"",n.appendChild(o),t.appendChild(n),e.status==="uploaded"&&e.serverUrl){let r=document.createElement("audio");r.controls=!0,r.preload="metadata",r.src=this.sanitizeUrlAttribute(e.serverUrl),r.className="basjoo-attachment-audio",t.appendChild(r)}let a=document.createElement("button");a.type="button",a.className="basjoo-attachment-chip-remove",a.setAttribute("aria-label",this.getText("attachmentRemove")),a.textContent="\xD7",a.addEventListener("click",()=>this._removePendingAttachment(e.clientId)),t.appendChild(a),this.attachmentsStripEl.appendChild(t)}}}async uploadPendingAttachments(){let e=[];for(let t of this.pendingAttachments){if(t.status==="uploaded"&&t.attachmentId){e.push(t.attachmentId);continue}t.status="uploading",t.errorMessage="",this.renderPendingStrip();let i=new FormData;if(t.file)i.append("file",t.file,t.filename);else if(t.chunks&&t.chunks.length){let n=new Blob(t.chunks,{type:t.mimeType});i.append("file",n,t.filename)}i.append("agent_id",this.config.agentId),i.append("session_id",this.sessionId||""),i.append("visitor_id",this.visitorId),t.durationMs&&i.append("duration_ms",String(t.durationMs));try{let n=await fetch(`${this.config.apiBase}/api/v1/chat/attachments`,{method:"POST",body:i,signal:this.streamAbortController?.signal});if(!n.ok)t.status="error",t.errorMessage=`HTTP ${n.status}`,e.push("");else{let s=await n.json(),o=s&&s.attachment;o&&typeof o.id=="string"?(t.attachmentId=o.id,t.serverUrl=o.url||"",t.status="uploaded",e.push(o.id)):(t.status="error",t.errorMessage="malformed response",e.push(""))}}catch(n){t.status="error",t.errorMessage=n?.message||"upload failed",e.push("")}this.renderPendingStrip()}return e}_clearSuccessfulPending(){this.pendingAttachments=this.pendingAttachments.filter(e=>e.status==="uploaded"?(e.previewUrl&&URL.revokeObjectURL(e.previewUrl),!1):!0),this.renderPendingStrip()}async _startRecording(){if(this.recordingState==="recording")return;if(typeof navigator>"u"||!navigator.mediaDevices||typeof navigator.mediaDevices.getUserMedia!="function"||typeof window>"u"||typeof window.MediaRecorder>"u"){this.showError(this.getText("recordingUnsupported"));return}let e;try{e=await navigator.mediaDevices.getUserMedia({audio:!0})}catch{this.showError(this.getText("micPermissionDenied"));return}this.mediaStream=e;let i=["audio/webm;codecs=opus","audio/webm","audio/ogg;codecs=opus","audio/mp4"].find(a=>window.MediaRecorder.isTypeSupported(a))||"",n=[],s=i?new window.MediaRecorder(e,{mimeType:i}):new window.MediaRecorder(e);s.ondataavailable=a=>{a.data&&a.data.size>0&&n.push(a.data)};let o=new Promise(a=>{s.onstop=()=>a()});this.mediaRecorder=s,this.recordingStartedAt=Date.now(),this.recordingState="recording",this.micBtnEl?.classList.add("basjoo-mic--recording"),this.recordingMaxTimerId=window.setTimeout(()=>void this._stopRecording(!0),6e4);try{s.start(250)}catch{this.mediaStream?.getTracks().forEach(a=>a.stop()),this.mediaStream=null,this.mediaRecorder=null,this.recordingState="idle",this.micBtnEl?.classList.remove("basjoo-mic--recording"),this.showError(this.getText("micPermissionDenied"));return}s._chunks=n,s._stopWaiter=o}async _stopRecording(e=!1){if(this.recordingState!=="recording")return;let t=this.mediaRecorder,i=this.mediaStream;if(this.recordingMaxTimerId!==null&&(window.clearTimeout(this.recordingMaxTimerId),this.recordingMaxTimerId=null),this.recordingState="idle",this.micBtnEl?.classList.remove("basjoo-mic--recording"),!t)return;try{try{t.requestData()}catch{}let c=t._stopWaiter;try{t.stop()}catch{}c&&await c}finally{i?.getTracks().forEach(c=>c.stop()),this.mediaStream=null,this.mediaRecorder=null}let n=t._chunks||[];if(n.length===0){e&&this.showError(this.getText("recordingCapReached"));return}let s=t.mimeType||"audio/webm",o=this.recordingStartedAt||Date.now(),a=s.includes("mp4")?"m4a":s.includes("ogg")?"ogg":"webm",r=`recording-${o}.${a}`,l=typeof crypto<"u"&&typeof crypto.randomUUID=="function"?crypto.randomUUID():"c_"+Math.random().toString(36).slice(2);this.pendingAttachments.push({clientId:l,kind:"audio",mimeType:s,filename:r,size:n.reduce((c,m)=>c+m.size,0),chunks:n,previewUrl:"",status:"pending",attachmentId:"",serverUrl:"",errorMessage:"",durationMs:Date.now()-o}),this.renderPendingStrip(),e&&this.showError(this.getText("recordingCapReached"))}_rerenderLastUserMessage(){let e=this.chatWindow?.querySelector(".basjoo-messages");if(!e)return;let t=Array.from(e.querySelectorAll(".basjoo-message-user")).pop();if(!t)return;let i=this.messages.length-1,n=this.messages[i];if(!n)return;let s=this.createMessageElement(n);t.replaceWith(s),e.scrollTop=e.scrollHeight}escapeHtml(e){return e.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}sanitizeUrlAttribute(e){try{let t=new URL(e);if(t.protocol==="http:"||t.protocol==="https:"||t.protocol==="blob:")return this.escapeHtml(e)}catch{}return""}renderMarkdown(e){if(!e)return"";let t=e.replace(/\r\n/g,`
`).split(/\n{2,}/).map(s=>s.trim()).filter(Boolean),i=s=>{let o=this.escapeHtml(s);return o=o.replace(/`([^`]+)`/g,"<code>$1</code>"),o=o.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>"),o=o.replace(/__([^_]+)__/g,"<strong>$1</strong>"),o=o.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g,"$1<em>$2</em>"),o=o.replace(/(^|[^_])_([^_]+)_(?!_)/g,"$1<em>$2</em>"),o=o.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(a,r,l)=>{let c=r,m=this.sanitizeUrlAttribute(l);return m?`<a href="${m}" target="_blank" rel="noopener noreferrer">${c}</a>`:c}),o};return t.map(s=>{if(/^```/.test(s)&&/```$/.test(s)){let o=s.replace(/^```\w*\n?/,"").replace(/```$/,"");return`<pre><code>${this.escapeHtml(o)}</code></pre>`}if(/^(?:[-*]\s.+\n?)+$/.test(s))return`<ul>${s.split(`
`).map(a=>a.replace(/^[-*]\s+/,"").trim()).filter(Boolean).map(a=>`<li>${i(a)}</li>`).join("")}</ul>`;if(/^(?:\d+\.\s.+\n?)+$/.test(s))return`<ol>${s.split(`
`).map(a=>a.replace(/^\d+\.\s+/,"").trim()).filter(Boolean).map(a=>`<li>${i(a)}</li>`).join("")}</ol>`;if(/^>\s?/.test(s)){let o=s.split(`
`).map(a=>a.replace(/^>\s?/,"")).join("<br>");return`<blockquote>${i(o)}</blockquote>`}if(/^#{1,6}\s/.test(s)){let o=s.replace(/^#{1,6}\s+/,"");return`<p><strong>${i(o)}</strong></p>`}return`<p>${i(s).replace(/\n/g,"<br>")}</p>`}).join("")}updateMessageContent(e,t,i=!1){e.innerHTML=this.renderMarkdown(t)+(i?'<span class="basjoo-stream-cursor"></span>':"")}createMessageElement(e){let t=document.createElement("div");t.className=`basjoo-message basjoo-message-${e.role}`;let i=document.createElement("div");if(i.className="basjoo-message-content",e.role==="assistant"){let s=L(e.content,e.sources),o=s.references.length>0?`

**${this.getText("references")}**
${s.references.map(a=>`- [${a.title}](${a.url})`).join(`
`)}`:"";this.updateMessageContent(i,s.content+o)}else this.updateMessageContent(i,e.content);if(t.appendChild(i),e.attachments&&e.attachments.length>0&&e.role==="user"){let s=document.createElement("div");s.className="basjoo-message-attachments";for(let o of e.attachments){let a=this.sanitizeUrlAttribute(o.preview_url||o.url);if(a){if(o.kind==="image"){let r=document.createElement("img");r.className="basjoo-message-attachment-thumb",r.src=a,r.alt=o.filename,s.appendChild(r)}else if(o.kind==="audio"){let r=document.createElement("audio");r.className="basjoo-message-attachment-audio",r.controls=!0,r.preload="metadata",r.src=a,s.appendChild(r)}}}s.children.length>0&&t.appendChild(s)}let n=document.createElement("div");return n.className="basjoo-message-time",n.textContent=e.timestamp.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}),t.appendChild(n),t}formatThinkingText(){return`${this.getText("thinking")} ${this.thinkingElapsed}s`}showThinkingIndicator(e=0){this.hideLoading(),this.currentStreamContent.trim()||(this.streamingMessage?.remove(),this.streamingMessage=null,this.streamingMessageContent=null),this.thinkingElapsed=e;let t=this.chatWindow?.querySelector(".basjoo-messages");if(t){if(!this.thinkingIndicator){let i=document.createElement("div");i.className="basjoo-thinking",i.innerHTML=`
        <span class="basjoo-thinking-spinner"></span>
        <span>${this.getText("thinking")}</span>
      `,t.appendChild(i),this.thinkingIndicator=i,this.thinkingIndicatorText=i.querySelector("span:last-child")}this.thinkingIndicatorText&&(this.thinkingIndicatorText.textContent=this.formatThinkingText()),t.scrollTop=t.scrollHeight,this.thinkingTimerId===null&&(this.thinkingTimerId=window.setInterval(()=>{this.thinkingElapsed+=1,this.thinkingIndicatorText&&(this.thinkingIndicatorText.textContent=this.formatThinkingText())},1e3))}}hideThinkingIndicator(){this.thinkingTimerId!==null&&(window.clearInterval(this.thinkingTimerId),this.thinkingTimerId=null),this.thinkingIndicator?.remove(),this.thinkingIndicator=null,this.thinkingIndicatorText=null,this.thinkingElapsed=0}removeStreamingMessage(){this.streamingMessage?.remove(),this.streamingMessage=null,this.streamingMessageContent=null,this.currentStreamContent="",this.currentStreamSources=[]}createStreamingMessage(e=!1){let t=this.chatWindow?.querySelector(".basjoo-messages"),i=document.createElement("div");i.className="basjoo-message basjoo-message-assistant";let n=document.createElement("div");return n.className="basjoo-message-content",this.updateMessageContent(n,this.currentStreamContent,e),i.appendChild(n),t?(t.appendChild(i),t.scrollTop=t.scrollHeight,this.streamingMessage=i,this.streamingMessageContent=n,this.currentStreamContent="",i):(this.streamingMessage=i,this.streamingMessageContent=n,this.currentStreamContent="",i)}appendToStreamingMessage(e){(!this.streamingMessage||!this.streamingMessageContent)&&(this.hideThinkingIndicator(),this.createStreamingMessage()),this.currentStreamContent+=e,this.streamingMessageContent&&this.updateMessageContent(this.streamingMessageContent,this.currentStreamContent,!0);let t=this.chatWindow?.querySelector(".basjoo-messages");t&&(t.scrollTop=t.scrollHeight)}finalizeStreamingMessage(e=[]){if(!this.streamingMessage||!this.streamingMessageContent)return;if(!this.currentStreamContent.trim()){this.removeStreamingMessage();return}this.streamingMessage.querySelector(".basjoo-stream-cursor")?.remove(),this.currentStreamSources=e;let i=L(this.currentStreamContent,e),n=i.references.length>0?`

**${this.getText("references")}**
${i.references.map(a=>`- [${a.title}](${a.url})`).join(`
`)}`:"",s=i.content+n;this.updateMessageContent(this.streamingMessageContent,s),this.messages.push({role:"assistant",content:s,sources:e,timestamp:new Date});let o=this.chatWindow?.querySelector(".basjoo-messages");o.scrollTop=o.scrollHeight,this.streamingMessage=null,this.streamingMessageContent=null,this.currentStreamContent="",this.currentStreamSources=[]}addMessage(e){this.messages.push(e);let t=this.chatWindow?.querySelector(".basjoo-messages");if(!e.content){console.error("Message content is null or undefined:",e);return}if(!t)return;let i=this.createMessageElement(e);t.appendChild(i),t.scrollTop=t.scrollHeight,e.role==="assistant"&&!this.isOpen&&(this.hasUnread=!0,this.updateUnreadBadge())}showLoading(){let e=this.chatWindow?.querySelector(".basjoo-messages");if(!e)return;let t=document.createElement("div");t.className="basjoo-loading",t.id="basjoo-loading",t.innerHTML=`
      <div class="basjoo-loading-dot"></div>
      <div class="basjoo-loading-dot"></div>
      <div class="basjoo-loading-dot"></div>
    `,e.appendChild(t),e.scrollTop=e.scrollHeight}hideLoading(){this.chatWindow?.querySelector("#basjoo-loading")?.remove()}showError(e){let t=this.chatWindow?.querySelector(".basjoo-messages");if(!t)return;let i=document.createElement("div");i.className="basjoo-error",i.textContent=e,t.appendChild(i),t.scrollTop=t.scrollHeight,setTimeout(()=>i.remove(),5e3)}startPolling(){this.pollIntervalId||(this.pollIntervalId=window.setInterval(()=>this.pollMessages(),3e3))}stopPolling(){this.pollIntervalId&&(clearInterval(this.pollIntervalId),this.pollIntervalId=null)}async pollMessages(){if(this.sessionId)try{let e=await fetch(`${this.config.apiBase}/api/v1/chat/messages?session_id=${encodeURIComponent(this.sessionId)}&after_id=${this.lastMessageId}&role=assistant`);if(!e.ok)return;let t=await e.json();for(let i of t)i.content&&(this.addMessage({role:i.role==="user"?"user":"assistant",content:i.content,sources:i.sources,timestamp:new Date,attachments:(i.attachments||[]).map(n=>({id:n.id,kind:n.kind,mime_type:n.mime_type,filename:n.filename,size_bytes:n.size_bytes,url:n.url,status:"uploaded",preview_url:"",duration_ms:n.duration_ms??void 0}))}),this.isOpen||this.startTitleBlink()),i.id>this.lastMessageId&&(this.lastMessageId=i.id)}catch{}}cleanupAfterStreamError(){this.hideLoading(),this.hideThinkingIndicator(),this.removeStreamingMessage()}async consumeStream(e){if(!e.body)throw new Error("Streaming response body is unavailable");let t=e.body.getReader(),i=new TextDecoder,n="",s=!1,o=l=>{if(!l.trim())return;let c="message",m=[];for(let h of l.split(`
`))h.startsWith("event:")?c=h.slice(6).trim():h.startsWith("data:")&&m.push(h.slice(5).trimStart());if(!m.length)return;let d=JSON.parse(m.join(`
`));switch(c){case"sources":this.currentStreamSources=Array.isArray(d.sources)?d.sources:[];break;case"thinking":this.showThinkingIndicator(typeof d.elapsed=="number"?d.elapsed:0);break;case"thinking_done":this.hideThinkingIndicator();break;case"content":{let h=d.content||"";this.appendToStreamingMessage(h);break}case"done":{let h=d;if(h.session_id&&(this.sessionId=h.session_id,this.storage.setItem(this.STORAGE_KEY,h.session_id),this.startPolling()),typeof h.message_id=="number"&&h.message_id>this.lastMessageId&&(this.lastMessageId=h.message_id),Array.isArray(h.attachments)&&h.attachments.length){for(let u of h.attachments){let w=this.pendingAttachments.find(E=>E.attachmentId===u.id);w&&(w.serverUrl=u.url||w.serverUrl,w.status="uploaded")}this.renderPendingStrip()}h.taken_over?(this.removeStreamingMessage(),this.addMessage({role:"assistant",content:this.getText("takenOverNotice"),timestamp:new Date})):(this.finalizeStreamingMessage(this.currentStreamSources),this.isOpen||this.startTitleBlink()),s=!0;break}case"error":{let h=d,u=new Error(h.error||"Stream failed");throw h.code&&(u.name=h.code),u}default:break}},a=()=>{let l=n.indexOf(`\r
\r
`),c=n.indexOf(`

`);return l===-1&&c===-1?null:l===-1?{index:c,length:2}:c===-1?{index:l,length:4}:l<c?{index:l,length:4}:{index:c,length:2}},r=9e4;for(;!s;){if(this.streamAbortController?.signal.aborted){t.cancel();return}let l=null;try{let{done:c,value:m}=await Promise.race([t.read(),new Promise((h,u)=>{l=window.setTimeout(()=>u(new Error("Stream read timeout")),r)})]);n+=i.decode(m||new Uint8Array,{stream:!c});let d=a();for(;d;){let h=n.slice(0,d.index);if(n=n.slice(d.index+d.length),o(h.replace(/\r\n/g,`
`)),s)break;d=a()}if(c)break}finally{l!==null&&window.clearTimeout(l)}}if(!s&&(n.trim()&&o(n),!s))throw new Error("Stream ended unexpectedly")}abortStream(){this.streamAbortController?.abort(),this.streamAbortController=null}async sendMessageWithRetry(e,t=[]){let i=null;for(let n=0;n<=1;n++){this.abortStream(),this.streamAbortController=new AbortController;try{let s=Intl.DateTimeFormat().resolvedOptions().timeZone,o=await fetch(`${this.config.apiBase}/api/v1/chat/stream`,{method:"POST",headers:{"Content-Type":"application/json",Accept:"text/event-stream"},signal:this.streamAbortController.signal,body:JSON.stringify({agent_id:this.config.agentId,message:e,locale:this.getRequestLocale(),widget_locale:this.widgetLocale,attachment_ids:t.filter(Boolean),session_id:this.sessionId||void 0,visitor_id:this.visitorId,timezone:s})});if(!o.ok){let a=`HTTP ${o.status}: ${o.statusText}`;try{let r=await o.json();a=r.message||r.detail||a}catch{}throw new Error(a)}this.hideLoading(),await this.consumeStream(o);return}catch(s){i=s;let o=String(s?.message||"");if(!(!(this.currentStreamContent.trim().length>0)&&(s instanceof TypeError||o.includes("fetch")||o.includes("Failed to fetch")||o.includes("Stream ended unexpectedly")))||n>=1)throw this.cleanupAfterStreamError(),s;this.cleanupAfterStreamError(),console.warn(`[Basjoo Widget] Stream attempt ${n+1} failed, retrying...`),await new Promise(l=>window.setTimeout(l,1e3)),this.showLoading()}}throw i}async sendMessage(e){if(this.isSending)return;this.isSending=!0,this.addMessage({role:"user",content:e,timestamp:new Date,attachments:this.pendingAttachments.map(i=>({id:i.attachmentId,kind:i.kind,mime_type:i.mimeType,filename:i.filename,size_bytes:i.size,url:i.serverUrl,status:i.status==="uploaded"?"uploaded":"pending",preview_url:i.previewUrl,duration_ms:i.durationMs}))}),this.hideLoading(),this.hideThinkingIndicator(),this.removeStreamingMessage(),this.createStreamingMessage(!0);let t=[];try{if(this.pendingAttachments.length>0){t=await this.uploadPendingAttachments();let i=this.messages[this.messages.length-1];i&&(i.attachments=this.pendingAttachments.filter(n=>n.status==="uploaded").map(n=>({id:n.attachmentId,kind:n.kind,mime_type:n.mimeType,filename:n.filename,size_bytes:n.size,url:n.serverUrl,status:"uploaded",preview_url:"",duration_ms:n.durationMs})),this._rerenderLastUserMessage())}await this.sendMessageWithRetry(e,t)}catch(i){console.error("[Basjoo Widget] Error sending message:",i);let n=this.getText("sendFailed"),s="",o=String(i?.message||"");i instanceof TypeError||o.includes("fetch")?(n=this.getText("networkError"),s=`Request may be blocked by CORS, network connectivity, or an incorrect apiBase. Current apiBase: ${this.config.apiBase||"(not set)"}`):o.includes("429")||o.toLowerCase().includes("quota")?n=this.getText("quotaExceeded"):i?.name==="ORIGIN_NOT_ALLOWED"||o.toLowerCase().includes("widget origin not allowed")?(n=this.getText("sendFailed"),s="Widget request was blocked because the current page origin is not on the allowed domain list."):o.includes("401")&&(s="Authentication failed. Please check the agent configuration and public API access."),this.config.apiBase||(s="apiBase could not be determined. When embedding the widget from a local file, set apiBase explicitly or load the SDK from the target server."),s&&console.error("[Basjoo Widget]",s),this.showError(n)}finally{this.isSending=!1}}destroy(){this.stopPolling(),this.stopTitleBlink(),this.hideThinkingIndicator(),this.removeStreamingMessage(),this.abortStream(),this.button&&this._buttonClickListener&&this.button.removeEventListener("click",this._buttonClickListener);let e=this.chatWindow?.querySelector(".basjoo-close");e&&this._closeBtnClickListener&&e.removeEventListener("click",this._closeBtnClickListener);let t=this.chatWindow?.querySelector(".basjoo-send");t&&this._sendBtnClickListener&&t.removeEventListener("click",this._sendBtnClickListener);let i=this.chatWindow?.querySelector(".basjoo-input");if(i&&this._inputKeypressListener&&i.removeEventListener("keypress",this._inputKeypressListener),this.recordingState==="recording"){try{this.mediaRecorder?.stop()}catch{}this.mediaStream?.getTracks().forEach(o=>o.stop()),this.recordingMaxTimerId!==null&&(window.clearTimeout(this.recordingMaxTimerId),this.recordingMaxTimerId=null),this.recordingState="idle",this.mediaRecorder=null,this.mediaStream=null}for(let o of this.pendingAttachments)o.previewUrl&&URL.revokeObjectURL(o.previewUrl);this.pendingAttachments=[],this.attachBtnEl&&this._attachBtnClickListener&&this.attachBtnEl.removeEventListener("click",this._attachBtnClickListener),this.micBtnEl&&this._micBtnPressListener&&(this.micBtnEl.removeEventListener("pointerdown",this._micBtnPressListener),this._micBtnReleaseListener&&(this.micBtnEl.removeEventListener("pointerup",this._micBtnReleaseListener),this.micBtnEl.removeEventListener("pointercancel",this._micBtnReleaseListener),this.micBtnEl.removeEventListener("pointerleave",this._micBtnReleaseListener))),this.fileInputEl&&this._fileInputChangeListener&&this.fileInputEl.removeEventListener("change",this._fileInputChangeListener),this._attachBtnClickListener=null,this._micBtnPressListener=null,this._micBtnReleaseListener=null,this._fileInputChangeListener=null;let n=this.chatWindow?.querySelector("[data-basjoo-locale-select]");n&&this._localeChangeListener&&n.removeEventListener("change",this._localeChangeListener),this._localeChangeListener=null,this.container?.remove(),document.getElementById("basjoo-widget-styles")?.remove()}};window.BasjooWidget=y;function b(g,e){for(let t of e){let i=g.get(t);if(i&&i.trim())return i.trim()}return null}function C(){if(document.currentScript instanceof HTMLScriptElement)return document.currentScript;let g=Array.from(document.querySelectorAll("script[src]"));for(let e=g.length-1;e>=0;e-=1){let t=g[e],i=t.getAttribute("src")||"";if(i.includes("sdk.js"))try{let n=new URL(i,window.location.href);if(b(n.searchParams,f.agentId))return t}catch{continue}}return null}function I(g){let e=g.getAttribute("src")||g.src;if(!e)return null;let t;try{t=new URL(e,window.location.href)}catch{return null}let i=b(t.searchParams,f.agentId);if(!i)return null;let n={agentId:i},s=b(t.searchParams,f.apiBase);s&&(n.apiBase=s);let o=b(t.searchParams,f.themeColor);o&&(n.themeColor=o);let a=b(t.searchParams,f.welcomeMessage);a&&(n.welcomeMessage=a);let r=b(t.searchParams,f.language);r&&(n.language=r);let l=b(t.searchParams,f.position);(l==="left"||l==="right")&&(n.position=l);let c=b(t.searchParams,f.theme);return(c==="light"||c==="dark"||c==="auto")&&(n.theme=c),n}(function(){let e=window,t=C();if(!t)return;let i=I(t);if(!i||e.__basjooWidgetAutoInitScheduled)return;e.__basjooWidgetAutoInitScheduled=!0;try{let s=b(new URL(t.src).searchParams,f.widgetLocale);s&&x(s)&&window.localStorage.setItem(v,s)}catch{}let n=()=>{new y(i).init()};if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",n,{once:!0});return}n()})();})();
//# sourceMappingURL=basjoo-widget.min.js.map
