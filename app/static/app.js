const state = {
  currentSessionId: null,
  isDraftChat: true,
  imagePaths: [],
  materials: [],
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

const chatPlaceholders = [
  "Опиши, что не получается со звуком: глухо, резко, не играет MIDI или потерялся эффект",
  "Спроси, где в Ableton Live искать Browser, Mixer, Sends, Automation и Detail View",
  "Напиши ошибку Ableton дословно: помогу понять, что она означает и куда смотреть",
  "Спроси, как записать MIDI, аудио или автоматизацию без хаоса в проекте",
  "Спроси, почему бас пропадает в миксе или синт звучит слишком тонко",
  "Разберем маршрут сигнала: Audio From, Monitor, Track Activator, Solo и Master",
  "Напиши, какой звук хочешь собрать: плотный лид, мягкий pad, ударный бас или атмосферный шум",
  "Разбери проблему как в студии: что сделал, что ожидал услышать и что получилось",
  "Попроси объяснить Ableton без магии: клипы, дорожки, эффекты, routing и automation",
  "Где найти Soundgoodizer в Ableton Live?",
  "Загрузи скрин или опиши цепочку эффектов, если звук ведет себя странно",
];

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
    .replaceAll(">", "&gt;");
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? options.headers || {} : { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(path, { headers, ...options });
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
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === tabName));
  document.querySelectorAll(".panel").forEach((item) => item.classList.remove("active-panel"));
  $(`#${tabName}Tab`).classList.add("active-panel");
  localStorage.setItem("activeTab", tabName);
}

function startDraftChat() {
  state.currentSessionId = null;
  state.isDraftChat = true;
  state.imagePaths = [];
  $("#chatTitle").textContent = "Новый диалог";
  renderAttachedImages();
  renderEmptyState();
  setActiveTab("chat");
  loadSessions();
  setTimeout(() => $("#messageInput").focus(), 0);
}

function renderEmptyState() {
  messagesEl.innerHTML = `
    <div class="empty-state">
      <img src="/static/herzen.svg" alt="" />
      <h2>Чем помочь в Ableton Live?</h2>
      <p>Опиши затруднение: интерфейс, MIDI, эффекты, обработка звука или проверка результата.</p>
    </div>
  `;
}

function renderMessage(role, content, citations = []) {
  const empty = document.querySelector(".empty-state");
  if (empty) empty.remove();
  const item = document.createElement("article");
  item.className = `message ${role}`;
  item.innerHTML = `<div class="message-bubble">${escapeHtml(content)}</div>`;
  if (citations.length) {
    const citationsEl = document.createElement("div");
    citationsEl.className = "citations";
    citationsEl.innerHTML = citations
      .map(
        (citation) =>
          `<a href="${escapeHtml(citation.url)}" target="_blank" rel="noreferrer">${escapeHtml(citation.title)}</a>`,
      )
      .join("");
    item.appendChild(citationsEl);
  }
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
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
    item.innerHTML = `
      <div>
        <div class="session-title">${escapeHtml(session.title)}</div>
        <div class="session-meta">${session.messages_count} сообщений</div>
      </div>
      <button class="delete-session" title="Удалить диалог" aria-label="Удалить диалог">×</button>
    `;
    item.addEventListener("click", () => openSession(session.id, session.title));
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
  $("#chatTitle").textContent = title || "Диалог";
  messagesEl.innerHTML = "";
  const messages = await api(`/api/sessions/${sessionId}/messages`);
  if (messages.length) {
    messages.forEach((message) => renderMessage(message.role, message.content, message.citations || []));
  } else {
    renderEmptyState();
  }
  setActiveTab("chat");
  await loadSessions();
}

async function deleteSession(sessionId) {
  if (!confirm("Удалить этот диалог?")) return;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (state.currentSessionId === sessionId) startDraftChat();
  await loadSessions();
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  resizeComposer(input);
  renderMessage("user", message);
  const result = await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.currentSessionId,
      message,
      image_paths: state.imagePaths,
    }),
  });
  state.currentSessionId = result.session_id;
  state.isDraftChat = false;
  state.imagePaths = [];
  $("#chatTitle").textContent = message.slice(0, 80);
  renderAttachedImages();
  renderMessage("assistant", result.answer, result.citations || []);
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

function rotateChatPlaceholder() {
  const input = $("#messageInput");
  let index = 0;
  let typingTimer = null;

  const typePlaceholder = (text) => {
    clearInterval(typingTimer);
    input.placeholder = "";
    let charIndex = 0;
    typingTimer = setInterval(() => {
      if (input.value.trim()) {
        clearInterval(typingTimer);
        return;
      }
      input.placeholder = text.slice(0, charIndex + 1);
      charIndex += 1;
      if (charIndex >= text.length) clearInterval(typingTimer);
    }, 28);
  };

  typePlaceholder(chatPlaceholders[index]);
  setInterval(() => {
    if (input.value.trim()) return;
    index = (index + 1) % chatPlaceholders.length;
    typePlaceholder(chatPlaceholders[index]);
  }, 5000);
}

