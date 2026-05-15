const state = {
  currentSessionId: null,
  isDraftChat: true,
  attachedImages: [],
  materials: [],
  reindexMode: "new",
  currentUser: null,
};

const $ = (selector) => document.querySelector(selector);
const messagesEl = $("#messages");
const sessionsListEl = $("#sessionsList");
const materialsListEl = $("#materialsList");
const toolsListEl = $("#toolsList");
const coursesListEl = $("#coursesList");

const sourceCategories = [
  "Пользовательская Инструкция",
  "Web-сайт с информацией",
  "Статья",
  "Книга",
  "Учебные материалы",
  "Курс",
];
const materialStatuses = [
  { value: "indexed", label: "Проиндексирован" },
  { value: "prepared", label: "Подготовлен" },
  { value: "pending", label: "Ожидает индексации" },
  { value: "metadata_only", label: "Только метаданные" },
  { value: "unavailable", label: "Недоступен" },
];
const materialStatusLabels = Object.fromEntries(materialStatuses.map((status) => [status.value, status.label]));
const materialStatusOrder = Object.fromEntries(materialStatuses.map((status, index) => [status.value, index + 1]));

const chatPlaceholders = [
  "Опишите, что не получается со звуком: глухо, резко, не играет MIDI или потерялся эффект",
  "Спросите, где в Ableton Live искать Browser, Mixer, Sends, Automation и Detail View",
  "Напишите ошибку Ableton дословно: помогу понять, что она означает и куда смотреть",
  "Спросите, как записать MIDI, аудио или автоматизацию без хаоса в проекте",
  "Спросите, почему бас пропадает в миксе или синт звучит слишком тонко",
  "Разберем маршрут сигнала: Audio From, Monitor, Track Activator, Solo и Master",
  "Напишите, какой звук Вы хотите собрать: плотный лид, мягкий pad, ударный бас или атмосферный шум",
  "Разберите проблему как в студии: что Вы сделали, что Вы ожидали услышать и что получилось",
  "Попросите объяснить Ableton без магии: клипы, дорожки, эффекты, routing и automation",
  "Где найти Soundgoodizer в Ableton Live?",
  "Загрузите скрин или опишите цепочку эффектов, если звук ведет себя странно",
];
const defaultChatPlaceholder = "Напишите ваш вопрос";
const placeholderState = {
  rotationTimer: null,
  typingTimer: null,
  index: 0,
};

const courses = [
  {
    id: "ableton-start",
    title: "Старт в Ableton Live",
    icon: "panel-top",
    description: "Базовая ориентация в интерфейсе, дорожках, клипах и логике Session/Arrangement View.",
    modules: [
      { id: "interface", status: "done", title: "Интерфейс и рабочие области", type: "обзор", time: "20 мин", task: "Найти Browser, Detail View, дорожки и транспорт." },
      { id: "audio-track", status: "active", title: "Audio track и импорт сэмпла", type: "практика", time: "25 мин", task: "Создать аудиодорожку и загрузить короткий сэмпл." },
      { id: "midi-clip", status: "locked", title: "MIDI-клип и инструмент", type: "практика", time: "30 мин", task: "Создать MIDI-клип и проверить, почему звук может не играть." },
      { id: "self-check", status: "locked", title: "Самопроверка проекта", type: "рефлексия", time: "10 мин", task: "Описать, какие действия изменили звучание." },
    ],
  },
  {
    id: "sound-processing",
    title: "Основы обработки звука",
    icon: "sliders-horizontal",
    description: "Эквализация, фильтры, динамика и пространственная обработка через причинно-следственные связи.",
    modules: [
      { id: "eq-filter", status: "locked", title: "EQ и фильтры", type: "теория + слух", time: "30 мин", task: "Сравнить low-pass, high-pass и bell-filter на одном звуке." },
      { id: "compression", status: "locked", title: "Компрессия без магии", type: "практика", time: "35 мин", task: "Понять threshold, ratio и attack через изменение огибающей." },
      { id: "reverb-delay", status: "locked", title: "Reverb и Delay", type: "практика", time: "30 мин", task: "Отделить ощущение пространства от повторов." },
      { id: "diagnostics", status: "locked", title: "Диагностика ошибок", type: "разбор", time: "20 мин", task: "Сформулировать причину: глухо, мутно, резко, слишком далеко." },
    ],
  },
  {
    id: "mentor-workflow",
    title: "Работа с AI-наставником",
    icon: "brain-circuit",
    description: "Как задавать вопросы агенту, проверять источники и не подменять самостоятельную работу готовыми решениями.",
    modules: [
      { id: "question", status: "done", title: "Хороший учебный вопрос", type: "методика", time: "15 мин", task: "Описать действие, ожидаемый звук и фактический результат." },
      { id: "rag", status: "done", title: "Ответ с источниками", type: "RAG", time: "20 мин", task: "Проверить цитаты и найти исходный материал." },
      { id: "reflection", status: "active", title: "Рефлексия после ответа", type: "рефлексия", time: "15 мин", task: "Сформулировать, что студент проверит сам." },
      { id: "portfolio", status: "locked", title: "Мини-отчет по модулю", type: "портфолио", time: "25 мин", task: "Собрать короткое описание проблемы и решения." },
    ],
  },
];

function refreshIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const IMAGE_NOTE_STRIP_RE = /\s*\n*\s*\[Прикрепленные изображения:[\s\S]*$/;
const IMAGE_NOTE_EXTRACT_RE = /\[Прикрепленные изображения:\s*([\s\S]*?)(?:\]|$)/;

function stripImageNote(text = "") {
  return String(text).replace(IMAGE_NOTE_STRIP_RE, "").trim();
}

function extractImagePaths(text = "") {
  const match = String(text).match(IMAGE_NOTE_EXTRACT_RE);
  if (!match) return [];
  return match[1].split(",").map((p) => p.trim()).filter(Boolean);
}

function imagePathToUrl(path) {
  if (!path) return null;
  const normalized = path.replace(/\\/g, "/");
  if (normalized.startsWith("http://") || normalized.startsWith("https://")) {
    return normalized;
  }
  const idx = normalized.indexOf("uploads/");
  if (idx !== -1) return "/" + normalized.slice(idx);
  const name = normalized.split("/").pop();
  return name ? `/uploads/images/${name}` : null;
}

function formatInlineMarkdown(text = "") {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderAssistantMarkdown(content = "") {
  const lines = String(content).replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let listType = null;

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };

  const openList = (type) => {
    if (listType === type) return;
    closeList();
    listType = type;
    html.push(`<${type}>`);
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      return;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 4);
      html.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`);
      return;
    }

    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      openList("ol");
      html.push(`<li>${formatInlineMarkdown(ordered[1])}</li>`);
      return;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      openList("ul");
      html.push(`<li>${formatInlineMarkdown(unordered[1])}</li>`);
      return;
    }

    closeList();
    html.push(`<p>${formatInlineMarkdown(trimmed)}</p>`);
  });

  closeList();
  return html.join("");
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? options.headers || {} : { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(path, { credentials: "same-origin", headers, ...options });
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    showAuthOverlay();
    throw new Error("Требуется вход в систему.");
  }
  if (!response.ok) {
    let detail = await response.text();
    try {
      detail = JSON.parse(detail).detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function setActiveTab(tabName) {
  document.querySelectorAll(".tab:not(#newSessionBtn)").forEach((item) => item.classList.toggle("active", item.dataset.tab === tabName));
  $("#newSessionBtn").classList.toggle("active", tabName === "chat" && state.isDraftChat);
  document.querySelectorAll(".panel").forEach((item) => item.classList.remove("active-panel"));
  $(`#${tabName}Tab`).classList.add("active-panel");
  localStorage.setItem("activeTab", tabName);
}

function startDraftChat() {
  state.currentSessionId = null;
  state.isDraftChat = true;
  clearAttachedImages();
  localStorage.removeItem("lastSessionId");
  $("#chatTitle").textContent = "Новый диалог";
  renderAttachedImages();
  renderEmptyState();
  setActiveTab("chat");
  loadSessions();
  startChatPlaceholderRotation();
  setTimeout(() => $("#messageInput").focus(), 0);
}

function renderEmptyState() {
  messagesEl.innerHTML = `
    <div class="empty-state">
      <img src="/static/herzen.svg" alt="" />
      <h2>Чем помочь в Ableton Live?</h2>
      <p>Опишите затруднение: интерфейс, MIDI, эффекты, обработка звука или проверка результата.</p>
    </div>
  `;
}

function isKnowledgeWarning(content, kind = "") {
  return kind === "knowledge-warning" || content.startsWith("Пока не нашел достаточно релевантных материалов");
}

function inlineCitations(html, citations) {
  if (!citations.length) return html;
  return html.replace(/\[(\d+)\]/g, (match, n) => {
    const idx = parseInt(n, 10) - 1;
    const c = citations[idx];
    if (!c) return match;
    const tooltip = escapeHtml(c.title) + (c.page_number ? ` · стр. ${c.page_number}` : "");
    return `<sup class="cite-ref"><a href="${escapeHtml(c.url)}" target="_blank" rel="noreferrer" title="${tooltip}">[${n}]</a></sup>`;
  });
}

function renderMessageImages(images) {
  if (!images || !images.length) return "";
  const tiles = images
    .map(
      (img, idx) =>
        `<button type="button" class="message-image-thumb" data-image-index="${idx}" aria-label="Открыть изображение">
          <img src="${escapeHtml(img.url)}" alt="" draggable="false" onerror="this.closest('.message-image-thumb').classList.add('image-broken')" />
        </button>`
    )
    .join("");
  return `<div class="message-images">${tiles}</div>`;
}

function renderMessage(role, content, citations = [], kind = "", images = []) {
  const empty = document.querySelector(".empty-state");
  if (empty) empty.remove();
  const item = document.createElement("article");
  item.className = `message ${role}${isKnowledgeWarning(content, kind) ? " knowledge-warning" : ""}`;
  const imagesHtml = renderMessageImages(images);
  const trimmed = (content || "").trim();
  let bubbleHtml = "";
  if (trimmed || role === "assistant") {
    const bubbleContent = role === "assistant"
      ? inlineCitations(renderAssistantMarkdown(content), citations)
      : escapeHtml(content);
    bubbleHtml = `<div class="message-bubble">${bubbleContent}</div>`;
  }
  item.innerHTML = `${imagesHtml}${bubbleHtml}`;
  if (images && images.length) {
    const urls = images.map((img) => img.url);
    item.querySelectorAll(".message-image-thumb").forEach((thumb, idx) => {
      thumb.addEventListener("click", () => openLightbox(urls, idx));
    });
  }
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function openLightbox(urls, startIndex = 0) {
  if (!urls || !urls.length) return;
  const modal = $("#imageLightbox");
  const img = $("#lightboxImage");
  img.src = urls[startIndex] || "";
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("body-no-scroll");
}

function closeLightbox() {
  const modal = $("#imageLightbox");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  $("#lightboxImage").src = "";
  document.body.classList.remove("body-no-scroll");
}

function bindLightbox() {
  const modal = $("#imageLightbox");
  $("#lightboxCloseBtn").addEventListener("click", closeLightbox);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeLightbox();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("open")) closeLightbox();
  });
}

function renderAssistantLoading() {
  const empty = document.querySelector(".empty-state");
  if (empty) empty.remove();
  const item = document.createElement("article");
  item.className = "message assistant message-loading";
  item.innerHTML = `
    <div class="message-bubble loading-bubble" aria-live="polite">
      <span class="thinking-wave" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span>
      <span class="loading-text">Готовлю ответ с учетом базы знаний</span>
    </div>
  `;
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return item;
}

async function loadHealth() {
  const health = await api("/api/health");
  $("#apiStatus").innerHTML = health.has_api_key
    ? '<span class="status-dot ok"></span>Система работает'
    : '<span class="status-dot bad"></span>API ключ не задан';
}

