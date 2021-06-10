--
-- PostgreSQL database dump
--

-- Dumped from database version 11.6
-- Dumped by pg_dump version 13.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: campaignstatuses; Type: TYPE; Schema: public; Owner: common
--

CREATE TYPE public.campaignstatuses AS ENUM (
    'ACTIVE',
    'DRAFT',
    'CANCELLED',
    'ENDED'
);


ALTER TYPE public.campaignstatuses OWNER TO common;

SET default_tablespace = '';

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: common
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO common;

--
-- Name: campaign; Type: TABLE; Schema: public; Owner: common
--

CREATE TABLE public.campaign (
    id integer NOT NULL,
    status public.campaignstatuses DEFAULT 'DRAFT'::public.campaignstatuses NOT NULL,
    name character varying(128) NOT NULL,
    slug character varying(32) NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, CURRENT_TIMESTAMP) NOT NULL,
    updated_at timestamp without time zone DEFAULT timezone('utc'::text, CURRENT_TIMESTAMP) NOT NULL,
    retailer_id integer NOT NULL,
    earn_inc_is_tx_value boolean NOT NULL
);


ALTER TABLE public.campaign OWNER TO common;

--
-- Name: campaign_id_seq; Type: SEQUENCE; Schema: public; Owner: common
--

CREATE SEQUENCE public.campaign_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.campaign_id_seq OWNER TO common;

--
-- Name: campaign_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: common
--

ALTER SEQUENCE public.campaign_id_seq OWNED BY public.campaign.id;


--
-- Name: earn_rule; Type: TABLE; Schema: public; Owner: common
--

CREATE TABLE public.earn_rule (
    id integer NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, CURRENT_TIMESTAMP) NOT NULL,
    updated_at timestamp without time zone DEFAULT timezone('utc'::text, CURRENT_TIMESTAMP) NOT NULL,
    threshold integer NOT NULL,
    increment integer,
    increment_multiplier numeric NOT NULL,
    campaign_id integer NOT NULL
);


ALTER TABLE public.earn_rule OWNER TO common;

--
-- Name: earn_rule_id_seq; Type: SEQUENCE; Schema: public; Owner: common
--

CREATE SEQUENCE public.earn_rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.earn_rule_id_seq OWNER TO common;

--
-- Name: earn_rule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: common
--

ALTER SEQUENCE public.earn_rule_id_seq OWNED BY public.earn_rule.id;


--
-- Name: retailer_rewards; Type: TABLE; Schema: public; Owner: common
--

CREATE TABLE public.retailer_rewards (
    id integer NOT NULL,
    slug character varying(32) NOT NULL
);


ALTER TABLE public.retailer_rewards OWNER TO common;

--
-- Name: retailer_rewards_id_seq; Type: SEQUENCE; Schema: public; Owner: common
--

CREATE SEQUENCE public.retailer_rewards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.retailer_rewards_id_seq OWNER TO common;

--
-- Name: retailer_rewards_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: common
--

ALTER SEQUENCE public.retailer_rewards_id_seq OWNED BY public.retailer_rewards.id;


--
-- Name: transaction; Type: TABLE; Schema: public; Owner: common
--

CREATE TABLE public.transaction (
    id integer NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('utc'::text, CURRENT_TIMESTAMP) NOT NULL,
    updated_at timestamp without time zone DEFAULT timezone('utc'::text, CURRENT_TIMESTAMP) NOT NULL,
    transaction_id character varying(128) NOT NULL,
    amount integer NOT NULL,
    mid character varying(128) NOT NULL,
    datetime timestamp without time zone NOT NULL,
    account_holder_uuid uuid NOT NULL,
    retailer_id integer
);


ALTER TABLE public.transaction OWNER TO common;

--
-- Name: transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: common
--

CREATE SEQUENCE public.transaction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.transaction_id_seq OWNER TO common;

--
-- Name: transaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: common
--

ALTER SEQUENCE public.transaction_id_seq OWNED BY public.transaction.id;


--
-- Name: campaign id; Type: DEFAULT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.campaign ALTER COLUMN id SET DEFAULT nextval('public.campaign_id_seq'::regclass);


--
-- Name: earn_rule id; Type: DEFAULT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.earn_rule ALTER COLUMN id SET DEFAULT nextval('public.earn_rule_id_seq'::regclass);


--
-- Name: retailer_rewards id; Type: DEFAULT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.retailer_rewards ALTER COLUMN id SET DEFAULT nextval('public.retailer_rewards_id_seq'::regclass);


