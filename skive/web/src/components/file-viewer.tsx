"use client";

import { Download, ExternalLink, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ANALYSIS_LABEL, api, formatSize, getConfig, getSupabase } from "@/lib/skive";
import { Badge, Button, Dialog, RowsSkeleton, Tabs } from "@/components/ui";
import { useApp } from "@/components/app-shell";

export async function openOriginal(file: any) {
  if (file.source === "google") {
    if (!file.google_web_url) throw new Error("구글 드라이브 링크가 없습니다");
    window.open(file.google_web_url, "_blank", "noopener");
    return;
  }
  if (file.upload_status !== "uploaded") throw new Error("업로드가 아직 끝나지 않았습니다");
  const [config, supabase] = await Promise.all([getConfig(), getSupabase()]);
  const { data, error } = await supabase.storage.from(config.bucket).createSignedUrl(file.storage_path, 60, { download: file.name });
  if (error) throw error;
  window.location.href = data.signedUrl;
}

function coverageLines(result: any): string[] {
  const details = result.analysis_coverage?.supplemental;
  if (result.analysis_status !== "ready") return [`현재 상태: ${ANALYSIS_LABEL[result.analysis_status] ?? result.analysis_status}. 추출이 끝나면 범위를 확인할 수 있습니다.`];
  if (!Array.isArray(details)) return ["세부 범위 기록이 없는 파일입니다. 다시 읽으면 주석과 노트 검사 결과가 표시됩니다."];
  if (!details.length) return ["이 형식에는 별도로 검사할 주석이나 노트가 없습니다."];
  return details.map((item: any) => {
    if (item.status === "absent") return `${item.label}: 없음 (검사함)`;
    if (item.status === "complete") return `${item.label}: ${item.extracted}개 읽음`;
    if (item.status === "partial") return `${item.label}: ${item.detected}개 중 ${item.extracted}개 읽음`;
    return `${item.label}: 검사 불완전${item.detail ? ` · ${item.detail}` : ""}`;
  });
}

const chunkLabel = (chunk: any) => `C${chunk.chunk_index} · ${chunk.location}`;

function Chunk({ chunk }: { chunk: any }) {
  return (
    <div className="rounded-md border border-line p-3">
      <p className="mb-1 text-[11px] text-muted">{chunkLabel(chunk)}</p>
      <p className="prose-md">{chunk.text}</p>
    </div>
  );
}

function ReadCard({ fileId }: { fileId: string }) {
  const { fail } = useApp();
  const [data, setData] = useState<any>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [after, setAfter] = useState(0);
  const [focus, setFocus] = useState<any>(null);

  const more = useCallback(async (from: number) => {
    const result = await api(`/files/${fileId}/read-card/chunks?after=${from}&limit=20`);
    setChunks((current) => (from === 0 ? result.chunks : [...current, ...result.chunks]));
    setAfter(result.next_after || 0);
  }, [fileId]);

  useEffect(() => {
    api(`/files/${fileId}/read-card`).then((result) => {
      setData(result);
      if (result.card) return more(0);
    }).catch(fail);
  }, [fileId, more, fail]);

  const open = async (index: number) => {
    try {
      const result = await api(`/files/${fileId}/read-card/chunks?after=${index - 1}&limit=1`);
      setFocus(result.chunks[0] ?? null);
    } catch (error) { fail(error); }
  };

  if (!data) return <RowsSkeleton rows={4} />;
  const card = data.card;
  if (!card) return <p className="text-[13px] text-muted">읽기 상태: {ANALYSIS_LABEL[data.state] ?? data.state}{data.file?.analysis_error ? ` · ${data.file.analysis_error}` : ""}. 준비되면 다시 열어 주세요.</p>;
  const samples = (title: string, items: any[], empty: string) => (
    <section>
      <h3 className="mb-1 text-[13px] font-semibold">{title}</h3>
      {items.length ? items.map((item, index) => (
        <button key={index} type="button" onClick={() => open(item.chunk_index)} className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-hover">
          <span className="text-muted">C{item.chunk_index} · {item.location}</span> — {item.quote}
        </button>
      )) : <p className="text-xs text-muted">{empty}</p>}
    </section>
  );
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">추출 구간 {card.chunk_count}개 · 문장 {card.quote_count}개 · 수치 {card.number_count}개 · 파일 버전 {card.file_version}{card.error ? ` · ${card.error}` : ""}. 수치가 성과인지, 누가 했는지는 아직 확인되지 않았습니다.</p>
      {focus && <Chunk chunk={focus} />}
      {samples("대표 문장", card.quote_samples, "추출한 문장이 없습니다.")}
      {samples("발견한 수치", card.number_samples, "수치 언급이 없습니다.")}
      <section className="space-y-2">
        <h3 className="text-[13px] font-semibold">원문 구간 전체</h3>
        {chunks.map((chunk) => <Chunk key={chunk.chunk_index} chunk={chunk} />)}
        {after > 0 && <Button size="sm" onClick={() => more(after).catch(fail)}>다음 구간 보기</Button>}
      </section>
    </div>
  );
}

