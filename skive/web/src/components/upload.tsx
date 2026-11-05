"use client";

import { ChevronDown, ChevronUp, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, cn, errorText, formatSize, getConfig, getSupabase, post } from "@/lib/skive";
import { Button } from "@/components/ui";

export type UploadItem = { file: File; relative: string };
type Task = UploadItem & { parentId: string | null };
type Row = { key: number; relative: string; state: string; percent: number; failed?: boolean };

const CONCURRENCY = 4;

const pendingKey = (userId: string, file: File, relative: string, parentId: string | null) =>
  `skive-upload:${userId}:${parentId || "root"}:${relative}:${file.size}:${file.lastModified}`;

function readStorage(key: string) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}
const writeStorage = (key: string, value: unknown) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };
const dropStorage = (key: string) => { try { localStorage.removeItem(key); } catch {} };

function uploadErrorMessage(error: any) {
  if (error?.originalResponse?.getStatus?.() === 413) return "파일이 저장소의 파일 크기 한도보다 큽니다.";
  return errorText(error);
}

async function uploadOne(task: Task, userId: string, onProgress: (sent: number, total: number) => void, onState: (text: string) => void) {
  const { file, relative, parentId } = task;
  const key = pendingKey(userId, file, relative, parentId);
  let info = readStorage(key);
  if (info) {
    try {
      const current = await api(`/files/${info.id}/status`);
      if (current.size_bytes !== file.size || current.storage_path !== info.storage_path) {
        dropStorage(key);
        info = null;
      } else if (current.upload_status === "uploaded") {
        dropStorage(key);
        onProgress(file.size, file.size);
        onState("이미 저장됨");
        return;
      }
    } catch (error) {
      if (!/File not found/.test(errorText(error))) throw error;
      dropStorage(key);
      info = null;
    }
  }
  if (!info) {
    info = await api("/files/init", post({ name: file.name, parent_id: parentId, size_bytes: file.size, mime_type: file.type || "application/octet-stream" }));
    writeStorage(key, info);
  }
  const [config, supabase, tus] = await Promise.all([getConfig(), getSupabase(), import("tus-js-client")]);
  const { data } = await supabase.auth.getSession();
  onState("전송 중");
  const storageHost = config.url.endsWith(".supabase.co") ? config.url.replace(".supabase.co", ".storage.supabase.co") : config.url;
  await new Promise<void>((resolve, reject) => {
    const upload = new tus.Upload(file, {
      endpoint: `${storageHost}/storage/v1/upload/resumable`,
      retryDelays: [0, 3000, 5000, 10000, 20000],
      fingerprint: async () => ["skive", userId, info.storage_path, file.name, file.size, file.lastModified].join(":"),
      headers: { authorization: `Bearer ${data.session?.access_token}`, apikey: config.key },
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      chunkSize: 6 * 1024 * 1024,
      metadata: { bucketName: config.bucket, objectName: info.storage_path, contentType: file.type || "application/octet-stream", cacheControl: "3600" },
      onError: reject,
      onProgress,
      onSuccess: () => resolve(),
    });
    upload.findPreviousUploads().then((previous) => {
      if (previous.length) upload.resumeFromPreviousUpload(previous[0]);
      upload.start();
    }).catch(reject);
  });
  onState("완료 처리 중");
  await api(`/files/${info.id}/complete`, { method: "POST" });
  dropStorage(key);
}

