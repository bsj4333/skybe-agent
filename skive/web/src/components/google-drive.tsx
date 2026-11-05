"use client";

import { ArrowUp, CloudDownload, FileText, Folder, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, errorText, optional, post } from "@/lib/skive";
import { Badge, Button, Card, Dialog, RowsSkeleton } from "@/components/ui";
import { useApp } from "@/components/app-shell";

const FOLDER = "application/vnd.google-apps.folder";
export type GoogleStatus = { enabled: boolean; connected: boolean; email: string | null; needs_reconnect: boolean };
const OFF: GoogleStatus = { enabled: false, connected: false, email: null, needs_reconnect: false };

export function useGoogleStatus() {
  const { fail } = useApp();
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const refresh = useCallback(async () => {
    try {
      setStatus(await optional(api<GoogleStatus>("/google/status"), OFF));
    } catch (error) {
      fail(error);
      setStatus(OFF);
    }
  }, [fail]);
  useEffect(() => { refresh(); }, [refresh]);
  return { status, refresh };
}

export async function connectGoogle() {
  const { url } = await api("/google/connect", post());
  window.location.href = url;
}

export function GoogleImportDialog({ open, parentId, onClose, onStarted }: { open: boolean; parentId: string | null; onClose: () => void; onStarted: () => void }) {
  const { fail } = useApp();
  const [trail, setTrail] = useState<{ name: string; parent: string }[]>([{ name: "내 드라이브", parent: "root" }]);
  const [files, setFiles] = useState<any[] | null>(null);
  const [selected, setSelected] = useState<Map<string, any>>(new Map());
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const place = trail[trail.length - 1];

  useEffect(() => {
    if (!open) return;
    setFiles(null);
    setMessage("");
    api(`/google/files?parent=${encodeURIComponent(place.parent)}`)
      .then((result) => setFiles(result.files))
      .catch((error) => { setFiles([]); setMessage(errorText(error)); });
  }, [open, place.parent]);

  useEffect(() => { if (open) { setSelected(new Map()); setTrail([{ name: "내 드라이브", parent: "root" }]); } }, [open]);

  const toggle = (item: any) => setSelected((current) => {
    const next = new Map(current);
    if (next.has(item.id)) next.delete(item.id); else next.set(item.id, item);
    return next;
  });

  const start = async () => {
    setBusy(true);
    try {
      await api("/google/imports", post({ items: [...selected.values()], parent_id: parentId }));
      onStarted();
      onClose();
    } catch (error) { fail(error); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={onClose} size="lg" title="구글 드라이브에서 가져오기" footer={(
      <>
        <Button onClick={onClose}>닫기</Button>
        <Button variant="primary" disabled={!selected.size || busy} onClick={start}>{selected.size ? `선택한 ${selected.size}개 가져오기` : "선택한 항목 가져오기"}</Button>
      </>
    )}>
      <div className="mb-2 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setTrail([{ name: "내 드라이브", parent: "root" }])}>내 드라이브</Button>
        <Button size="sm" onClick={() => setTrail([{ name: "공유 문서함", parent: "shared" }])}>공유 문서함</Button>
        <Button size="sm" disabled={trail.length < 2} onClick={() => setTrail(trail.slice(0, -1))}><ArrowUp className="h-3.5 w-3.5" />위로</Button>
      </div>
      <p className="mb-2 truncate text-xs text-muted">{trail.map((step) => step.name).join(" / ")}</p>
      <div className="h-[45vh] overflow-y-auto rounded-md border border-line">
        {files === null ? <div className="p-2"><RowsSkeleton /></div> : files.map((item) => (
          <label key={item.id} className="flex items-center gap-2 border-b border-line px-3 py-2 text-[13px] last:border-0 hover:bg-hover">
            <input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item)} />
            {item.mimeType === FOLDER ? (
              <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={(event) => { event.preventDefault(); setTrail([...trail, { name: item.name, parent: item.id }]); }}>
                <Folder className="h-4 w-4 shrink-0 text-accent" /><span className="truncate">{item.name}</span>
              </button>
            ) : <span className="flex min-w-0 flex-1 items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-muted" /><span className="truncate">{item.name}</span></span>}
          </label>
        ))}
        {files?.length === 0 && !message && <p className="p-6 text-center text-[13px] text-muted">이 위치에는 항목이 없습니다.</p>}
      </div>
      {message && <p className="mt-2 text-[13px] text-danger">{message}</p>}
      <p className="mt-2 text-xs text-muted">원본은 구글 드라이브에 그대로 두고, 스카이브는 읽은 글자만 보관합니다.</p>
    </Dialog>
  );
}

