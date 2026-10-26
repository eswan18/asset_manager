\restrict dbmate

-- Dumped from database version 17.11 (11592b3)
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts (
    id integer NOT NULL,
    name text NOT NULL,
    type character varying(10) NOT NULL,
    formula jsonb,
    retired_at date,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    category text,
    workspace_id integer NOT NULL,
    CONSTRAINT accounts_category_check CHECK ((category = ANY (ARRAY['credit_cards'::text, 'bank_accounts'::text, 'investment_accounts'::text, 'tax_liability'::text]))),
    CONSTRAINT accounts_type_check CHECK (((type)::text = ANY ((ARRAY['asset'::character varying, 'liability'::character varying])::text[])))
);


--
-- Name: accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounts_id_seq OWNED BY public.accounts.id;


--
-- Name: cash_flow_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_flow_categories (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    name text NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cash_flow_categories_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: cash_flow_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cash_flow_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cash_flow_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cash_flow_categories_id_seq OWNED BY public.cash_flow_categories.id;


--
-- Name: cash_flows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_flows (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    name text NOT NULL,
    direction text NOT NULL,
    amount numeric(15,2) NOT NULL,
    every integer NOT NULL,
    unit text NOT NULL,
    category_id integer,
    description text,
    is_estimate boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cash_flows_amount_check CHECK ((amount >= (0)::numeric)),
    CONSTRAINT cash_flows_direction_check CHECK ((direction = ANY (ARRAY['income'::text, 'expense'::text]))),
    CONSTRAINT cash_flows_every_check CHECK (((every >= 1) AND (every <= 1000))),
    CONSTRAINT cash_flows_name_check CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT cash_flows_unit_check CHECK ((unit = ANY (ARRAY['day'::text, 'week'::text, 'month'::text, 'year'::text])))
);


--
-- Name: cash_flows_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cash_flows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cash_flows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cash_flows_id_seq OWNED BY public.cash_flows.id;


--
-- Name: formula_inputs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_inputs (
    account_id integer NOT NULL,
    input_id integer NOT NULL,
    workspace_id integer NOT NULL,
    CONSTRAINT formula_inputs_check CHECK ((account_id <> input_id))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.snapshots (
    id integer NOT NULL,
    date date NOT NULL,
    amount numeric(15,2) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    account_id integer NOT NULL,
    workspace_id integer NOT NULL
);


--
-- Name: snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.snapshots_id_seq OWNED BY public.snapshots.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    idp_sub text,
    email text NOT NULL,
    name text,
    is_admin boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_login_at timestamp with time zone,
    CONSTRAINT users_email_check CHECK ((email = lower(email)))
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: workspace_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_invites (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    invited_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    accepted_by integer,
    declined_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT workspace_invites_check CHECK ((num_nonnulls(accepted_at, declined_at, revoked_at) <= 1)),
    CONSTRAINT workspace_invites_check1 CHECK (((accepted_at IS NULL) = (accepted_by IS NULL))),
    CONSTRAINT workspace_invites_email_check CHECK (((email = lower(email)) AND (email ~~ '%_@_%'::text))),
    CONSTRAINT workspace_invites_role_check CHECK ((role = ANY (ARRAY['owner'::text, 'editor'::text, 'viewer'::text])))
);


--
-- Name: workspace_invites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspace_invites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspace_invites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspace_invites_id_seq OWNED BY public.workspace_invites.id;


--
-- Name: workspace_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_members (
    workspace_id integer NOT NULL,
    user_id integer NOT NULL,
    role text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT workspace_members_role_check CHECK ((role = ANY (ARRAY['owner'::text, 'editor'::text, 'viewer'::text])))
);


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    id integer NOT NULL,
    name text NOT NULL,
    timezone text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workspaces_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: workspaces_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspaces_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspaces_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspaces_id_seq OWNED BY public.workspaces.id;


--
-- Name: accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts ALTER COLUMN id SET DEFAULT nextval('public.accounts_id_seq'::regclass);


--
-- Name: cash_flow_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_categories ALTER COLUMN id SET DEFAULT nextval('public.cash_flow_categories_id_seq'::regclass);


--
-- Name: cash_flows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows ALTER COLUMN id SET DEFAULT nextval('public.cash_flows_id_seq'::regclass);


--
-- Name: snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots ALTER COLUMN id SET DEFAULT nextval('public.snapshots_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: workspace_invites id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites ALTER COLUMN id SET DEFAULT nextval('public.workspace_invites_id_seq'::regclass);


--
-- Name: workspaces id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces ALTER COLUMN id SET DEFAULT nextval('public.workspaces_id_seq'::regclass);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_workspace_id_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_workspace_id_id_key UNIQUE (workspace_id, id);


--
-- Name: accounts accounts_workspace_type_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_workspace_type_name_key UNIQUE (workspace_id, type, name);


--
-- Name: cash_flow_categories cash_flow_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_categories
    ADD CONSTRAINT cash_flow_categories_pkey PRIMARY KEY (id);


--
-- Name: cash_flow_categories cash_flow_categories_workspace_id_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_categories
    ADD CONSTRAINT cash_flow_categories_workspace_id_id_key UNIQUE (workspace_id, id);


--
-- Name: cash_flow_categories cash_flow_categories_workspace_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_categories
    ADD CONSTRAINT cash_flow_categories_workspace_id_name_key UNIQUE (workspace_id, name);


--
-- Name: cash_flows cash_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows
    ADD CONSTRAINT cash_flows_pkey PRIMARY KEY (id);


--
-- Name: cash_flows cash_flows_workspace_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows
    ADD CONSTRAINT cash_flows_workspace_id_name_key UNIQUE (workspace_id, name);


--
-- Name: formula_inputs formula_inputs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_inputs
    ADD CONSTRAINT formula_inputs_pkey PRIMARY KEY (account_id, input_id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: snapshots snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_pkey PRIMARY KEY (id);


--
-- Name: users users_idp_sub_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_idp_sub_key UNIQUE (idp_sub);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: workspace_invites workspace_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT workspace_invites_pkey PRIMARY KEY (id);


--
-- Name: workspace_members workspace_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_pkey PRIMARY KEY (workspace_id, user_id);


--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);


--
-- Name: idx_formula_inputs_input; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_formula_inputs_input ON public.formula_inputs USING btree (input_id);


--
-- Name: idx_snapshots_account_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_snapshots_account_date ON public.snapshots USING btree (account_id, date);


--
-- Name: idx_snapshots_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_snapshots_date ON public.snapshots USING btree (date);


--
-- Name: idx_snapshots_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_snapshots_unique ON public.snapshots USING btree (date, account_id);


--
-- Name: idx_snapshots_workspace_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_snapshots_workspace_date ON public.snapshots USING btree (workspace_id, date);


--
-- Name: idx_workspace_invites_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workspace_invites_email ON public.workspace_invites USING btree (email);


--
-- Name: idx_workspace_members_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workspace_members_user ON public.workspace_members USING btree (user_id);


--
-- Name: users_unclaimed_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX users_unclaimed_email ON public.users USING btree (email) WHERE (idp_sub IS NULL);


--
-- Name: workspace_invites_open; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX workspace_invites_open ON public.workspace_invites USING btree (workspace_id, email) WHERE ((accepted_at IS NULL) AND (declined_at IS NULL) AND (revoked_at IS NULL));


--
-- Name: accounts accounts_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: cash_flow_categories cash_flow_categories_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_categories
    ADD CONSTRAINT cash_flow_categories_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: cash_flows cash_flows_workspace_id_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows
    ADD CONSTRAINT cash_flows_workspace_id_category_id_fkey FOREIGN KEY (workspace_id, category_id) REFERENCES public.cash_flow_categories(workspace_id, id) ON DELETE SET NULL (category_id);


--
-- Name: cash_flows cash_flows_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows
    ADD CONSTRAINT cash_flows_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: formula_inputs formula_inputs_account_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_inputs
    ADD CONSTRAINT formula_inputs_account_fkey FOREIGN KEY (workspace_id, account_id) REFERENCES public.accounts(workspace_id, id) ON DELETE CASCADE;


--
-- Name: formula_inputs formula_inputs_input_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_inputs
    ADD CONSTRAINT formula_inputs_input_fkey FOREIGN KEY (workspace_id, input_id) REFERENCES public.accounts(workspace_id, id);


--
-- Name: snapshots snapshots_account_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_account_fkey FOREIGN KEY (workspace_id, account_id) REFERENCES public.accounts(workspace_id, id);


--
-- Name: workspace_invites workspace_invites_accepted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT workspace_invites_accepted_by_fkey FOREIGN KEY (accepted_by) REFERENCES public.users(id);


--
-- Name: workspace_invites workspace_invites_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT workspace_invites_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.users(id);


--
-- Name: workspace_invites workspace_invites_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT workspace_invites_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- Name: workspace_members workspace_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: workspace_members workspace_members_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_members
    ADD CONSTRAINT workspace_members_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20260123040144'),
    ('20260906120000'),
    ('20261019120000'),
    ('20261026120000'),
    ('20261027120000'),
    ('20261028120000');
