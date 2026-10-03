// Importing a backup, and what the import says it did (in the Settings dialog's Data controls; the exports are plain
// links there, the server builds the files); see docs/backup.md.
import { $ } from "./core.js";
import { commitDelete } from "./delete.js";
import { refreshList } from "./list.js";

const chats = (n) => `${n} chat${n === 1 ? "" : "s"}`;

function setBackupStatus(text, failed = false) {
  const status = $("backup-status");
  status.textContent = text;
  status.hidden = !text;
  status.classList.toggle("is-error", failed);
}

$("import-file").onchange = async (e) => {
  const [file] = e.target.files;
  e.target.value = ""; // so choosing the same file again still counts
  if (!file) return;
  setBackupStatus(`Importing ${file.name}…`);
  await commitDelete(); // a chat deleted a moment ago is gone for good now, so an import of it is not hidden or deleted again
  const body = new FormData();
  body.append("file", file);
  try {
    const res = await fetch("/api/import", { method: "POST", body });
    const result = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof result.detail === "string" ? result.detail : `The import failed (${res.status}).`);
    const files = result.attachments ? ` with ${result.attachments} file${result.attachments === 1 ? "" : "s"}` : "";
    const instructions = result.custom_instructions ? "; custom instructions added" : "";
    setBackupStatus(result.imported
      ? `Imported ${chats(result.imported)}${files}${result.skipped ? `; ${result.skipped} already here` : ""}${instructions}.`
      : `Nothing new: ${chats(result.skipped)} already here${instructions}.`);
    await refreshList();
  } catch (err) {
    setBackupStatus(err instanceof TypeError ? "Couldn't reach the server." : err.message, true);
  }
};