async function loadSessions() {
  const sessions = await api("/api/sessions");
  sessionsListEl.innerHTML = "";
  sessions.forEach((session) => {
    const item = document.createElement("div");
    item.className = `session-item ${session.id === state.currentSessionId ? "active" : ""}`;
    const cleanTitle = stripImageNote(session.title) || "Прикрепленные файлы";
    item.innerHTML = `
      <div>
        <div class="session-title">${escapeHtml(cleanTitle)}</div>
        <div class="session-meta">${session.messages_count} сообщений</div>
      </div>
      <button class="delete-session" title="Удалить диалог" aria-label="Удалить диалог">
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>
      </button>
    `;
    item.addEventListener("click", () => openSession(session.id, cleanTitle));
    item.querySelector(".delete-session").addEventListener("click", (event) => {
      event.stopPropagation();
      deleteSession(session.id);
    });
    sessionsListEl.appendChild(item);
  });
  refreshIcons();
}

async function openSession(sessionId, title = "Диалог") {
  state.currentSessionId = sessionId;
  state.isDraftChat = false;
  stopChatPlaceholderRotation();
  localStorage.setItem("lastSessionId", sessionId);
  $("#chatTitle").textContent = stripImageNote(title) || "Диалог";
  messagesEl.innerHTML = "";
  const messages = await api(`/api/sessions/${sessionId}/messages`);
  if (messages.length) {
    messages.forEach((message) => {
      let images = (message.image_urls || []).map((url) => ({ url, name: "" }));
      let content = message.content || "";
      if (message.role === "user") {
        if (!images.length) {
          const fallbackPaths = extractImagePaths(content);
          images = fallbackPaths
            .map((p) => imagePathToUrl(p))
            .filter(Boolean)
            .map((url) => ({ url, name: "" }));
        }
        content = stripImageNote(content);
      }
      renderMessage(message.role, content, message.citations || [], "", images);
    });
  } else {
    renderEmptyState();
  }
  setActiveTab("chat");
  await loadSessions();
}

async function deleteSession(sessionId) {
  if (!confirm("Удалить этот диалог?")) return;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (localStorage.getItem("lastSessionId") === sessionId) localStorage.removeItem("lastSessionId");
  if (state.currentSessionId === sessionId) startDraftChat();
  await loadSessions();
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  const hasImages = state.attachedImages.length > 0;
  if (!message && !hasImages) return;
  if (state.attachedImages.some((img) => img.uploading)) {
    return;
  }
  stopChatPlaceholderRotation();

  const sentImages = state.attachedImages.map((img) => ({
    url: img.blobUrl,
    name: img.name,
    path: img.path,
  }));
  const imagePaths = sentImages.map((img) => img.path).filter(Boolean);

  state.attachedImages = [];
  renderAttachedImages();
  input.value = "";
  resizeComposer(input);

  renderMessage("user", message, [], "", sentImages);
  const loadingMessage = renderAssistantLoading();

  let result;
  try {
    result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.currentSessionId,
        message,
        image_paths: imagePaths,
      }),
    });
  } catch (error) {
    loadingMessage.remove();
    renderMessage("assistant", `Не удалось получить ответ.\n\n**Причина:** ${error.message}`, [], "knowledge-warning");
    return;
  }
  loadingMessage.remove();
  state.currentSessionId = result.session_id;
  state.isDraftChat = false;
  localStorage.setItem("lastSessionId", result.session_id);
  const titleSource = result.title || stripImageNote(message) || (sentImages.length ? "Прикрепленные файлы" : "");
  if (titleSource) $("#chatTitle").textContent = titleSource.slice(0, 80);
  renderMessage("assistant", result.answer, result.citations || [], result.kind);
  await loadSessions();
}

function resizeComposer(textarea) {
  textarea.style.height = "auto";
  const maxHeight = 180;
  textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
}

function handleComposerKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  event.currentTarget.form.requestSubmit();
}

function shouldRotateChatPlaceholder() {
  return state.isDraftChat && !state.currentSessionId && !document.querySelector(".message");
}

function stopChatPlaceholderRotation() {
  clearInterval(placeholderState.rotationTimer);
  clearInterval(placeholderState.typingTimer);
  placeholderState.rotationTimer = null;
  placeholderState.typingTimer = null;
  const input = $("#messageInput");
  if (input) input.placeholder = defaultChatPlaceholder;
}

function startChatPlaceholderRotation() {
  const input = $("#messageInput");
  if (!input) return;
  stopChatPlaceholderRotation();
  if (!shouldRotateChatPlaceholder()) return;
  placeholderState.index = 0;

  const typePlaceholder = (text) => {
    clearInterval(placeholderState.typingTimer);
    input.placeholder = "";
    let charIndex = 0;
    placeholderState.typingTimer = setInterval(() => {
      if (!shouldRotateChatPlaceholder() || input.value.trim()) {
        stopChatPlaceholderRotation();
        return;
      }
      input.placeholder = text.slice(0, charIndex + 1);
      charIndex += 1;
      if (charIndex >= text.length) clearInterval(placeholderState.typingTimer);
    }, 28);
  };

  typePlaceholder(chatPlaceholders[placeholderState.index]);
  placeholderState.rotationTimer = setInterval(() => {
    if (!shouldRotateChatPlaceholder() || input.value.trim()) {
      stopChatPlaceholderRotation();
      return;
    }
    placeholderState.index = (placeholderState.index + 1) % chatPlaceholders.length;
    typePlaceholder(chatPlaceholders[placeholderState.index]);
  }, 5000);
}

function clearAttachedImages() {
  state.attachedImages.forEach((img) => {
    if (img.blobUrl) URL.revokeObjectURL(img.blobUrl);
  });
  state.attachedImages = [];
  renderAttachedImages();
}

function removeAttachedImage(id) {
  const idx = state.attachedImages.findIndex((img) => img.id === id);
  if (idx === -1) return;
  const [removed] = state.attachedImages.splice(idx, 1);
  if (removed.blobUrl) URL.revokeObjectURL(removed.blobUrl);
  renderAttachedImages();
}

function reorderAttachedImage(fromId, toId) {
  if (!fromId || fromId === toId) return;
  const fromIdx = state.attachedImages.findIndex((img) => img.id === fromId);
  const toIdx = state.attachedImages.findIndex((img) => img.id === toId);
  if (fromIdx === -1 || toIdx === -1) return;
  const [moved] = state.attachedImages.splice(fromIdx, 1);
  state.attachedImages.splice(toIdx, 0, moved);
  renderAttachedImages();
}

