CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  wa_id           text UNIQUE NOT NULL,           -- E.164, no plus sign
  name            text,
  tz              text NOT NULL DEFAULT 'Asia/Dhaka',
  lang_style      text NOT NULL DEFAULT 'banglish', -- bangla|banglish|english
  brief_time      time NOT NULL DEFAULT '07:30',
  last_inbound_at timestamptz,                    -- drives the 24-hour window
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------- messages
CREATE TABLE IF NOT EXISTS messages (
  id              bigserial PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES users(id),
  direction       text NOT NULL CHECK (direction IN ('in','out')),
  wamid           text UNIQUE,                    -- dedupe + quoted replies
  reply_to_wamid  text,
  kind            text,                           -- text|audio|image|button
  body            text,
  transcript      text,
  media_id        text,
  entity_refs     jsonb NOT NULL DEFAULT '[]',
  status          text NOT NULL DEFAULT 'queued', -- queued|processing|done|failed
  attempts        int  NOT NULL DEFAULT 0,
  error           text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS msg_queue_idx
  ON messages (created_at) WHERE direction = 'in' AND status = 'queued';
CREATE INDEX IF NOT EXISTS msg_user_idx ON messages (user_id, created_at DESC);

-- ----------------------------------------------------------- actions_log
CREATE TABLE IF NOT EXISTS actions_log (
  id           bigserial PRIMARY KEY,
  user_id      uuid   NOT NULL REFERENCES users(id),
  msg_id       bigint NOT NULL REFERENCES messages(id),
  idx          int    NOT NULL,
  tool         text   NOT NULL,
  args         jsonb,
  result       jsonb,
  entity_type  text,
  entity_id    uuid,
  undone_at    timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (msg_id, idx)                            -- the idempotency guard
);

-- -------------------------------------------------------------- expenses
CREATE TABLE IF NOT EXISTS expenses (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id),
  amount_minor  bigint NOT NULL,                  -- paisa; never a float
  currency      text NOT NULL DEFAULT 'BDT',
  category      text,
  pay_method    text,
  note          text,
  spent_on      date NOT NULL,
  src_msg_id    bigint,
  deleted_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS exp_user_date_idx ON expenses (user_id, spent_on);

-- ------------------------------------------------------------- reminders
CREATE TABLE IF NOT EXISTS reminders (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id),
  title          text NOT NULL,
  kind           text NOT NULL DEFAULT 'reminder',  -- reminder|task
  due_local      timestamp,                         -- wall clock the user meant
  tz             text NOT NULL DEFAULT 'Asia/Dhaka',
  rrule          text,                              -- e.g. FREQ=DAILY
  next_fire_at   timestamptz,                       -- the UTC instant to fire
  status         text NOT NULL DEFAULT 'scheduled', -- scheduled|sending|sent|done|withheld
  snoozed_until  timestamptz,
  src_msg_id     bigint,
  deleted_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rem_due_idx ON reminders (next_fire_at)
  WHERE status = 'scheduled' AND deleted_at IS NULL;

-- -------------------------------------------------------------- memories
CREATE TABLE IF NOT EXISTS memories (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  kind        text NOT NULL DEFAULT 'note',
  subject     text,                                 -- "internet", "Tanvir"
  content     text NOT NULL,                        -- the user's own words
  canonical   text,                                 -- short English keywords
  embedding   vector(768),                          -- unused in the demo
  src_msg_id  bigint,
  deleted_at  timestamptz,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mem_user_idx ON memories (user_id);
CREATE INDEX IF NOT EXISTS mem_trgm_idx
  ON memories USING gin ((coalesce(content,'') || ' ' || coalesce(canonical,'')) gin_trgm_ops);

-- --------------------------------------------------------- lists + items
CREATE TABLE IF NOT EXISTS lists (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  name        text NOT NULL,
  deleted_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS list_name_idx
  ON lists (user_id, lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS list_items (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  list_id     uuid NOT NULL REFERENCES lists(id),
  text        text NOT NULL,
  done        boolean NOT NULL DEFAULT false,
  src_msg_id  bigint,
  deleted_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS item_list_idx ON list_items (list_id) WHERE deleted_at IS NULL;

-- -------------------------------------------------------- scheduled_jobs
CREATE TABLE IF NOT EXISTS scheduled_jobs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id),
  kind         text NOT NULL,                     -- morning_brief
  local_time   time NOT NULL,
  next_run_at  timestamptz NOT NULL,
  enabled      boolean NOT NULL DEFAULT true,
  UNIQUE (user_id, kind)
);