--
-- Name: transaction id; Type: DEFAULT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.transaction ALTER COLUMN id SET DEFAULT nextval('public.transaction_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: common
--

COPY public.alembic_version (version_num) FROM stdin;
6435085f69d3
\.


--
-- Data for Name: campaign; Type: TABLE DATA; Schema: public; Owner: common
--

COPY public.campaign (id, status, name, slug, created_at, updated_at, retailer_id, earn_inc_is_tx_value) FROM stdin;
1	ACTIVE	Trenette campaign	trenette-campaign	2021-05-11 10:27:17.836008	2021-05-11 10:27:17.836008	1	f
2	ACTIVE	Test campaign 1	test-campaign-1	2021-05-11 10:28:07.835409	2021-05-11 10:28:07.835409	2	f
3	ACTIVE	Test campaign 2	test-campaign-2	2021-05-11 10:28:32.381959	2021-05-21 11:06:05.6018	2	f
4	DRAFT	Draft Campaign Test	draft-campaign	2021-05-26 13:46:55.526518	2021-05-26 13:46:55.526518	2	f
\.


--
-- Data for Name: earn_rule; Type: TABLE DATA; Schema: public; Owner: common
--

COPY public.earn_rule (id, created_at, updated_at, threshold, increment, increment_multiplier, campaign_id) FROM stdin;
2	2021-06-02 09:19:45.348177	2021-06-02 09:19:45.348177	1050	1	1	1
1	2021-05-21 11:07:03.382336	2021-06-03 12:48:30.263308	5	3	1	2
\.


--
-- Data for Name: retailer_rewards; Type: TABLE DATA; Schema: public; Owner: common
--

COPY public.retailer_rewards (id, slug) FROM stdin;
1	trenette
2	test-retailer
3	no-campaign-retailer
4	davetest
\.


--
-- Data for Name: transaction; Type: TABLE DATA; Schema: public; Owner: common
--

COPY public.transaction (id, created_at, updated_at, transaction_id, amount, mid, datetime, account_holder_uuid, retailer_id) FROM stdin;
1	2021-05-26 10:49:00.795848	2021-05-26 10:49:00.795848	BPLimatransaction1	9950	12345678	2021-03-16 10:22:23	4cbbd1b3-4323-47f1-88cd-439dd9aabf87	2
3	2021-05-26 14:14:27.675623	2021-05-26 14:14:27.675623	BPL1234567891	1325	12432432	2021-03-16 10:22:24	7c6d1528-f4e4-45be-a9e7-24fb19900951	2
4	2021-06-01 13:32:22.939113	2021-06-01 13:32:22.939113	d221f58d-f472-4812-b991-16933a70de1e	1325	12432432	2021-06-01 10:32:22	53bc0ae5-66db-4d3c-8944-50b2656190cd	2
5	2021-06-01 13:32:25.142243	2021-06-01 13:32:25.142243	512cba7c-76e1-435c-a6dd-dd13956f6da0	1325	12432432	2021-06-01 10:32:24	53bc0ae5-66db-4d3c-8944-50b2656190cd	2
7	2021-06-01 13:53:22.687867	2021-06-01 13:53:22.687867	71293b08-487b-4f00-8201-779900e8ce1c	1325	12432432	2021-06-01 10:53:22	53bc0ae5-66db-4d3c-8944-50b2656190cd	2
8	2021-06-01 13:53:24.75036	2021-06-01 13:53:24.75036	b0cfe1e7-ef05-4fbb-b1e7-61c42563a78b	1325	12432432	2021-06-01 10:53:24	53bc0ae5-66db-4d3c-8944-50b2656190cd	2
10	2021-06-01 14:06:24.895953	2021-06-01 14:06:24.895953	d1e9a7f5-9348-468b-8e83-42e6beff093b	1325	12432432	2021-06-01 11:06:24	53bc0ae5-66db-4d3c-8944-50b2656190cd	2
11	2021-06-01 14:06:26.989668	2021-06-01 14:06:26.989668	c9f4c8b3-1cc4-4974-bef6-cb30becd0f26	1325	12432432	2021-06-01 11:06:26	53bc0ae5-66db-4d3c-8944-50b2656190cd	2
13	2021-06-08 11:40:02.049743	2021-06-08 11:40:02.049743	BPLimatransaction1	9950	12345678	2021-03-16 10:22:23	b80a0be9-918c-4e55-91f7-e9f969596a7d	1
15	2021-06-08 16:55:48.776862	2021-06-08 16:55:48.776862	BPLimatransaction2	9950	12345678	2021-03-16 10:22:23	b80a0be9-918c-4e55-91f7-e9f969596a7d	1
18	2021-06-09 11:19:16.693307	2021-06-09 11:19:16.693307	BPL1234567892	1325	12432432	2021-03-16 10:22:24	9d66a552-458f-4377-84b9-c62c3c4045fd	2
19	2021-06-09 11:49:42.38715	2021-06-09 11:49:42.38715	1111111151-settlement	1222	abc	2020-10-27 15:01:59	b80a0be9-918c-4e55-91f7-e9f969596a7d	1
20	2021-06-09 13:29:50.399301	2021-06-09 13:29:50.399301	1111111311-settlement	1222	test-mid-123	2020-10-27 15:01:59	404448d2-01cd-4972-a6b5-7cf18dfc70d8	1
21	2021-06-09 14:45:26.087695	2021-06-09 14:45:26.087695	1111111511-settlement	1222	test-mid-123	2020-10-27 15:01:59	404448d2-01cd-4972-a6b5-7cf18dfc70d8	1
\.


--
-- Name: campaign_id_seq; Type: SEQUENCE SET; Schema: public; Owner: common
--

SELECT pg_catalog.setval('public.campaign_id_seq', 4, true);


--
-- Name: earn_rule_id_seq; Type: SEQUENCE SET; Schema: public; Owner: common
--

SELECT pg_catalog.setval('public.earn_rule_id_seq', 2, true);


--
-- Name: retailer_rewards_id_seq; Type: SEQUENCE SET; Schema: public; Owner: common
--

SELECT pg_catalog.setval('public.retailer_rewards_id_seq', 4, true);


--
-- Name: transaction_id_seq; Type: SEQUENCE SET; Schema: public; Owner: common
--

SELECT pg_catalog.setval('public.transaction_id_seq', 21, true);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: campaign campaign_pkey; Type: CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.campaign
    ADD CONSTRAINT campaign_pkey PRIMARY KEY (id);


--
-- Name: earn_rule earn_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.earn_rule
    ADD CONSTRAINT earn_rule_pkey PRIMARY KEY (id);


--
-- Name: retailer_rewards retailer_rewards_pkey; Type: CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.retailer_rewards
    ADD CONSTRAINT retailer_rewards_pkey PRIMARY KEY (id);


--
-- Name: transaction transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_pkey PRIMARY KEY (id);


--
-- Name: transaction transaction_retailer_unq; Type: CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_retailer_unq UNIQUE (transaction_id, retailer_id);


--
-- Name: ix_campaign_id; Type: INDEX; Schema: public; Owner: common
--

CREATE INDEX ix_campaign_id ON public.campaign USING btree (id);


--
-- Name: ix_campaign_slug; Type: INDEX; Schema: public; Owner: common
--

CREATE UNIQUE INDEX ix_campaign_slug ON public.campaign USING btree (slug);


--
-- Name: ix_earn_rule_id; Type: INDEX; Schema: public; Owner: common
--

CREATE INDEX ix_earn_rule_id ON public.earn_rule USING btree (id);


--
-- Name: ix_retailer_rewards_id; Type: INDEX; Schema: public; Owner: common
--

CREATE INDEX ix_retailer_rewards_id ON public.retailer_rewards USING btree (id);


--
-- Name: ix_retailer_rewards_slug; Type: INDEX; Schema: public; Owner: common
--

CREATE UNIQUE INDEX ix_retailer_rewards_slug ON public.retailer_rewards USING btree (slug);


--
-- Name: ix_transaction_id; Type: INDEX; Schema: public; Owner: common
--

CREATE INDEX ix_transaction_id ON public.transaction USING btree (id);


--
-- Name: ix_transaction_transaction_id; Type: INDEX; Schema: public; Owner: common
--

CREATE INDEX ix_transaction_transaction_id ON public.transaction USING btree (transaction_id);


--
-- Name: campaign campaign_retailer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.campaign
    ADD CONSTRAINT campaign_retailer_id_fkey FOREIGN KEY (retailer_id) REFERENCES public.retailer_rewards(id) ON DELETE CASCADE;


--
-- Name: earn_rule earn_rule_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.earn_rule
    ADD CONSTRAINT earn_rule_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaign(id) ON DELETE CASCADE;


--
-- Name: transaction transaction_retailer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: common
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_retailer_id_fkey FOREIGN KEY (retailer_id) REFERENCES public.retailer_rewards(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

