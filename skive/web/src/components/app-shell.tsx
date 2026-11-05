"use client";

import type { Session } from "@supabase/supabase-js";
import { BriefcaseBusiness, FileText, FolderOpen, LogOut, Menu as MenuIcon, MessageSquare, Moon, Settings, Sparkles, Sun, UserRound, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { authErrorMessage, cn, errorText, getSupabase } from "@/lib/skive";
import { FileViewer } from "@/components/file-viewer";
import { ProjectSummary } from "@/components/project-summary";
import { Button, Skeleton } from "@/components/ui";
import { droppedItems, UploadToast, useUploader, type UploadItem } from "@/components/upload";

type Toast = { id: number; text: string; tone: "info" | "error" };
type App = {
  session: Session | null;
  notice: (text: string) => void;
  fail: (error: unknown) => void;
  openFile: (id: string) => void;
  openProject: (folderId: string) => void;
  uploadItems: (items: UploadItem[], parentId: string | null) => Promise<void>;
  driveVersion: number;
  signOut: () => void;
};

const AppContext = createContext<App | null>(null);
export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("AppShell is missing");
  return value;
}

const NAV: [string, string, LucideIcon][] = [
  ["/drive", "내 드라이브", FolderOpen],
  ["/experiences", "내 경험", Sparkles],
  ["/chat", "챗봇", MessageSquare],
  ["/career", "자소서", FileText],
  ["/profile", "프로필", UserRound],
  ["/settings", "설정", Settings],
];

function Sidebar({ email, open, onClose, onSignOut }: { email?: string; open: boolean; onClose: () => void; onSignOut: () => void }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("skive-theme", next ? "dark" : "light"); } catch {}
  };
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={onClose} />}
      <aside className={cn("fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-line bg-sidebar transition-transform md:static md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-12 items-center justify-between px-4">
          <Link prefetch={false} href="/drive" className="flex items-center gap-1.5 text-[15px] font-bold tracking-tight" onClick={onClose}><BriefcaseBusiness className="h-4 w-4 text-accent" />SKIVE</Link>
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="메뉴 닫기" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        <nav className="flex-1 space-y-0.5 px-2 py-1" aria-label="주 메뉴">
          {NAV.map(([href, label, Icon]) => {
            const active = pathname?.startsWith(href);
            return (
              <Link key={href} prefetch={false} href={href} onClick={onClose} aria-current={active ? "page" : undefined} className={cn("flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px]", active ? "bg-hover font-medium" : "text-muted hover:bg-hover hover:text-ink")}>
                <Icon className="h-4 w-4" />{label}
              </Link>
            );
          })}
        </nav>
        <div className="space-y-1 border-t border-line p-2">
          <p className="truncate px-2 text-[11px] text-muted" title={email}>{email}</p>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="flex-1 justify-start" onClick={toggleTheme}>{dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}{dark ? "밝게" : "어둡게"}</Button>
            <Button variant="ghost" size="sm" onClick={onSignOut}><LogOut className="h-3.5 w-3.5" />로그아웃</Button>
          </div>
        </div>
      </aside>
    </>
  );
}

