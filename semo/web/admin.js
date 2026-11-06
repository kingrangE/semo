const kinds = { calendar: "학사일정", academic_guide: "학사안내", notice: "공지사항", program: "취업·비교과" };
const states = { indexed: "색인 완료", needs_index: "갱신 필요", skipped: "색인 제외", unknown: "미확인" };
const byId = (id) => document.getElementById(id);
const rows = byId("document-rows");
const detail = byId("detail");
let overview = null;
let selectedId = null;
let detailRequest = null;
let detailVersion = 0;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function badge(state) { return node("span", states[state] || state, `badge ${state}`); }
function dateText(value, withTime = false) {
  if (!value) return "—";
  const raw = /^\d{4}\.\d{2}\.\d{2}$/.test(value) ? value.replaceAll(".", "-") : value;
  const parsed = new Date(raw.length === 10 ? `${raw}T00:00:00+09:00` : raw);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) }).format(parsed);
}
function originalLink(url) {
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return null;
    const link = node("a", "공식 원문 보기 ↗", "original-link");
    link.href = parsed.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch { return null; }
}
async function getJson(url, signal) {
  const response = await fetch(url, { cache: "no-store", signal });
  let data;
  try { data = await response.json(); } catch { throw new Error("서버 응답을 읽지 못했습니다. 다시 시도해 주세요."); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "자료를 가져오지 못했습니다.");
  return data;
}
function showMessage(text, error = false) {
  byId("load-status").textContent = text;
  byId("load-status").classList.toggle("error", error);
}
function renderSummary() {
  const cards = byId("summary");
  cards.replaceChildren();
  for (const [kind, label] of Object.entries(kinds)) {
    const card = node("button", undefined, "summary-card");
    card.type = "button";
    card.dataset.kind = kind;
    card.setAttribute("aria-pressed", String(byId("kind").value === kind));
    card.classList.toggle("active", byId("kind").value === kind);
    card.append(node("span", label));
    const count = node("strong", String(overview.documents_by_kind[kind] || 0));
    count.append(node("small", "건"));
    card.append(count);
    card.addEventListener("click", () => {
      byId("kind").value = byId("kind").value === kind ? "" : kind;
      renderSummary(); renderRows();
    });
    cards.append(card);
  }
  byId("total-count").textContent = `${overview.total.toLocaleString()}건`;
  const index = overview.index;
  const state = index ? (index.postgresql.in_sync ? "indexed" : "needs_index") : "unknown";
  byId("index-badge").className = `badge ${state}`;
  byId("index-badge").textContent = index ? (index.postgresql.in_sync ? "동기화 완료" : "갱신 필요") : "미확인";
  byId("index-message").textContent = index ? (index.postgresql.in_sync ? "원문과 검색 색인이 일치합니다." : "원문과 다른 검색 청크가 있습니다.") : "검색 색인에 연결하지 못했습니다. 원문 자료는 조회할 수 있습니다.";
  byId("index-counts").textContent = index ? `저장 ${index.chunks}청크 · 예상 ${index.postgresql.expected_chunks}청크 · 누락 ${Object.values(index.postgresql.missing_chunks_by_kind).reduce((a, b) => a + b, 0)}개 · 이전 청크 ${index.postgresql.stale_chunks}개 · 색인 제외 ${Object.values(index.postgresql.skipped_documents_by_reason).reduce((a, b) => a + b, 0)}문서` : "색인 상태를 확인할 때는 새로고침해 주세요.";
  byId("checked-at").textContent = `상태 조회 ${dateText(overview.checked_at, true)} KST · 수집 시각은 각 자료에서 확인하세요`;
}
function renderRows() {
  if (!overview) return;
  const query = byId("search").value.trim().normalize("NFC").toLocaleLowerCase("ko-KR");
  const selectedKind = byId("kind").value;
  const selectedState = byId("index-state").value;
  const items = overview.items.filter((item) => (!selectedKind || item.kind === selectedKind) && (!selectedState || item.index_state === selectedState) && (!query || (item.title || "").normalize("NFC").toLocaleLowerCase("ko-KR").includes(query)));
  rows.replaceChildren();
  byId("result-count").textContent = `${items.length.toLocaleString()}건 표시 / 전체 ${overview.total.toLocaleString()}건`;
  if (!items.length) {
    const row = node("tr");
    const cell = node("td", overview.total ? "조건에 맞는 자료가 없습니다. 검색 조건을 바꿔보세요." : "아직 수집된 자료가 없습니다. 수집을 완료한 뒤 새로고침해 주세요.", "empty");
    cell.colSpan = 4; row.append(cell); rows.append(row); return;
  }
  const fragment = document.createDocumentFragment();
  for (const item of items) {
    const row = node("tr");
    row.classList.toggle("selected", item.id === selectedId);
    const titleCell = node("td");
    titleCell.append(node("span", kinds[item.kind] || item.kind, "document-kind"));
    const title = node("button", item.title, "document-title");
    title.type = "button";
    title.setAttribute("aria-pressed", String(item.id === selectedId));
    title.addEventListener("click", () => selectDocument(item));
    titleCell.append(title);
    const period = node("td");
    if (item.start_date) {
      period.append(node("time", dateText(item.start_date)), node("time", `~ ${dateText(item.end_date)}`));
    } else if (item.application_start) {
      period.append(node("time", dateText(item.application_start)), node("time", `~ ${dateText(item.application_end)}`));
    } else { period.textContent = dateText(item.published_at); }
    const checked = node("td", dateText(item.checked_at));
    checked.title = dateText(item.checked_at, true);
    const status = node("td"); status.append(badge(item.index_state));
    status.append(node("small", item.indexed_chunks === null ? `예상 ${item.expected_chunks}개` : `${item.indexed_chunks} / ${item.expected_chunks}개`, "chunk-count"));
    row.append(titleCell, period, checked, status); fragment.append(row);
  }
  rows.append(fragment);
}
function metadataRows(pairs) {
  const list = node("dl", undefined, "detail-meta");
  for (const [label, value] of pairs) list.append(node("dt", label), node("dd", value ?? "—"));
  return list;
}
function renderDetail(doc, item) {
  detail.replaceChildren();
  const header = node("div", undefined, "detail-header");
  header.append(node("span", kinds[doc.kind] || doc.kind, "document-kind"), node("h2", doc.title));
  const link = originalLink(doc.url); if (link) header.append(link);
  const pairs = [["수집 확인", dateText(doc.checked_at, true)], ["작성일", dateText(doc.published_at)], ["색인 상태", states[item.index_state]], ["청크 수", `${item.indexed_chunks ?? "미확인"} / 예상 ${item.expected_chunks}개`]];
  if (doc.start_date) pairs.push(["일정", `${dateText(doc.start_date)} ~ ${dateText(doc.end_date)}`]);
  if (doc.application_start) pairs.push(["신청 기간", `${dateText(doc.application_start, true)} ~ ${dateText(doc.application_end, true)}`]);
  if (doc.event_start) pairs.push(["운영 기간", `${dateText(doc.event_start, true)} ~ ${dateText(doc.event_end, true)}`]);
  if (doc.target) pairs.push(["모집 대상", doc.target]);
  header.append(metadataRows(pairs)); detail.append(header);
  const nav = node("div", undefined, "detail-navigation");
  nav.setAttribute("aria-label", "자료 보기 방식");
  const body = node("div", undefined, "detail-body");
  const views = {};
  views.content = node("div");
  views.content.append(node("pre", doc.content?.trim() || (doc.body_status === "image_only" ? "이미지에만 본문이 있어 텍스트를 추출하지 못한 자료입니다." : "추출한 본문이 없습니다."), "extracted-text"));
  views.tables = node("div");
  const tables = doc.tables || [];
  if (!tables.length) views.tables.append(node("p", "추출된 표가 없습니다.", "subtle"));
  tables.forEach((data, index) => {
    const wrapper = node("div", undefined, "table-wrapper");
    const table = node("table", undefined, "extracted-table"); table.append(node("caption", `표 ${index + 1} · 원문 셀 병합 유지`));
    const tbody = node("tbody");
    for (const row of data) {
      const tr = node("tr");
      for (const cell of row) {
        const td = node("td", cell.text);
        const rowSpan = Number(cell.rowspan), colSpan = Number(cell.colspan);
        td.rowSpan = Number.isInteger(rowSpan) && rowSpan >= 1 && rowSpan <= 1000 ? rowSpan : 1;
        td.colSpan = Number.isInteger(colSpan) && colSpan >= 1 && colSpan <= 100 ? colSpan : 1;
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody); wrapper.append(table); views.tables.append(wrapper);
  });
  views.metadata = node("div");
  const { content, tables: ignoredTables, ...metadata } = doc;
  views.metadata.append(node("pre", JSON.stringify({ ...metadata, index: { state: item.index_state, expected_chunks: item.expected_chunks, indexed_chunks: item.indexed_chunks, missing_chunks: item.missing_chunks, stale_chunks: item.stale_chunks } }, null, 2), "metadata-text"));
  for (const [key, label] of [["content", "본문"], ["tables", `표 ${tables.length}`], ["metadata", "상세 정보"]]) {
    const button = node("button", label); button.type = "button";
    button.setAttribute("aria-pressed", String(key === "content"));
    button.addEventListener("click", () => {
      for (const child of nav.children) child.setAttribute("aria-pressed", String(child === button));
      for (const [name, view] of Object.entries(views)) view.hidden = name !== key;
    });
    nav.append(button); views[key].hidden = key !== "content"; body.append(views[key]);
  }
  detail.append(nav, body);
}
async function selectDocument(item, move = true) {
  selectedId = item.id; renderRows();
  if (detailRequest) detailRequest.abort();
  detailRequest = new AbortController();
  const version = ++detailVersion;
  detail.setAttribute("aria-busy", "true");
  detail.replaceChildren(node("p", "자료 본문을 불러오고 있습니다…", "detail-placeholder"));
  if (move && window.matchMedia("(max-width:1200px)").matches) detail.scrollIntoView({ block: "start", behavior: "instant" });
  try {
    const doc = await getJson(`/api/admin/document?${new URLSearchParams({ id: item.id })}`, detailRequest.signal);
    if (version === detailVersion) renderDetail(doc, item);
  } catch (error) {
    if (error.name !== "AbortError" && version === detailVersion) detail.replaceChildren(node("p", error instanceof TypeError ? "연결하지 못했습니다. 자료를 다시 선택해 주세요." : error.message, "detail-placeholder"));
  } finally { if (version === detailVersion) detail.setAttribute("aria-busy", "false"); }
}
async function refresh() {
  byId("refresh").disabled = true;
  byId("summary").setAttribute("aria-busy", "true");
  showMessage("수집 자료와 색인 상태를 확인하고 있습니다…");
  try {
    overview = await getJson("/api/admin/documents");
    for (const kind of Object.keys(overview.documents_by_kind)) {
      if (!Array.from(byId("kind").options).some((option) => option.value === kind)) {
        const option = node("option", kinds[kind] || kind); option.value = kind; byId("kind").append(option);
      }
    }
    renderSummary(); renderRows();
    showMessage("현재 저장된 자료입니다. 수집·색인 작업 중에는 상태가 일시적으로 달라질 수 있습니다.");
    const selected = overview.items.find((item) => item.id === selectedId);
    if (selected) await selectDocument(selected, false);
    else if (selectedId !== null) {
      selectedId = null; ++detailVersion; if (detailRequest) detailRequest.abort();
      detail.setAttribute("aria-busy", "false");
      detail.replaceChildren(node("p", "선택한 자료가 목록에 없습니다. 다른 자료를 선택해 주세요.", "detail-placeholder"));
    }
  } catch (error) {
    showMessage((error instanceof TypeError ? "서버에 연결하지 못했습니다." : error.message) + (overview ? " 이전 조회 결과를 표시합니다." : ""), true);
    if (!overview) { rows.replaceChildren(); const tr = node("tr"), td = node("td", "자료를 불러오지 못했습니다. 새로고침해 주세요.", "empty"); td.colSpan = 4; tr.append(td); rows.append(tr); byId("result-count").textContent = "연결 확인 필요"; }
  } finally { byId("refresh").disabled = false; byId("summary").setAttribute("aria-busy", "false"); }
}
byId("filters").addEventListener("submit", (event) => event.preventDefault());
byId("search").addEventListener("input", renderRows);
byId("kind").addEventListener("change", () => { if (overview) { renderSummary(); renderRows(); } });
byId("index-state").addEventListener("change", renderRows);
byId("reset").addEventListener("click", () => { byId("filters").reset(); if (overview) { renderSummary(); renderRows(); } byId("search").focus(); });
byId("refresh").addEventListener("click", refresh);
refresh();