export function GoogleImportProgress({ watch }: { watch: number }) {
  const { notice } = useApp();
  const [job, setJob] = useState<any>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const result = await optional(api("/google/imports/latest"), {});
        if (stopped) return;
        const running = result.status === "queued" || result.status === "processing";
        const recent = result.updated_at && Date.now() - Date.parse(result.updated_at) < 60000;
        setJob(running || recent ? result : null);
        if (running) timer = setTimeout(tick, 3000);
        else if (result.error && recent) notice(result.error);
      } catch {
        setJob(null);
      }
    };
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [watch, notice]);

  if (!job?.id) return null;
  const running = job.status === "queued" || job.status === "processing";
  const finished = job.done + job.failed;
  const percent = job.total ? Math.round((finished / job.total) * 100) : 0;
  return (
    <div className="mb-3 rounded-md border border-line px-3 py-2">
      <div className="flex items-center gap-2 text-[13px]">
        {running && <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />}
        <span className="font-medium">{running ? "구글 드라이브에서 가져오는 중" : job.status === "failed" ? "구글 드라이브 가져오기 실패" : "구글 드라이브 가져오기 완료"}</span>
        <span className="text-xs text-muted">{job.total ? `${finished}/${job.total}개` : "목록 확인 중"}</span>
      </div>
      <p className="text-xs text-muted">{job.error || `${job.failed ? `실패 ${job.failed}개 · ` : ""}${job.skipped ? `파일이 아닌 항목 ${job.skipped}개 제외 · ` : ""}서버에서 처리 중입니다. 서버가 잠들면 다음 접속 때 이어집니다.`}</p>
    </div>
  );
}

export function GoogleConnectCard() {
  const { fail, notice } = useApp();
  const { status: google, refresh } = useGoogleStatus();
  const [importing, setImporting] = useState(false);
  const [watch, setWatch] = useState(0);
  if (!google?.enabled) return null;
  const ready = google.connected && !google.needs_reconnect;
  const disconnect = async () => {
    if (!confirm("구글 드라이브 연결을 해제할까요? 이미 읽은 글자 내용은 남고, 새 파일 읽기와 갱신은 멈춥니다.")) return;
    try {
      await api("/google/connection", { method: "DELETE" });
      await refresh();
      notice("구글 드라이브 연결을 해제했습니다.");
    } catch (error) { fail(error); }
  };
  return (
    <Card>
      <div className="mb-1 flex items-center gap-2">
        <h2 className="font-semibold">구글 드라이브</h2>
        {ready && <Badge tone="accent">연결됨</Badge>}
        {google.needs_reconnect && <Badge tone="warn">다시 연동 필요</Badge>}
      </div>
      <p id="google-state" className="mb-3 text-[13px] text-muted">{google.needs_reconnect ? "구글 연결이 만료되었습니다. 다시 연동해 주세요." : google.connected ? (google.email ?? "구글 계정") : "연동하면 구글 드라이브의 폴더를 바로 가져올 수 있습니다."}</p>
      <GoogleImportProgress watch={watch} />
      <div className="flex flex-wrap gap-2">
        {!ready && <Button id="google-connect" variant="primary" onClick={() => connectGoogle().catch(fail)}>{google.needs_reconnect ? "다시 연동하기" : "구글 드라이브 연동하기"}</Button>}
        {ready && <Button id="google-import" onClick={() => setImporting(true)}><CloudDownload className="h-3.5 w-3.5" />폴더 가져오기</Button>}
        {google.connected && <Button id="google-disconnect" onClick={disconnect}>연결 해제</Button>}
      </div>
      <GoogleImportDialog open={importing} parentId={null} onClose={() => setImporting(false)} onStarted={() => setWatch((value) => value + 1)} />
    </Card>
  );
}
