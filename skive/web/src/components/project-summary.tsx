"use client";

import { Download, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, saveText } from "@/lib/skive";
import { Button, Dialog, RowsSkeleton } from "@/components/ui";
import { useApp } from "@/components/app-shell";

export function ProjectSummary({ folderId, onClose }: { folderId: string | null; onClose: () => void }) {
  const { fail, notice } = useApp();
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (folderId) setData(await api(`/folders/${folderId}/project-summary`));
  }, [folderId]);

  useEffect(() => {
    setData(null);
    load().catch((error) => { fail(error); onClose(); });
  }, [load, fail, onClose]);

  const pending = data?.status === "queued" || data?.status === "processing";
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => load().catch(() => {}), 8000);
    return () => clearInterval(timer);
  }, [pending, load]);

  const generate = async () => {
    setBusy(true);
    try {
      const target = data?.status === "ready" && data?.root_folder_id ? data.root_folder_id : folderId;
      await api(`/folders/${target}/project-summary`, { method: "POST" });
      notice("프로젝트 분석을 시작했습니다.");
      await load();
    } catch (error) { fail(error); } finally { setBusy(false); }
  };

  const coverage = data?.coverage ?? {};
  const status = !data ? "" : data.status === "missing" ? "이 폴더와 하위 폴더를 하나의 프로젝트로 분석합니다."
    : data.status === "queued" ? "파일 읽기가 끝나는 대로 분석을 시작합니다."
    : data.status === "processing" ? "폴더 구조와 원문을 조사하고 있습니다."
    : data.status === "failed" ? "프로젝트 분석에 실패했습니다. 다시 시도해 주세요."
    : `${data.stale ? "자료가 바뀌어 갱신이 필요합니다 · " : ""}파일 ${coverage.files_total ?? 0}개 · 글자 추출 ${coverage.text_ready ?? 0}개`;

  return (
    <Dialog open={!!folderId} onClose={onClose} size="lg" title={`${data?.root_name ?? "프로젝트"} · 통합 요약`} footer={data && (
      <>
        {data.status === "ready" && data.markdown && <Button onClick={() => saveText(`${data.root_name || "project"}_SKIVE_요약.md`, data.markdown)}><Download className="h-3.5 w-3.5" />MD 내려받기</Button>}
        <Button onClick={() => load().catch(fail)}><RefreshCw className="h-3.5 w-3.5" />새로고침</Button>
        {!pending && <Button variant="primary" disabled={busy} onClick={generate}><Sparkles className="h-3.5 w-3.5" />{data.status === "ready" ? "다시 분석" : "프로젝트로 분석"}</Button>}
      </>
    )}>
      {!data ? <RowsSkeleton /> : (
        <div className="space-y-3">
          <p className="rounded-md bg-hover px-3 py-2 text-[13px]">{status}</p>
          {data.status === "failed" && <p className="text-[13px] text-danger">{data.error || "오류 내용이 없습니다."}</p>}
          {data.status === "ready" && <div className="prose-md" id="project-summary-markdown">{data.markdown}</div>}
        </div>
      )}
    </Dialog>
  );
}
