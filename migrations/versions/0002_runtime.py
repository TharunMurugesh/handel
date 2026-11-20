"""P2 runtime: Buy-loop tables, workflow infrastructure, governance, row-level security.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19

Design notes (architecture §4.1, §5, §10):
- Business rows carry ``unit_id``. Row-level security isolates units for the
  ``handel_app`` role, which unit-scoped sessions switch to with ``SET LOCAL ROLE``.
  System loops (dispatcher, scheduler) run as the table owner and see all units.
- ``ops.job`` and ``ops.outbox`` are claimed with ``FOR UPDATE SKIP LOCKED``.
- ``ops.audit_event`` is append-only (a trigger blocks UPDATE and DELETE) and
  hash-chained. It stores ids only, never personal data, so erasure never needs to edit it.
- The ``handel_app`` role is cluster-wide, so downgrade leaves it in place.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "handel_app"

# Tables isolated per unit with row-level security.
RLS_TABLES = (
    "core.person",
    "core.supplier",
    "cases.need",
    "cases.purchase_case",
    "cases.quote",
    "cases.landed_cost",
    "cases.case_event",
    "cases.approval",
    "privacy.consent",
)

UPGRADE = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------- identity and tenancy ----------
CREATE TABLE core.unit (
    id text PRIMARY KEY,
    name text NOT NULL,
    itc_eligible boolean NOT NULL,
    cost_of_money_monthly numeric(6,4) NOT NULL CHECK (cost_of_money_monthly BETWEEN 0 AND 0.10),
    settings jsonb NOT NULL DEFAULT '{{}}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.person (
    id text PRIMARY KEY,
    unit_id text REFERENCES core.unit(id),
    role text NOT NULL CHECK (role IN ('owner', 'delegate', 'operator')),
    name text NOT NULL,
    phone_enc bytea,
    phone_hash text,
    language text NOT NULL DEFAULT 'en',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX person_phone_hash ON core.person (phone_hash) WHERE phone_hash IS NOT NULL;

CREATE TABLE core.supplier (
    id text PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    name text NOT NULL,
    phone_enc bytea,
    phone_hash text,
    mode text NOT NULL DEFAULT 'compete' CHECK (mode IN ('compete', 'relationship')),
    materials text[] NOT NULL DEFAULT '{{}}',
    language text NOT NULL DEFAULT 'en',
    source text NOT NULL DEFAULT 'owner',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX supplier_unit_phone ON core.supplier (unit_id, phone_hash)
    WHERE phone_hash IS NOT NULL;

CREATE TABLE core.channel_identity (
    id bigserial PRIMARY KEY,
    party_type text NOT NULL CHECK (party_type IN ('person', 'supplier', 'transporter', 'buyer')),
    party_id text NOT NULL,
    channel text NOT NULL,
    handle text NOT NULL,
    verified_at timestamptz,
    UNIQUE (channel, handle)
);

-- ---------- cases ----------
CREATE TABLE cases.need (
    id text PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cases.purchase_case (
    id text PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    need_id text NOT NULL REFERENCES cases.need(id),
    state text NOT NULL,
    plan jsonb NOT NULL DEFAULT '[]',
    version integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cases.quote (
    id text PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    case_id text NOT NULL REFERENCES cases.purchase_case(id),
    supplier_id text NOT NULL REFERENCES core.supplier(id),
    round integer NOT NULL DEFAULT 0,
    payload jsonb NOT NULL,
    received_at timestamptz NOT NULL
);

CREATE TABLE cases.landed_cost (
    quote_id text PRIMARY KEY REFERENCES cases.quote(id),
    unit_id text NOT NULL REFERENCES core.unit(id),
    effective_paise bigint NOT NULL,
    components jsonb NOT NULL,
    flags text[] NOT NULL DEFAULT '{{}}',
    trace jsonb NOT NULL
);

CREATE TABLE cases.case_event (
    id bigserial PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    case_id text NOT NULL,
    seq integer NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{{}}',
    created_at timestamptz NOT NULL,
    UNIQUE (case_id, seq)
);

CREATE TABLE cases.approval (
    id text PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    case_id text NOT NULL,
    kind text NOT NULL,
    approver_id text NOT NULL,
    approver_role text NOT NULL,
    channel text NOT NULL,
    granted_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    terms_digest text,
    used_at timestamptz
);

-- ---------- privacy ----------
CREATE TABLE privacy.consent (
    id bigserial PRIMARY KEY,
    unit_id text NOT NULL REFERENCES core.unit(id),
    party_type text NOT NULL,
    party_id text NOT NULL,
    purpose text NOT NULL,
    notice_version text NOT NULL,
    language text NOT NULL,
    granted_at timestamptz NOT NULL,
    withdrawn_at timestamptz
);
CREATE INDEX consent_lookup ON privacy.consent (party_type, party_id, purpose);

-- ---------- workflow infrastructure ----------
CREATE TABLE ops.inbound_event (
    id bigserial PRIMARY KEY,
    channel text NOT NULL,
    update_id text NOT NULL,
    payload jsonb NOT NULL,
    received_at timestamptz NOT NULL,
    UNIQUE (channel, update_id)
);

CREATE TABLE ops.job (
    id bigserial PRIMARY KEY,
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{{}}',
    unit_id text,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    run_after timestamptz NOT NULL,
    locked_by text,
    locked_until timestamptz,
    last_error text,
    idempotency_key text UNIQUE,
    created_at timestamptz NOT NULL,
    done_at timestamptz
);
CREATE INDEX job_claimable ON ops.job (run_after, id) WHERE status IN ('queued', 'running');

CREATE TABLE ops.outbox (
    id bigserial PRIMARY KEY,
    unit_id text NOT NULL,
    case_id text,
    idempotency_key text NOT NULL UNIQUE,
    message_id text NOT NULL,
    purpose text NOT NULL,
    channel text NOT NULL,
    chat_id text NOT NULL,
    party_type text NOT NULL,
    party_id text NOT NULL,
    body jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'refused')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 8,
    next_attempt_at timestamptz NOT NULL,
    locked_until timestamptz,
    claim_token text,
    provider_message_id text,
    last_error text,
    created_at timestamptz NOT NULL,
    sent_at timestamptz
);
CREATE INDEX outbox_claimable ON ops.outbox (next_attempt_at, id)
    WHERE status IN ('queued', 'sending');

CREATE TABLE ops.timer (
    id bigserial PRIMARY KEY,
    unit_id text NOT NULL,
    case_id text NOT NULL,
    kind text NOT NULL,
    due_at timestamptz NOT NULL,
    fired_at timestamptz,
    cancelled_at timestamptz,
    UNIQUE (case_id, kind, due_at)
);
CREATE INDEX timer_due ON ops.timer (due_at) WHERE fired_at IS NULL AND cancelled_at IS NULL;

CREATE TABLE ops.model_call (
    id bigserial PRIMARY KEY,
    task text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    prompt_version text NOT NULL,
    request_hash text NOT NULL,
    cache_hit boolean NOT NULL DEFAULT false,
    latency_ms integer,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cost_paise bigint NOT NULL DEFAULT 0,
    result_ref text,
    eval_label text,
    created_at timestamptz NOT NULL
);

-- ---------- audit: append-only, hash-chained ----------
CREATE TABLE ops.audit_event (
    id bigserial PRIMARY KEY,
    unit_id text,
    case_ref text,
    actor_type text NOT NULL CHECK (actor_type IN ('person', 'agent', 'system')),
    actor_id text NOT NULL,
    action text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{{}}',
    created_at timestamptz NOT NULL,
    prev_hash text NOT NULL,
    hash text NOT NULL UNIQUE
);

CREATE FUNCTION ops.audit_event_is_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ops.audit_event is append-only (% refused)', TG_OP;
END;
$$;
CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON ops.audit_event
    FOR EACH ROW EXECUTE FUNCTION ops.audit_event_is_append_only();

-- ---------- application role + row-level security ----------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN;
    END IF;
END
$$;
GRANT {APP_ROLE} TO CURRENT_USER;
GRANT USAGE ON SCHEMA core, cases, network, privacy, ops TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, cases, privacy TO {APP_ROLE};
GRANT SELECT, INSERT ON ops.audit_event, ops.outbox, ops.job TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE ON ops.timer TO {APP_ROLE};  -- cancel timers
GRANT USAGE ON ALL SEQUENCES IN SCHEMA core, cases, privacy, ops TO {APP_ROLE};
"""

