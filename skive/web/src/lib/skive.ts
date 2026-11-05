import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export type Config = { url: string; key: string; bucket: string };

let configPromise: Promise<Config> | null = null;
let clientPromise: Promise<SupabaseClient> | null = null;

export function getConfig(): Promise<Config> {
  configPromise ??= fetch("/api/drive/config").then(async (response) => {
    if (!response.ok) {
      configPromise = null;
      throw new Error("서버 설정을 불러오지 못했습니다. 잠시 뒤 새로고침해 주세요.");
    }
    return response.json();
  });
  return configPromise;
}

export function getSupabase(): Promise<SupabaseClient> {
  clientPromise ??= getConfig().then((config) => createClient(config.url, config.key));
  return clientPromise;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(prefix: string, path: string, options: RequestInit = {}): Promise<T> {
  const supabase = await getSupabase();
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new ApiError("로그인이 필요합니다", 401);
  const response = await fetch(`/api/${prefix}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${data.session.access_token}`, ...options.headers },
  });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `요청 실패 (${response.status})`, response.status);
  }
  return body as T;
}

export const api = <T = any>(path: string, options?: RequestInit) => request<T>("drive", path, options);
export const workspace = <T = any>(path: string, options?: RequestInit) => request<T>("workspace", path, options);
export const career = <T = any>(path: string, options?: RequestInit) => request<T>("career", path, options);

export const post = (body?: unknown): RequestInit => ({ method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = (body: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(body) });

/** New endpoints may not be deployed yet; a missing route should read as an empty screen. */
export async function optional<T>(load: Promise<T>, fallback: T): Promise<T> {
  try {
    return await load;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405 || error.status === 410)) return fallback;
    throw error;
  }
}

export const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function authErrorMessage(error: unknown) {
  const message = errorText(error);
  if (/invalid login credentials/i.test(message)) return "이메일 또는 비밀번호가 맞지 않습니다.";
  if (/email not confirmed/i.test(message)) return "이메일 확인이 필요합니다. 받은편지함과 스팸함을 확인해 주세요.";
  if (/user already registered/i.test(message)) return "이미 가입된 이메일입니다. 로그인해 주세요.";
  return message;
}

export function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  const unit = Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** unit).toFixed(1)} ${["B", "KB", "MB", "GB", "TB"][unit]}`;
}

export const formatDate = (value?: string | null) => (value ? new Date(value).toLocaleDateString("ko-KR") : "—");

export function saveText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const ANALYSIS_LABEL: Record<string, string> = {
  waiting: "대기", queued: "읽기 대기", processing: "읽는 중", ready: "읽음", unsupported: "읽기 미지원", failed: "읽기 실패",
};
export const FACT_KIND_LABEL: Record<string, string> = {
  context: "배경", goal: "목표", action: "수행", result: "결과", skill: "역량", lesson: "배운 점", other: "기타",
};
export const SUBJECT_LABEL: Record<string, string> = { unclear: "주체 불명", project: "프로젝트", team: "팀", user: "내가 직접 함" };
export const REVIEW_LABEL: Record<string, string> = { candidate: "확인 대기", confirmed: "확인됨", rejected: "제외됨" };
export const JOB_LABEL: Record<string, string> = {
  idle: "시작 전", queued: "대기 중", processing: "분석 중", ready: "완료", failed: "실패", missing: "없음",
};
export const OWNER_LABEL: Record<string, string> = { self: "본인", team: "팀", other_person: "타인", reference: "참고자료", unknown: "불명" };
export const DOC_TYPE_LABEL: Record<string, string> = {
  report: "보고서", slides: "발표자료", code: "코드", data: "데이터", essay: "자소서", resume: "이력서", job_posting: "공고",
  lecture: "강의자료", exam: "시험자료", notes: "노트", certificate: "증명서", other: "기타",
};
export const EXPERIENCE_STATUS_LABEL: Record<string, string> = { candidate: "확인 대기", confirmed: "확인됨", excluded: "제외됨" };
export const CATEGORIES = ["학교 수업", "프로젝트", "대외활동·공모전", "인턴·직장", "연구", "취업 준비", "참고자료"];
export const ENTRY_KIND_LABEL: Record<string, string> = {
  education: "학력", work: "직장경력", military: "병역", license: "자격증", language: "어학", award: "수상", overseas: "해외경험",
};
