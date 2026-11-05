"use client";

import { Award, BriefcaseBusiness, Check, FileSearch, FolderKanban, GraduationCap, Languages, Pencil, Plane, Plus, RefreshCw, ScrollText, Shield, Sparkles, Trash2, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ENTRY_KIND_LABEL, optional, patch, post, workspace } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { GoogleConnectCard } from "@/components/google-drive";
import { Badge, Button, Card, Dialog, EmptyState, Field, Input, PageHeader, RowsSkeleton, Select, Textarea } from "@/components/ui";

type Entry = { id: string; kind: string; title: string; organization?: string; start_date?: string; end_date?: string; detail?: string; status: string; source_file_id?: string };

const COLORS: Record<string, string> = {
  education: "#8fb8f5", work: "#7cc38a", military: "#8a8d93", experience: "#f3c14b", license: "#7f8cf0", award: "#ef8fa8", language: "#5dbcae", overseas: "#f0a35e",
};
const SECTIONS: [string, string, LucideIcon][] = [
  ["education", "학력", GraduationCap], ["work", "직장경력", BriefcaseBusiness], ["military", "병역", Shield], ["license", "자격증", ScrollText],
  ["language", "어학", Languages], ["award", "수상", Award], ["overseas", "해외경험", Plane],
];

function toYear(value?: string | null): number | null {
  const match = value?.match(/(\d{4})(?:[-.\s/]+(\d{1,2}))?/);
  return match ? Number(match[1]) + (match[2] ? (Number(match[2]) - 1) / 12 : 0) : null;
}

function periodRange(text?: string | null): [number, number] | null {
  const found = [...(text ?? "").matchAll(/(\d{4})(?:[-.\s/]+(\d{1,2}))?/g)].map((match) => Number(match[1]) + (match[2] ? (Number(match[2]) - 1) / 12 : 0));
  if (!found.length) return null;
  return [found[0], found[found.length - 1] + (found.length === 1 ? 0.25 : 0.08)];
}

const shortRange = (entry: Entry) => [entry.start_date, entry.end_date].filter(Boolean).join(" ~ ");

function Timeline({ entries, experiences }: { entries: Entry[]; experiences: any[] }) {
  const items = useMemo(() => {
    const now = new Date().getFullYear() + new Date().getMonth() / 12;
    const fromEntries = entries.flatMap((entry) => {
      const start = toYear(entry.start_date) ?? toYear(entry.end_date);
      if (start === null) return [];
      const ranged = ["education", "work", "military"].includes(entry.kind);
      return [{ key: entry.id, label: entry.title, color: COLORS[entry.kind] ?? "#999", start, end: ranged ? toYear(entry.end_date) ?? now : null, lane: entry.kind }];
    });
    const fromExperiences = experiences.flatMap((item) => {
      const range = periodRange(item.period_text);
      return range ? [{ key: item.id, label: item.title, color: COLORS.experience, start: range[0], end: range[1], lane: "experience" }] : [];
    });
    return [...fromEntries, ...fromExperiences].sort((left, right) => left.start - right.start);
  }, [entries, experiences]);

  if (!items.length) return null;
  const first = Math.floor(Math.min(...items.map((item) => item.start)));
  const last = Math.ceil(Math.max(...items.map((item) => item.end ?? item.start))) + 1;
  const span = Math.max(1, last - first);
  const left = (value: number) => `${((value - first) / span) * 100}%`;
  const years = Array.from({ length: span + 1 }, (_, index) => first + index);
  const levels = 6;
  const height = 34 + levels * 24;
  const lanes = ["education", "work", "military", "experience"];
  return (
    <div className="overflow-x-auto">
      <div className="relative mx-4 min-w-[680px]" style={{ height: height + 28 }} role="img" aria-label="연대기">
        {items.map((item, index) => {
          const level = index % levels;
          return (
            <div key={item.key} className="absolute" style={{ left: left(item.start), top: (levels - 1 - level) * 24, height: height - (levels - 1 - level) * 24 }}>
              <div className="absolute top-3 bottom-0 left-0 w-px opacity-40" style={{ background: item.color }} />
              <div className="flex max-w-44 items-center gap-1 text-[11px] whitespace-nowrap">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: item.color }} />
                <span className="truncate">{item.label}</span>
              </div>
            </div>
          );
        })}
        <div className="absolute inset-x-0" style={{ top: height }}>
          {lanes.map((lane, laneIndex) => items.filter((item) => item.lane === lane && item.end).map((item) => (
            <div key={item.key} title={item.label} className="absolute rounded-sm" style={{ left: left(item.start), width: `${(((item.end ?? item.start) - item.start) / span) * 100}%`, top: laneIndex * 5 - 18, height: 5, background: item.color }} />
          )))}
          <div className="h-px bg-muted" />
          {years.map((year) => <span key={year} className="absolute top-1 -translate-x-1/2 text-[10px] text-muted" style={{ left: left(year) }}>{String(year).slice(2)}</span>)}
        </div>
      </div>
    </div>
  );
}