function renderAttachedImages() {
  $("#attachedImages").innerHTML = state.imagePaths
    .map((path) => `<span class="image-chip">${escapeHtml(path)}</span>`)
    .join("");
}

async function uploadImage(event) {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/api/uploads/images", { method: "POST", body: formData });
  if (!response.ok) {
    alert("Не удалось загрузить изображение");
    return;
  }
  const result = await response.json();
  state.imagePaths.push(result.path);
  renderAttachedImages();
  event.target.value = "";
  $("#attachMenu").classList.remove("open");
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
  fillSelectOptions($("#statusFilter"), uniqueValues("status"), $("#statusFilter").value);
  fillSelectOptions($("#typeFilter"), sourceCategories, $("#typeFilter").value);
}

function matchesMaterialFilters(material) {
  const query = $("#materialSearch").value.trim().toLowerCase();
  const status = $("#statusFilter").value;
  const origin = $("#originFilter").value;
  const type = $("#typeFilter").value;
  const haystack = `${material.title} ${material.url} ${material.type} ${material.status}`.toLowerCase();
  return (!query || haystack.includes(query)) && (!status || material.status === status) && (!origin || material.origin === origin) && (!type || material.type === type);
}

function createMaterialCard(material) {
  const item = document.createElement("article");
  item.className = "material-item";
  item.dataset.sourceId = material.id;
  const originIcon = material.origin === "manual" ? "book-open" : "globe";
  const originLabel = material.origin === "manual" ? "Manual" : "Web";
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
          <span class="status-${material.status}">${escapeHtml(material.status)}</span>
          <span class="origin-badge"><i data-lucide="${originIcon}"></i>${originLabel}</span>
          <span>${escapeHtml(material.type)}</span>
          <span>chunks: ${material.chunks_count}</span>
        </div>
      </div>
      <div class="material-actions">
        <button class="edit-material" title="Редактировать источник" aria-label="Редактировать источник"><i data-lucide="pencil"></i></button>
        <button class="delete-material" title="Удалить источник" aria-label="Удалить источник">×</button>
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

  const statusOrder = { indexed: 1, prepared: 2, pending: 3, metadata_only: 4, unavailable: 5 };
  let items = state.materials.filter(matchesMaterialFilters);

  items.sort((a, b) => {
    if (sort === "status") return (statusOrder[a.status] || 99) - (statusOrder[b.status] || 99) || a.title.localeCompare(b.title);
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

async function reindex() {
  const confirmed = confirm("Переиндексация скачает источники и перестроит базу. Без API ключа токены не тратятся, с ключом будут потрачены embeddings-токены. Продолжить?");
  if (!confirmed) return;
  const button = $("#reindexBtn");
  const status = $("#reindexStatus");
  button.disabled = true;
  button.classList.add("loading");
  status.className = "status-line status-working";
  status.innerHTML = '<span class="status-spinner"></span><span>Переиндексация запущена. Скачиваю источники, читаю PDF и обновляю базу поиска...</span>';
  try {
    const result = await api("/api/reindex", { method: "POST" });
    status.className = "status-line status-success";
    status.innerHTML = `
      <span class="status-dot ok"></span>
      <span>${escapeHtml(result.message)} Готово: ${result.prepared}, vector: ${result.indexed}, metadata: ${result.metadata_only}, недоступно: ${result.unavailable}.</span>
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
  });
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

async function init() {
  bindTabs();
  bindAttachMenu();
  bindSourceModal();
  $("#chatForm").addEventListener("submit", sendMessage);
  $("#messageInput").addEventListener("input", (event) => resizeComposer(event.target));
  $("#messageInput").addEventListener("keydown", handleComposerKeydown);
  rotateChatPlaceholder();
  $("#imageInput").addEventListener("change", uploadImage);
  $("#reindexBtn").addEventListener("click", reindex);
  $("#refreshMaterialsBtn").addEventListener("click", refreshMaterials);
  $("#addSourceForm").addEventListener("submit", addSource);
  $("#editSourceForm").addEventListener("submit", updateSource);
  ["materialSearch", "statusFilter", "originFilter", "typeFilter", "sortMaterials"].forEach((id) => {
    $(`#${id}`).addEventListener("input", renderMaterials);
  });
  await loadHealth();
  await loadSessions();
  await loadMaterials();
  await loadTools();
  renderCourses();
  const savedTab = localStorage.getItem("activeTab") || "chat";
  if (savedTab === "chat") {
    startDraftChat();
  } else {
    renderEmptyState();
    setActiveTab(["materials", "tools", "courses"].includes(savedTab) ? savedTab : "chat");
  }
  refreshIcons();
}

init().catch((error) => {
  console.error(error);
  $("#apiStatus").textContent = "Ошибка запуска интерфейса";
});
