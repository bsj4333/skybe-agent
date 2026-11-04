-- Account-scoped profile, conversations, and essay drafts for the Supabase drive.
create table skive.drive_profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    display_name text not null default '',
    school text not null default '',
    major text not null default '',
    grade text not null default '',
    career_goal text not null default '',
    personal_notes text not null default '',
    essay_style text not null default '',
    updated_at timestamptz not null default now()
);

create table skive.drive_chat_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    folder_id uuid,
    title text not null default '새 대화',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id),
    constraint drive_chat_folder_owner_fk foreign key (user_id, folder_id)
        references skive.drive_folders(user_id, id) on delete restrict
);
create index drive_chat_sessions_owner_idx on skive.drive_chat_sessions(user_id, updated_at desc);

create table skive.drive_chat_messages (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    session_id uuid not null,
    role text not null check (role in ('user','assistant')),
    content text not null,
    citations jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    constraint drive_chat_message_owner_fk foreign key (user_id, session_id)
        references skive.drive_chat_sessions(user_id, id) on delete cascade
);
create index drive_chat_messages_session_idx on skive.drive_chat_messages(session_id, id);

create table skive.drive_essays (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    folder_id uuid,
    job_text text not null,
    question text not null,
    draft text not null,
    citations jsonb not null default '[]'::jsonb,
    review_status text not null default 'needs_review',
    revision_count int not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint drive_essay_folder_owner_fk foreign key (user_id, folder_id)
        references skive.drive_folders(user_id, id) on delete restrict
);
create index drive_essays_owner_idx on skive.drive_essays(user_id, updated_at desc);

alter table skive.drive_profiles enable row level security;
alter table skive.drive_chat_sessions enable row level security;
alter table skive.drive_chat_messages enable row level security;
alter table skive.drive_essays enable row level security;

create policy drive_profiles_owner on skive.drive_profiles for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy drive_chat_sessions_owner on skive.drive_chat_sessions for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy drive_chat_messages_owner on skive.drive_chat_messages for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy drive_essays_owner on skive.drive_essays for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

grant select, insert, update, delete on skive.drive_profiles, skive.drive_chat_sessions,
    skive.drive_chat_messages, skive.drive_essays to authenticated;
grant usage, select on sequence skive.drive_chat_messages_id_seq to authenticated;
revoke all on skive.drive_profiles, skive.drive_chat_sessions,
    skive.drive_chat_messages, skive.drive_essays from anon;
