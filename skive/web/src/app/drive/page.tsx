"use client";

import { ArrowDown, ArrowUp, ChevronRight, CloudDownload, Download, ExternalLink, File as FileIcon, FileText, Folder, FolderInput, FolderOpen, FolderPlus, LayoutGrid, Link2, List, MessageSquare, MoreHorizontal, Pencil, RefreshCw, Search, Sparkles, Trash2, Upload, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ANALYSIS_LABEL, api, cn, formatDate, formatSize, patch, post } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { openOriginal } from "@/components/file-viewer";
import { connectGoogle, GoogleImportDialog, GoogleImportProgress, useGoogleStatus } from "@/components/google-drive";
import { ExperiencePicker, FolderPicker } from "@/components/pickers";
import { Badge, Button, Dialog, EmptyState, Field, Input, Menu, MenuItem, RowsSkeleton } from "@/components/ui";

type Row = { kind: "folder" | "file"; item: any };
type SortKey = "name" | "date" | "size";

const statusText = (row: Row) => row.kind === "folder" ? "폴더" : row.item.upload_status === "pending" ? "업로드 대기" : ANALYSIS_LABEL[row.item.analysis_status] ?? "—";

function NameDialog({ title, initial, onClose, onSave }: { title: string; initial: string; onClose: () => void; onSave: (name: string) => void }) {
  const [name, setName] = useState(initial);
  return (
    <Dialog open onClose={onClose} size="sm" title={title} footer={<><Button onClick={onClose}>취소</Button><Button variant="primary" disabled={!name.trim()} onClick={() => onSave(name.trim())}>저장</Button></>}>
      <Field label="이름"><Input autoFocus value={name} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && name.trim()) onSave(name.trim()); }} /></Field>
    </Dialog>
  );
}

