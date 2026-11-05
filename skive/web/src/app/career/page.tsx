"use client";

import { AlertTriangle, ExternalLink, FileText, History, Loader2, Plus, Send } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { career, cn, formatDate, post } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { Badge, Button, Card, Dialog, EmptyState, Field, Input, RowsSkeleton, Select, Textarea } from "@/components/ui";

function highlight(draft: string, checks: any[] = []): ReactNode[] {
  const flagged = checks.filter((check) => check.status === "unsupported" && check.sentence);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  const ranges = flagged.map((check) => ({ check, at: draft.indexOf(check.sentence) })).filter((item) => item.at >= 0).sort((a, b) => a.at - b.at);
  for (const { check, at } of ranges) {
    if (at < cursor) continue;
    nodes.push(draft.slice(cursor, at));
    nodes.push(<mark key={at} title={check.reason} className="rounded bg-warn-soft px-0.5 text-ink underline decoration-warn decoration-dotted">{check.sentence}</mark>);
    cursor = at + check.sentence.length;
  }
  nodes.push(draft.slice(cursor));
  return nodes;
}

function References({ references }: { references: any }) {
  const { openFile, openProject } = useApp();
  if (!references) return null;
  const files = references.files ?? (Array.isArray(references) ? references : []);
  const chip = (key: string, label: string, open: () => void) => (
    <button key={key} type="button" onClick={open} className="inline-flex max-w-full items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs text-muted hover:bg-hover hover:text-ink"><FileText className="h-3 w-3 shrink-0" /><span className="truncate">{label}</span></button>
  );
  return (
    <div className="flex flex-wrap gap-1.5">
      {files.map((source: any) => chip(`f${source.index}`, `[파일 ${source.index}] ${source.name}`, () => (source.source_type === "project_summary" ? openProject(source.project_folder_id) : openFile(source.file_id))))}
      {(references.activity_facts ?? []).map((fact: any) => chip(`a${fact.index}`, `[활동 사실 ${fact.index}] ${fact.activity_title}`, () => openFile(fact.file_id)))}
      {!!references.user_statements?.length && <span className="text-xs text-muted">본인 진술 {references.user_statements.length}건 참고</span>}
      {!!references.past_essays?.length && <span className="text-xs text-muted">이전 자소서 {references.past_essays.length}건 표현 참고</span>}
    </div>
  );
}

function NewJob({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { fail, notice } = useApp();
  const [form, setForm] = useState({ title: "", job_url: "", values_url: "", job_text: "", questions: "" });
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm({ ...form, [key]: event.target.value });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const job = await career("/jobs", post({ ...form, title: form.title.trim(), questions: form.questions.split("\n").map((value) => value.trim()).filter(Boolean) }));
      notice("공고 작업 공간을 만들었습니다.");
      setForm({ title: "", job_url: "", values_url: "", job_text: "", questions: "" });
      onCreated(job.id);
    } catch (error) { fail(error); }
  };
  return (
    <Dialog open={open} onClose={onClose} title="공고 만들기">
      <form id="career-new-form" onSubmit={submit} className="space-y-3">
        <Field label="공고 이름"><Input id="career-title" required maxLength={200} placeholder="예: 기아 생산기술" value={form.title} onChange={set("title")} /></Field>
        <Field label="공고 URL (참고 링크)"><Input id="career-url" type="url" placeholder="https://..." value={form.job_url} onChange={set("job_url")} /></Field>
        <Field label="인재상 URL (참고 링크)"><Input id="career-values-url" type="url" placeholder="https://..." value={form.values_url} onChange={set("values_url")} /></Field>
        <Field label="공고 내용"><Textarea id="career-job-text" placeholder="직무와 요구사항을 붙여 넣으세요" value={form.job_text} onChange={set("job_text")} /></Field>
        <Field label="자소서 문항 (한 줄에 하나)"><Textarea id="career-questions" value={form.questions} onChange={set("questions")} /></Field>
        <Button type="submit" variant="primary" className="w-full">공고 저장</Button>
      </form>
    </Dialog>
  );
}