function renderAttachedImages() {
  const container = $("#attachedImages");
  container.innerHTML = "";
  state.attachedImages.forEach((img) => {
    const chip = document.createElement("div");
    chip.className = "image-chip" + (img.uploading ? " uploading" : "");
    chip.draggable = true;
    chip.dataset.id = img.id;
    chip.innerHTML = `
      <img src="${img.blobUrl}" alt="${escapeHtml(img.name)}" draggable="false" />
      ${img.uploading ? '<div class="image-chip-spinner"></div>' : ''}
      <button type="button" class="image-chip-remove" aria-label="Удалить">
        <svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
          <line x1="4" y1="4" x2="12" y2="12"/>
          <line x1="12" y1="4" x2="4" y2="12"/>
        </svg>
      </button>
    `;
    chip.querySelector(".image-chip-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      removeAttachedImage(img.id);
    });
    chip.addEventListener("dragstart", (e) => {
      chip.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("application/x-image-chip", img.id);
    });
    chip.addEventListener("dragend", () => chip.classList.remove("dragging"));
    chip.addEventListener("dragover", (e) => {
      if (!Array.from(e.dataTransfer.types || []).includes("application/x-image-chip")) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      chip.classList.add("drop-target");
    });
    chip.addEventListener("dragleave", () => chip.classList.remove("drop-target"));
    chip.addEventListener("drop", (e) => {
      const draggedId = e.dataTransfer.getData("application/x-image-chip");
      if (!draggedId) return;
      e.preventDefault();
      e.stopPropagation();
      chip.classList.remove("drop-target");
      reorderAttachedImage(draggedId, img.id);
    });
    container.appendChild(chip);
  });
}