export default function DrivePage() {
  const { fail, notice, openFile, openProject, uploadItems, driveVersion } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const folderId = params.get("folder");
  const query = params.get("q") ?? "";
  const [data, setData] = useState<{ folders: any[]; files: any[] } | null>(null);
  const [crumbs, setCrumbs] = useState<any[]>([]);
  const [search, setSearch] = useState(query);
  const [summary, setSummary] = useState<any>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [direction, setDirection] = useState(1);
  const [grid, setGrid] = useState(false);
  const [selected, setSelected] = useState<Row | null>(null);
  const [nameDialog, setNameDialog] = useState<null | { title: string; initial: string; save: (name: string) => Promise<void> }>(null);
  const [moving, setMoving] = useState<Row | null>(null);
  const [linkFile, setLinkFile] = useState<string | null>(null);
  const [googleOpen, setGoogleOpen] = useState(false);
  const [importWatch, setImportWatch] = useState(0);
  const [bannerOff, setBannerOff] = useState(true);
  const { status: google } = useGoogleStatus();
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => { try { setBannerOff(localStorage.getItem("skive-google-banner") === "off"); } catch { setBannerOff(false); } }, []);
  useEffect(() => setSearch(query), [query]);

  const load = useCallback(async () => {
    const items = query ? await api(`/search?q=${encodeURIComponent(query)}`) : await api(`/items${folderId ? `?parent_id=${folderId}` : ""}`);
    setData(items);
    setCrumbs(folderId && !query ? await api(`/folders/${folderId}/breadcrumbs`) : []);
  }, [folderId, query]);

  useEffect(() => { setData(null); setSelected(null); load().catch(fail); }, [load, fail]);
  useEffect(() => { if (driveVersion) load().catch(() => {}); }, [driveVersion, load]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const result = await api("/summary");
        if (!alive) return;
        setSummary(result);
        const pending = result.total_files - result.uploaded_files + result.uploaded_files - (result.analyzed_files + result.analysis_issues);
        if (pending) load().catch(() => {});
      } catch {}
    };
    tick();
    const timer = setInterval(tick, 10000);
    return () => { alive = false; clearInterval(timer); };
  }, [load]);

  const rows = useMemo<Row[]>(() => {
    if (!data) return [];
    const collator = new Intl.Collator("ko", { numeric: true, sensitivity: "base" });
    const value = (item: any) => sortKey === "name" ? item.name : sortKey === "date" ? Date.parse(item.updated_at || 0) || 0 : item.size_bytes ?? -1;
    return [...data.folders.map((item) => ({ kind: "folder" as const, item })), ...data.files.map((item) => ({ kind: "file" as const, item }))].sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
      const left = value(a.item), right = value(b.item);
      const difference = typeof left === "string" ? collator.compare(left, right) : left - right;
      return difference * direction || collator.compare(a.item.name, b.item.name);
    });
  }, [data, sortKey, direction]);

  const sort = (key: SortKey) => {
    if (sortKey === key) setDirection(-direction);
    else { setSortKey(key); setDirection(key === "date" ? -1 : 1); }
  };

  const goFolder = (id: string | null) => router.push(id ? `/drive?folder=${id}` : "/drive");
  const open = (row: Row) => row.kind === "folder" ? goFolder(row.item.id) : openFile(row.item.id);
  const refresh = () => load().catch(fail);

  const rename = (row: Row) => setNameDialog({
    title: "이름 변경", initial: row.item.name,
    save: async (name) => { await api(`/${row.kind}s/${row.item.id}`, patch({ name })); await load(); },
  });
  const remove = async (row: Row) => {
    if (!confirm(`${row.item.name}을(를) 휴지통으로 이동할까요?`)) return;
    try {
      await api(`/${row.kind}s/${row.item.id}`, { method: "DELETE" });
      setSelected(null);
      await load();
    } catch (error) { fail(error); }
  };
  const newFolder = () => setNameDialog({
    title: "새 폴더", initial: "",
    save: async (name) => { await api("/folders", post({ name, parent_id: folderId })); await load(); },
  });
  const pickFiles = (input: HTMLInputElement, isFolder: boolean) => {
    const items = [...(input.files ?? [])].map((file) => ({ file, relative: isFolder ? file.webkitRelativePath : file.name }));
    input.value = "";
    uploadItems(items, folderId).catch(fail);
  };

  const pendingUpload = summary ? summary.total_files - summary.uploaded_files : 0;
  const analysisDone = summary ? summary.analyzed_files + summary.analysis_issues : 0;
  const pendingAnalysis = summary ? summary.uploaded_files - analysisDone : 0;
  const syncPercent = !summary ? 0 : pendingUpload ? (summary.total_bytes ? Math.round((100 * summary.uploaded_bytes) / summary.total_bytes) : 0) : summary.uploaded_files ? Math.round((100 * analysisDone) / summary.uploaded_files) : 0;
  const showBanner = google?.enabled && !google.connected && !bannerOff;

  const rowActions = (row: Row, close: () => void) => {
    const run = (action: () => unknown) => () => { close(); Promise.resolve(action()).catch(fail); };
    return (
      <>
        {row.kind === "file" && <MenuItem icon={FileText} onClick={run(() => openFile(row.item.id))}>원문·읽기 상태</MenuItem>}
        {row.kind === "file" && <MenuItem icon={Link2} onClick={run(() => setLinkFile(row.item.id))}>경험에 연결</MenuItem>}
        {row.kind === "file" && row.item.source === "google" && <MenuItem icon={ExternalLink} onClick={run(() => openOriginal(row.item))}>구글 드라이브에서 열기</MenuItem>}
        {row.kind === "file" && row.item.source !== "google" && row.item.upload_status === "uploaded" && <MenuItem icon={Download} onClick={run(() => openOriginal(row.item))}>다운로드</MenuItem>}
        {row.kind === "folder" && <MenuItem icon={Sparkles} onClick={run(() => openProject(row.item.id))}>프로젝트 통합 요약</MenuItem>}
        <MenuItem icon={Pencil} onClick={run(() => rename(row))}>이름 변경</MenuItem>
        <MenuItem icon={FolderInput} onClick={run(() => setMoving(row))}>이동</MenuItem>
        <MenuItem icon={Trash2} danger onClick={run(() => remove(row))}>휴지통으로 이동</MenuItem>
      </>
    );
  };

  const header = (key: SortKey, label: string, className = "") => (
    <button type="button" onClick={() => sort(key)} aria-sort={sortKey === key ? (direction === 1 ? "ascending" : "descending") : "none"} className={cn("flex items-center gap-1 text-left text-xs font-medium text-muted hover:text-ink", className)}>
      {label}{sortKey === key && (direction === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
    </button>
  );

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1 overflow-y-auto px-4 py-4 md:px-8 md:py-6">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <nav aria-label="폴더 경로" className="flex min-w-0 flex-1 flex-wrap items-center gap-0.5 text-[15px]">
            <button type="button" className="rounded px-1.5 py-0.5 font-semibold hover:bg-hover" onClick={() => goFolder(null)}>내 드라이브</button>
            {crumbs.map((crumb, index) => (
              <span key={crumb.id} className="flex items-center gap-0.5">
                <ChevronRight className="h-3.5 w-3.5 text-muted" />
                <button type="button" aria-current={index === crumbs.length - 1 ? "page" : undefined} className="max-w-48 truncate rounded px-1.5 py-0.5 font-semibold hover:bg-hover" onClick={() => goFolder(crumb.id)}>{crumb.name}</button>
              </span>
            ))}
            {query && <span className="flex items-center gap-1 text-muted"><ChevronRight className="h-3.5 w-3.5" />검색: {query}</span>}
          </nav>
          <form className="relative w-full sm:w-64" onSubmit={(event) => { event.preventDefault(); router.push(search.trim() ? `/drive?q=${encodeURIComponent(search.trim())}` : "/drive"); }}>
            <Search className="absolute top-2 left-2 h-4 w-4 text-muted" />
            <Input id="search" className="pl-8" placeholder="내 드라이브에서 검색" aria-label="드라이브 검색" value={search} onChange={(event) => setSearch(event.target.value)} />
          </form>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <Button onClick={newFolder}><FolderPlus className="h-3.5 w-3.5" />새 폴더</Button>
          <Button onClick={() => fileInput.current?.click()}><Upload className="h-3.5 w-3.5" />파일 업로드</Button>
          <Button onClick={() => folderInput.current?.click()}><FolderOpen className="h-3.5 w-3.5" />폴더 업로드</Button>
          {google?.enabled && <Button id="import-gdrive" onClick={() => (google.connected && !google.needs_reconnect ? setGoogleOpen(true) : connectGoogle().catch(fail))}><CloudDownload className="h-3.5 w-3.5" />구글 드라이브</Button>}
          {folderId && <Button id="project-summary" onClick={() => openProject(folderId)}><Sparkles className="h-3.5 w-3.5" />프로젝트 통합 요약</Button>}
          {folderId && <Link prefetch={false} href={`/chat?folder=${folderId}`}><Button><MessageSquare className="h-3.5 w-3.5" />이 폴더로 대화</Button></Link>}
          <span className="flex-1" />
          <span className="text-xs text-muted">{data ? `폴더 ${data.folders.length} · 파일 ${data.files.length}` : ""}</span>
          <Button variant="ghost" size="icon" aria-label="새로고침" id="refresh" onClick={refresh}><RefreshCw className="h-3.5 w-3.5" /></Button>
          <Button variant="ghost" size="icon" aria-label={grid ? "목록으로 보기" : "격자로 보기"} onClick={() => setGrid(!grid)}>{grid ? <List className="h-3.5 w-3.5" /> : <LayoutGrid className="h-3.5 w-3.5" />}</Button>
        </div>
        <input ref={fileInput} type="file" multiple hidden id="file-input" onChange={(event) => pickFiles(event.target, false)} />
        <input ref={folderInput} type="file" multiple hidden id="folder-input" {...({ webkitdirectory: "" } as object)} onChange={(event) => pickFiles(event.target, true)} />

        {showBanner && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-line bg-accent-soft px-3 py-2 text-[13px]">
            <span className="min-w-52 flex-1">구글 드라이브를 연동하면 과제와 프로젝트 폴더를 바로 가져올 수 있어요.</span>
            <Button variant="primary" size="sm" onClick={() => connectGoogle().catch(fail)}>구글 드라이브 연동하기</Button>
            <Button size="sm" onClick={() => { try { localStorage.setItem("skive-google-banner", "off"); } catch {} setBannerOff(true); }}>나중에</Button>
          </div>
        )}
        <GoogleImportProgress watch={importWatch} />
        {(pendingUpload > 0 || pendingAnalysis > 0) && (
          <div className="mb-3 rounded-md border border-line px-3 py-2 text-xs text-muted" role="status">
            {pendingUpload > 0 ? `서버 저장 ${summary.uploaded_files}/${summary.total_files}개 · ${formatSize(summary.uploaded_bytes)} / ${formatSize(summary.total_bytes)}` : `자료 읽는 중 ${analysisDone}/${summary.uploaded_files}개 · 읽기 미지원·실패 ${summary.analysis_issues}개`}
            <div className="mt-1 h-1 overflow-hidden rounded bg-hover"><div className="h-full bg-accent" style={{ width: `${syncPercent}%` }} /></div>
          </div>
        )}

        {!data ? <RowsSkeleton rows={8} /> : !rows.length ? (
          <EmptyState icon={query ? Search : FolderOpen} title={query ? "검색 결과가 없습니다" : "아직 파일이 없습니다"} hint={query ? undefined : "파일이나 폴더를 이 화면에 끌어다 놓거나 업로드 버튼을 눌러 주세요."} />
        ) : grid ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {rows.map((row) => (
              <div key={row.item.id} className={cn("group relative rounded-lg border border-line p-3 hover:bg-hover", selected?.item.id === row.item.id && "border-accent")} onClick={() => setSelected(row)}>
                <button type="button" className="name-button block w-full min-w-0 text-left" onDoubleClick={() => open(row)} onClick={(event) => { event.stopPropagation(); open(row); }}>
                  {row.kind === "folder" ? <Folder className="mb-2 h-6 w-6 text-accent" /> : <FileIcon className="mb-2 h-6 w-6 text-muted" />}
                  <p className="truncate text-[13px]" title={row.item.name}>{row.item.name}</p>
                </button>
                <p className="mt-0.5 text-[11px] text-muted">{statusText(row)}</p>
              </div>
            ))}
          </div>
        ) : (
          <div role="table" aria-label="드라이브 파일 목록">
            <div className="grid grid-cols-[minmax(0,1fr)_32px] items-center gap-2 border-b border-line px-2 py-1.5 sm:grid-cols-[minmax(0,1fr)_100px_80px_90px_32px]">
              {header("name", "이름")}
              {header("date", "수정 날짜", "hidden sm:flex")}
              {header("size", "크기", "hidden sm:flex")}
              <span className="hidden text-xs font-medium text-muted sm:block">읽기 상태</span>
              <span />
            </div>
            <div id="items">
              {rows.map((row) => (
                <div key={row.item.id} role="row" onClick={() => setSelected(row)} className={cn("drive-row grid grid-cols-[minmax(0,1fr)_32px] items-center gap-2 border-b border-line px-2 py-1 hover:bg-hover sm:grid-cols-[minmax(0,1fr)_100px_80px_90px_32px]", selected?.item.id === row.item.id && "bg-accent-soft")}>
                  <button type="button" title={row.item.name} className="name-button flex min-w-0 items-center gap-2 py-1 text-left text-[13px]" onClick={(event) => { event.stopPropagation(); open(row); }}>
                    {row.kind === "folder" ? <Folder className="h-4 w-4 shrink-0 text-accent" /> : <FileIcon className="h-4 w-4 shrink-0 text-muted" />}
                    <span className="truncate">{row.item.name}</span>
                    {row.item.source === "google" && <Badge className="hidden sm:inline-flex">구글</Badge>}
                  </button>
                  <span className="hidden text-xs text-muted sm:block">{formatDate(row.item.updated_at)}</span>
                  <span className="hidden text-xs text-muted sm:block">{row.kind === "folder" ? "—" : formatSize(row.item.size_bytes || 0)}</span>
                  <span className="hidden truncate text-xs text-muted sm:block">{statusText(row)}</span>
                  <div onClick={(event) => event.stopPropagation()}>
                    <Menu trigger={(toggle) => <Button variant="ghost" size="icon" className="row-more h-7 w-7" aria-label={`${row.item.name} 더보기`} onClick={toggle}><MoreHorizontal className="h-4 w-4" /></Button>}>
                      {(close) => rowActions(row, close)}
                    </Menu>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {selected && (
        <aside className="hidden w-72 shrink-0 overflow-y-auto border-l border-line p-4 lg:block" aria-label="상세 정보">
          <div className="mb-3 flex items-start justify-between gap-2">
            <p className="min-w-0 font-semibold break-words">{selected.item.name}</p>
            <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" aria-label="상세 닫기" onClick={() => setSelected(null)}><X className="h-3.5 w-3.5" /></Button>
          </div>
          <dl className="space-y-2 text-xs">
            <div><dt className="text-muted">종류</dt><dd>{selected.kind === "folder" ? "폴더" : selected.item.mime_type}</dd></div>
            {selected.kind === "file" && <div><dt className="text-muted">크기</dt><dd>{formatSize(selected.item.size_bytes || 0)}</dd></div>}
            <div><dt className="text-muted">수정 날짜</dt><dd>{formatDate(selected.item.updated_at)}</dd></div>
            <div><dt className="text-muted">상태</dt><dd>{statusText(selected)}</dd></div>
            {selected.item.source === "google" && <div><dt className="text-muted">원본 위치</dt><dd>구글 드라이브</dd></div>}
            {selected.item.analysis_error && <div><dt className="text-muted">오류</dt><dd className="text-danger">{selected.item.analysis_error}</dd></div>}
          </dl>
          <div className="mt-4 flex flex-col gap-1.5">
            <Button onClick={() => open(selected)}>{selected.kind === "folder" ? "폴더 열기" : "원문 보기"}</Button>
            {selected.kind === "file" && <Button onClick={() => setLinkFile(selected.item.id)}>경험에 연결</Button>}
          </div>
        </aside>
      )}

      {nameDialog && <NameDialog title={nameDialog.title} initial={nameDialog.initial} onClose={() => setNameDialog(null)} onSave={(name) => { nameDialog.save(name).then(() => setNameDialog(null)).catch(fail); }} />}
      <FolderPicker open={!!moving} onClose={() => setMoving(null)} onPick={(target) => {
        const row = moving!;
        setMoving(null);
        api(`/${row.kind}s/${row.item.id}/move`, post({ parent_id: target })).then(() => { notice("이동했습니다."); return load(); }).catch(fail);
      }} />
      <ExperiencePicker fileId={linkFile} onClose={() => setLinkFile(null)} />
      <GoogleImportDialog open={googleOpen} parentId={folderId} onClose={() => setGoogleOpen(false)} onStarted={() => setImportWatch((value) => value + 1)} />
    </div>
  );
}