function Workspace({ children, session, signOut, value }: { children: ReactNode; session: Session; signOut: () => void; value: App & { panel: ReturnType<typeof useUploader>["panel"] } }) {
  const [menu, setMenu] = useState(false);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const router = useRouter();
  const pathname = usePathname();
  const hasFiles = (event: React.DragEvent) => [...event.dataTransfer.types].includes("Files");

  const onDrop = (event: React.DragEvent) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth.current = 0;
    setDragging(false);
    const pending = droppedItems(event.dataTransfer);
    const folder = pathname?.startsWith("/drive") ? new URLSearchParams(window.location.search).get("folder") : null;
    if (!pathname?.startsWith("/drive")) router.push("/drive");
    pending.then((items) => value.uploadItems(items, folder)).catch(value.fail);
  };

  return (
    <div id="app" className={cn("flex h-dvh overflow-hidden", dragging && "drop-active")}
      onDragEnter={(event) => { if (hasFiles(event)) { depth.current++; setDragging(true); } }}
      onDragOver={(event) => { if (hasFiles(event)) event.preventDefault(); }}
      onDragLeave={(event) => { if (hasFiles(event) && --depth.current <= 0) { depth.current = 0; setDragging(false); } }}
      onDrop={onDrop}>
      <Sidebar email={session.user.email} open={menu} onClose={() => setMenu(false)} onSignOut={signOut} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 items-center gap-2 border-b border-line px-3 md:hidden">
          <Button variant="ghost" size="icon" aria-label="메뉴 열기" onClick={() => setMenu(true)}><MenuIcon className="h-4 w-4" /></Button>
          <span className="font-bold">SKIVE</span>
        </div>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Suspense fallback={<div className="p-6"><Skeleton className="h-40 w-full" /></div>}>{children}</Suspense>
        </main>
      </div>
      {dragging && <div className="pointer-events-none fixed inset-2 z-50 flex items-end justify-center rounded-xl border-2 border-dashed border-accent bg-accent/5 pb-8"><span className="rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-accent-text">놓으면 지금 폴더에 올립니다</span></div>}
      {value.panel && <UploadToast panel={value.panel} />}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [fileId, setFileId] = useState<string | null>(null);
  const [folderId, setFolderId] = useState<string | null>(null);
  const [driveVersion, setDriveVersion] = useState(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const push = useCallback((text: string, tone: Toast["tone"]) => {
    const id = Date.now() + Math.random();
    setToasts((items) => [...items, { id, text, tone }]);
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 5000);
  }, []);
  const notice = useCallback((text: string) => push(text, "info"), [push]);
  const fail = useCallback((error: unknown) => { console.error(error); push(errorText(error), "error"); }, [push]);
  const changed = useCallback(() => {
    if (refreshTimer.current) return;
    refreshTimer.current = setTimeout(() => { refreshTimer.current = null; setDriveVersion((value) => value + 1); }, 1500);
  }, []);
  const { uploadItems, panel } = useUploader(session?.user.id, notice, changed);

  useEffect(() => {
    let unsubscribe = () => {};
    getSupabase().then(async (supabase) => {
      const { data } = await supabase.auth.getSession();
      setSession(data.session);
      setReady(true);
      const { data: listener } = supabase.auth.onAuthStateChange((_event, active) => setTimeout(() => setSession(active), 0));
      unsubscribe = () => listener.subscription.unsubscribe();
    }).catch((error) => { setBootError(authErrorMessage(error)); setReady(true); });
    return () => unsubscribe();
  }, []);

  const isLogin = pathname?.startsWith("/login");
  useEffect(() => {
    if (!ready || bootError) return;
    if (!session && !isLogin) router.replace("/login");
    if (session && (isLogin || pathname === "/")) {
      const google = new URLSearchParams(window.location.search).get("google");
      if (google) {
        const messages: Record<string, string> = { connected: "구글 드라이브를 연동했습니다.", denied: "구글 드라이브 연동을 취소했습니다.", failed: "구글 드라이브 연동에 실패했습니다. 다시 시도해 주세요." };
        if (messages[google]) notice(messages[google]);
      }
      router.replace(google ? "/profile" : "/drive");
    }
  }, [ready, bootError, session, isLogin, pathname, router, notice]);

  const signOut = useCallback(() => { getSupabase().then((supabase) => supabase.auth.signOut()).catch(fail); }, [fail]);
  const closeFile = useCallback(() => setFileId(null), []);
  const closeProject = useCallback(() => setFolderId(null), []);
  const value = useMemo<App>(() => ({ session, notice, fail, openFile: setFileId, openProject: setFolderId, uploadItems, driveVersion, signOut }), [session, notice, fail, uploadItems, driveVersion, signOut]);

  return (
    <AppContext.Provider value={value}>
      {isLogin ? children
        : bootError ? <div className="flex h-dvh items-center justify-center p-6 text-center text-[13px] text-danger">{bootError}</div>
        : session ? <Workspace session={session} signOut={signOut} value={{ ...value, panel }}>{children}</Workspace>
        : <div className="flex h-dvh items-center justify-center"><Skeleton className="h-8 w-40" /></div>}
      {session && <FileViewer fileId={fileId} onClose={closeFile} />}
      {session && <ProjectSummary folderId={folderId} onClose={closeProject} />}
      <div className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
        {toasts.map((toast) => <div key={toast.id} className={cn("max-w-md rounded-md px-3 py-2 text-[13px] shadow-lg", toast.tone === "error" ? "bg-danger text-white dark:text-black" : "bg-ink text-bg")}>{toast.text}</div>)}
      </div>
    </AppContext.Provider>
  );
}
