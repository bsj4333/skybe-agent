"use client";

import { BriefcaseBusiness } from "lucide-react";
import { useState, type FormEvent } from "react";
import { authErrorMessage, getSupabase } from "@/lib/skive";
import { Button, Field, Input } from "@/components/ui";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(kind: "signin" | "signup") {
    if (!email.trim() || !password) {
      setMessage({ text: "이메일과 비밀번호를 입력해 주세요.", error: true });
      return;
    }
    setBusy(true);
    setMessage({ text: kind === "signin" ? "로그인 확인 중..." : "가입 요청 중..." });
    try {
      const supabase = await getSupabase();
      const credentials = { email: email.trim(), password };
      // Without emailRedirectTo the confirmation link follows the project's Site URL, which was localhost.
      const result = await (kind === "signin"
        ? supabase.auth.signInWithPassword(credentials)
        : supabase.auth.signUp({ ...credentials, options: { emailRedirectTo: `${window.location.origin}/login/` } }));
      if (result.error) throw result.error;
      if (!result.data.session) setMessage({ text: "이메일 확인 링크를 보냈습니다. 받은편지함과 스팸함을 확인한 뒤 로그인해 주세요." });
    } catch (error) {
      setMessage({ text: authErrorMessage(error), error: true });
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (event: FormEvent) => { event.preventDefault(); submit("signin"); };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-sidebar p-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm rounded-xl border border-line bg-surface p-6 shadow-sm">
        <div className="mb-1 flex items-center gap-2 text-lg font-bold"><BriefcaseBusiness className="h-5 w-5 text-accent" />SKIVE</div>
        <p className="mb-5 text-[13px] text-muted">내 자료로 경험을 정리하고 자소서를 씁니다.</p>
        <div className="space-y-3">
          <Field label="이메일"><Input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
          <Field label="비밀번호"><Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field>
        </div>
        <p role="status" aria-live="polite" className={`mt-3 min-h-5 text-[13px] ${message?.error ? "text-danger" : "text-muted"}`}>{message?.text}</p>
        <div className="mt-2 flex gap-2">
          <Button id="signin" type="submit" variant="primary" className="flex-1" disabled={busy}>로그인</Button>
          <Button id="signup" className="flex-1" disabled={busy} onClick={() => submit("signup")}>가입하기</Button>
        </div>
      </form>
    </div>
  );
}
