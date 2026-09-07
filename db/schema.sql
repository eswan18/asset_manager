\restrict dbmate

-- Dumped from database version 16.10 (Debian 16.10-1.pgdg13+1)
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
-- Name: formula_inputs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formula_inputs (
    account_id integer NOT NULL,
    input_id integer NOT NULL,
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
    account_id integer NOT NULL
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
-- Name: accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts ALTER COLUMN id SET DEFAULT nextval('public.accounts_id_seq'::regclass);


--
-- Name: snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots ALTER COLUMN id SET DEFAULT nextval('public.snapshots_id_seq'::regclass);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_type_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_type_name_key UNIQUE (type, name);


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
-- Name: formula_inputs formula_inputs_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_inputs
    ADD CONSTRAINT formula_inputs_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE CASCADE;


--
-- Name: formula_inputs formula_inputs_input_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formula_inputs
    ADD CONSTRAINT formula_inputs_input_id_fkey FOREIGN KEY (input_id) REFERENCES public.accounts(id);


--
-- Name: snapshots snapshots_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id);


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20260123040144'),
    ('20260906120000');
