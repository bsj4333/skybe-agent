"use client";

import { ArrowLeft, Download, FileText, FolderInput, Loader2, RefreshCw, Scissors, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ANALYSIS_LABEL, api, CATEGORIES, DOC_TYPE_LABEL, EXPERIENCE_STATUS_LABEL, FACT_KIND_LABEL, JOB_LABEL, optional, OWNER_LABEL, patch, post, REVIEW_LABEL, saveText, SUBJECT_LABEL } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { GoogleFolderDialog, GoogleImportProgress, useGoogleStatus } from "@/components/google-drive";
import { FolderPicker } from "@/components/pickers";
import { Badge, Button, Card, Dialog, EmptyState, Field, Input, RowsSkeleton, Select } from "@/components/ui";

function Fact({ fact, disabled, onReview, onOpen }: { fact: any; disabled: boolean; onReview: (state: string, subject: string, note: string) => void; onOpen: () => void }) {
  const [subject, setSubject] = useState(fact.subject);
  const [note, setNote] = useState(fact.review_note ?? "");
  return (
    <Card className="activity-fact p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge>{FACT_KIND_LABEL[fact.kind] ?? fact.kind}</Badge>
        <Badge tone={fact.review_state === "confirmed" ? "accent" : fact.review_state === "rejected" ? "neutral" : "warn"}>{REVIEW_LABEL[fact.review_state] ?? fact.review_state}</Badge>
        {fact.stale && <Badge tone="danger">원본 변경, 재검토 필요</Badge>}
      </div>
      <p className="mt-2 text-[13px]">{fact.content}</p>
      <button type="button" onClick={onOpen} className="mt-1 inline-flex max-w-full items-center gap-1 text-xs text-muted hover:text-ink"><FileText className="h-3 w-3 shrink-0" /><span className="truncate">{fact.source_file_name || "삭제된 파일"} · {fact.source_location}</span></button>
      {fact.source_quote && fact.source_quote !== fact.content && <blockquote className="mt-1 border-l-2 border-line pl-2 text-xs text-muted">{fact.source_quote}</blockquote>}
      <div className="mt-2 grid gap-2 sm:grid-cols-[130px_minmax(0,1fr)]">
        <Select aria-label="주체" value={subject} onChange={(event) => setSubject(event.target.value)}>
          {Object.entries(SUBJECT_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </Select>
        <Input aria-label="확인 메모" maxLength={1000} placeholder="내 역할, 측정 조건 등 확인 메모" value={note} onChange={(event) => setNote(event.target.value)} />
      </div>
      <div className="mt-2 flex gap-1.5">
        <Button size="sm" variant="primary" disabled={disabled} onClick={() => onReview("confirmed", subject, note)}>확인</Button>
        <Button size="sm" disabled={disabled} onClick={() => onReview("rejected", subject, note)}>이 내용 제외</Button>
      </div>
    </Card>
  );
}

export default function ExperienceDetailPage() {
  const { fail, notice, openFile } = useApp();
  const router = useRouter();
  const id = useSearchParams().get("id");
  const [item, setItem] = useState<any>(null);
  const [factData, setFactData] = useState<any>(null);
  const [reviewed, setReviewed] = useState<any>(null);
  const [split, setSplit] = useState<Set<string>>(new Set());
  const [splitTitle, setSplitTitle] = useState<string | null>(null);
  const [folderOpen, setFolderOpen] = useState(false);
  const [googleOpen, setGoogleOpen] = useState(false);
  const [watch, setWatch] = useState(0);
  const { status: google } = useGoogleStatus();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ title: "", category: "", subcategory: "", period_text: "" });
  const [generating, setGenerating] = useState(false);

  const loadFacts = useCallback(async () => {
    const [facts, markdown] = await Promise.all([api(`/activities/${id}/facts`), api(`/activities/${id}/reviewed-markdown`)]);
    setFactData(facts);
    setReviewed(markdown);
  }, [id]);

  const load = useCallback(async () => {
    const activity = await api(`/activities/${id}`);
    const extra = await optional(api(`/experiences/${id}`), null);
    setItem({ ...activity, ...(extra ?? {}), files: extra?.files ?? activity.files });
    await loadFacts();
  }, [id, loadFacts]);

  useEffect(() => { if (id) load().catch(fail); }, [id, load, fail]);

  const analyzing = ["queued", "processing"].includes(factData?.job?.status);
  useEffect(() => {
    if (!analyzing) return;
    const timer = setInterval(() => loadFacts().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [analyzing, loadFacts]);

  const reading = item?.files?.filter((file: any) => ["queued", "processing"].includes(file.analysis_status)).length ?? 0;
  useEffect(() => {
    if (!reading) return;
    const timer = setInterval(() => load().catch(() => {}), 6000);
    return () => clearInterval(timer);
  }, [reading, load]);

  const run = (action: () => Promise<unknown>) => action().catch(fail);

  const review = (factId: string, review_state: string, subject: string, review_note: string) => run(async () => {
    await api(`/activities/${id}/facts/${factId}`, patch({ review_state, subject, review_note }));
    await loadFacts();
  });
  const unlink = (fileId: string) => run(async () => { await api(`/activities/${id}/files/${fileId}`, { method: "DELETE" }); await load(); });
  const setOwner = (fileId: string, owner: string) => run(async () => { await api(`/experiences/files/${fileId}/owner`, patch({ owner })); await load(); });
  const doSplit = () => run(async () => {
    const created = await api(`/experiences/${id}/split`, post({ file_ids: [...split], title: splitTitle?.trim() }));
    setSplitTitle(null);
    setSplit(new Set());
    notice("경험을 나눴습니다.");
    router.push(`/experiences/detail?id=${created.id}`);
  });
  const saveEdit = () => run(async () => {
    await api(`/activities/${id}`, patch({ title: draft.title, kind_tags: item.kind_tags ?? [] }));
    await optional(api(`/experiences/${id}`, patch(draft)), null);
    setEditing(false);
    await load();
  });
  const setStatus = (status: string) => run(async () => { await api(`/experiences/${id}`, patch({ status })); await load(); });
  const generateMarkdown = async () => {
    setGenerating(true);
    try {
      await api(`/activities/${id}/reviewed-markdown`, post());
      setReviewed(await api(`/activities/${id}/reviewed-markdown`));
      notice("확인된 내용으로 요약을 만들었습니다.");
    } catch (error) { fail(error); } finally { setGenerating(false); }
  };

  if (!id) return <div className="p-6"><EmptyState icon={Sparkles} title="경험을 선택해 주세요" /></div>;
  if (!item) return <div className="mx-auto max-w-4xl p-6"><RowsSkeleton rows={8} /></div>;

  const job = factData?.job;
  const snapshot = reviewed?.snapshot;
  return (
    <div className="mx-auto max-w-4xl px-4 py-6 md:px-8">
      <Link prefetch={false} href="/experiences" className="mb-3 inline-flex items-center gap-1 text-xs text-muted hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" />내 경험</Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 id="activity-detail-title" className="text-xl font-semibold">{item.title}</h1>
          <p className="mt-0.5 text-xs text-muted">{[item.category, item.subcategory, item.period_text || item.period_note].filter(Boolean).join(" · ") || "분류 전"}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {item.status && <Badge tone={item.status === "confirmed" ? "accent" : "warn"}>{EXPERIENCE_STATUS_LABEL[item.status]}</Badge>}
          {item.status && item.status !== "confirmed" && <Button size="sm" variant="primary" onClick={() => setStatus("confirmed")}>맞음</Button>}
          {item.status && item.status !== "excluded" && <Button size="sm" onClick={() => setStatus("excluded")}>제외</Button>}
          <Button size="sm" onClick={() => { setDraft({ title: item.title ?? "", category: item.category ?? "", subcategory: item.subcategory ?? "", period_text: item.period_text ?? "" }); setEditing(true); }}>수정</Button>
        </div>
      </div>

      <section className="mb-6">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">연결 파일 {item.files.length}개</h2>
          {reading > 0 && <Badge tone="warn">읽는 중 {reading}개</Badge>}
          <span className="flex-1" />
          {split.size > 0 && <Button size="sm" onClick={() => setSplitTitle("")}><Scissors className="h-3 w-3" />선택한 {split.size}개 나누기</Button>}
          <Button id="experience-folder-link" size="sm" onClick={() => (google?.enabled ? setGoogleOpen(true) : setFolderOpen(true))}><FolderInput className="h-3 w-3" />폴더 연결</Button>
          <Button size="sm" onClick={() => run(async () => { const result = await api(`/activities/${id}/markdown`); saveText(result.filename, result.markdown); })}><Download className="h-3 w-3" />자료 목차</Button>
        </div>
        <GoogleImportProgress watch={watch} activityId={id} onFinish={() => load().catch(fail)} />
        <div id="activity-files" className="max-h-72 overflow-y-auto rounded-md border border-line">
          {item.files.map((file: any) => (
            <div key={file.id} className="activity-row flex items-center gap-2 border-b border-line px-2 py-1.5 last:border-0">
              <input type="checkbox" aria-label={`${file.name} 선택`} checked={split.has(file.id)} onChange={() => setSplit((current) => { const next = new Set(current); if (next.has(file.id)) next.delete(file.id); else next.add(file.id); return next; })} />
              <button type="button" onClick={() => openFile(file.id)} className="min-w-0 flex-1 truncate text-left text-[13px] hover:underline" title={file.path ?? file.name}>{file.name}</button>
              {file.doc_type && <Badge className="hidden sm:inline-flex">{DOC_TYPE_LABEL[file.doc_type] ?? file.doc_type}</Badge>}
              {file.owner && (
                <Select aria-label="소유" className="h-7 w-24 text-xs" value={file.owner} onChange={(event) => setOwner(file.id, event.target.value)}>
                  {Object.entries(OWNER_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </Select>
              )}
              <span className="hidden w-16 text-right text-[11px] text-muted sm:block">{ANALYSIS_LABEL[file.analysis_status] ?? ""}</span>
              <Button variant="ghost" size="icon" className="h-6 w-6" aria-label={`${file.name} 연결 해제`} onClick={() => unlink(file.id)}><Trash2 className="h-3 w-3" /></Button>
            </div>
          ))}
          {!item.files.length && <p className="p-4 text-center text-[13px] text-muted">연결된 파일이 없습니다.</p>}
        </div>
      </section>

      <section className="mb-6" id="activity-facts">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">자료에서 찾은 사실</h2>
          <span className="flex-1" />
          <Button size="sm" variant="primary" disabled={analyzing} onClick={() => run(async () => { await api(`/activities/${id}/analyze`, post()); notice("분석을 시작했습니다."); await loadFacts(); })}>{analyzing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}연결 파일 분석 시작</Button>
          <Button size="sm" onClick={() => run(loadFacts)}><RefreshCw className="h-3 w-3" />결과 새로고침</Button>
        </div>
        <p className="mb-2 text-xs text-muted">{job ? `분석 ${JOB_LABEL[job.status] ?? job.status} · 파일 ${job.files_total ?? 0}개 중 ${job.files_analyzed ?? 0}개 검토` : "아직 분석하지 않았습니다."}{factData?.source_changed ? " · 연결 파일이 바뀌어 다시 분석이 필요합니다." : ""}{job?.error ? ` · ${job.error}` : ""}</p>
        {job && job.files_total > job.files_analyzed && <p className="mb-2 text-xs text-muted">문서를 먼저 읽었습니다. 코드와 데이터 파일은 필요할 때만 살펴봅니다.</p>}
        {!!factData?.questions?.length && (
          <div className="mb-3 space-y-1 rounded-md bg-warn-soft p-3 text-[13px]">
            <p className="font-medium">확인이 필요합니다</p>
            {factData.questions.map((question: string) => <p key={question}>{question}</p>)}
          </div>
        )}
        <div className="space-y-2">
          {factData?.facts?.map((fact: any) => <Fact key={fact.id} fact={fact} disabled={fact.stale} onOpen={() => openFile(fact.source_file_id)} onReview={(state, subject, note) => review(fact.id, state, subject, note)} />)}
        </div>
        {factData && !factData.facts.length && <p className="rounded-md border border-dashed border-line p-5 text-center text-[13px] text-muted">아직 검토할 사실이 없습니다. 분석을 시작해 주세요.</p>}
      </section>

      <section id="activity-reviewed-md">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">확인된 활동 요약</h2>
          {reviewed?.needs_refresh && <Badge tone="warn">갱신 필요</Badge>}
          {reviewed?.needs_source_review && <Badge tone="danger">출처 재검토 필요</Badge>}
          <span className="flex-1" />
          <Button size="sm" disabled={generating} onClick={generateMarkdown}>{snapshot ? "현재 확인 내용으로 갱신" : "확인된 내용으로 MD 만들기"}</Button>
          {snapshot && <Button size="sm" onClick={() => saveText(reviewed.filename, snapshot.markdown)}><Download className="h-3 w-3" />내려받기</Button>}
        </div>
        {snapshot ? <Card><pre className="prose-md font-sans">{snapshot.markdown}</pre></Card> : <p className="text-[13px] text-muted">아직 만든 요약이 없습니다.</p>}
      </section>

      <GoogleFolderDialog open={googleOpen} activityId={id} onClose={() => setGoogleOpen(false)} onStarted={() => setWatch((value) => value + 1)} onLocal={() => { setGoogleOpen(false); setFolderOpen(true); }} />
      <FolderPicker title="연결할 폴더" action="이 폴더 연결" open={folderOpen} onClose={() => setFolderOpen(false)} onPick={(folderId) => {
        setFolderOpen(false);
        if (!folderId) { notice("연결할 폴더를 열어서 선택해 주세요."); return; }
        run(async () => { const result = await api(`/activities/${id}/folders/${folderId}/files`, post()); notice(`${result.added}개 파일을 새로 연결했습니다.`); await load(); });
      }} />
      <Dialog open={splitTitle !== null} onClose={() => setSplitTitle(null)} size="sm" title="새 경험으로 나누기" footer={<><Button onClick={() => setSplitTitle(null)}>취소</Button><Button variant="primary" disabled={!splitTitle?.trim()} onClick={doSplit}>나누기</Button></>}>
        <Field label="새 경험 이름"><Input autoFocus value={splitTitle ?? ""} onChange={(event) => setSplitTitle(event.target.value)} /></Field>
      </Dialog>
      <Dialog open={editing} onClose={() => setEditing(false)} size="sm" title="경험 수정" footer={<><Button onClick={() => setEditing(false)}>취소</Button><Button variant="primary" disabled={!draft.title.trim()} onClick={saveEdit}>저장</Button></>}>
        <div className="space-y-3">
          <Field label="이름"><Input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></Field>
          <Field label="대분류"><Select value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}><option value="">선택 안 함</option>{CATEGORIES.map((name) => <option key={name} value={name}>{name}</option>)}</Select></Field>
          <Field label="소분류"><Input value={draft.subcategory} onChange={(event) => setDraft({ ...draft, subcategory: event.target.value })} /></Field>
          <Field label="기간"><Input placeholder="예: 2025-08~2025-12" value={draft.period_text} onChange={(event) => setDraft({ ...draft, period_text: event.target.value })} /></Field>
        </div>
      </Dialog>
    </div>
  );
}
