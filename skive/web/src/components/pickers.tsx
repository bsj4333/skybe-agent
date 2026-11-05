"use client";

import { ArrowUp, Folder, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/skive";
import { Button, Dialog, RowsSkeleton } from "@/components/ui";
import { useApp } from "@/components/app-shell";

export function FolderPicker({ open, onClose, onPick, title = "이동할 폴더", action = "여기로 이동" }: { open: boolean; onClose: () => void; onPick: (folderId: string | null) => void; title?: string; action?: string }) {
  const { fail } = useApp();
  const [selected, setSelected] = useState<string | null>(null);
  const [path, setPath] = useState<any[]>([]);
  const [folders, setFolders] = useState<any[] | null>(null);

  useEffect(() => { if (open) setSelected(null); }, [open]);
  useEffect(() => {
    if (!open) return;
    setFolders(null);
    Promise.all([selected ? api(`/folders/${selected}/breadcrumbs`) : Promise.resolve([]), api(`/items${selected ? `?parent_id=${selected}` : ""}`)])
      .then(([crumbs, items]) => { setPath(crumbs); setFolders(items.folders); })
      .catch(fail);
  }, [open, selected, fail]);

  return (
    <Dialog open={open} onClose={onClose} size="sm" title={title} footer={<><Button onClick={onClose}>취소</Button><Button variant="primary" onClick={() => onPick(selected)}>{action}</Button></>}>
      <p className="mb-2 truncate text-xs text-muted">{path.length ? path.map((item) => item.name).join(" › ") : "내 드라이브"}</p>
      {selected && <button type="button" className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-[13px] hover:bg-hover" onClick={() => setSelected(path[path.length - 2]?.id ?? null)}><ArrowUp className="h-4 w-4" />상위 폴더</button>}
      {folders === null ? <RowsSkeleton rows={3} /> : folders.map((folder) => (
        <button key={folder.id} type="button" className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] hover:bg-hover" onClick={() => setSelected(folder.id)}>
          <Folder className="h-4 w-4 shrink-0 text-accent" /><span className="truncate">{folder.name}</span>
        </button>
      ))}
      {folders?.length === 0 && <p className="py-3 text-center text-xs text-muted">하위 폴더가 없습니다.</p>}
    </Dialog>
  );
}

export function ExperiencePicker({ fileId, onClose }: { fileId: string | null; onClose: () => void }) {
  const { fail, notice } = useApp();
  const [items, setItems] = useState<any[] | null>(null);

  useEffect(() => {
    if (!fileId) return;
    setItems(null);
    api("/activities").then(setItems).catch(fail);
  }, [fileId, fail]);

  const link = async (id: string) => {
    try {
      await api(`/activities/${id}/files/${fileId}`, { method: "PUT" });
      notice("파일을 경험에 연결했습니다.");
      onClose();
    } catch (error) { fail(error); }
  };

  return (
    <Dialog open={!!fileId} onClose={onClose} size="sm" title="연결할 경험 선택">
      {items === null ? <RowsSkeleton rows={3} /> : items.length ? items.map((item) => (
        <button key={item.id} type="button" className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] hover:bg-hover" onClick={() => link(item.id)}>
          <Sparkles className="h-4 w-4 shrink-0 text-accent" /><span className="min-w-0 flex-1 truncate">{item.title}</span><span className="text-xs text-muted">파일 {item.file_count}</span>
        </button>
      )) : <p className="py-4 text-center text-[13px] text-muted">아직 경험이 없습니다. 내 경험 화면에서 만들어 주세요.</p>}
    </Dialog>
  );
}