async function attachImageFile(file) {
  if (!file || !file.type || !file.type.startsWith("image/")) return;
  const id = `img-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const entry = {
    id,
    name: file.name || "image.png",
    blobUrl: URL.createObjectURL(file),
    path: null,
    uploading: true,
  };
  state.attachedImages.push(entry);
  renderAttachedImages();
  try {
    const formData = new FormData();
    formData.append("file", file, entry.name);
    const response = await fetch("/api/uploads/images", { method: "POST", body: formData });
    if (!response.ok) throw new Error("upload failed");
    const result = await response.json();
    entry.path = result.path;
    entry.name = result.name || entry.name;
    entry.uploading = false;
    renderAttachedImages();
  } catch (err) {
    removeAttachedImage(id);
    alert("Не удалось загрузить изображение");
  }
}

async function uploadImage(event) {
  const files = Array.from(event.target.files || []);
  for (const file of files) await attachImageFile(file);
  event.target.value = "";
  $("#attachMenu").classList.remove("open");
}

function bindImagePaste() {
  $("#messageInput").addEventListener("paste", (event) => {
    const items = Array.from(event.clipboardData?.items || []);
    const imageItems = items.filter((it) => it.kind === "file" && it.type.startsWith("image/"));
    if (!imageItems.length) return;
    event.preventDefault();
    imageItems.forEach((it) => {
      const file = it.getAsFile();
      if (file) attachImageFile(file);
    });
  });
}

function bindImageDrop() {
  const overlay = $("#dropOverlay");
  let dragDepth = 0;
  const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    dragDepth++;
    overlay.classList.add("active");
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) overlay.classList.remove("active");
  });
  window.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove("active");
    const files = Array.from(e.dataTransfer.files || []).filter((f) => f.type.startsWith("image/"));
    files.forEach(attachImageFile);
  });
}

function uniqueValues(key) {
  return [...new Set(state.materials.map((item) => item[key]).filter(Boolean))].sort();
}

function fillSelectOptions(select, values, current) {
  const first = select.querySelector("option");
  select.innerHTML = "";
  select.appendChild(first);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = value === current;
    select.appendChild(option);
  });
}

function fillMappedSelectOptions(select, options, current) {
  const first = select.querySelector("option");
  select.innerHTML = "";
  select.appendChild(first);
  options.forEach(({ value, label }) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === current;
    select.appendChild(option);
  });
}

async function loadMaterials() {
  state.materials = await api("/api/materials");
  syncMaterialFilterOptions();
  renderMaterials();
}

async function refreshMaterials() {
  const button = $("#refreshMaterialsBtn");
  button.disabled = true;
  button.classList.add("loading");
  $("#reindexStatus").textContent = "Обновляю список источников...";
  try {
    await loadMaterials();
    materialsListEl.classList.remove("just-refreshed");
    void materialsListEl.offsetWidth;
    materialsListEl.classList.add("just-refreshed");
    $("#reindexStatus").textContent = `Список обновлен: ${state.materials.length} источников.`;
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    refreshIcons();
  }
}

function syncMaterialFilterOptions() {
  fillMappedSelectOptions($("#statusFilter"), materialStatuses, $("#statusFilter").value);
  fillSelectOptions($("#typeFilter"), sourceCategories, $("#typeFilter").value);
}

function matchesMaterialFilters(material) {
  const query = $("#materialSearch").value.trim().toLowerCase();
  const status = $("#statusFilter").value;
  const origin = $("#originFilter").value;
  const type = $("#typeFilter").value;
  const statusLabel = materialStatusLabels[material.status] || material.status;
  const haystack = `${material.title} ${material.url} ${material.type} ${material.status} ${statusLabel}`.toLowerCase();
  return (!query || haystack.includes(query)) && (!status || material.status === status) && (!origin || material.origin === origin) && (!type || material.type === type);
}

function createMaterialCard(material) {
  const item = document.createElement("article");
  item.className = "material-item";
  item.dataset.sourceId = material.id;
  const originIcon = material.origin === "manual" ? "book-open" : "globe";
  const originLabel = material.origin === "manual" ? "Manual" : "Web";
  const statusLabel = materialStatusLabels[material.status] || material.status || "Неизвестный статус";
  const sourceLink =
    material.origin === "manual"
      ? ""
      : `<a class="material-link" href="${escapeHtml(material.url)}" target="_blank" rel="noreferrer">
          <i data-lucide="external-link"></i>
          Открыть источник
        </a>`;
  item.innerHTML = `
    <div class="material-card-head">
      <div>
        <div class="material-title">${escapeHtml(material.title)}</div>
        <div class="material-meta">
          <span class="status-${escapeHtml(material.status)}">${escapeHtml(statusLabel)}</span>
          <span class="origin-badge"><i data-lucide="${originIcon}"></i>${originLabel}</span>
          <span>${escapeHtml(material.type)}</span>
          <span>chunks: ${material.chunks_count}</span>
        </div>
      </div>
      <div class="material-actions">
        <button class="edit-material" title="Редактировать источник" aria-label="Редактировать источник"><i data-lucide="pencil"></i></button>
        <button class="delete-material" title="Удалить источник" aria-label="Удалить источник">
          <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>
        </button>
      </div>
    </div>
    <div class="material-note">${escapeHtml(material.note || "Описание пока не добавлено.")}</div>
    ${sourceLink}
  `;
  item.querySelector(".edit-material").addEventListener("click", () => openEditSourceModal(material));
  item.querySelector(".delete-material").addEventListener("click", () => deleteMaterial(material));
  return item;
}

function flashMaterialCard(sourceId, className) {
  const card = materialsListEl.querySelector(`[data-source-id="${CSS.escape(sourceId)}"]`);
  if (!card) return;
  card.classList.remove(className);
  void card.offsetWidth;
  card.classList.add(className);
}

function renderMaterials() {
  const sort = $("#sortMaterials").value;

  let items = state.materials.filter(matchesMaterialFilters);

  items.sort((a, b) => {
    if (sort === "status") return (materialStatusOrder[a.status] || 99) - (materialStatusOrder[b.status] || 99) || a.title.localeCompare(b.title);
    if (sort === "origin") return a.origin.localeCompare(b.origin) || a.title.localeCompare(b.title);
    if (sort === "chunks") return b.chunks_count - a.chunks_count || a.title.localeCompare(b.title);
    return a.title.localeCompare(b.title);
  });

  materialsListEl.innerHTML = "";
  items.forEach((material) => {
    materialsListEl.appendChild(createMaterialCard(material));
  });
  refreshIcons();
}

async function addSource(event) {
  event.preventDefault();
  const payload = {
    title: $("#sourceTitle").value.trim(),
    url: $("#sourceUrl").value.trim(),
    type: $("#sourceType").value,
  };
  const created = await api("/api/materials", { method: "POST", body: JSON.stringify(payload) });
  const material = {
    id: created.id,
    title: created.title,
    url: created.url,
    type: created.type,
    status: "pending",
    origin: "web",
    chunks_count: 0,
    note: "Ожидает индексации.",
    updated_at: new Date().toISOString(),
  };
  state.materials = [material, ...state.materials.filter((item) => item.id !== material.id)];
  syncMaterialFilterOptions();
  renderMaterials();
  event.target.reset();
  closeSourceModal();
  $("#reindexStatus").textContent = "Источник добавлен. Нажмите «Переиндексировать», чтобы подготовить его для поиска.";
  flashMaterialCard(material.id, "card-added");
  refreshIcons();
}

async function deleteMaterial(material) {
  const message =
    material.origin === "manual"
      ? "Удалить manual-файл и источник из базы?"
      : "Удалить источник из списка и базы?";
  if (!confirm(message)) return;
  const card = materialsListEl.querySelector(`[data-source-id="${CSS.escape(material.id)}"]`);
  if (card) {
    card.classList.add("card-removing");
  }
  await api(`/api/materials/${encodeURIComponent(material.id)}`, { method: "DELETE" });
  state.materials = state.materials.filter((item) => item.id !== material.id);
  syncMaterialFilterOptions();
  setTimeout(() => renderMaterials(), card ? 220 : 0);
  $("#reindexStatus").textContent = "Источник удален. При необходимости нажмите «Переиндексировать».";
}

function openReindexModal() {
  selectReindexMode(state.reindexMode || "new");
  $("#reindexModal").classList.add("open");
  $("#reindexModal").setAttribute("aria-hidden", "false");
}

function closeReindexModal() {
  $("#reindexModal").classList.remove("open");
  $("#reindexModal").setAttribute("aria-hidden", "true");
}

function selectReindexMode(mode) {
  state.reindexMode = mode === "all" ? "all" : "new";
  document.querySelectorAll(".reindex-option").forEach((option) => {
    option.classList.toggle("selected", option.dataset.reindexMode === state.reindexMode);
  });
  const runButton = $("#runReindexBtn");
  if (runButton) {
    runButton.textContent = state.reindexMode === "all" ? "Переиндексировать все" : "Индексировать новые";
    runButton.classList.toggle("warning-button", state.reindexMode === "all");
    runButton.classList.toggle("primary-button", state.reindexMode !== "all");
  }
}

async function reindex(mode = "all") {
  closeReindexModal();
  const button = $("#reindexBtn");
  const status = $("#reindexStatus");
  const modeLabel = mode === "new" ? "новых источников" : "всех источников";
  button.disabled = true;
  button.classList.add("loading");
  status.className = "status-line status-working";
  status.innerHTML = `<span class="status-spinner"></span><span>Переиндексация ${modeLabel} запущена. Скачиваю источники, читаю PDF и обновляю базу поиска...</span>`;
  try {
    const result = await api("/api/reindex", { method: "POST", body: JSON.stringify({ mode }) });
    status.className = "status-line status-success";
    status.innerHTML = `
      <span class="status-dot ok"></span>
      <span>${escapeHtml(result.message)} Подготовлено: ${result.prepared}, vector: ${result.indexed}, только метаданные: ${result.metadata_only}, недоступно: ${result.unavailable}, пропущено: ${result.skipped || 0}.</span>
    `;
    materialsListEl.classList.remove("just-refreshed");
    void materialsListEl.offsetWidth;
    materialsListEl.classList.add("just-refreshed");
  } catch (error) {
    status.className = "status-line status-error";
    status.innerHTML = `<span class="status-dot bad"></span><span>Ошибка индексации: ${escapeHtml(error.message)}</span>`;
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    refreshIcons();
  }
  await loadMaterials();
}

async function loadTools() {
  const tools = await api("/api/tools");
  const iconMap = {
    mentor: "message-circle-question",
    critic: "badge-check",
    methodologist: "route",
    "task-generator": "clipboard-list",
    "audio-project-analyzer": "audio-lines",
  };
  toolsListEl.innerHTML = "";
  tools.forEach((tool) => {
    const isActive = tool.status === "active";
    const item = document.createElement("article");
    item.className = `tool-card ${isActive ? "active-tool" : "dev-tool"}`;
    item.innerHTML = `
      <div class="tool-icon"><i data-lucide="${iconMap[tool.id] || "sparkles"}"></i></div>
      <div class="tool-title">${escapeHtml(tool.title)}</div>
      <div class="tool-meta">${escapeHtml(tool.description)}</div>
      <div class="tool-status ${isActive ? "status-active-tool" : "status-dev-tool"}">
        <span></span>${isActive ? "Активен" : "В разработке"}
      </div>
      ${
        isActive
          ? '<button class="tool-start-button" type="button">Начать</button>'
          : ""
      }
    `;
    if (isActive) {
      item.querySelector(".tool-start-button").addEventListener("click", startDraftChat);
    }
    toolsListEl.appendChild(item);
  });
  refreshIcons();
}

function renderCourses() {
  const totalModules = courses.reduce((sum, course) => sum + course.modules.length, 0);
  const completedTotal = courses.reduce((sum, course) => sum + course.modules.filter((module) => module.status === "done").length, 0);
  const totalPercent = totalModules ? Math.round((completedTotal / totalModules) * 100) : 0;
  const statusMap = {
    done: { label: "пройден", icon: "check" },
    active: { label: "начат", icon: "play" },
    locked: { label: "не начат", icon: "circle" },
  };

  $("#courseTotalProgress").textContent = `${totalPercent}%`;
  $("#courseCompletedModules").textContent = completedTotal;

  coursesListEl.innerHTML = "";
  courses.forEach((course, index) => {
    const completed = course.modules.filter((module) => module.status === "done").length;
    const percent = Math.round((completed / course.modules.length) * 100);
    const hasStarted = course.modules.some((module) => module.status === "done" || module.status === "active");
    const card = document.createElement("article");
    card.className = "course-card";
    card.style.animationDelay = `${index * 60}ms`;
    card.innerHTML = `
      <div class="course-head">
        <div class="course-icon"><i data-lucide="${course.icon}"></i></div>
        <div>
          <h3>${escapeHtml(course.title)}</h3>
          <p>${escapeHtml(course.description)}</p>
          <button class="course-dev-button" type="button" disabled>
            <i data-lucide="lock"></i>
            ${hasStarted ? "Продолжить курс" : "Начать курс"} · в разработке
          </button>
        </div>
        <div class="course-progress-box">
          <div class="course-progress-meta">
            <span>${completed}/${course.modules.length} модулей</span>
            <strong>${percent}%</strong>
          </div>
          <div class="progress-track"><div class="progress-fill" style="width: ${percent}%"></div></div>
        </div>
      </div>
      <div class="module-list">
        ${course.modules
          .map((module) => {
            const status = statusMap[module.status] || statusMap.locked;
            return `
              <div class="module-card ${escapeHtml(module.status || "locked")}">
                <div class="module-check" aria-hidden="true">
                  <i data-lucide="${status.icon}"></i>
                </div>
                <div>
                  <h4>${escapeHtml(module.title)}</h4>
                  <p>${escapeHtml(module.task)}</p>
                  <div class="module-meta">
                    <span class="module-status">${status.label}</span>
                    <span>${escapeHtml(module.type)}</span>
                    <span>${escapeHtml(module.time)}</span>
                  </div>
                </div>
              </div>
            `;
          })
          .join("")}
      </div>
    `;
    coursesListEl.appendChild(card);
  });
  refreshIcons();
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.id === "newSessionBtn") {
        startDraftChat();
        return;
      }
      setActiveTab(tab.dataset.tab);
      if (tab.dataset.tab === "materials") loadMaterials();
      if (tab.dataset.tab === "courses") renderCourses();
      if (tab.dataset.tab === "tools") loadTools();
      if (tab.dataset.tab === "admin") { loadInvites(); loadAdminUsers(); }
    });
  });
}

function bindAttachMenu() {
  $("#attachMenuBtn").addEventListener("click", () => $("#attachMenu").classList.toggle("open"));
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".attach-wrap")) $("#attachMenu").classList.remove("open");
  });
}

function openSourceModal() {
  $("#sourceModal").classList.add("open");
  $("#sourceModal").setAttribute("aria-hidden", "false");
  setTimeout(() => $("#sourceTitle").focus(), 0);
}

function closeSourceModal() {
  $("#sourceModal").classList.remove("open");
  $("#sourceModal").setAttribute("aria-hidden", "true");
}

function openEditSourceModal(material) {
  $("#editSourceId").value = material.id;
  $("#editSourceOrigin").value = material.origin;
  $("#editSourceTitle").value = material.title;
  $("#editSourceUrl").value = material.url;
  $("#editSourceType").value = material.type;
  $("#editSourceUrl").disabled = material.origin === "manual";
  $("#editSourceModal").classList.add("open");
  $("#editSourceModal").setAttribute("aria-hidden", "false");
  setTimeout(() => $("#editSourceTitle").focus(), 0);
}

function closeEditSourceModal() {
  $("#editSourceModal").classList.remove("open");
  $("#editSourceModal").setAttribute("aria-hidden", "true");
}

function bindSourceModal() {
  $("#openSourceModalBtn").addEventListener("click", openSourceModal);
  $("#closeSourceModalBtn").addEventListener("click", closeSourceModal);
  $("#cancelSourceModalBtn").addEventListener("click", closeSourceModal);
  $("#closeEditSourceModalBtn").addEventListener("click", closeEditSourceModal);
  $("#cancelEditSourceModalBtn").addEventListener("click", closeEditSourceModal);
  $("#sourceModal").addEventListener("click", (event) => {
    if (event.target.id === "sourceModal") closeSourceModal();
  });
  $("#editSourceModal").addEventListener("click", (event) => {
    if (event.target.id === "editSourceModal") closeEditSourceModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSourceModal();
    if (event.key === "Escape") closeEditSourceModal();
    if (event.key === "Escape") closeReindexModal();
  });
}

function bindReindexModal() {
  $("#reindexBtn").addEventListener("click", openReindexModal);
  $("#closeReindexModalBtn").addEventListener("click", closeReindexModal);
  $("#cancelReindexModalBtn").addEventListener("click", closeReindexModal);
  $("#runReindexBtn").addEventListener("click", () => reindex(state.reindexMode));
  document.querySelectorAll(".reindex-option").forEach((option) => {
    option.addEventListener("click", () => selectReindexMode(option.dataset.reindexMode));
  });
  $("#reindexModal").addEventListener("click", (event) => {
    if (event.target.id === "reindexModal") closeReindexModal();
  });
  selectReindexMode(state.reindexMode);
}

async function updateSource(event) {
  event.preventDefault();
  const sourceId = $("#editSourceId").value;
  const origin = $("#editSourceOrigin").value;
  const payload = {
    title: $("#editSourceTitle").value.trim(),
    type: $("#editSourceType").value.trim(),
    url: origin === "manual" ? undefined : $("#editSourceUrl").value.trim(),
  };
  const updated = await api(`/api/materials/${encodeURIComponent(sourceId)}`, { method: "PATCH", body: JSON.stringify(payload) });
  state.materials = state.materials.map((item) => (item.id === sourceId ? { ...item, ...updated } : item));
  syncMaterialFilterOptions();
  renderMaterials();
  closeEditSourceModal();
  $("#reindexStatus").textContent = "Источник обновлен. Нажмите «Переиндексировать», чтобы обновить поиск.";
  flashMaterialCard(sourceId, "card-updated");
  refreshIcons();
}

// ============ Auth ============

function showAuthOverlay() {
  $("#authOverlay").classList.add("active");
  $("#authOverlay").setAttribute("aria-hidden", "false");
}

function hideAuthOverlay() {
  $("#authOverlay").classList.remove("active");
  $("#authOverlay").setAttribute("aria-hidden", "true");
}

function setAuthMode(mode) {
  document.querySelectorAll(".auth-tab").forEach((t) => t.classList.toggle("active", t.dataset.authMode === mode));
  $("#loginForm").classList.toggle("active", mode === "login");
  $("#registerForm").classList.toggle("active", mode === "register");
  $("#loginError").hidden = true;
  $("#registerError").hidden = true;
}

function renderUserPanel() {
  const user = state.currentUser;
  const panel = $("#userPanel");
  if (!user) {
    panel.hidden = true;
    document.body.classList.remove("role-admin", "role-user");
    return;
  }
  panel.hidden = false;
  $("#userEmail").textContent = user.display_name || user.email;
  const roleEl = $("#userRole");
  roleEl.textContent = user.role === "admin" ? "Администратор" : "Пользователь";
  roleEl.classList.toggle("admin", user.role === "admin");
  $("#userAvatar").textContent = (user.display_name || user.email).trim().charAt(0).toUpperCase();
  document.body.classList.toggle("role-admin", user.role === "admin");
  document.body.classList.toggle("role-user", user.role !== "admin");
}

async function loadCurrentUser() {
  try {
    const res = await fetch("/api/auth/me", { credentials: "same-origin" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.authenticated) return null;
    return data.user;
  } catch (_) {
    return null;
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const errEl = $("#loginError");
  errEl.hidden = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || "Ошибка входа.");
    }
    const user = await res.json();
    state.currentUser = user;
    renderUserPanel();
    hideAuthOverlay();
    await postLoginInit();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const errEl = $("#registerError");
  errEl.hidden = true;
  try {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || "Ошибка регистрации.");
    }
    const user = await res.json();
    state.currentUser = user;
    renderUserPanel();
    hideAuthOverlay();
    await postLoginInit();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  }
}

async function handleLogout() {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch (_) {}
  state.currentUser = null;
  state.currentSessionId = null;
  state.isDraftChat = true;
  state.attachedImages = [];
  localStorage.removeItem("lastSessionId");
  messagesEl.innerHTML = "";
  sessionsListEl.innerHTML = "";
  renderUserPanel();
  showAuthOverlay();
  setAuthMode("login");
  document.querySelectorAll(".auth-form input").forEach((i) => (i.value = ""));
}

function bindAuth() {
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => setAuthMode(tab.dataset.authMode));
  });
  $("#loginForm").addEventListener("submit", handleLogin);
  $("#registerForm").addEventListener("submit", handleRegister);
  $("#logoutBtn").addEventListener("click", handleLogout);
}

// ============ Mobile sidebar drawer ============

function openMobileSidebar() {
  $("#sidebar").classList.add("open");
  $("#sidebarBackdrop").classList.add("open");
  document.body.classList.add("body-no-scroll");
}

function closeMobileSidebar() {
  $("#sidebar").classList.remove("open");
  $("#sidebarBackdrop").classList.remove("open");
  document.body.classList.remove("body-no-scroll");
}

function isMobileViewport() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function bindMobileSidebar() {
  $("#mobileMenuBtn").addEventListener("click", openMobileSidebar);
  $("#sidebarCloseBtn").addEventListener("click", closeMobileSidebar);
  $("#sidebarBackdrop").addEventListener("click", closeMobileSidebar);
  // Close drawer when user picks a tab or a session on mobile.
  $("#sidebar").addEventListener("click", (e) => {
    if (!isMobileViewport()) return;
    const tab = e.target.closest(".tab");
    const session = e.target.closest(".session-item");
    if (tab || session) {
      // Defer slightly so the tap effect plays before the drawer slides out.
      setTimeout(closeMobileSidebar, 80);
    }
  });
}

// ============ Admin: invites & users ============

async function loadInvites() {
  const container = $("#invitesList");
  try {
    const invites = await api("/api/admin/invites");
    if (!invites.length) {
      container.innerHTML = '<div class="empty-hint">Нет активных кодов. Создайте новый.</div>';
      return;
    }
    container.innerHTML = "";
    invites.forEach((inv) => {
      const card = document.createElement("div");
      card.className = "invite-card";
      const usedLabel = inv.max_uses ? `${inv.used_count}/${inv.max_uses}` : `${inv.used_count}/∞`;
      const consumed = inv.max_uses > 0 && inv.used_count >= inv.max_uses;
      card.innerHTML = `
        <span class="invite-code" title="Кликни чтобы скопировать">${escapeHtml(inv.code)}</span>
        <div class="invite-meta">
          <span class="role-badge ${inv.role}">${inv.role === "admin" ? "Админ" : "User"}</span>
          <strong>${usedLabel}</strong> исп.
          ${consumed ? " · <em>исчерпан</em>" : ""}
          ${inv.note ? ` · ${escapeHtml(inv.note)}` : ""}
        </div>
        <button type="button" class="invite-delete" aria-label="Удалить код">
          <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>
        </button>
      `;
      card.querySelector(".invite-code").addEventListener("click", () => {
        navigator.clipboard?.writeText(inv.code);
      });
      card.querySelector(".invite-delete").addEventListener("click", async () => {
        if (!confirm(`Удалить код ${inv.code}?`)) return;
        await api(`/api/admin/invites/${inv.id}`, { method: "DELETE" });
        loadInvites();
      });
      container.appendChild(card);
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-hint">Ошибка загрузки: ${escapeHtml(e.message)}</div>`;
  }
}

