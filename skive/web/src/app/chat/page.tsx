"use client";

import { FileText, Loader2, MessageSquare, Plus, Send } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn, post, workspace } from "@/lib/skive";
import { useApp } from "@/components/app-shell";
import { Button, EmptyState, RowsSkeleton, Select, Textarea } from "@/components/ui";

type Message = { role: string; content: string; citations?: any[] };

export default function ChatPage() {
  const { fail, openFile, openProject } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const sessionId = params.get("session");
  const presetFolder = params.get("folder");
  const [sessions, setSessions] = useState<any[] | null>(null);
  const [folders, setFolders] = useState<any[]>([]);
  const [scope, setScope] = useState(presetFolder ?? "");
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const skipLoad = useRef<string | null>(null);

  const loadSessions = useCallback(() => workspace("/chat/sessions").then(setSessions), []);
  useEffect(() => {
    loadSessions().catch(fail);
    workspace("/folders").then(setFolders).catch(fail);
  }, [loadSessions, fail]);

  useEffect(() => {
    if (presetFolder) setScope(presetFolder);
  }, [presetFolder]);

  useEffect(() => {
    if (!sessionId) { setMessages([]); return; }
    if (skipLoad.current === sessionId) { skipLoad.current = null; return; }
    workspace(`/chat/sessions/${sessionId}`).then((result) => {
      setMessages(result.messages);
      setScope(result.folder_id ?? "");
    }).catch(fail);
  }, [sessionId, fail]);

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [messages, busy]);

  const send = async () => {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true);
    setText("");
    setMessages((items) => [...items, { role: "user", content: message }]);
    try {
      let id = sessionId;
      if (!id) {
        id = (await workspace("/chat/sessions", post({ folder_id: scope || null }))).id as string;
        skipLoad.current = id;
        router.replace(`/chat?session=${id}`);
      }
      const result = await workspace(`/chat/sessions/${id}/messages`, post({ message }));
      setMessages((items) => [...items, result]);
      await loadSessions();
    } catch (error) {
      fail(error);
      setText(message);
      setMessages((items) => items.slice(0, -1));
    } finally {
      setBusy(false);
    }
  };

  const openSource = (source: any) => source.source_type === "project_summary" ? openProject(source.project_folder_id) : openFile(source.file_id);

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line p-2 md:flex">
        <Button id="chat-new" className="mb-2 w-full" onClick={() => { setScope(""); router.push("/chat"); }}><Plus className="h-3.5 w-3.5" />새 대화</Button>
        <div id="chat-session-list" className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {sessions === null ? <RowsSkeleton rows={4} /> : sessions.map((item) => (
            <button key={item.id} type="button" title={item.folder_name ? `${item.folder_name} 범위` : "전체 드라이브"} onClick={() => router.push(`/chat?session=${item.id}`)} className={cn("block w-full truncate rounded px-2 py-1.5 text-left text-[13px] hover:bg-hover", item.id === sessionId && "bg-hover font-medium")}>{item.title}</button>
          ))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2">
          <span className="text-xs text-muted">검색 범위</span>
          <Select id="chat-scope" aria-label="검색 범위" className="max-w-xs" value={scope} disabled={!!sessionId} onChange={(event) => setScope(event.target.value)}>
            <option value="">전체 드라이브</option>
            {folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.path}</option>)}
          </Select>
          {sessionId && <span className="text-xs text-muted">범위를 바꾸려면 새 대화를 시작하세요</span>}
          <Select aria-label="대화 선택" className="max-w-40 md:hidden" value={sessionId ?? ""} onChange={(event) => router.push(event.target.value ? `/chat?session=${event.target.value}` : "/chat")}>
            <option value="">새 대화</option>
            {(sessions ?? []).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </Select>
        </div>

        <div id="chat-log" ref={log} className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-5">
            {!messages.length && !busy && <EmptyState icon={MessageSquare} title="내 자료에 대해 물어보세요" hint="답변에는 어떤 파일을 근거로 썼는지 출처가 함께 표시됩니다." />}
            {messages.map((message, index) => (
              <div key={index} className={cn(message.role === "user" && "flex justify-end")}>
                <div className={cn("text-[14px] leading-7 whitespace-pre-wrap", message.role === "user" && "max-w-[80%] rounded-2xl bg-hover px-4 py-2")}>{message.content}</div>
                {message.role === "assistant" && !!message.citations?.length && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {message.citations.map((source, sourceIndex) => (
                      <button key={sourceIndex} type="button" onClick={() => openSource(source)} title={source.location} className="inline-flex max-w-64 items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs text-muted hover:bg-hover hover:text-ink">
                        <FileText className="h-3 w-3 shrink-0" /><span className="truncate">[{source.index}] {source.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {busy && <p className="flex items-center gap-2 text-[13px] text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />내 자료를 검색하고 답변하는 중…</p>}
          </div>
        </div>

        <div className="border-t border-line p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Textarea id="chat-input" aria-label="메시지" className="min-h-10 flex-1 resize-none" rows={2} placeholder="메시지 입력 (Enter 전송, Shift+Enter 줄바꿈)" value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }} />
            <Button id="chat-send" variant="primary" size="icon" aria-label="보내기" disabled={busy || !text.trim()} onClick={send}><Send className="h-4 w-4" /></Button>
          </div>
        </div>
      </div>
    </div>
  );
}