export function FileViewer({ fileId, onClose }: { fileId: string | null; onClose: () => void }) {
  const { fail, notice } = useApp();
  const [result, setResult] = useState<any>(null);
  const [tab, setTab] = useState<"original" | "text" | "card">("original");
  const [frame, setFrame] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    const data = await api(`/files/${id}/analysis`);
    setResult(data);
    setFrame(null);
    const previewable = data.source !== "google" && data.upload_status === "uploaded" && (data.mime_type === "application/pdf" || data.mime_type?.startsWith("image/"));
    if (previewable) {
      const [config, supabase] = await Promise.all([getConfig(), getSupabase()]);
      const signed = await supabase.storage.from(config.bucket).createSignedUrl(data.storage_path, 60);
      if (!signed.error) setFrame(signed.data.signedUrl);
    }
  }, []);

  useEffect(() => {
    setResult(null);
    setTab("original");
    if (fileId) load(fileId).catch((error) => { fail(error); onClose(); });
  }, [fileId, load, fail, onClose]);

  const reanalyze = async () => {
    try {
      await api(`/files/${fileId}/reanalyze`, { method: "POST" });
      notice("다시 읽기를 시작했습니다. 잠시 뒤 다시 열어 확인하세요.");
      await load(fileId!);
    } catch (error) { fail(error); }
  };

  const seen = new Set((result?.preview_chunks ?? []).map((chunk: any) => chunk.chunk_index));
  const google = result?.source === "google";
  return (
    <Dialog open={!!fileId} onClose={onClose} size="xl" title={result?.name ?? "파일 불러오는 중"}>
      {!result ? <RowsSkeleton /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={result.analysis_status === "ready" ? "accent" : result.analysis_status === "failed" ? "danger" : "neutral"}>{ANALYSIS_LABEL[result.analysis_status] ?? result.analysis_status}</Badge>
            {google && <Badge>구글 드라이브</Badge>}
            <span className="flex-1" />
            <Button size="sm" onClick={() => openOriginal(result).catch(fail)} disabled={!google && result.upload_status !== "uploaded"}>
              {google ? <ExternalLink className="h-3.5 w-3.5" /> : <Download className="h-3.5 w-3.5" />}{google ? "구글 드라이브에서 열기" : "원본 다운로드"}
            </Button>
            <Button size="sm" onClick={reanalyze} disabled={result.upload_status !== "uploaded" || ["queued", "processing"].includes(result.analysis_status)}><RefreshCw className="h-3.5 w-3.5" />다시 읽기</Button>
          </div>
          <Tabs value={tab} onChange={setTab} items={[["original", "원본"], ["text", "AI가 읽은 글자"], ["card", "읽기 카드"]]} />
          {tab === "original" && (frame
            ? <iframe src={frame} title="원본 미리보기" className="h-[60vh] w-full rounded-md border border-line bg-white" />
            : <p className="py-8 text-center text-[13px] text-muted">{google ? "원본은 구글 드라이브에 있습니다. 스카이브는 읽은 글자만 보관합니다." : result.upload_status !== "uploaded" ? "원본 업로드가 아직 끝나지 않았습니다." : "이 형식은 미리보기를 지원하지 않습니다. 원본을 내려받거나 AI가 읽은 글자를 확인하세요."}</p>)}
          {tab === "text" && (
            <div className="space-y-2">
              <div className="rounded-md bg-hover p-3 text-xs">
                <p className="mb-1 font-semibold">읽기 범위</p>
                {coverageLines(result).map((line) => <p key={line}>{line}</p>)}
                <p className="mt-1 text-muted">읽은 글자는 원문 색인입니다. 사실과 본인 기여 확인은 경험 화면에서 합니다.</p>
              </div>
              {result.analysis_error && <p className="text-[13px] text-danger">{result.analysis_error}</p>}
              {(result.preview_chunks ?? []).map((chunk: any) => <Chunk key={chunk.chunk_index} chunk={chunk} />)}
              {(result.supplemental_chunks ?? []).filter((chunk: any) => !seen.has(chunk.chunk_index)).map((chunk: any) => <Chunk key={`s${chunk.chunk_index}`} chunk={chunk} />)}
              {!result.preview_chunks?.length && !result.analysis_error && <p className="text-[13px] text-muted">아직 읽은 글자가 없습니다.</p>}
            </div>
          )}
          {tab === "card" && <ReadCard fileId={result.id} />}
          <p className="text-[11px] text-muted">{result.size_bytes ? formatSize(result.size_bytes) : ""}</p>
        </div>
      )}
    </Dialog>
  );
}

