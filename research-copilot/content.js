(() => {
  const url = window.location.href;
  const selection = window.getSelection() ? window.getSelection().toString().trim() : "";
  let recordData = {};
  let transcription = "";
  let isImageRecord = false;

  // 1. FAMILYSEARCH
  if (url.includes("familysearch.org")) {
    if (url.includes("/ark:/61903/3:1:") || url.includes("/records/images/")) {
      isImageRecord = true;
    }
    const fieldElements = document.querySelectorAll(
      "table tr, dl div, [data-testid*='record-field'], .record-field, .field-row"
    );
    fieldElements.forEach((el) => {
      const label = el.querySelector("th, dt, [class*='label']")?.innerText?.trim();
      const value = el.querySelector("td, dd, [class*='value']")?.innerText?.trim();
      if (label && value && label !== value) {
        recordData[label.replace(/:$/, "")] = value;
      }
    });

    const transcriptionEl = document.querySelector(
      "[data-testid*='transcription'], .transcription-text, #transcription-viewer, .ocr-text"
    );
    if (transcriptionEl) {
      transcription = transcriptionEl.innerText.trim();
    }
  }

  // 2. ANCESTRY
  else if (url.includes("ancestry.com")) {
    if (url.includes("/imageviewer/")) {
      isImageRecord = true;
    }
    const rows = document.querySelectorAll(
      "#recordData table tr, .table-record tr, .tblData tr, [data-testid*='recordData'] tr"
    );
    rows.forEach((row) => {
      const th = row.querySelector("th")?.innerText?.trim();
      const td = row.querySelector("td")?.innerText?.trim();
      if (th && td) {
        recordData[th.replace(/:$/, "")] = td;
      }
    });

    const householdRows = document.querySelectorAll(".household-table tr, #household tr");
    if (householdRows.length > 1) {
      const hhList = [];
      householdRows.forEach((r) => {
        const text = r.innerText.replace(/\s+/g, " ").trim();
        if (text) hhList.push(text);
      });
      if (hhList.length) recordData["Household Members"] = hhList.join(" | ");
    }
  }

  // 3. ALL OTHER SITES (Find A Grave, Newspapers.com, Archives, Wikipedia, Blogs)
  else {
    // Check for tabular metadata (common on Find A Grave, state archives, directories)
    document.querySelectorAll("table tr, dl").forEach((row) => {
      const label = row.querySelector("th, dt")?.innerText?.trim();
      const val = row.querySelector("td, dd")?.innerText?.trim();
      if (label && val && label.length < 40 && val.length < 300) {
        recordData[label.replace(/:$/, "")] = val;
      }
    });

    // Extract readable text directly from rendered elements (avoids Chromium detached-clone bug)
    const container = document.querySelector("article, main, #main-content, #content, .post-content") || document.body;
    const readableBlocks = container.querySelectorAll("h1, h2, h3, p, blockquote, li");
    if (readableBlocks.length > 0) {
      const parts = [];
      readableBlocks.forEach((b) => {
        const t = b.innerText?.trim();
        if (t && t.length > 25) parts.push(t);
      });
      transcription = parts.join("\n\n").slice(0, 5000);
    } else {
      transcription = container.innerText.slice(0, 4000);
    }
  }

  return {
    isImageRecord: isImageRecord,
    recordData: recordData,
    transcription: transcription,
    selection: selection,
    rawFallback: document.body ? document.body.innerText.slice(0, 2500) : ""
  };
})();
