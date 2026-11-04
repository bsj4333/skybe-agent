-- File/version reading manifests. Samples are raw source observations, not verified facts.
create table skive.drive_file_read_cards (
    user_id uuid not null,
    file_id uuid not null,
    file_version int not null check (file_version >= 1),
    parser_version text not null,
    status text not null check (status in ('ready','unsupported','failed')),
    chunk_count int not null default 0 check (chunk_count >= 0),
    quote_count int not null default 0 check (quote_count >= 0),
    number_count int not null default 0 check (number_count >= 0),
    quote_samples jsonb not null default '[]'::jsonb,
    number_samples jsonb not null default '[]'::jsonb,
    coverage jsonb not null default '{}'::jsonb,
    error text,
    created_at timestamptz not null default now(),
    primary key (file_id, file_version),
    constraint drive_read_card_file_owner_fk foreign key (user_id, file_id)
        references skive.drive_files(user_id, id) on delete cascade
);
create index drive_file_read_cards_owner_idx on skive.drive_file_read_cards(user_id, file_id);
alter table skive.drive_file_read_cards enable row level security;
create policy drive_file_read_cards_owner on skive.drive_file_read_cards for select to authenticated
    using (user_id = (select auth.uid()));
grant select on skive.drive_file_read_cards to authenticated;
revoke all on skive.drive_file_read_cards from anon;
