"use strict";

// The deployment artifact and the local `http.server -d site` command both
// expose the generated data mirror below the website root.
const DATA_PATHS = ["./data/papers.json", "../data/papers.json"];

const searchInput = document.querySelector("#search");
const economistFilter = document.querySelector("#economist-filter");
const paperList = document.querySelector("#paper-list");
const resultCount = document.querySelector("#result-count");
const emptyState = document.querySelector("#empty-state");
const errorState = document.querySelector("#error-state");

let papers = [];

async function loadPapers() {
  let lastError;
  for (const path of DATA_PATHS) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error("Paper data is not an array");
      return data;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

function populateEconomistFilter() {
  const names = [...new Set(papers.map((paper) => paper.economist).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));

  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    economistFilter.append(option);
  }
}

function formatDate(rawDate) {
  if (!rawDate) return "Date unavailable";
  // Avoid timezone conversion: first_seen is already an ISO calendar date.
  const [year, month, day] = rawDate.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) return rawDate;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function createPaperCard(paper) {
  const article = document.createElement("article");
  article.className = "paper-card";

  const meta = document.createElement("p");
  meta.className = "paper-meta";
  meta.textContent = `${paper.economist || "Unknown economist"} · First seen ${formatDate(paper.first_seen)}`;

  const title = document.createElement("h2");
  const paperLink = document.createElement("a");
  paperLink.href = paper.url;
  paperLink.target = "_blank";
  paperLink.rel = "noopener noreferrer";
  paperLink.textContent = paper.title || "Untitled paper";
  title.append(paperLink);

  const sourceLink = document.createElement("a");
  sourceLink.className = "source-link";
  sourceLink.href = paper.source_page;
  sourceLink.target = "_blank";
  sourceLink.rel = "noopener noreferrer";
  sourceLink.textContent = "View source page →";

  article.append(meta, title, sourceLink);
  return article;
}

function render() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const selectedEconomist = economistFilter.value;

  const visiblePapers = papers
    .filter((paper) => {
      const searchable = `${paper.title || ""} ${paper.economist || ""}`.toLocaleLowerCase();
      return searchable.includes(query) && (!selectedEconomist || paper.economist === selectedEconomist);
    })
    .sort((a, b) => (b.first_seen || "").localeCompare(a.first_seen || ""));

  paperList.replaceChildren(...visiblePapers.map(createPaperCard));
  const noun = visiblePapers.length === 1 ? "paper" : "papers";
  resultCount.textContent = `${visiblePapers.length} ${noun}`;
  emptyState.hidden = visiblePapers.length !== 0;
}

searchInput.addEventListener("input", render);
economistFilter.addEventListener("change", render);

loadPapers()
  .then((data) => {
    papers = data;
    populateEconomistFilter();
    render();
  })
  .catch((error) => {
    console.error("Unable to load paper data:", error);
    resultCount.textContent = "No data loaded";
    errorState.hidden = false;
  });
