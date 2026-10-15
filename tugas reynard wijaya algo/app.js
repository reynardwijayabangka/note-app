const elements = {
  list: document.querySelector("#notes-list"),
  count: document.querySelector("#note-count"),
  search: document.querySelector("#search-input"),
  welcome: document.querySelector("#welcome-state"),
  editor: document.querySelector("#editor"),
  title: document.querySelector("#title-input"),
  content: document.querySelector("#content-input"),
  save: document.querySelector("#save-button"),
  remove: document.querySelector("#delete-button"),
  saveStatus: document.querySelector("#save-status"),
  editorDate: document.querySelector("#editor-date"),
  breadcrumb: document.querySelector("#breadcrumb-title"),
  wordCount: document.querySelector("#word-count"),
  toast: document.querySelector("#toast"),
};

let notes = [];
let activeNote = null;
let isDirty = false;
let isSaving = false;
let toastTimer;
let searchTimer;

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Terjadi kesalahan. Coba lagi.");
  return payload;
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function formatDate(value) {
  if (!value) return "Baru saja";
  const date = new Date(value);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  if (sameDay) return `Hari ini, ${new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit" }).format(date)}`;
  return new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short" }).format(date);
}

function renderNotes() {
  elements.count.textContent = String(notes.length);
  if (!notes.length) {
    const hasSearch = elements.search.value.trim().length > 0;
    elements.list.innerHTML = `<div class="list-empty">${hasSearch ? "Catatan tidak ditemukan." : "Belum ada catatan.\nMulai dengan menulis ide pertamamu."}</div>`;
    return;
  }
  elements.list.innerHTML = notes.map((note) => `
    <button class="note-row ${activeNote?.id === note.id ? "active" : ""}" type="button" data-id="${note.id}" aria-current="${activeNote?.id === note.id ? "true" : "false"}">
      <span class="note-row-title">${escapeHTML(note.title || "Catatan tanpa judul")}</span>
      <span class="note-row-preview">${escapeHTML(note.content.trim().replace(/\s+/g, " ") || "Belum ada isi")}</span>
      <span class="note-row-date">${escapeHTML(formatDate(note.updated_at))}</span>
    </button>`).join("");
}

async function loadNotes() {
  try {
    const query = elements.search.value.trim();
    notes = await request(`/api/notes${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    renderNotes();
    if (activeNote && !notes.some((note) => note.id === activeNote.id) && !isDirty) {
      showWelcome();
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

function showWelcome() {
  activeNote = null;
  isDirty = false;
  elements.editor.hidden = true;
  elements.welcome.hidden = false;
  elements.breadcrumb.textContent = "Selamat datang";
  renderNotes();
}

function setActiveNote(note, { focus = false } = {}) {
  activeNote = note;
  isDirty = false;
  elements.title.value = note.title || "";
  elements.content.value = note.content || "";
  elements.welcome.hidden = true;
  elements.editor.hidden = false;
  elements.remove.hidden = false;
  elements.editorDate.textContent = note.created_at ? `Diperbarui ${formatDate(note.updated_at)}` : "Catatan baru";
  elements.saveStatus.textContent = "Tersimpan";
  elements.breadcrumb.textContent = note.title || "Catatan tanpa judul";
  updateWordCount();
  renderNotes();
  if (focus) elements.title.focus();
}

function createNote() {
  if (isDirty && !window.confirm("Perubahanmu belum disimpan. Buang perubahan dan buat catatan baru?")) return;
  setActiveNote({ id: null, title: "", content: "", created_at: null, updated_at: null }, { focus: true });
  elements.remove.hidden = true;
  elements.saveStatus.textContent = "Belum disimpan";
  elements.title.value = "";
  elements.content.value = "";
  updateWordCount();
  renderNotes();
}

function markDirty() {
  isDirty = true;
  elements.saveStatus.textContent = "Belum disimpan";
  elements.breadcrumb.textContent = elements.title.value.trim() || "Catatan baru";
  updateWordCount();
}

function updateWordCount() {
  const words = elements.content.value.trim().split(/\s+/).filter(Boolean).length;
  elements.wordCount.textContent = `${words} kata`;
}

async function saveNote() {
  if (isSaving) return;
  const title = elements.title.value.trim();
  const content = elements.content.value;
  if (!title && !content.trim()) {
    elements.title.focus();
    showToast("Tulis judul atau isi catatan terlebih dahulu.", true);
    return;
  }

  isSaving = true;
  elements.save.disabled = true;
  elements.saveStatus.textContent = "Menyimpan...";
  const existingId = activeNote?.id;
  try {
    const saved = await request(existingId ? `/api/notes/${existingId}` : "/api/notes", {
      method: existingId ? "PUT" : "POST",
      body: JSON.stringify({ title, content }),
    });
    activeNote = saved;
    isDirty = false;
    elements.title.value = saved.title;
    elements.breadcrumb.textContent = saved.title;
    elements.editorDate.textContent = `Diperbarui ${formatDate(saved.updated_at)}`;
    elements.saveStatus.textContent = "Tersimpan";
    await loadNotes();
    renderNotes();
    showToast(existingId ? "Perubahan catatan disimpan." : "Catatan berhasil disimpan.");
  } catch (error) {
    elements.saveStatus.textContent = "Gagal menyimpan";
    showToast(error.message, true);
  } finally {
    isSaving = false;
    elements.save.disabled = false;
  }
}

async function deleteNote() {
  if (!activeNote?.id) return;
  const name = activeNote.title || "catatan ini";
  if (!window.confirm(`Hapus “${name}”? Catatan yang dihapus tidak dapat dipulihkan.`)) return;
  try {
    await request(`/api/notes/${activeNote.id}`, { method: "DELETE" });
    showWelcome();
    await loadNotes();
    showToast("Catatan berhasil dihapus.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function showToast(message, error = false) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.style.color = error ? "#a65049" : "";
  elements.toast.style.borderColor = error ? "#f0d7d3" : "";
  elements.toast.classList.add("show");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("show"), 2600);
}

elements.list.addEventListener("click", (event) => {
  const button = event.target.closest(".note-row");
  if (!button) return;
  if (isDirty && !window.confirm("Perubahanmu belum disimpan. Buang perubahan dan buka catatan lain?")) return;
  const note = notes.find((item) => item.id === Number(button.dataset.id));
  if (note) setActiveNote(note);
});
elements.search.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(loadNotes, 180);
});
elements.title.addEventListener("input", markDirty);
elements.content.addEventListener("input", markDirty);
elements.save.addEventListener("click", saveNote);
elements.remove.addEventListener("click", deleteNote);
document.querySelectorAll("#new-note-button, #welcome-new-button, #mobile-new-button").forEach((button) => button.addEventListener("click", createNote));
document.addEventListener("keydown", (event) => {
  const modifier = event.ctrlKey || event.metaKey;
  if (modifier && event.key.toLowerCase() === "s") {
    event.preventDefault();
    if (!elements.editor.hidden) saveNote();
  }
  if (modifier && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }
  if (!modifier && event.key.toLowerCase() === "n" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    createNote();
  }
});

loadNotes();