export default function CareerPage() {
  const { fail, notice } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const jobId = params.get("job");
  const [jobs, setJobs] = useState<any[] | null>(null);
  const [job, setJob] = useState<any>(null);
  const [essayId, setEssayId] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [versions, setVersions] = useState<any[] | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const log = useRef<HTMLDivElement>(null);

  const loadJobs = useCallback(() => career("/jobs").then(setJobs), []);
  const loadJob = useCallback(async (id: string) => {
    const data = await career(`/jobs/${id}`);
    setJob(data);
    setEssayId((current) => (data.essays.some((item: any) => item.id === current) ? current : data.essays[0]?.id ?? ""));
  }, []);

  useEffect(() => { loadJobs().catch(fail); }, [loadJobs, fail]);
  useEffect(() => {
    setJob(null);
    setVersions(null);
    setPreview(null);
    if (jobId) loadJob(jobId).catch(fail);
  }, [jobId, loadJob, fail]);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [job, busy]);

  const essay = useMemo(() => job?.essays.find((item: any) => item.id === essayId), [job, essayId]);
  const shown = preview ?? essay;
  const unsupported = (shown?.sentence_checks ?? []).filter((check: any) => check.status === "unsupported");

  const send = async (answerPending: boolean) => {
    const message = text.trim();
    if (!jobId || !message || busy) return;
    setBusy(true);
    try {
      const result = await career(`/jobs/${jobId}/messages`, post({ message, essay_id: essayId || null, answer_pending: answerPending }));
      setText("");
      setPreview(null);
      await loadJob(jobId);
      await loadJobs();
      if (result.action === "ask") notice("AI가 확인 질문을 남겼습니다. 답변은 본인 진술로 저장됩니다.");
      if (result.action === "draft") notice("초안을 저장했습니다. 문장과 출처를 검토해 주세요.");
    } catch (error) {
      fail(error);
      // A long answer can finish on the server after the connection drops. Show whatever was saved.
      await loadJob(jobId).catch(() => undefined);
    } finally { setBusy(false); }
  };

  const toggleVersions = async () => {
    if (versions) { setVersions(null); return; }
    try { setVersions(await career(`/jobs/${jobId}/essays/${essayId}/versions`)); } catch (error) { fail(error); }
  };

  return (
    <div className="flex h-full flex-col lg:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-line p-2 lg:w-56 lg:border-r lg:border-b-0">
        <Button id="career-new-toggle" variant="primary" className="mb-2 w-full" onClick={() => setCreating(true)}><Plus className="h-3.5 w-3.5" />공고 만들기</Button>
        <div id="career-jobs" className="max-h-40 min-h-0 flex-1 space-y-0.5 overflow-y-auto lg:max-h-none">
          {jobs === null ? <RowsSkeleton rows={3} /> : jobs.map((item) => (
            <button key={item.id} type="button" onClick={() => router.push(`/career?job=${item.id}`)} className={cn("block w-full rounded px-2 py-1.5 text-left text-[13px] hover:bg-hover", item.id === jobId && "bg-hover font-medium")}>
              <span className="block truncate">{item.title}</span>
              <span className="text-[11px] text-muted">{item.question_count}문항</span>
            </button>
          ))}
        </div>
      </aside>

      {!jobId ? (
        <div className="flex-1 p-6"><EmptyState icon={FileText} title="공고를 선택하거나 새로 만드세요" hint="공고별로 대화와 초안이 따로 저장됩니다. 드라이브 자료, 본인 진술, 이전 자소서는 필요할 때 함께 찾아봅니다."><Button variant="primary" onClick={() => setCreating(true)}>공고 만들기</Button></EmptyState></div>
      ) : !job ? <div className="flex-1 p-6"><RowsSkeleton /></div> : (
        <>
          <section className="min-w-0 flex-1 overflow-y-auto p-4 md:p-6">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h1 id="career-job-title" className="truncate text-lg font-semibold">{job.title}</h1>
                {job.job_url && <a href={job.job_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-accent">공고 원문<ExternalLink className="h-3 w-3" /></a>}
              </div>
              <span className="shrink-0 text-xs text-muted">{formatDate(job.created_at)}</span>
            </div>
            <Field label="작성할 문항" className="mb-3">
              <Select id="career-question-select" value={essayId} onChange={(event) => { setEssayId(event.target.value); setPreview(null); setVersions(null); }}>
                <option value="">일반 대화</option>
                {job.essays.map((item: any) => <option key={item.id} value={item.id}>{item.question}</option>)}
              </Select>
            </Field>
            <Card>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h2 className="font-semibold">{preview ? `버전 ${preview.revision_no}` : "현재 초안"}</h2>
                {shown?.draft && (unsupported.length ? <Badge tone="warn"><AlertTriangle className="mr-1 h-3 w-3" />근거 확인 필요 {unsupported.length}문장</Badge> : shown?.sentence_checks?.length ? <Badge tone="accent">문장 근거 확인됨</Badge> : <Badge>검토 필요</Badge>)}
                <span className="flex-1" />
                {preview && <Button size="sm" onClick={() => setPreview(null)}>현재 초안 보기</Button>}
                {essayId && <Button id="career-versions" size="sm" onClick={toggleVersions}><History className="h-3.5 w-3.5" />이전 버전</Button>}
              </div>
              <div id="career-draft" className="min-h-40 text-[14px] leading-7 whitespace-pre-wrap">{shown?.draft ? highlight(shown.draft, shown.sentence_checks) : <span className="text-muted">문항을 선택하고 AI와 대화하며 초안을 작성하세요.</span>}</div>
              {!!unsupported.length && (
                <ul className="mt-3 space-y-1 rounded-md bg-warn-soft p-3 text-xs">
                  {unsupported.map((check: any, index: number) => <li key={index}><span className="font-medium">{check.sentence}</span>{check.reason ? ` — ${check.reason}` : ""}</li>)}
                </ul>
              )}
              <div id="career-draft-sources" className="mt-3"><References references={shown?.citations} /></div>
              {versions && (
                <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-3">
                  {versions.length ? versions.map((version) => <Button key={version.revision_no} size="sm" onClick={() => setPreview(version)}>버전 {version.revision_no} · {new Date(version.created_at).toLocaleString("ko-KR")}</Button>) : <span className="text-xs text-muted">아직 저장된 버전이 없습니다.</span>}
                </div>
              )}
            </Card>
            <p className="mt-2 text-xs text-muted">파일 근거, 본인 진술, 이전 자소서 표현을 구분합니다. 원본에 없거나 충돌하면 먼저 질문합니다.</p>
          </section>

          <section className="flex w-full shrink-0 flex-col border-t border-line lg:w-96 lg:border-t-0 lg:border-l">
            <div id="career-messages" ref={log} className="min-h-40 flex-1 space-y-2 overflow-y-auto p-3">
              {job.messages.map((message: any, index: number) => (
                <div key={index} className={cn(message.role === "user" && "flex justify-end")}>
                  <div className={cn("rounded-xl px-3 py-2 text-[13px] leading-6 whitespace-pre-wrap", message.role === "user" ? "max-w-[85%] bg-accent-soft" : "bg-hover")}>{message.content}</div>
                  {message.role === "assistant" && message.references_json && <div className="mt-1"><References references={message.references_json} /></div>}
                </div>
              ))}
              {busy && <p className="flex items-center gap-2 text-xs text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />자료를 찾아 작성하는 중…</p>}
            </div>
            <div className="border-t border-line p-3">
              {job.pending_question && <p id="career-pending" className="mb-2 rounded-md bg-warn-soft p-2 text-xs">AI 확인 질문: {job.pending_question}</p>}
              <Textarea id="career-message-input" aria-label="메시지" placeholder="예: 이 문항 초안 써줘" value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(false); } }} />
              <div className="mt-2 flex gap-2">
                <Button id="career-send" variant="primary" className="flex-1" disabled={busy || !text.trim()} onClick={() => send(false)}><Send className="h-3.5 w-3.5" />보내기</Button>
                {job.pending_question && <Button id="career-answer" disabled={busy || !text.trim()} onClick={() => send(true)}>질문에 답변으로 저장</Button>}
              </div>
            </div>
          </section>
        </>
      )}
      <NewJob open={creating} onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); loadJobs().catch(fail); router.push(`/career?job=${id}`); }} />
    </div>
  );
}