POLICY = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY unit_isolation ON {table}
    USING (unit_id = current_setting('app.unit_id', true))
    WITH CHECK (unit_id = current_setting('app.unit_id', true));
"""

DOWNGRADE = f"""
REVOKE {APP_ROLE} FROM CURRENT_USER;
DROP TABLE ops.audit_event, ops.model_call, ops.timer, ops.outbox, ops.job, ops.inbound_event;
DROP FUNCTION ops.audit_event_is_append_only();
DROP TABLE privacy.consent;
DROP TABLE cases.approval, cases.case_event, cases.landed_cost, cases.quote,
    cases.purchase_case, cases.need;
DROP TABLE core.channel_identity, core.supplier, core.person, core.unit;
REVOKE USAGE ON SCHEMA core, cases, network, privacy, ops FROM {APP_ROLE};
"""


def _statements(sql: str) -> list[str]:
    """Split on ';' outside $$-quoted bodies (asyncpg runs one statement per call)."""
    out, current, in_body = [], [], False
    i = 0
    while i < len(sql):
        if sql.startswith("$$", i):
            in_body = not in_body
            current.append("$$")
            i += 2
            continue
        ch = sql[i]
        if ch == ";" and not in_body:
            stmt = "".join(current).strip()
            if stmt and not all(line.strip().startswith("--") for line in stmt.splitlines()):
                out.append(stmt)
            current = []
        else:
            current.append(ch)
        i += 1
    return out


def _run(sql: str) -> None:
    for statement in _statements(sql):
        op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)
    for table in RLS_TABLES:
        _run(POLICY.format(table=table))


def downgrade() -> None:
    _run(DOWNGRADE)