export function useUploader(userId: string | undefined, notice: (text: string) => void, changed: () => void) {
  const queue = useRef<Task[]>([]);
  const running = useRef(0);
  const stats = useRef({ total: 0, done: 0, failed: 0, totalBytes: 0, doneBytes: 0, nextKey: 0 });
  const active = useRef(new Map<number, number>());
  const rows = useRef<Row[]>([]);
  const painted = useRef(false);
  const [, setTick] = useState(0);
  const [title, setTitle] = useState<string | null>(null);

  const paint = useCallback(() => {
    if (painted.current) return;
    painted.current = true;
    requestAnimationFrame(() => { painted.current = false; setTick((value) => value + 1); });
  }, []);

  const pump = useCallback(() => {
    if (!userId) return;
    while (running.current < CONCURRENCY && queue.current.length) {
      const task = queue.current.shift()!;
      const stat = stats.current;
      const key = ++stat.nextKey;
      const row: Row = { key, relative: task.relative, state: "준비 중", percent: 0 };
      rows.current = [row, ...rows.current].slice(0, 12);
      running.current++;
      active.current.set(key, 0);
      uploadOne(task, userId, (sent, total) => {
        active.current.set(key, sent);
        row.percent = total ? Math.round((sent / total) * 100) : 100;
        row.state = `전송 중 · ${row.percent}%`;
        paint();
      }, (text) => { row.state = text; paint(); }).then(() => {
        stat.doneBytes += task.file.size;
        stat.done++;
        row.percent = 100;
        row.state = "완료";
      }).catch((error) => {
        stat.failed++;
        row.failed = true;
        row.state = `실패 · ${uploadErrorMessage(error)}`;
        console.error("SKIVE upload failed", task.relative, error);
      }).finally(() => {
        active.current.delete(key);
        running.current--;
        changed();
        paint();
        pump();
        if (!running.current && !queue.current.length) {
          setTitle(stat.failed ? "일부 파일 업로드 실패" : "업로드 완료");
          notice(`${stat.done}개 파일 업로드 완료${stat.failed ? ` · ${stat.failed}개 실패. 같은 폴더를 다시 올리면 이어집니다.` : ""}`);
        }
      });
    }
  }, [userId, paint, changed, notice]);

  const uploadItems = useCallback(async (items: UploadItem[], parentId: string | null) => {
    if (!items.length) return;
    if (!running.current && !queue.current.length) {
      stats.current = { total: 0, done: 0, failed: 0, totalBytes: 0, doneBytes: 0, nextKey: stats.current.nextKey };
      active.current.clear();
      rows.current = [];
    }
    setTitle("폴더 준비 중");
    let folders: Record<string, string> = {};
    const paths = [...new Set(items.map((item) => item.relative.split("/").slice(0, -1).join("/")).filter(Boolean))];
    if (paths.length) {
      try {
        folders = (await api("/folders/import-tree", post({ parent_id: parentId, paths }))).folders;
        changed();
      } catch (error) {
        setTitle("폴더 준비 실패");
        throw error;
      }
    }
    for (const { file, relative } of items) {
      const folderPath = relative.split("/").slice(0, -1).join("/");
      queue.current.push({ file, relative, parentId: folderPath ? folders[folderPath] : parentId });
      stats.current.total++;
      stats.current.totalBytes += file.size;
    }
    setTitle("파일 업로드 중");
    paint();
    pump();
  }, [changed, paint, pump]);

  const stat = stats.current;
  const sent = stat.doneBytes + [...active.current.values()].reduce((sum, value) => sum + value, 0);
  const percent = stat.totalBytes ? Math.min(100, Math.round((sent / stat.totalBytes) * 100)) : stat.total ? Math.round((stat.done / stat.total) * 100) : 0;
  const busy = running.current > 0 || queue.current.length > 0;
  return { uploadItems, panel: title ? { title, percent, busy, done: stat.done, total: stat.total, failed: stat.failed, sent, totalBytes: stat.totalBytes, rows: rows.current, close: () => setTitle(null) } : null };
}

export type UploadPanel = NonNullable<ReturnType<typeof useUploader>["panel"]>;

export function UploadToast({ panel }: { panel: UploadPanel }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (panel.busy || panel.failed) return;
    const timer = setTimeout(panel.close, 8000);
    return () => clearTimeout(timer);
  }, [panel.busy, panel.failed, panel.close]);
  return (
    <div id="upload-panel" role="status" aria-live="polite" className="fixed right-4 bottom-4 z-40 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-surface shadow-lg">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p id="upload-title" className="truncate text-[13px] font-medium">{panel.title}</p>
          <p id="upload-count" className="text-[11px] text-muted">{panel.done}/{panel.total}개{panel.totalBytes ? ` · ${formatSize(panel.sent)} / ${formatSize(panel.totalBytes)}` : ""}{panel.failed ? ` · 실패 ${panel.failed}개` : ""}</p>
        </div>
        <span className="text-xs font-medium text-accent">{panel.percent}%</span>
        <Button variant="ghost" size="icon" className="h-6 w-6" aria-label={open ? "목록 접기" : "목록 펼치기"} onClick={() => setOpen(!open)}>{open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}</Button>
        {!panel.busy && <Button variant="ghost" size="icon" className="h-6 w-6" aria-label="닫기" onClick={panel.close}><X className="h-3.5 w-3.5" /></Button>}
      </div>
      <div className="h-1 overflow-hidden rounded-b bg-hover"><div className="h-full bg-accent transition-all" style={{ width: `${panel.percent}%` }} /></div>
      {open && (
        <div className="max-h-56 overflow-y-auto border-t border-line px-3 py-2">
          {panel.rows.map((row) => (
            <div key={row.key} className="py-1">
              <p className="truncate text-xs" title={row.relative}>{row.relative}</p>
              <p className={cn("truncate text-[11px] text-muted", row.failed && "text-danger")} title={row.state}>{row.state}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

async function readEntry(entry: any, prefix: string, out: UploadItem[]): Promise<void> {
  if (entry.isFile) {
    const file: File = await new Promise((resolve, reject) => entry.file(resolve, reject));
    out.push({ file, relative: prefix + file.name });
    return;
  }
  const reader = entry.createReader();
  for (;;) { // readEntries returns at most about 100 entries per call.
    const batch: any[] = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) return;
    for (const child of batch) await readEntry(child, `${prefix}${entry.name}/`, out);
  }
}

/** Must be called synchronously in the drop event: entries expire when it ends. */
export function droppedItems(data: DataTransfer): Promise<UploadItem[]> {
  const entries = [...data.items].filter((item) => item.kind === "file").map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  const files = [...data.files];
  return (async () => {
    if (!entries.length) return files.map((file) => ({ file, relative: file.name }));
    const out: UploadItem[] = [];
    for (const entry of entries) await readEntry(entry, "", out);
    return out;
  })();
}
