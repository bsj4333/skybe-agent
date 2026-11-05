"use client";

import { LogOut } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { career, post, workspace } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { GoogleConnectCard } from "@/components/google-drive";
import { Button, Card, Field, Input, PageHeader, RowsSkeleton, Textarea } from "@/components/ui";

const FIELDS: [string, string, number, boolean?][] = [
  ["display_name", "이름", 100], ["school", "학교", 200], ["major", "전공", 200], ["grade", "학년·시기", 100],
  ["career_goal", "진로 목표", 3000, true], ["personal_notes", "내가 직접 적는 경험 메모", 10000, true], ["essay_style", "자소서 문체 지침", 3000, true],
];

export default function SettingsPage() {
  const { fail, notice, session, signOut } = useApp();
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [memory, setMemory] = useState<any[]>([]);
  const [memo, setMemo] = useState("");

  const loadMemory = useCallback(() => career("/memory").then(setMemory), []);
  useEffect(() => {
    workspace("/profile").then((profile) => setForm(Object.fromEntries(FIELDS.map(([key]) => [key, profile[key] ?? ""])))).catch(fail);
    loadMemory().catch(fail);
  }, [loadMemory, fail]);

  const save = async () => {
    try {
      await workspace("/profile", { method: "PUT", body: JSON.stringify(Object.fromEntries(Object.entries(form!).map(([key, value]) => [key, value.trim()]))) });
      notice("프로필을 저장했습니다.");
    } catch (error) { fail(error); }
  };
  const saveMemo = async () => {
    if (!memo.trim()) return;
    try {
      await career("/memory", post({ content: memo.trim() }));
      setMemo("");
      await loadMemory();
      notice("본인 진술로 저장했습니다.");
    } catch (error) { fail(error); }
  };
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-6 md:px-8">
      <PageHeader title="설정" />

      <GoogleConnectCard />

      <Card>
        <h2 className="mb-1 font-semibold">기본 프로필</h2>
        <p className="mb-3 text-xs text-muted">여기 적은 내용은 본인 진술로 저장됩니다. 이름은 내 자료와 다른 사람 자료를 구분하는 기준입니다.</p>
        {!form ? <RowsSkeleton rows={4} /> : (
          <div className="grid gap-3 sm:grid-cols-2">
            {FIELDS.map(([key, label, limit, wide]) => (
              <Field key={key} label={label} className={wide ? "sm:col-span-2" : undefined}>
                {wide ? <Textarea id={`profile-${key}`} maxLength={limit} value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /> : <Input id={`profile-${key}`} maxLength={limit} value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />}
              </Field>
            ))}
            <div className="sm:col-span-2"><Button id="profile-save" variant="primary" onClick={save}>저장</Button></div>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-1 font-semibold">내가 확인한 경험 메모</h2>
        <p className="mb-3 text-xs text-muted">직접 말한 내용은 본인 진술로 저장되고, 파일에서 확인된 사실과 구분해 씁니다.</p>
        <Textarea id="profile-memory-input" maxLength={4000} placeholder="예: 그 프로젝트에서 저는 데이터 전처리를 맡았습니다." value={memo} onChange={(event) => setMemo(event.target.value)} />
        <Button className="mt-2" onClick={saveMemo}>메모 저장</Button>
        <div id="profile-memory-list" className="mt-3 space-y-1.5">
          {memory.map((item) => <p key={item.id} className="rounded-md bg-hover px-3 py-2 text-[13px]">{item.content}</p>)}
          {!memory.length && <p className="text-xs text-muted">아직 저장한 메모가 없습니다.</p>}
        </div>
      </Card>

      <Card>
        <h2 className="mb-1 font-semibold">계정</h2>
        <p className="mb-3 text-[13px] text-muted">{session?.user.email}</p>
        <Button onClick={signOut}><LogOut className="h-3.5 w-3.5" />로그아웃</Button>
      </Card>

    </div>
  );
}