function EntryDialog({ entry, onClose, onSaved }: { entry: Partial<Entry> | null; onClose: () => void; onSaved: () => void }) {
  const { fail } = useApp();
  const [form, setForm] = useState<Partial<Entry>>({});
  useEffect(() => setForm(entry ?? {}), [entry]);
  const set = (key: keyof Entry) => (event: { target: { value: string } }) => setForm({ ...form, [key]: event.target.value });
  const save = async () => {
    try {
      const body = { kind: form.kind ?? "education", title: form.title, organization: form.organization ?? "", start_date: form.start_date ?? "", end_date: form.end_date ?? "", detail: form.detail ?? "", status: "confirmed" };
      await (form.id ? api(`/profile-entries/${form.id}`, patch(body)) : api("/profile-entries", post(body)));
      onSaved();
    } catch (error) { fail(error); }
  };
  return (
    <Dialog open={!!entry} onClose={onClose} size="sm" title={form.id ? "이력 수정" : "이력 추가"} footer={<><Button onClick={onClose}>취소</Button><Button variant="primary" disabled={!form.title?.trim()} onClick={save}>저장</Button></>}>
      <div className="space-y-3">
        <Field label="종류"><Select value={form.kind ?? "education"} onChange={set("kind")}>{Object.entries(ENTRY_KIND_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Select></Field>
        <Field label="이름"><Input value={form.title ?? ""} onChange={set("title")} placeholder="예: 한양대학교 산업공학과" /></Field>
        <Field label="기관"><Input value={form.organization ?? ""} onChange={set("organization")} /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="시작"><Input value={form.start_date ?? ""} onChange={set("start_date")} placeholder="2021-03" /></Field>
          <Field label="종료"><Input value={form.end_date ?? ""} onChange={set("end_date")} placeholder="2027-02" /></Field>
        </div>
        <Field label="상세"><Textarea value={form.detail ?? ""} onChange={set("detail")} /></Field>
      </div>
    </Dialog>
  );
}

export default function ProfilePage() {
  const { fail, notice } = useApp();
  const [profile, setProfile] = useState<any>(null);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [experiences, setExperiences] = useState<any[]>([]);
  const [narrative, setNarrative] = useState<any>({ paragraphs: [], skills: [] });
  const [editing, setEditing] = useState<Partial<Entry> | null>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const [me, list, all, story] = await Promise.all([
      workspace("/profile"), optional(api<Entry[]>("/profile-entries"), []), optional(api<any[]>("/experiences"), []),
      optional(api("/narrative"), { paragraphs: [], skills: [] }),
    ]);
    setProfile(me);
    setEntries(list);
    setExperiences(all);
    setNarrative(story);
  }, []);
  useEffect(() => { load().catch(fail); }, [load, fail]);

  const run = async (name: string, action: () => Promise<unknown>) => {
    setBusy(name);
    try { await action(); await load(); } catch (error) { fail(error); } finally { setBusy(""); }
  };

  const confirmed = (entries ?? []).filter((entry) => entry.status === "confirmed");
  const candidates = (entries ?? []).filter((entry) => entry.status !== "confirmed");
  const confirmedExperiences = experiences.filter((item) => item.status === "confirmed");
  const projects = confirmedExperiences.filter((item) => item.category !== "취업 준비" && item.category !== "참고자료");
  const titleOf = (id: string) => experiences.find((item) => item.id === id)?.title;

  if (entries === null) return <div className="mx-auto max-w-5xl p-6"><RowsSkeleton rows={8} /></div>;
  const empty = !confirmed.length && !confirmedExperiences.length;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <PageHeader title={profile?.display_name || "내 프로필"} hint={[profile?.school, profile?.major, profile?.grade].filter(Boolean).join(" · ") || "확인한 항목만 표시됩니다."}>
        <Button disabled={busy === "extract"} onClick={() => run("extract", async () => { const result = await api("/profile-entries/extract", post()); notice(`이력 후보 ${result?.created ?? 0}개를 찾았습니다.`); })}><FileSearch className="h-3.5 w-3.5" />이력서에서 찾기</Button>
        <Button onClick={() => setEditing({ kind: "education" })}><Plus className="h-3.5 w-3.5" />이력 추가</Button>
      </PageHeader>
      {profile?.career_goal && <p className="mb-4 text-[13px] text-muted">진로 목표: {profile.career_goal}</p>}
      <div className="mb-4"><GoogleConnectCard /></div>

      {!!candidates.length && (
        <Card className="mb-4 border-warn">
          <h2 className="mb-2 font-semibold">확인이 필요한 이력 {candidates.length}개</h2>
          <div className="space-y-1.5">
            {candidates.map((entry) => (
              <div key={entry.id} className="flex flex-wrap items-center gap-2 text-[13px]">
                <Badge>{ENTRY_KIND_LABEL[entry.kind] ?? entry.kind}</Badge>
                <span className="min-w-0 flex-1 truncate">{entry.title}{entry.organization ? ` · ${entry.organization}` : ""}<span className="ml-1 text-xs text-muted">{shortRange(entry)}</span></span>
                <Button size="sm" variant="primary" onClick={() => run(entry.id, () => api(`/profile-entries/${entry.id}`, patch({ status: "confirmed" })))}><Check className="h-3 w-3" />맞음</Button>
                <Button size="sm" onClick={() => setEditing(entry)}><Pencil className="h-3 w-3" />수정</Button>
                <Button size="sm" onClick={() => run(entry.id, () => api(`/profile-entries/${entry.id}`, { method: "DELETE" }))}><Trash2 className="h-3 w-3" />삭제</Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {empty ? (
        <EmptyState icon={Sparkles} title="아직 확인한 이력이 없습니다" hint="이력서에서 후보를 찾거나 내 경험을 확인하면 연대기가 만들어집니다.">
          <Link prefetch={false} href="/experiences"><Button variant="primary">내 경험 확인하기</Button></Link>
        </EmptyState>
      ) : (
        <>
          <Card className="mb-4"><Timeline entries={confirmed} experiences={confirmedExperiences} /></Card>
          <div className="grid gap-3 md:grid-cols-2">
            {SECTIONS.map(([kind, label, Icon]) => {
              const list = confirmed.filter((entry) => entry.kind === kind);
              if (!list.length) return null;
              return (
                <Card key={kind}>
                  <h2 className="mb-2 flex items-center gap-1.5 font-semibold"><Icon className="h-4 w-4 text-accent" />{label} <span className="text-xs font-normal text-muted">{list.length}건</span></h2>
                  <div className="space-y-2">
                    {list.map((entry) => (
                      <div key={entry.id} className="group flex items-start gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="text-[13px]">{entry.title}</p>
                          <p className="text-xs text-muted">{[entry.organization, shortRange(entry), entry.detail].filter(Boolean).join(" · ")}</p>
                        </div>
                        <Button variant="ghost" size="icon" className="h-6 w-6" aria-label={`${entry.title} 수정`} onClick={() => setEditing(entry)}><Pencil className="h-3 w-3" /></Button>
                      </div>
                    ))}
                  </div>
                </Card>
              );
            })}
            {!!projects.length && (
              <Card>
                <h2 className="mb-2 flex items-center gap-1.5 font-semibold"><FolderKanban className="h-4 w-4 text-accent" />프로젝트·활동 <span className="text-xs font-normal text-muted">{projects.length}건</span></h2>
                <div className="space-y-2">
                  {projects.map((item) => (
                    <Link key={item.id} prefetch={false} href={`/experiences/detail?id=${item.id}`} className="block hover:underline">
                      <p className="text-[13px]">{item.title}</p>
                      <p className="text-xs text-muted">{[item.category, item.period_text].filter(Boolean).join(" · ")}</p>
                    </Link>
                  ))}
                </div>
              </Card>
            )}
          </div>
        </>
      )}

      <section className="mt-6">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">성장 서사</h2>
          {narrative.stale && <Badge tone="warn">갱신 필요</Badge>}
          <span className="flex-1" />
          <Button size="sm" disabled={busy === "narrative" || !confirmedExperiences.length} onClick={() => run("narrative", () => api("/narrative", post()))}><RefreshCw className="h-3 w-3" />{narrative.paragraphs?.length ? "다시 만들기" : "서사 만들기"}</Button>
        </div>
        {narrative.paragraphs?.length ? (
          <Card className="space-y-3">
            {narrative.paragraphs.map((paragraph: any, index: number) => (
              <div key={index}>
                <p className="text-[14px] leading-7">{paragraph.text}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {(paragraph.experience_ids ?? []).map((id: string) => <Link key={id} prefetch={false} href={`/experiences/detail?id=${id}`} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted hover:bg-hover">{titleOf(id) ?? "근거 경험"}</Link>)}
                </div>
              </div>
            ))}
            <p className="text-xs text-muted">확인된 경험으로 AI가 쓴 해석입니다. 자소서의 사실 근거로 직접 쓰이지는 않습니다.</p>
          </Card>
        ) : <p className="text-[13px] text-muted">경험을 확인하면 시간순으로 어떻게 성장했는지 정리합니다.</p>}
        {!!narrative.skills?.length && (
          <div className="mt-3">
            <h3 className="mb-1.5 text-[13px] font-semibold">역량 흐름</h3>
            <div className="flex flex-wrap gap-1.5">{narrative.skills.map((skill: any) => <Badge key={skill.name} tone="accent">{skill.name} · {skill.experience_ids?.length ?? 0}개 경험</Badge>)}</div>
          </div>
        )}
      </section>

      <EntryDialog entry={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load().catch(fail); }} />
    </div>
  );
}
