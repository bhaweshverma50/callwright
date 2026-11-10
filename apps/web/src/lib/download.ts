/** Hands a blob to the browser as a file download. */
export function saveBlob(filename: string, blob: Blob) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1_000);
}

/** Saves a JSON value as a file download. */
export function downloadJson(filename: string, data: unknown) {
  saveBlob(filename, new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
}
