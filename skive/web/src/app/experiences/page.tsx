"use client";

import { Check, ChevronDown, Combine, Loader2, Plus, RefreshCw, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ANALYSIS_LABEL, api, CATEGORIES, cn, EXPERIENCE_STATUS_LABEL, JOB_LABEL, optional, patch, post } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { Badge, Button, Card, Dialog, EmptyState, Field, Input, PageHeader, RowsSkeleton, Select } from "@/components/ui";

function Suggestion({ candidate, activities, onDone }: { candidate: any; activities: any[]; onDone: (id: string) => void }) {
  const { fail, notice } = useApp();
  const [title, setTitle] = useState(candidate.title);
  const [target, setTarget] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set(candidate.files.slice(0, 200).map((file: any) => file.id)));
  const [busy, setBusy] = useState(false);
  const toggle = (id: string) => setPicked((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const accept = async () => {
    if (!picked.size) { notice("연결할 파일을 선택해 주세요."); return; }
    setBusy(true);
    try {
      const id = target || (await api("/activities", post({ title: title.trim() }))).id;
      await api(`/activities/${id}/files`, post({ file_ids: [...picked] }));
      notice(`${picked.size}개 파일을 경험에 연결했습니다.`);
      onDone(id);
    } catch (error) { fail(error); } finally { setBusy(false); }
  };
  return (
    <details className="activity-suggestion rounded-md border border-line px-3 py-2">
      <summary className="cursor-pointer text-[13px]">{candidate.title} · 파일 {candidate.file_count}개 · {candidate.reason}</summary>
      <div className="mt-2 space-y-2">
        <Input aria-label="경험 이름" maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
        <Select aria-label="연결 대상" value={target} onChange={(event) => setTarget(event.target.value)}>
          <option value="">새 경험 만들기</option>
          {activities.map((activity) => <option key={activity.id} value={activity.id}>기존 경험에 합치기: {activity.title}</option>)}
        </Select>
        <div className="suggestion-files max-h-48 space-y-0.5 overflow-y-auto rounded border border-line p-2">
          {candidate.files.slice(0, 200).map((file: any) => (
            <label key={file.id} className="flex items-center gap-2 text-xs"><input type="checkbox" value={file.id} checked={picked.has(file.id)} onChange={() => toggle(file.id)} /><span className="truncate">{file.name}</span><span className="text-muted">{ANALYSIS_LABEL[file.analysis_status] ?? file.analysis_status}</span></label>
          ))}
        </div>
        {candidate.files.length > 200 && <p className="text-xs text-muted">앞의 200개만 표시합니다. 나머지는 경험을 만든 뒤 폴더 연결로 추가하세요.</p>}
        <Button size="sm" variant="primary" disabled={busy} onClick={accept}>선택한 파일 연결</Button>
      </div>
    </details>
  );
}

export default function ExperiencesPage() {
  const { fail, notice } = useApp();
  const router = useRouter();
  const [items, setItems] = useState<any[] | null>(null);
  const [build, setBuild] = useState<any>({ status: "idle" });
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [mergeTitle, setMergeTitle] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<any>(null);
  const [activities, setActivities] = useState<any[]>([]);

  const load = useCallback(async () => {
    const [list, job] = await Promise.all([optional(api<any[]>("/experiences"), []), optional(api("/experiences/build"), { status: "idle" })]);
    setItems(list);
    setBuild(job);
  }, []);

  useEffect(() => { load().catch(fail); }, [load, fail]);

  const running = build.status === "queued" || build.status === "processing";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => load().catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [running, load]);

  const start = async () => {
    try {
      setBuild(await api("/experiences/build", post()));
      notice("파일을 살펴보고 경험 후보를 만들고 있습니다.");
      await load();
    } catch (error) { fail(error); }
  };

  const setItemStatus = async (id: string, next: string) => {
    try {
      await api(`/experiences/${id}`, patch({ status: next }));
      await load();
    } catch (error) { fail(error); }
  };

  const merge = async () => {
    try {
      const result = await api("/experiences/merge", post({ ids: [...picked], title: mergeTitle?.trim() || undefined }));
      setMergeTitle(null);
      setPicked(new Set());
      notice("경험을 합쳤습니다.");
      await load();
      if (result?.id) router.push(`/experiences/detail?id=${result.id}`);
    } catch (error) { fail(error); }
  };

  const create = async () => {
    try {
      const created = await api("/activities", post({ title: newTitle?.trim(), kind_tags: [] }));
      setNewTitle(null);
      router.push(`/experiences/detail?id=${created.id}`);
    } catch (error) { fail(error); }
  };

  const loadSuggestions = async () => {
    try {
      const [data, list] = await Promise.all([api("/activities/suggestions"), api<any[]>("/activities")]);
      setSuggestions(data);
      setActivities(list);
    } catch (error) { fail(error); }
  };

  const visible = useMemo(() => (items ?? []).filter((item) => (!category || item.category === category) && (status ? item.status === status : item.status !== "excluded")), [items, category, status]);
  const groups = useMemo(() => {
    const map = new Map<string, any[]>();
    for (const item of visible) {
      const key = item.category || "분류 전";
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return [...map.entries()].sort(([left], [right]) => CATEGORIES.indexOf(left) - CATEGORIES.indexOf(right));
  }, [visible]);
  const toggle = (id: string) => setPicked((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const waiting = (items ?? []).filter((item) => item.status === "candidate").length;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <PageHeader title="내 경험" hint="드라이브 폴더는 그대로 두고, 파일을 읽어 경험 단위로 다시 묶습니다. 확인한 경험만 프로필과 자소서에 쓰입니다.">
        <Button onClick={() => setNewTitle("")}><Plus className="h-3.5 w-3.5" />직접 만들기</Button>
        <Button id="experience-build" variant="primary" disabled={running} onClick={start}>{running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}{items?.length ? "다시 분석" : "경험 찾기"}</Button>
      </PageHeader>

      {running && (
        <Card className="mb-4">
          <p className="text-[13px] font-medium">{build.stage === "map" ? "경험으로 묶는 중" : "파일 카드 만드는 중"}</p>
          <p className="mt-0.5 text-xs text-muted">{JOB_LABEL[build.status]}{build.cards_total ? ` · ${build.cards_done ?? 0}/${build.cards_total}개` : ""}</p>
          <div className="mt-2 h-1 overflow-hidden rounded bg-hover"><div className="h-full bg-accent transition-all" style={{ width: `${build.cards_total ? Math.round(((build.cards_done ?? 0) / build.cards_total) * 100) : 5}%` }} /></div>
        </Card>
      )}
      {build.status === "failed" && <p className="mb-4 rounded-md bg-danger-soft px-3 py-2 text-[13px] text-danger">경험 분석에 실패했습니다. {build.error}</p>}

      {!!items?.length && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Select aria-label="대분류" className="w-40" value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">전체 분류</option>
            {CATEGORIES.map((name) => <option key={name} value={name}>{name}</option>)}
          </Select>
          <Select aria-label="상태" className="w-32" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">제외 빼고 보기</option>
            {Object.entries(EXPERIENCE_STATUS_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </Select>
          {waiting > 0 && <Badge tone="warn">확인 대기 {waiting}개</Badge>}
          <span className="flex-1" />
          {picked.size >= 2 && <Button onClick={() => setMergeTitle("")}><Combine className="h-3.5 w-3.5" />선택한 {picked.size}개 합치기</Button>}
          <Button variant="ghost" size="icon" aria-label="새로고침" onClick={() => load().catch(fail)}><RefreshCw className="h-3.5 w-3.5" /></Button>
        </div>
      )}

      {items === null ? <RowsSkeleton rows={6} /> : !items.length ? (
        !running && <EmptyState icon={Sparkles} title="아직 경험이 없습니다" hint="드라이브 자료를 읽어 프로젝트, 수업, 인턴 같은 경험 후보를 만듭니다. 본인 자료와 다른 사람 자료도 구분합니다."><Button variant="primary" onClick={start}>경험 찾기</Button></EmptyState>
      ) : (
        <div className="space-y-5">
          {groups.map(([name, group]) => (
            <section key={name}>
              <h2 className="mb-2 text-[13px] font-semibold text-muted">{name} · {group.length}</h2>
              <div className="grid gap-2 md:grid-cols-2">
                {group.map((item) => (
                  <Card key={item.id} className={cn("p-3", item.status === "excluded" && "opacity-60")}>
                    <div className="flex items-start gap-2">
                      <input type="checkbox" className="mt-1" aria-label={`${item.title} 선택`} checked={picked.has(item.id)} onChange={() => toggle(item.id)} />
                      <div className="min-w-0 flex-1">
                        <Link prefetch={false} href={`/experiences/detail?id=${item.id}`} className="block truncate font-medium hover:underline">{item.title}</Link>
                        <p className="truncate text-xs text-muted">{[item.subcategory, item.period_text || "시기 미확인", `파일 ${item.file_count}개`].filter(Boolean).join(" · ")}</p>
                        {item.why && <p className="mt-1 line-clamp-2 text-xs text-muted">{item.why}</p>}
                      </div>
                      <Badge tone={item.status === "confirmed" ? "accent" : item.status === "excluded" ? "neutral" : "warn"}>{EXPERIENCE_STATUS_LABEL[item.status] ?? "확인 대기"}</Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
                      {item.status !== "confirmed" && <Button size="sm" onClick={() => setItemStatus(item.id, "confirmed")}><Check className="h-3 w-3" />맞음</Button>}
                      {item.status !== "excluded" && <Button size="sm" onClick={() => setItemStatus(item.id, "excluded")}><X className="h-3 w-3" />제외</Button>}
                      {item.status === "excluded" && <Button size="sm" onClick={() => setItemStatus(item.id, "candidate")}>되돌리기</Button>}
                      <Link prefetch={false} href={`/experiences/detail?id=${item.id}`}><Button size="sm">나누기·사실 확인</Button></Link>
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          ))}
          {!groups.length && <p className="py-6 text-center text-[13px] text-muted">조건에 맞는 경험이 없습니다.</p>}
        </div>
      )}

      <section className="mt-8 border-t border-line pt-4">
        <button type="button" id="open-activities" onClick={loadSuggestions} className="flex items-center gap-1 text-[13px] font-medium text-muted hover:text-ink"><ChevronDown className="h-4 w-4" />폴더와 공통 단어로 찾은 묶음 보기</button>
        {suggestions && (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-muted">파일을 골라 새 경험으로 만들거나 기존 경험에 합칩니다.{suggestions.truncated ? " 파일 5,000개까지만 살폈습니다." : ""}{suggestions.content_limited ? " 원문 비교는 최근 파일 500개까지만 했습니다." : ""}</p>
            {suggestions.suggestions.map((candidate: any, index: number) => <Suggestion key={index} candidate={candidate} activities={activities} onDone={(id) => router.push(`/experiences/detail?id=${id}`)} />)}
            {!suggestions.suggestions.length && <p className="text-[13px] text-muted">제안할 묶음이 없습니다.</p>}
          </div>
        )}
      </section>

      <Dialog open={mergeTitle !== null} onClose={() => setMergeTitle(null)} size="sm" title="경험 합치기" footer={<><Button onClick={() => setMergeTitle(null)}>취소</Button><Button variant="primary" onClick={merge}>합치기</Button></>}>
        <Field label="합친 경험 이름 (비우면 첫 경험 이름 사용)"><Input autoFocus value={mergeTitle ?? ""} onChange={(event) => setMergeTitle(event.target.value)} /></Field>
      </Dialog>
      <Dialog open={newTitle !== null} onClose={() => setNewTitle(null)} size="sm" title="새 경험" footer={<><Button onClick={() => setNewTitle(null)}>취소</Button><Button variant="primary" disabled={!newTitle?.trim()} onClick={create}>만들기</Button></>}>
        <Field label="경험 이름"><Input id="activity-name" autoFocus value={newTitle ?? ""} onChange={(event) => setNewTitle(event.target.value)} /></Field>
      </Dialog>
    </div>
  );
}