async function loadAdminUsers() {
  const container = $("#usersList");
  try {
    const users = await api("/api/admin/users");
    container.innerHTML = "";
    users.forEach((u) => {
      const card = document.createElement("div");
      card.className = "user-card";
      const isSelf = state.currentUser && u.id === state.currentUser.id;
      card.innerHTML = `
        <div class="user-avatar">${escapeHtml((u.display_name || u.email).charAt(0).toUpperCase())}</div>
        <div class="user-meta">
          <div><strong>${escapeHtml(u.display_name || u.email)}</strong> ${isSelf ? "<small>(вы)</small>" : ""}</div>
          <div style="font-size:12px;color:var(--muted);">${escapeHtml(u.email)} · <span class="role-badge ${u.role}">${u.role === "admin" ? "Админ" : "User"}</span></div>
        </div>
        ${isSelf ? "" : `<button type="button" class="user-delete" aria-label="Удалить пользователя">
          <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>
        </button>`}
      `;
      if (!isSelf) {
        card.querySelector(".user-delete").addEventListener("click", async () => {
          if (!confirm(`Удалить пользователя ${u.email}? Все его диалоги удалятся.`)) return;
          await api(`/api/admin/users/${u.id}`, { method: "DELETE" });
          loadAdminUsers();
        });
      }
      container.appendChild(card);
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-hint">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

function openInviteModal() {
  $("#inviteModal").classList.add("open");
  $("#inviteModal").setAttribute("aria-hidden", "false");
}

function closeInviteModal() {
  $("#inviteModal").classList.remove("open");
  $("#inviteModal").setAttribute("aria-hidden", "true");
  $("#inviteForm").reset();
}

async function handleCreateInvite(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  const payload = {
    role: data.role || "user",
    max_uses: parseInt(data.max_uses, 10) || 1,
    note: (data.note || "").trim() || null,
  };
  await api("/api/admin/invites", { method: "POST", body: JSON.stringify(payload) });
  closeInviteModal();
  loadInvites();
}

function bindAdmin() {
  $("#createInviteBtn").addEventListener("click", openInviteModal);
  $("#closeInviteModalBtn").addEventListener("click", closeInviteModal);
  $("#cancelInviteModalBtn").addEventListener("click", closeInviteModal);
  $("#inviteForm").addEventListener("submit", handleCreateInvite);
  $("#inviteModal").addEventListener("click", (e) => {
    if (e.target.id === "inviteModal") closeInviteModal();
  });
}

async function postLoginInit() {
  // After successful login/register — load user-specific data and bootstrap the UI.
  await loadHealth();
  await loadSessions();
  if (state.currentUser?.role === "admin") {
    await loadMaterials();
  }
  await loadTools();
  renderCourses();
  const savedTab = localStorage.getItem("activeTab") || "chat";
  const allowedTabs = state.currentUser?.role === "admin"
    ? ["chat", "materials", "admin", "tools", "courses"]
    : ["chat", "tools", "courses"];
  if (savedTab === "chat") {
    const lastSessionId = localStorage.getItem("lastSessionId");
    const sessions = await api("/api/sessions");
    const lastSession = sessions.find((session) => session.id === lastSessionId);
    if (lastSession) {
      try {
        await openSession(lastSession.id, stripImageNote(lastSession.title) || "Диалог");
      } catch (err) {
        console.warn("Failed to restore last session:", err);
        localStorage.removeItem("lastSessionId");
        startDraftChat();
      }
    } else if (sessions.length) {
      // No matching id (maybe deleted or stale). Open most recent session instead.
      const recent = sessions[0];
      try {
        await openSession(recent.id, stripImageNote(recent.title) || "Диалог");
      } catch (_) {
        startDraftChat();
      }
    } else {
      startDraftChat();
    }
  } else {
    renderEmptyState();
    setActiveTab(allowedTabs.includes(savedTab) ? savedTab : "chat");
  }
  refreshIcons();
}

async function init() {
  bindTabs();
  bindAttachMenu();
  bindSourceModal();
  bindReindexModal();
  bindAuth();
  bindAdmin();
  bindMobileSidebar();
  $("#chatForm").addEventListener("submit", sendMessage);
  $("#messageInput").addEventListener("input", (event) => resizeComposer(event.target));
  $("#messageInput").addEventListener("keydown", handleComposerKeydown);
  $("#imageInput").addEventListener("change", uploadImage);
  bindImagePaste();
  bindImageDrop();
  bindLightbox();
  $("#refreshMaterialsBtn").addEventListener("click", refreshMaterials);
  $("#addSourceForm").addEventListener("submit", addSource);
  $("#editSourceForm").addEventListener("submit", updateSource);
  ["materialSearch", "statusFilter", "originFilter", "typeFilter", "sortMaterials"].forEach((id) => {
    $(`#${id}`).addEventListener("input", renderMaterials);
  });

  // Auth check
  const user = await loadCurrentUser();
  if (!user) {
    showAuthOverlay();
    setAuthMode("login");
    refreshIcons();
    return;
  }
  state.currentUser = user;
  renderUserPanel();
  await postLoginInit();
}

init().catch((error) => {
  console.error(error);
  $("#apiStatus").textContent = "Ошибка запуска интерфейса";
});
