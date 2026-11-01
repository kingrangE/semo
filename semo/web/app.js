const form = document.querySelector("#chat-form");
const input = document.querySelector("#question");
const messages = document.querySelector("#messages");
const welcome = document.querySelector("#welcome");
const status = document.querySelector("#status");
const send = document.querySelector("#send");
const clear = document.querySelector("#clear");
const history = document.querySelector("#history");
let busy = false;

function message(kind, text) {
  const article = document.createElement("article");
  article.className = `message ${kind}`;
  if (kind !== "user") {
    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = "△ 세모";
    article.append(label);
  }
  const content = document.createElement("div");
  content.className = "message-text";
  content.textContent = text;
  article.append(content);
  messages.append(article);
  article.scrollIntoView({ block: "nearest" });
  return article;
}

function showSources(article, sources, asOf) {
  const list = document.createElement("div");
  list.className = "source-list";
  list.setAttribute("aria-label", "답변의 공식 출처");
  for (const source of sources) {
    let url;
    try { url = new URL(source.url); } catch { continue; }
    if (!["https:", "http:"].includes(url.protocol)) continue;
    const link = document.createElement("a");
    link.className = "source-link";
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const number = document.createElement("span");
    number.className = "source-number";
    number.textContent = `[${source.id}]`;
    link.append(number, document.createTextNode(source.title + " ↗"));
    if (source.published_at) {
      const published = document.createElement("span");
      published.className = "source-date";
      published.textContent = `게시 ${source.published_at}`;
      link.append(published);
    }
    list.append(link);
  }
  if (list.childElementCount) article.append(list);
  const date = document.createElement("p");
  date.className = "as-of";
  date.textContent = `${asOf} 기준 안내`;
  article.append(date);
}

function setBusy(value) {
  busy = value;
  send.disabled = value;
  input.disabled = value;
  history.disabled = value;
  clear.disabled = value;
  form.setAttribute("aria-busy", String(value));
  status.textContent = value ? "공식 자료에서 근거를 찾아 답변을 작성하고 있어요…" : "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  const question = input.value.trim();
  if (!question) { input.focus(); return; }
  const includeHistory = history.checked;
  welcome.hidden = true;
  message("user", question);
  const pending = message("assistant pending", "자료를 확인하고 있어요…");
  input.value = "";
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, include_history: includeHistory }),
    });
    let data;
    try { data = await response.json(); } catch { throw new Error("서버 응답을 읽지 못했습니다. 잠시 후 다시 질문해 주세요."); }
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "질문은 1~1,000자로 입력해 주세요.");
    }
    pending.classList.remove("pending");
    pending.querySelector(".message-text").textContent = data.answer;
    showSources(pending, data.sources, data.as_of);
  } catch (error) {
    pending.classList.remove("pending");
    pending.classList.add("error");
    pending.querySelector(".message-text").textContent = error instanceof TypeError ? "서버에 연결하지 못했습니다. 연결 상태를 확인한 뒤 다시 질문해 주세요." : error.message;
    input.value = question;
  } finally {
    setBusy(false);
    pending.scrollIntoView({ block: "nearest" });
    input.focus();
  }
});

input.addEventListener("keydown", (event) => {
  // Enter confirms Korean IME composition before it can submit a question.
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!busy) form.requestSubmit();
  }
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    if (busy) return;
    input.value = button.dataset.question;
    input.focus();
  });
});

clear.addEventListener("click", () => {
  if (busy) return;
  messages.replaceChildren();
  welcome.hidden = false;
  input.value = "";
  input.focus();
});
